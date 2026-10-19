const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {compilerInvocation}=require('../lib/compiler');
const common={extension:path.resolve('.'),project:'D:\\Mod source\\Test_UUID',state:'D:\\Build output\\Test'};

test('OsiCheck checks and builds never require a Toolkit path or preparation arguments',()=>{
  for(const action of ['check','build']) {
    const result=compilerInvocation({...common,action,selected:'auto',osicheck:'D:\\Tools\\OsiCheck'});
    assert.equal(result.backend,'osicheck');
    assert.equal(result.args[2],action);
    assert.ok(!result.args.includes('--toolkit'));
    assert.ok(!result.args.includes('prepare'));
    assert.equal(result.args[result.args.indexOf('--project')+1],common.project);
    assert.deepEqual(JSON.parse(result.args[result.args.indexOf('--base-mods')+1]),['Shared','SharedDev','Gustav','GustavDev','GustavX','Honour','HonourX']);
  }
});
test('Check always selects OsiCheck and reports the correct missing setting',()=>{
  assert.equal(compilerInvocation({...common,action:'check',backend:'toolkit',osicheck:'D:\\OsiCheck'}).backend,'osicheck');
  assert.throws(()=>compilerInvocation({...common,action:'check',selected:'toolkit'}),/OsiCheck Path/);
});
test('Toolkit remains available for explicit builds and preparation',t=>{
  const local=path.resolve('.local'); fs.mkdirSync(local,{recursive:true});
  const toolkit=fs.mkdtempSync(path.join(local,'compiler-selection-'));
  t.after(()=>{assert.ok(toolkit.startsWith(local+path.sep));fs.rmSync(toolkit,{recursive:true,force:true});});
  fs.writeFileSync(path.join(toolkit,'Osiris.dll'),'selection fixture');
  for(const settings of [{action:'build',selected:'toolkit'},{action:'prepare',selected:'osicheck'},{action:'build',selected:'auto'}]) {
    const result=compilerInvocation({...common,...settings,toolkit});
    assert.equal(result.backend,'toolkit'); assert.ok(result.args.includes('--toolkit'));
  }
  const selected=compilerInvocation({...common,action:'build',backend:'toolkit',selected:'auto',toolkit,osicheck:'D:\\OsiCheck'});
  assert.equal(selected.backend,'toolkit');
});
test('OsiCheck receives exact dependency lists and an explicitly empty exemption list',()=>{
  const result=compilerInvocation({...common,action:'build',selected:'osicheck',osicheck:'D:\\OsiCheck',dependencies:['Shared','Custom_UUID'],vanillaIssues:[]});
  assert.deepEqual(JSON.parse(result.args[result.args.indexOf('--base-mods')+1]),['Shared','Custom_UUID']);
  assert.deepEqual(JSON.parse(result.args[result.args.indexOf('--known-vanilla-issues')+1]),[]);
});
