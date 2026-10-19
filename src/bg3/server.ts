import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createConnection, ProposedFeatures, TextDocuments, TextDocumentSyncKind, CompletionItemKind,
  MarkupKind, SymbolKind, type Diagnostic, type SignatureInformation } from 'vscode-languageserver/node';
import { TextDocument } from 'vscode-languageserver-textdocument';
import { activeCall, callAt, findProjectRoots, headerEnums, maskComments, signatures, signatureLabel,
  syntaxIssues, tokenAt, type Signature } from './language';

const connection = createConnection(ProposedFeatures.all);
const documents = new TextDocuments(TextDocument);
const files = new Map<string, string>();
const definitions = new Map<string, Signature[]>();
const enumTypes = new Map<string, Map<string, number>>();
const aliases = new Set(['INTEGER', 'INTEGER64', 'REAL', 'STRING', 'GUIDSTRING']);
let roots: string[] = [], configured = '', diagnosticsEnabled = true;
let modules: string[] = [];
let apiHeaderPaths: string[] = [];
let timer: NodeJS.Timeout | undefined;
let supportsFolders = false;

function addFile(uri: string, text: string, header = false) {
  files.set(uri, text);
  definitions.set(uri, signatures(text, uri, header));
  if (header) {
    for (const [type, members] of headerEnums(text)) { enumTypes.set(type, members); aliases.add(type); }
    for (const match of text.matchAll(/alias_type\s*\{(\w+)/g)) aliases.add(match[1]);
  }
}

function readFile(filename: string, header = false) {
  try { addFile(pathToFileURL(filename).href, fs.readFileSync(filename, 'utf8'), header); } catch { /* Optional generated inputs. */ }
}

function allSymbols(): Signature[] {
  // Own definitions take precedence over the generated dependency snapshot.
  const unique = new Map<string, Signature>();
  for (const values of definitions.values()) for (const symbol of values) unique.set(`${symbol.name}/${symbol.parameters.length}`, symbol);
  return [...unique.values()];
}

function publishGoals() {
  const goals: { uri: string; name: string; parents: string[]; module: string }[] = [];
  for (const module of modules) {
    const goalPath = pathToFileURL(path.join(module, 'Story/RawFiles/Goals/')).href;
    for (const [uri, text] of files) if (uri.startsWith(goalPath) && uri.endsWith('.txt')) goals.push({ uri,
      name: path.basename(fileURLToPath(uri), '.txt'), module,
      parents: [...maskComments(text).matchAll(/^ParentTargetEdge\s+"([^"]+)"/gm)].map(m => m[1]) });
  }
  connection.sendNotification('bg3/goals', goals);
}

function indexWorkspace() {
  files.clear(); definitions.clear(); enumTypes.clear();
  aliases.clear();
  for (const name of ['INTEGER', 'INTEGER64', 'REAL', 'STRING', 'GUIDSTRING']) aliases.add(name);
  for (const header of apiHeaderPaths) readFile(header, true);
  modules = findProjectRoots(roots, configured, documents.all().filter(d => d.uri.startsWith('file:')).map(d => fileURLToPath(d.uri)));
  for (const module of modules) {
    readFile(path.join(module, 'Story/RawFiles/story_header.div'), true);
    readFile(path.join(module, 'Story/RawFiles/story_definitions.div'), true);
    // This Toolkit-produced snapshot supplies dependency procedures and queries without a DOS2 PAK parser.
    const aggregate = path.join(module, 'Story/goals.raw');
    if (fs.existsSync(aggregate)) readFile(aggregate);
    const goalDir = path.join(module, 'Story/RawFiles/Goals');
    for (const file of fs.readdirSync(goalDir)) if (file.endsWith('.txt')) readFile(path.join(goalDir, file));
  }
  for (const document of documents.all()) addFile(document.uri, document.getText(), document.languageId === 'divinity-story-div');
  publishGoals();
  for (const document of documents.all()) validate(document);
  connection.console.info(`BG3: indexed ${modules.length} module(s), ${allSymbols().length} signatures.`);
}

function validate(document: TextDocument) {
  const diagnostics: Diagnostic[] = [];
  if (diagnosticsEnabled && document.languageId === 'divinity-story-goal') {
    try {
      for (const issue of syntaxIssues(document.getText(), enumTypes).slice(0, 100)) diagnostics.push({
        range: { start: document.positionAt(Math.max(0, issue.offset)), end: document.positionAt(Math.max(issue.offset + 1, issue.endOffset)) },
        message: issue.message, severity: issue.severity === 2 ? 2 : 1, source: 'BG3 Osiris syntax', code: issue.code
      });
    } catch (error) { connection.console.error(`Syntax analysis failed: ${String(error)}`); }
  }
  connection.sendDiagnostics({ uri: document.uri, version: document.version, diagnostics });
}

connection.onInitialize(params => {
  supportsFolders = !!params.capabilities.workspace?.workspaceFolders;
  roots = (params.workspaceFolders ?? []).filter(f => f.uri.startsWith('file:')).map(f => fileURLToPath(f.uri));
  configured = params.initializationOptions?.projectPath ?? '';
  apiHeaderPaths = params.initializationOptions?.apiHeaderPaths ?? [];
  diagnosticsEnabled = params.initializationOptions?.enableDiagnostics ?? true;
  return { capabilities: {
    textDocumentSync: TextDocumentSyncKind.Full,
    completionProvider: { triggerCharacters: ['.'] }, hoverProvider: true,
    signatureHelpProvider: { triggerCharacters: ['(', ','], retriggerCharacters: [','] },
    definitionProvider: true, referencesProvider: true, documentSymbolProvider: true,
    workspace: { workspaceFolders: { supported: true, changeNotifications: true } }
  } };
});
connection.onInitialized(() => {
  if (supportsFolders) connection.workspace.onDidChangeWorkspaceFolders(event => {
    const removed = new Set(event.removed.map(f => f.uri));
    roots = roots.filter(root => !removed.has(pathToFileURL(root).href));
    roots.push(...event.added.filter(f => f.uri.startsWith('file:')).map(f => fileURLToPath(f.uri)));
    indexWorkspace();
  });
  indexWorkspace();
});
connection.onNotification('bg3/refresh', indexWorkspace);
connection.onNotification('bg3/apiHeaders', (params: { paths?: string[] }) => {
  apiHeaderPaths = Array.isArray(params.paths) ? params.paths.filter(value => typeof value === 'string') : [];
  indexWorkspace();
});
connection.onDidChangeWatchedFiles(() => { clearTimeout(timer); timer = setTimeout(indexWorkspace, 200); });
connection.onDidChangeConfiguration(params => {
  const config = params.settings?.bg3Osiris;
  if (config) { configured = config.projectPath ?? ''; diagnosticsEnabled = config.enableDiagnostics ?? true; indexWorkspace(); }
});
documents.onDidChangeContent(({ document }) => {
  addFile(document.uri, document.getText(), document.languageId === 'divinity-story-div');
  validate(document); publishGoals();
});
documents.onDidOpen(({ document }) => {
  if (!document.uri.startsWith('file:')) return;
  const inferred = findProjectRoots([], configured, [fileURLToPath(document.uri)]);
  if (inferred.some(module => !modules.includes(module))) indexWorkspace();
});
documents.onDidClose(({ document }) => {
  if (document.uri.startsWith('file:')) readFile(fileURLToPath(document.uri), document.languageId === 'divinity-story-div');
  connection.sendDiagnostics({ uri: document.uri, diagnostics: [] });
});

connection.onCompletion(params => {
  const document = documents.get(params.textDocument.uri);
  const prefix = document?.getText().slice(0, document.offsetAt(params.position)) ?? '';
  const enumPrefix = /\b(\w+)\.(\w*)$/.exec(prefix);
  if (enumPrefix && enumTypes.has(enumPrefix[1])) return [...enumTypes.get(enumPrefix[1])!].map(([name, value]) => ({
    label: name, kind: CompletionItemKind.EnumMember, detail: `${enumPrefix[1]}.${name} = ${value}`
  }));
  return [
    ...allSymbols().map(symbol => ({ label: symbol.name,
      kind: symbol.kind === 'event' ? CompletionItemKind.Event : CompletionItemKind.Function,
      detail: signatureLabel(symbol), documentation: symbol.builtin ? 'Signature from this project’s generated BG3 story header.' : 'Project or dependency definition.' })),
    ...[...aliases].map(label => ({ label, kind: CompletionItemKind.TypeParameter })),
    ...['IF', 'IFF', 'AND', 'THEN', 'NOT', 'PROC', 'QRY', 'GoalCompleted'].map(label => ({ label, kind: CompletionItemKind.Keyword }))
  ];
});

connection.onHover(params => {
  const document = documents.get(params.textDocument.uri); if (!document) return null;
  const word = tokenAt(document.getText(), document.offsetAt(params.position)); if (!word) return null;
  const symbols = allSymbols().filter(s => s.name === word.name);
  const [type, member] = word.name.split('.');
  let value = symbols.map(s => `\`\`\`osiris\n${s.kind} ${signatureLabel(s)}\n\`\`\``).join('\n\n');
  if (enumTypes.get(type)?.has(member)) value = `\`${word.name}\` = ${enumTypes.get(type)!.get(member)}`;
  if (!value) return null;
  if (symbols.some(s => s.builtin)) value += `\n\n[BG3 API documentation](https://docs.baldursgate3.game/index.php?title=${encodeURIComponent(word.name)})`;
  return { contents: { kind: MarkupKind.Markdown, value }, range: { start: document.positionAt(word.start), end: document.positionAt(word.end) } };
});

connection.onSignatureHelp(params => {
  const document = documents.get(params.textDocument.uri); if (!document) return null;
  const call = activeCall(document.getText(), document.offsetAt(params.position)); if (!call) return null;
  const symbols = allSymbols().filter(s => s.name === call.name); if (!symbols.length) return null;
  const result: SignatureInformation[] = symbols.map(symbol => ({ label: signatureLabel(symbol),
    parameters: symbol.parameters.map(p => ({ label: `${p.flow ? `[${p.flow}]` : ''}(${p.type})${p.name}` })) }));
  const activeSignature = Math.max(0, symbols.findIndex(s => s.parameters.length > call.argument));
  return { signatures: result, activeSignature, activeParameter: Math.min(call.argument, Math.max(0, symbols[activeSignature].parameters.length - 1)) };
});

function locations(name: string, declarationsOnly: boolean) {
  if (declarationsOnly) return allSymbols().filter(s => s.name === name).map(symbol => {
    const doc = TextDocument.create(symbol.uri, '', 0, files.get(symbol.uri) ?? '');
    return { uri: symbol.uri, range: { start: doc.positionAt(symbol.offset), end: doc.positionAt(symbol.offset + name.length) } };
  });
  const result: { uri: string; range: ReturnType<typeof documentRange> }[] = [];
  for (const [uri, text] of files) {
    if (!uri.endsWith('.txt')) continue;
    const doc = TextDocument.create(uri, '', 0, text);
    for (const match of maskComments(text, true).matchAll(new RegExp(`\\b${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'g'))) {
      result.push({ uri, range: documentRange(doc, match.index!, match.index! + name.length) });
    }
  }
  return result;
}
function documentRange(doc: TextDocument, start: number, end: number) { return { start: doc.positionAt(start), end: doc.positionAt(end) }; }
connection.onDefinition(params => {
  const doc = documents.get(params.textDocument.uri); if (!doc) return null;
  const word = tokenAt(doc.getText(), doc.offsetAt(params.position)); return word ? locations(word.name, true) : null;
});
connection.onReferences(params => {
  const doc = documents.get(params.textDocument.uri); if (!doc) return [];
  const word = tokenAt(doc.getText(), doc.offsetAt(params.position)); return word ? locations(word.name, false) : [];
});
connection.onDocumentSymbol(params => {
  const doc = documents.get(params.textDocument.uri); if (!doc) return [];
  const text = doc.getText();
  return [...maskComments(text).matchAll(/^\s*(IF|IFF|PROC|QRY)\s+([A-Za-z_]\w*)\s*\(/gm)].map(match => {
    const start = match.index! + match[0].lastIndexOf(match[2]);
    const call = callAt(text, start, match.index! + match[0].lastIndexOf('('), match[2]);
    return { name: `${match[1]} ${match[2]}`, kind: SymbolKind.Function,
      range: documentRange(doc, start, Math.min(text.length, call.close + 1)),
      selectionRange: documentRange(doc, start, start + match[2].length) };
  });
});
documents.listen(connection);
connection.listen();
