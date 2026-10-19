const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { fork } = require('node:child_process');

for (const workspace of ['module', 'Story', 'RawFiles', 'Goals', 'standalone', 'cached-api', 'generated-api']) {
test(`real language server discovers ${workspace} and serves BG3 editing features`, { timeout: 20000 }, async t => {
  const local = path.resolve('.local'); fs.mkdirSync(local, { recursive: true });
  const root = fs.mkdtempSync(path.join(local, 'bg3-osiris-lsp-'));
  const goals = path.join(root, 'Story/RawFiles/Goals'); fs.mkdirSync(goals, { recursive: true });
  const header = `enum_type {ARMOURSET, 34, 0, Normal = 0, Vanity = 1}
event CastedSpell((GUIDSTRING)_Caster, (STRING)_Spell, (STRING)_SpellType, (STRING)_SpellElement, (INTEGER)_StoryActionID) (3,0,1182,1)\n`;
  const headerPath=path.join(root, ['cached-api','generated-api'].includes(workspace) ? 'cached-api.div' : 'Story/RawFiles/story_header.div');
  fs.writeFileSync(headerPath, header);
  const source = 'Version 1\nSubGoalCombiner SGC_AND\nINITSECTION\nKBSECTION\nIF\nCastedSpell(_Caster, _, _, _, _)\nTHEN\nDebugText(_Caster, "test");\nEXITSECTION\nENDEXITSECTION\n';
  const goal = path.join(goals, 'Test.txt'); fs.writeFileSync(goal, source);
  const uri = pathToFileURL(goal).href;
  const child = fork(path.resolve('lib/server.js'), ['--node-ipc'], { silent: true });
  t.after(() => { child.kill(); assert.ok(root.startsWith(local + path.sep)); fs.rmSync(root, { recursive: true, force: true }); });
  let nextId = 1, stderr = ''; const pending = new Map(), notices = [];
  child.stderr.on('data', chunk => { stderr += chunk; });
  child.on('message', message => {
    if (message.id !== undefined && pending.has(message.id)) {
      const callback = pending.get(message.id); pending.delete(message.id);
      message.error ? callback.reject(new Error(JSON.stringify(message.error))) : callback.resolve(message.result);
    } else notices.push(message);
  });
  child.on('exit', code => { for (const callback of pending.values()) callback.reject(new Error(`Server exited ${code}: ${stderr}`)); });
  const notify = (method, params) => child.send({ jsonrpc: '2.0', method, params });
  const request = (method, params) => new Promise((resolve, reject) => {
    const id = nextId++; const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`Timed out: ${method}; ${stderr}`)); }, 8000);
    pending.set(id, { resolve: result => { clearTimeout(timeout); resolve(result); }, reject: error => { clearTimeout(timeout); reject(error); } });
    child.send({ jsonrpc: '2.0', id, method, params });
  });
  const workspacePath = { module: root, Story: path.join(root, 'Story'), RawFiles: path.dirname(goals), Goals: goals }[workspace];
  const initialized = await request('initialize', { processId: process.pid, capabilities: {}, workspaceFolders: workspacePath ? [{ uri: pathToFileURL(workspacePath).href, name: 'Test' }] : null,
    initializationOptions: { apiHeaderPaths: workspace==='cached-api' ? [headerPath] : [] } });
  assert.ok(initialized.capabilities.signatureHelpProvider);
  notify('initialized', {});
  notify('textDocument/didOpen', { textDocument: { uri, languageId: 'divinity-story-goal', version: 1, text: source } });
  if(workspace==='generated-api') {
    const before=await request('textDocument/completion', { textDocument: { uri }, position: { line: 5, character: 5 } });
    assert.ok(!before.some(item=>item.label==='CastedSpell'));
    notify('bg3/apiHeaders',{paths:[headerPath]});
  }
  const completion = await request('textDocument/completion', { textDocument: { uri }, position: { line: 5, character: 5 } });
  assert.ok(completion.some(item => item.label === 'CastedSpell'));
  assert.ok(completion.some(item => item.label === 'IFF'));
  const hover = await request('textDocument/hover', { textDocument: { uri }, position: { line: 5, character: 3 } });
  assert.match(hover.contents.value, /_StoryActionID/);
  const signature = await request('textDocument/signatureHelp', { textDocument: { uri }, position: { line: 5, character: 24 } });
  assert.equal(signature.signatures[0].parameters.length, 5);
  assert.ok(notices.some(item => item.method === 'bg3/goals' && item.params[0].some(goal => goal.uri === uri && goal.module === root)));
  const symbols = await request('textDocument/documentSymbol', { textDocument: { uri } });
  assert.equal(symbols[0].name, 'IF CastedSpell');
  const bare = 'IF\nLeveledUp\nTHEN\nApplyStatus("DebugMode", 1);';
  notify('textDocument/didChange', { textDocument: { uri, version: 2 }, contentChanges: [{ text: bare }] });
  // A request after the change acts as a barrier for queued IPC notifications.
  await request('textDocument/documentSymbol', { textDocument: { uri } });
  const diagnostic = notices.filter(item => item.method === 'textDocument/publishDiagnostics' && item.params.version === 2).at(-1);
  assert.equal(diagnostic.params.diagnostics.length, 1);
  assert.equal(diagnostic.params.diagnostics[0].code, 'bg3-goal-sections');
  notify('textDocument/didChange', { textDocument: { uri, version: 3 }, contentChanges: [{ text: source.replace('\nIF\n','\nIFF\n') }] });
  const globalSymbols = await request('textDocument/documentSymbol', { textDocument: { uri } });
  assert.equal(globalSymbols[0].name, 'IFF CastedSpell');
  const globalDiagnostics=notices.filter(item=>item.method==='textDocument/publishDiagnostics' && item.params.version===3).at(-1);
  assert.deepEqual(globalDiagnostics.params.diagnostics,[]);
  await request('shutdown', null); notify('exit');
});
}
