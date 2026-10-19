const { test } = require('node:test');
const assert = require('node:assert/strict');
const language = require('../lib/language');

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
test('signature help ignores commas in strings and parentheses in type annotations', () => {
  const source = 'CastedSpell((CHARACTER)_Caster, "name, with comma", ';
  assert.deepEqual(language.activeCall(source, source.length), { name: 'CastedSpell', argument: 2 });
});
