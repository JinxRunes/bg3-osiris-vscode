import GoalParser from './parser/GoalParser';

export interface Parameter { name: string; type: string; flow?: string }
export interface Signature {
  name: string; kind: string; parameters: Parameter[]; uri: string; offset: number; builtin: boolean;
}
export interface Issue { offset: number; endOffset: number; message: string; severity: number; code?: string }
export interface Call { name: string; start: number; open: number; close: number; args: string[] }

// Preserve UTF-16 offsets and line breaks so parser diagnostics map back to the real document.
export function maskComments(text: string, strings = false): string {
  return text.replace(/\/\/[^\r\n]*|\/\*[\s\S]*?\*\/|"(?:[^"\\]|\\.)*"/g, value =>
    value.startsWith('"') && !strings ? value : value.replace(/[^\r\n]/g, ' '));
}

export function callAt(text: string, start: number, open: number, name: string, masked = maskComments(text, true)): Call {
  let depth = 0, argument = open + 1, close = text.length;
  const args: string[] = [];
  for (let i = open + 1; i < masked.length; i++) {
    if (masked[i] === '(') depth++;
    else if (masked[i] === ')') {
      if (depth === 0) { close = i; break; }
      depth--;
    } else if (masked[i] === ',' && depth === 0) {
      args.push(text.slice(argument, i).trim()); argument = i + 1;
    }
  }
  const final = text.slice(argument, close).trim();
  if (final || args.length) args.push(final);
  return { name, start, open, close, args };
}

function parameters(args: string[]): Parameter[] {
  return args.map((arg, i) => ({
    name: /(_\w+)\s*$/.exec(arg)?.[1] ?? `_Arg${i + 1}`,
    type: /\((\w+)\)/.exec(arg)?.[1] ?? 'UNKNOWN',
    flow: /\[(in|out)\]/.exec(arg)?.[1]
  }));
}

export function signatures(text: string, uri: string, header: boolean): Signature[] {
  const pattern = header
    ? /^(?:[ \t]*)(syscall|sysquery|call|query|event)\s+([A-Za-z_]\w*)\s*\(/gm
    : /^(?:[ \t]*)(PROC|QRY)\s+([A-Za-z_]\w*)\s*\(/gm;
  const masked = maskComments(text, true);
  const result: Signature[] = [];
  for (const match of masked.matchAll(pattern)) {
    const start = match.index! + match[0].lastIndexOf(match[2]);
    const call = callAt(text, start, match.index! + match[0].lastIndexOf('('), match[2], masked);
    result.push({ name: match[2], kind: match[1], parameters: parameters(call.args), uri, offset: start, builtin: header });
  }
  return result;
}

export function headerEnums(text: string): Map<string, Map<string, number>> {
  const result = new Map<string, Map<string, number>>();
  for (const match of maskComments(text).matchAll(/enum_type\s*\{(\w+),\s*\d+,\s*\d+,([^}]+)\}/g)) {
    result.set(match[1], new Map([...match[2].matchAll(/(\w+)\s*=\s*(-?\d+)/g)].map(v => [v[1], Number(v[2])])));
  }
  return result;
}

export function signatureLabel(symbol: Signature): string {
  return `${symbol.name}(${symbol.parameters.map(p => `${p.flow ? `[${p.flow}]` : ''}(${p.type})${p.name}`).join(', ')})`;
}

export function enumNormalized(text: string, enums: Map<string, Map<string, number>>): { text: string; issues: Issue[] } {
  const issues: Issue[] = [];
  const normalized = text.replace(/\/\/[^\r\n]*|\/\*[\s\S]*?\*\/|"(?:[^"\\]|\\.)*"|\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b/g,
    (value: string, type: string | undefined, member: string | undefined, offset: number) => {
      if (!type || !member) return value;
      const members = enums.get(type);
      const number = members?.get(member);
      if (enums.size && number === undefined) issues.push({ offset, endOffset: offset + value.length, severity: 1, code: 'bg3-enum', message: `Unknown BG3 enum member ${value}.` });
      return String(number ?? 0).padEnd(value.length, ' ');
    });
  return { text: normalized, issues };
}

export function syntaxIssues(text: string, enums: Map<string, Map<string, number>>): Issue[] {
  const masked = maskComments(text, true);
  const rule = /^\s*(IF|PROC|QRY)\b/m.exec(masked);
  if (rule && !/^\s*(INITSECTION|KBSECTION|EXITSECTION|ENDEXITSECTION)\b/m.test(masked)) {
    const offset = rule.index + rule[0].lastIndexOf(rule[1]);
    return [{ offset, endOffset: offset + rule[1].length, severity: 1, code: 'bg3-goal-sections',
      message: 'Goal rules must be inside KBSECTION. Add Version 1, SubGoalCombiner SGC_AND, INITSECTION, KBSECTION, EXITSECTION and ENDEXITSECTION. Use the "goal" snippet for a complete file.' }];
  }
  const normalized = enumNormalized(text, enums);
  const { diagnostics } = new GoalParser(normalized.text).parse();
  return [...normalized.issues, ...diagnostics.map(d => ({ offset: d.startOffset, endOffset: d.endOffset,
    message: d.message, severity: d.severity, code: String(d.code) }))];
}

export function tokenAt(text: string, offset: number): { name: string; start: number; end: number } | undefined {
  let start = offset, end = offset;
  while (start > 0 && /[A-Za-z0-9_.]/.test(text[start - 1])) start--;
  while (end < text.length && /[A-Za-z0-9_.]/.test(text[end])) end++;
  const name = text.slice(start, end);
  return name ? { name, start, end } : undefined;
}

export function activeCall(text: string, offset: number): { name: string; argument: number } | undefined {
  const prefix = maskComments(text.slice(0, offset), true);
  const stack: { name: string; argument: number }[] = [];
  for (let i = 0; i < prefix.length; i++) {
    if (prefix[i] === '(') {
      const name = /([A-Za-z_]\w*)\s*$/.exec(prefix.slice(0, i))?.[1] ?? '';
      stack.push({ name, argument: 0 });
    } else if (prefix[i] === ')') stack.pop();
    else if (prefix[i] === ',' && stack.length) stack[stack.length - 1].argument++;
  }
  return [...stack].reverse().find(call => call.name && !/^[A-Z_]+$/.test(call.name));
}

export function findProjectRoots(roots: string[], configured?: string, documents: string[] = []): string[] {
  // Imported lazily to keep the language helpers usable without a VS Code host.
  const fs = require('node:fs') as typeof import('node:fs');
  const path = require('node:path') as typeof import('node:path');
  const projects = new Map<string, string>();
  function isProject(folder: string): boolean {
    try { return fs.statSync(path.join(folder, 'Story/RawFiles/Goals')).isDirectory(); } catch { return false; }
  }
  function add(folder: string) {
    const resolved = path.resolve(folder);
    projects.set(process.platform === 'win32' ? resolved.toLowerCase() : resolved, resolved);
  }
  function ancestor(candidate: string): string | undefined {
    let folder = path.resolve(candidate);
    try { if (!fs.statSync(folder).isDirectory()) folder = path.dirname(folder); } catch { return; }
    while (true) {
      if (isProject(folder)) return folder;
      const parent = path.dirname(folder);
      if (parent === folder) return;
      folder = parent;
    }
  }
  function walk(folder: string, depth: number) {
    if (isProject(folder)) { add(folder); return; }
    if (depth === 0) return;
    try {
      for (const item of fs.readdirSync(folder, { withFileTypes: true })) {
        if (item.isDirectory() && !item.isSymbolicLink() && !/^(\.|node_modules$|bin$|obj$)/.test(item.name)) walk(path.join(folder, item.name), depth - 1);
      }
    } catch { /* Not every workspace folder is accessible. */ }
  }
  if (configured) {
    const project = ancestor(configured);
    if (project) add(project);
  } else {
    for (const root of roots) {
      const project = ancestor(root);
      if (project) add(project);
      else walk(root, 3);
    }
    // A goal or generated header can be opened without opening its module as a workspace.
    for (const document of documents) {
      const project = ancestor(document);
      if (project) add(project);
    }
  }
  return [...projects.values()].sort();
}
