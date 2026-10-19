const { test } = require('node:test');
const assert = require('node:assert/strict');
const language = require('../lib/language');
const fs = require('node:fs');
const path = require('node:path');

const header = `alias_type {CHARACTER, 6, 5}
enum_type {ARMOURSET, 34, 0, Normal = 0, Vanity = 1}
event CastedSpell((GUIDSTRING)_Caster, (STRING)_Spell, (STRING)_SpellType, (STRING)_SpellElement, (INTEGER)_StoryActionID) (3,0,1182,1)
query GetGold([in](GUIDSTRING)_InventoryHolder, [out](INTEGER)_Amount) (2,0,561,1)`;
const goal = `Version 1
SubGoalCombiner SGC_AND
INITSECTION
KBSECTION
IF
CastedSpell(_Caster, _, _, _, _)
THEN
SetArmourSet((CHARACTER)_Caster, ARMOURSET.Normal);
EXITSECTION
ENDEXITSECTION
ParentTargetEdge "__Start"
`;
module.exports = { header, goal };

test('BG3 header preserves all five event parameters and query OUT flow', () => {
  const result = language.signatures(header, 'file:///header.div', true);
  assert.equal(result[0].parameters.length, 5);
  assert.equal(result[0].parameters[4].name, '_StoryActionID');
  assert.equal(result[1].parameters[1].flow, 'out');
});
test('typed user procedures and queries retain argument counts', () => {
  const result = language.signatures('PROC\nPROC_Test((CHARACTER)_Caster, (INTEGER)_Gold)\nTHEN\nDB_Test(_Gold);', 'file:///goal.txt', false);
  assert.equal(result[0].parameters.length, 2);
  assert.equal(result[0].parameters[0].type, 'CHARACTER');
});
test('current BG3 enums parse without moving source offsets or replacing strings/comments', () => {
  const enums = language.headerEnums(header);
  const result = language.enumNormalized(goal + '// ARMOURSET.Normal\n', enums);
  assert.equal(result.text.length, goal.length + '// ARMOURSET.Normal\n'.length);
  assert.match(result.text, /\/\/ ARMOURSET.Normal/);
  assert.deepEqual(language.syntaxIssues(goal, enums), []);
  assert.match(language.syntaxIssues(goal.replace('ARMOURSET.Normal', 'ARMOURSET.Missing'), enums)[0].message, /Unknown BG3 enum/);
});
test('syntax diagnostics catch missing action semicolons', () => {
  assert.ok(language.syntaxIssues(goal.replace('ARMOURSET.Normal);', 'ARMOURSET.Normal)'), language.headerEnums(header)).length > 0);
});
test('IFF global rules retain their keyword and accept the same rule syntax', () => {
  const source = goal.replace('\nIF\n','\nIFF\n');
  assert.deepEqual(language.syntaxIssues(source,language.headerEnums(header)),[]);
  assert.equal(language.syntaxIssues('IFF\nCharacterCreationStarted()\nTHEN\nDebugLog("test");',new Map())[0].code,'bg3-goal-sections');
});
test('signature help ignores commas in strings and parentheses in type annotations', () => {
  const source = 'CastedSpell((CHARACTER)_Caster, "name, with comma", ';
  assert.deepEqual(language.activeCall(source, source.length), { name: 'CastedSpell', argument: 2 });
});
test('bare rules explain the required goal sections without cascading token errors', () => {
  const source = '// KBSECTION in a comment is not a section\nIF\nLeveledUp\nTHEN\nApplyStatus("DebugMode", 1);\n';
  const issues = language.syntaxIssues(source, new Map());
  assert.equal(issues.length, 1);
  assert.equal(issues[0].code, 'bg3-goal-sections');
  assert.match(issues[0].message, /KBSECTION/);
  assert.equal(source.slice(issues[0].offset, issues[0].endOffset), 'IF');
  const snippet = require('../syntaxes/divinity-story-goal.snippets.json')['BG3 goal file'];
  assert.equal(snippet.prefix, 'goal');
  const expanded = snippet.body.join('\n').replace('$0', 'IF\nLeveledUp(_Character)\nTHEN\nApplyStatus(_Character, "DebugMode", -1.0, 1, _Character);').replace('${1:__Start}', '__Start');
  assert.deepEqual(language.syntaxIssues(expanded, new Map()), []);
});
test('project discovery handles module subfolders, explicit overrides, and standalone files', t => {
  const local = path.resolve('.local'); fs.mkdirSync(local, { recursive: true });
  const base = fs.mkdtempSync(path.join(local, 'bg3-osiris-discovery-'));
  t.after(() => { assert.ok(base.startsWith(local + path.sep)); fs.rmSync(base, { recursive: true, force: true }); });
  const moduleRoot = path.join(base, 'Data/Mods/Test_UUID');
  const goals = path.join(moduleRoot, 'Story/RawFiles/Goals'); fs.mkdirSync(goals, { recursive: true });
  const goal = path.join(goals, 'Test.txt'); fs.writeFileSync(goal, '');
  const header = path.join(moduleRoot, 'Story/RawFiles/story_header.div'); fs.writeFileSync(header, '');
  const inputs = [moduleRoot, path.dirname(path.dirname(goals)), path.dirname(goals), goals, goal, header];
  for (const input of inputs) {
    assert.deepEqual(language.findProjectRoots([input]), [moduleRoot], `workspace: ${input}`);
    assert.deepEqual(language.findProjectRoots([], input), [moduleRoot], `configured: ${input}`);
  }
  assert.deepEqual(language.findProjectRoots([path.join(base, 'Data')]), [moduleRoot]);
  assert.deepEqual(language.findProjectRoots([], undefined, [goal]), [moduleRoot]);
  assert.deepEqual(language.findProjectRoots([goals, moduleRoot], undefined, [goal]), [moduleRoot]);
  assert.deepEqual(language.findProjectRoots([moduleRoot], path.join(base, 'Missing'), [goal]), []);
  assert.deepEqual(language.findProjectRoots([path.join(base, 'Missing')]), []);
});
