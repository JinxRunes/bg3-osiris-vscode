"""Checks/builds isolated source-only projects; never changes installed game stories."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import osicheck_backend as tool


class OsiCheckTests(unittest.TestCase):
    osicheck = None
    data = None

    def test_invalid_compiler_and_data_paths_give_settings_guidance(self):
        with self.assertRaisesRegex(ValueError, 'OsiCheck Path'): tool.library_dir(Path(__file__).parent/'missing-compiler')
        with self.assertRaisesRegex(ValueError, 'Game Data Path'): tool.game_data(Path(__file__).parent, str(Path(__file__).parent/'missing-game'))

    def test_source_only_check_compile_and_failures(self):
        if not self.osicheck or not self.data:
            self.skipTest('Pass --osicheck and --game-data to test against the installed game.')
        local=(Path(__file__).resolve().parent.parent/'.local').resolve(); local.mkdir(exist_ok=True)
        live={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.data/'Mods').glob('*/Story/story.div.osi')}
        with tempfile.TemporaryDirectory(prefix='osicheck-test-',dir=local) as temporary:
            root=Path(temporary).resolve(); self.assertTrue(root.is_relative_to(local))
            project=root/'Standalone_Verification'; goals=project/'Story/RawFiles/Goals'; goals.mkdir(parents=True)
            goal=goals/'OSICHECK_Verification.txt'
            source=('Version 1\nSubGoalCombiner SGC_AND\nINITSECTION\nKBSECTION\n'
                    'IF\nUsingSpell(_Caster, _, _, _, _)\nTHEN\nSetArmourSet((CHARACTER)_Caster, ARMOURSET.Vanity);\n'
                    'IFF\nCharacterCreationStarted()\nTHEN\nDebugLog("OsiCheck IFF proof");\nEXITSECTION\nENDEXITSECTION\n')
            goal.write_text(source)
            self.assertEqual([p.name for p in goals.iterdir()],[goal.name])
            self.assertFalse((project/'Story/RawFiles/story_header.div').exists())
            self.assertFalse((project/'Story/goals.raw').exists())
            def run(action): return tool.run(action,project,self.osicheck,root/'state',str(self.data))
            checked=run('check'); self.assertTrue(checked['success'],checked)
            self.assertFalse((Path(checked['build'])/'story.div.osi').exists())
            self.assertTrue(Path(checked['header_file']).is_file())
            built=run('build'); self.assertTrue(built['success'],built)
            self.assertTrue(built['binary']['readback_verified'])
            self.assertTrue(built['binary']['enum_values_verified'])
            self.assertGreaterEqual(built['binary']['global_rules'],5)
            self.assertGreater(built['binary']['enums'],0)
            output=Path(built['build'])/'story.div.osi'
            self.assertEqual(tool.shared.sha(output),built['compiled_osi_sha256'])
            previous_report=(root/'state/last-build.json').read_bytes()
            bad=source.replace('DebugLog("OsiCheck IFF proof");','PROC_OSICHECK_Missing();')
            goal.write_text(bad)
            failed=run('check'); self.assertFalse(failed['success'])
            self.assertEqual((root/'state/last-build.json').read_bytes(),previous_report)
            diagnostic=next(d for d in failed['diagnostics'] if 'PROC_OSICHECK_Missing' in d['message'])
            self.assertEqual(Path(diagnostic['file']),goal)
            self.assertEqual(diagnostic['line'],bad.splitlines().index('PROC_OSICHECK_Missing();')+1)
            goal.write_text(source.replace('DebugLog("OsiCheck IFF proof");','DebugLog(1);'))
            wrong_type=run('check'); self.assertFalse(wrong_type['success'])
            self.assertTrue(any(d['code']=='E11' and Path(d['file'])==goal for d in wrong_type['diagnostics']))
            goal.write_text(source.replace('INITSECTION\n','INITSECTION\nDB_OSICHECK_Unused(1);\n'))
            failed_build=run('build'); self.assertFalse(failed_build['success'])
            self.assertTrue(any(d['code']=='E25' and 'DB_OSICHECK_Unused' in d['message'] for d in failed_build['diagnostics']))
            self.assertFalse((Path(failed_build['build'])/'story.div.osi').exists())
            goal.write_text(source+'ParentTargetEdge "OSICHECK_Verification"\n')
            cyclic=run('build'); self.assertFalse(cyclic['success'])
            self.assertIn('Cycle',cyclic['error'])
            self.assertFalse((Path(cyclic['build'])/'story.div.osi').exists())
            goal.write_text('IF\nCharacterCreationStarted()\nTHEN\nDebugLog("incomplete");')
            syntax=run('check'); self.assertFalse(syntax['success'])
            self.assertTrue(any(d['code']=='X00' and Path(d['file'])==goal for d in syntax['diagnostics']))
            self.assertEqual(tool.shared.sha(output),built['compiled_osi_sha256'])
            self.assertFalse((project/'Story/story.div.osi').exists())
            self.assertFalse((root/'state/baseline').exists())
        for path,before in live.items(): self.assertEqual(tool.shared.sha(path),before)
        print(json.dumps({'toolkit_independent_source_only':True,'check_without_output':True,
                          'enum_and_iff_roundtrip':True,'compiler_errors_preserved':True,
                          'failed_build_has_no_output':True,'cycle_rejected':True,'installed_stories_unchanged':True}))

    def test_package_only_inputs_fail_with_actionable_guidance(self):
        if not self.osicheck or not self.data:
            self.skipTest('Pass --osicheck and --game-data for the package-only integration test.')
        local=(Path(__file__).resolve().parent.parent/'.local').resolve(); local.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='osicheck-pak-only-',dir=local) as temporary:
            root=Path(temporary).resolve(); self.assertTrue(root.is_relative_to(local))
            project=root/'PakOnly_Verification'; goals=project/'Story/RawFiles/Goals'; goals.mkdir(parents=True)
            (goals/'OSICHECK_PakOnly.txt').write_text('Version 1\nSubGoalCombiner SGC_AND\nINITSECTION\nKBSECTION\nIFF\nCharacterCreationStarted()\nTHEN\nDebugLog("package-only");\nEXITSECTION\nENDEXITSECTION\n')
            report=tool.run('build',project,self.osicheck,root/'state',str(self.data),package_only=True)
            self.assertFalse(report['success'],report)
            self.assertIn('extracted story_header.div and raw dependency goals',report['error'])
            self.assertFalse((Path(report['build'])/'story.div.osi').exists())
            snapshots=list((Path(report['build'])/'inputs/Mods').iterdir())
            self.assertEqual([path.name for path in snapshots],[project.name])
            print(json.dumps({'retail_packages_alone_rejected_with_guidance':True,'failed_build_has_no_output':True}))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--osicheck',type=Path)
    parser.add_argument('--game-data',type=Path)
    args,rest=parser.parse_known_args()
    OsiCheckTests.osicheck=args.osicheck
    OsiCheckTests.data=args.game_data
    unittest.main(argv=[__file__,*rest])
