import * as vscode from 'vscode';
import * as path from 'node:path';
import * as fs from 'node:fs';
import { spawn, type ChildProcess } from 'node:child_process';
import { createHash } from 'node:crypto';
import { LanguageClient, TransportKind } from 'vscode-languageclient/node';
import { findProjectRoots } from './language';
import { compilerInvocation } from './compiler';

interface Goal { uri: string; name: string; parents: string[]; module: string }
interface BuildDefinition extends vscode.TaskDefinition { type: 'bg3-osiris'; action: 'prepare' | 'check' | 'build'; projectPath?: string; backend?: 'osicheck' | 'toolkit' }
interface BuildReport {
  success: boolean; error?: string; build?: string; errors?: number; warnings?: number; compiler?: string; action?: string; header_file?: string;
  diagnostics?: { file?: string; line?: number; column?: number; severity: string; message: string }[];
}
let client: LanguageClient | undefined;

class GoalOutline implements vscode.TreeDataProvider<Goal> {
  private changed = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changed.event;
  goals: Goal[] = [];
  update(goals: Goal[]) { this.goals = goals; this.changed.fire(); }
  getTreeItem(goal: Goal) {
    const children = this.goals.some(g => g.module === goal.module && g.parents.includes(goal.name));
    const item = new vscode.TreeItem(goal.name, children ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None);
    item.resourceUri = vscode.Uri.parse(goal.uri);
    item.command = { command: 'vscode.open', title: 'Open Goal', arguments: [item.resourceUri] };
    item.tooltip = `${goal.name}\n${goal.parents.length ? `Parents: ${goal.parents.join(', ')}` : 'Root goal'}`;
    return item;
  }
  getChildren(parent?: Goal) {
    return this.goals.filter(goal => parent
      ? goal.module === parent.module && goal.parents.includes(parent.name)
      : !goal.parents.some(name => this.goals.some(g => g.module === goal.module && g.name === name)))
      .sort((a, b) => a.name.localeCompare(b.name));
  }
  dispose() { this.changed.dispose(); }
}

function config() { return vscode.workspace.getConfiguration('bg3Osiris'); }
function projects() {
  return findProjectRoots((vscode.workspace.workspaceFolders ?? []).filter(f => f.uri.scheme === 'file').map(f => f.uri.fsPath), config().get<string>('projectPath'),
    vscode.workspace.textDocuments.filter(d => d.uri.scheme === 'file' && ['divinity-story-goal', 'divinity-story-div'].includes(d.languageId)).map(d => d.uri.fsPath));
}
function trusted() {
  if (!vscode.workspace.isTrusted) throw new Error('Trust this workspace before running the BG3 compiler.');
}

export async function activate(context: vscode.ExtensionContext) {
  const output = vscode.window.createOutputChannel('BG3 Osiris Build');
  const diagnostics = vscode.languages.createDiagnosticCollection('BG3 story compiler');
  const outline = new GoalOutline();
  context.subscriptions.push(output, diagnostics, outline, vscode.window.registerTreeDataProvider('bg3Osiris.goals', outline));
  const lastBuild = new Map<string, string>();

  function stateDir(project: string) {
    const id = createHash('sha256').update(path.resolve(project).toLowerCase()).digest('hex').slice(0, 20);
    return path.join(context.globalStorageUri.fsPath, 'projects', id);
  }
  function apiHeaders() { return projects().map(project => path.join(stateDir(project), 'osicheck-api-header.div')).filter(filename => fs.existsSync(filename)); }

  async function chooseProject(): Promise<string | undefined> {
    const available = projects();
    if (available.length === 1) return available[0];
    if (available.length > 1) return (await vscode.window.showQuickPick(available.map(project => ({ label: path.basename(project), description: project, project }))))?.project;
    throw new Error('No BG3 module found. Open the module, its Story/RawFiles or Goals folder, or a goal file under Story/RawFiles/Goals. You can also set BG3 Osiris: Project Path to the module folder.');
  }

  class CompilerTerminal implements vscode.Pseudoterminal {
    private writeEvent = new vscode.EventEmitter<string>();
    private closeEvent = new vscode.EventEmitter<number>();
    readonly onDidWrite = this.writeEvent.event;
    readonly onDidClose = this.closeEvent.event;
    private process?: ChildProcess;
    private closed = false;
    constructor(private definition: BuildDefinition, private project: string) {}
    open() { void this.run().catch(error => { this.write(String(error) + '\n'); this.finish(1); }); }
    close() {
      this.closed = true;
      if (this.process?.pid && this.process.exitCode === null) {
        if (process.platform === 'win32') {
          const killer = spawn('taskkill.exe', ['/PID', String(this.process.pid), '/T', '/F'], { shell: false, windowsHide: true, stdio: 'ignore' });
          killer.on('error', () => this.process?.kill());
        } else this.process.kill();
      }
      this.writeEvent.dispose(); this.closeEvent.dispose();
    }
    private write(text: string) { if (!this.closed) { this.writeEvent.fire(text.replace(/\r?\n/g, '\r\n')); output.append(text); } }
    private finish(code: number) { if (!this.closed) this.closeEvent.fire(code); }
    private async run() {
      trusted();
      if (process.platform !== 'win32') throw new Error('The packaged BG3 compiler integrations currently require Windows x64.');
      if (!await vscode.workspace.saveAll(false)) throw new Error('Save the modified files before compiling.');
      const { backend, args } = compilerInvocation({ action: this.definition.action, backend: this.definition.backend,
        selected: config().get<string>('compilerBackend'), extension: context.extensionPath,
        project: this.project, state: stateDir(this.project), toolkit: config().get<string>('toolkitPath'),
        osicheck: config().get<string>('osiCheckPath'), gameData: config().get<string>('gameDataPath'),
        dotnet: config().get<string>('dotnetPath'), dependencies: config().get<string[]>('dependencyMods'),
        vanillaIssues: config().get<string[]>('osiCheckKnownVanillaIssues') });
      diagnostics.clear(); output.clear();
      this.write(`BG3 Osiris: ${this.definition.action} ${path.basename(this.project)} (${backend})\n`);
      let pending = '', report: BuildReport | undefined;
      const consume = (chunk: Buffer | string) => {
        pending += chunk.toString();
        let newline: number;
        while ((newline = pending.indexOf('\n')) !== -1) {
          const line = pending.slice(0, newline).replace(/\r$/, ''); pending = pending.slice(newline + 1);
          if (line.startsWith('BG3_RESULT ')) {
            try { report = JSON.parse(line.slice(11)); } catch { this.write('Could not read the compiler report.\n'); }
          } else this.write(line + '\n');
        }
      };
      this.process = spawn(config().get<string>('pythonPath') ?? 'python', args, { shell: false, windowsHide: true });
      this.process.stdout?.on('data', consume);
      this.process.stderr?.on('data', consume);
      this.process.on('error', error => { this.write(`Could not launch Python: ${error.message}\n`); this.finish(1); });
      this.process.on('close', code => {
        if (this.closed) return;
        if (pending) consume('\n');
        if (report?.error) this.write(report.error + '\n');
        if (report?.build && this.definition.action !== 'check') lastBuild.set(this.project, report.build);
        if (report?.header_file) void client?.sendNotification('bg3/apiHeaders', { paths: apiHeaders() });
        const byFile = new Map<string, vscode.Diagnostic[]>();
        for (const item of report?.diagnostics ?? []) {
          if (!item.file) continue;
          const row = Math.max(0, (item.line ?? 1) - 1);
          const diagnostic = new vscode.Diagnostic(new vscode.Range(row, 0, row, 1000), item.message,
            item.severity === 'warning' ? vscode.DiagnosticSeverity.Warning : vscode.DiagnosticSeverity.Error);
          diagnostic.source = backend === 'osicheck' ? 'BG3 OsiCheck' : 'BG3 native compiler';
          byFile.set(item.file, [...(byFile.get(item.file) ?? []), diagnostic]);
        }
        for (const [file, entries] of byFile) diagnostics.set(vscode.Uri.file(file), entries);
        const success = code === 0 && report?.success;
        if (success) void vscode.window.showInformationMessage(this.definition.action === 'prepare' ? 'BG3 project prepared.'
          : this.definition.action === 'check' ? `BG3 story checked. ${report?.warnings ?? 0} warning(s).`
          : `BG3 story compiled with ${backend === 'osicheck' ? 'OsiCheck' : 'the Toolkit'}. ${report?.warnings ?? 0} warning(s).`);
        else { this.write('No game story was installed. See BG3 Osiris Build output for details.\n'); output.show(true); }
        this.finish(success ? 0 : 1);
      });
    }
  }

  function makeTask(definition: BuildDefinition, project: string) {
    const execution = new vscode.CustomExecution(async () => new CompilerTerminal(definition, project));
    const task = new vscode.Task(definition, vscode.workspace.getWorkspaceFolder(vscode.Uri.file(project)) ?? vscode.TaskScope.Workspace,
      `${definition.action === 'build' ? 'Build Story' : definition.action === 'check' ? 'Check Story' : 'Prepare Project'}: ${path.basename(project)}`, 'BG3 Osiris', execution, ['$bg3-osiris']);
    if (definition.action === 'build') task.group = vscode.TaskGroup.Build;
    task.presentationOptions = { reveal: vscode.TaskRevealKind.Always, clear: true };
    return task;
  }
  context.subscriptions.push(vscode.tasks.registerTaskProvider('bg3-osiris', {
    provideTasks: () => projects().flatMap(project => (['check', 'build'] as const).map(action => makeTask({ type: 'bg3-osiris', action, projectPath: project }, project))),
    resolveTask: task => {
      const definition = task.definition as BuildDefinition;
      const available = definition.projectPath ? findProjectRoots([], definition.projectPath) : projects();
      const project = available.length === 1 ? available[0] : undefined;
      return project && ['check', 'build', 'prepare'].includes(definition.action) ? makeTask(definition, project) : undefined;
    }
  }));
  for (const [command, action] of [['prepareProject', 'prepare'], ['checkStory', 'check'], ['buildStory', 'build']] as const) {
    context.subscriptions.push(vscode.commands.registerCommand(`bg3Osiris.${command}`, async () => {
      try {
        trusted(); const project = await chooseProject(); if (!project) return;
        const definition: BuildDefinition = { type: 'bg3-osiris', action, projectPath: project };
        if (vscode.workspace.workspaceFolders?.length) await vscode.tasks.executeTask(makeTask(definition, project));
        else {
          // VS Code tasks require a workspace; the same compiler terminal also supports loose goal files.
          const terminal = vscode.window.createTerminal({ name: `BG3 Osiris: ${action}`, pty: new CompilerTerminal(definition, project) });
          context.subscriptions.push(terminal); terminal.show();
        }
      }
      catch (error) { void vscode.window.showErrorMessage(String(error)); }
    }));
  }
  context.subscriptions.push(vscode.commands.registerCommand('bg3Osiris.showBuildOutput', async () => {
    try {
      const project = await chooseProject(); if (!project) return;
      let folder = lastBuild.get(project);
      if (!folder) {
        const report = path.join(stateDir(project), 'last-build.json');
        if (fs.existsSync(report)) folder = JSON.parse(fs.readFileSync(report, 'utf8')).build;
      }
      if (folder) await vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(path.join(folder, 'report.json')));
      else void vscode.window.showInformationMessage('Build this project first.');
    } catch (error) { void vscode.window.showErrorMessage(String(error)); }
  }));
  context.subscriptions.push(vscode.commands.registerCommand('bg3Osiris.openApiDocumentation', async () => {
    const editor = vscode.window.activeTextEditor;
    const range = editor?.document.getWordRangeAtPosition(editor.selection.active, /[A-Za-z_]\w*/);
    const name = range ? editor!.document.getText(range) : 'Main_Page';
    await vscode.env.openExternal(vscode.Uri.parse(`https://docs.baldursgate3.game/index.php?title=${encodeURIComponent(name)}`));
  }));

  client = new LanguageClient('bg3-osiris', 'BG3 Osiris Language Server',
    { module: context.asAbsolutePath('lib/server.js'), transport: TransportKind.ipc },
    { documentSelector: [{ scheme: 'file', language: 'divinity-story-goal' }, { scheme: 'file', language: 'divinity-story-div' }],
      initializationOptions: { projectPath: config().get('projectPath'), enableDiagnostics: config().get('enableDiagnostics'), apiHeaderPaths: apiHeaders() },
      synchronize: { configurationSection: 'bg3Osiris', fileEvents: [
        vscode.workspace.createFileSystemWatcher('**/Story/{RawFiles/**,goals.raw}'),
        ...projects().map(project => vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(path.join(project, 'Story'), '{RawFiles/**,goals.raw}')))
      ] } });
  context.subscriptions.push(client.onNotification('bg3/goals', (goals: Goal[]) => outline.update(goals)));
  context.subscriptions.push(vscode.commands.registerCommand('bg3Osiris.refreshWorkspace', () => client?.sendNotification('bg3/refresh')));
  await client.start();
  await client.sendNotification('bg3/refresh');
}

export async function deactivate() { await client?.stop(); client = undefined; }
