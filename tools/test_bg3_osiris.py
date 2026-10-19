"""Integration checks against copied local module inputs; never installs a story."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import bg3_osiris as tool


class NativeBuildTests(unittest.TestCase):
    project = None
    toolkit = None

    def test_prepare_accepts_drafts_and_failed_refresh_preserves_completed_baseline(self):
        local = (Path(__file__).resolve().parent.parent / '.local').resolve()
        local.mkdir(exist_ok=True)
        saved = {name: getattr(tool, name) for name in ['TOOLKIT','STORY','GOALS','ROOT','CACHE','BUILDS','BACKUPS','NATIVE','DOTNET','MODULE']}
        try:
            with tempfile.TemporaryDirectory(prefix='bg3-prepare-test-', dir=local) as temporary:
                root=Path(temporary).resolve(); self.assertTrue(root.is_relative_to(local))
                project=root/'Test_Module'; story=project/'Story'; goals=story/'RawFiles/Goals'
                goals.mkdir(parents=True)
                raw=('version "0.0.6.1"\nGoal(1).Title("Dependency");\nGoal(1)\n{\n'
                     '\tINIT\n\t{\n\t}\n\tKB\n\t{\n\t}\n\tEXIT\n\t{\n\t}\n}\n')
                tool.write_text(story/'goals.raw',raw)
                for name in ['story_header.div','story_definitions.div']: tool.write_text(story/'RawFiles'/name,'')
                tool.write_text(story/'story_orphanqueries_ignore.txt','')
                tool.write_text(story/'log.txt','0 error(s), 0 warning(s). Compilation ended.')
                (story/'story.div.osi').write_bytes(b'fixture baseline')
                # Reproduce the user's empty goal at the time Prepare was run.
                draft=goals/'ASC_Debug.txt'; draft.write_text('')
                tool.configure(project, root/'toolkit', root/'state')
                with tool.locked():
                    metadata=tool.seed()
                    self.assertIn('ASC_Debug',metadata['draft_goals'])
                    self.assertIn('ASC_Debug',metadata['uncompiled_goals'])
                    self.assertEqual(tool.baseline(),metadata)
                    with self.assertRaisesRegex(ValueError,r'ASC_Debug\.txt: Expected exactly one'):
                        tool.preflight_source(draft)
                    original=(tool.CACHE/'seed.json').read_bytes()
                    with patch.object(tool.shutil,'copy2',side_effect=OSError('simulated read failure')):
                        with self.assertRaisesRegex(OSError,'simulated read failure'): tool.seed()
                    self.assertEqual((tool.CACHE/'seed.json').read_bytes(),original)
                    self.assertEqual(tool.baseline(),metadata)
                    self.assertEqual(list(tool.ROOT.glob('baseline.preparing-*')),[])
                    # The same source is still compared once the goal is completed.
                    tool.write_text(draft,'Version 1\nSubGoalCombiner SGC_AND\nINITSECTION\nKBSECTION\nEXITSECTION\nENDEXITSECTION\n')
                    tool.seed()
                    self.assertEqual(tool.baseline()['draft_goals'],{})
                    self.assertEqual(len(list(tool.ROOT.glob('baseline.previous-*'))),1)
        finally:
            for name,value in saved.items(): setattr(tool,name,value)

    def test_native_iff_preserves_binary_graph_with_only_global_goal_reference_difference(self):
        if not self.project or not self.toolkit:
            self.skipTest('Pass --project and --toolkit to run the native IFF preservation check.')
        local = (Path(__file__).resolve().parent.parent / '.local').resolve()
        local.mkdir(exist_ok=True)
        source=tool.read_text(self.project/'Story/story.div')
        probe_id=max(int(value) for value in re.findall(r'^Goal\((\d+)\)\.Title',source,re.M))+1
        probe=(f'\nGoal({probe_id}).Title("BG3_IFF_Regression");\nGoal({probe_id})\n{{\n'
               '\tINIT\n\t{\n\t}\n\tKB\n\t{\n'
               '\t\tIF\n\t\tCharacterCreationStarted()\n\t\tTHEN\n\t\tDebugLog("BG3_IF_CONTROL");\n'
               '\t\tIFF\n\t\tCharacterCreationStarted()\n\t\tTHEN\n\t\tDebugLog("BG3_IFF_PROBE");\n'
               '\t}\n\tEXIT\n\t{\n\t}\n}\n')
        before=tool.sha(self.project/'Story/story.div.osi')
        with tempfile.TemporaryDirectory(prefix='bg3-iff-test-',dir=local) as temporary:
            root=Path(temporary).resolve(); self.assertTrue(root.is_relative_to(local))
            tool.configure(self.project,self.toolkit,root/'state'); tool.ensure_tools()
            payloads={}
            for variant in ['iff','if']:
                target=root/variant; target.mkdir()
                tool.write_text(target/'story.div',source+(probe if variant=='iff' else probe.replace('\t\tIFF\n','\t\tIF\n')))
                shutil.copy2(self.project/'Story/story_orphanqueries_ignore.txt',target/'story_orphanqueries_ignore.txt')
                result=subprocess.run([tool.DOTNET,str(tool.WORKER),str(tool.NATIVE),tool.NATIVE_SHA,
                                       str(target/'story.div'),str(target/'story.div.osi'),str(target/'log.txt')],
                                      capture_output=True,text=True,timeout=180)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertEqual(tool.COMPILE_SUMMARY.findall(tool.read_text(target/'log.txt'))[-1],('0','0'))
                data=(target/'story.div.osi').read_bytes()
                payloads[variant]=data[data.index(b'\0',1)+1:]
            iff,ordinary=payloads['iff'],payloads['if']
            self.assertEqual(len(iff),len(ordinary))
            different=[index for index,(a,b) in enumerate(zip(iff,ordinary)) if a!=b]
            self.assertTrue(different,'IFF and IF must retain different activation semantics')
            offsets=[index for index in range(max(0,different[0]-3),different[0]+1)
                     if iff[index:index+4]==bytes(4) and ordinary[index:index+4]==probe_id.to_bytes(4,'little')]
            self.assertEqual(len(offsets),1)
            offset=offsets[0]
            # Direct graph inspection establishes this field as NodeEntryItem.GoalRef.
            # IFF keeps the rule and incoming event link with global goal 0.
            self.assertEqual(iff[offset:offset+4],bytes(4))
            self.assertEqual(ordinary[offset:offset+4],probe_id.to_bytes(4,'little'))
            self.assertEqual(iff[:offset],ordinary[:offset])
            self.assertEqual(iff[offset+4:],ordinary[offset+4:])
            self.assertEqual(tool.sha(self.project/'Story/story.div.osi'),before)
            print(json.dumps({'iff_graph_preserved':True,'global_goal_reference':0,
                              'if_goal_reference':probe_id,'changed_bytes':len(different),'live_story_unchanged':True}))

    def test_native_build_and_failure_locations(self):
        if not self.project or not self.toolkit:
            self.skipTest('Pass --project and --toolkit to run the native compiler integration test.')
        live = self.project / 'Story/story.div.osi'
        before = tool.sha(live)
        local = (Path(__file__).resolve().parent.parent / '.local').resolve()
        local.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='bg3-native-test-', dir=local) as temporary:
            root = Path(temporary)
            assert root.resolve().is_relative_to(local)
            project = root / self.project.name
            story = project / 'Story'
            (story / 'RawFiles/Goals').mkdir(parents=True)
            for name in ['goals.raw', 'story_orphanqueries_ignore.txt', 'log.txt', 'story.div.osi']:
                shutil.copy2(self.project / 'Story' / name, story / name)
            for name in ['story_header.div', 'story_definitions.div']:
                shutil.copy2(self.project / 'Story/RawFiles' / name, story / 'RawFiles' / name)
            for goal in (self.project / 'Story/RawFiles/Goals').glob('*.txt'):
                shutil.copy2(goal, story / 'RawFiles/Goals' / goal.name)
            tool.configure(project, self.toolkit, root / 'state')
            tool.ensure_tools()
            with tool.locked():
                tool.seed()
                baseline = tool.compile_build()
                self.assertTrue(baseline['success'], baseline.get('diagnostic_tail'))
                # Serializer embeds a timestamp; compare all bytes following that field.
                def payload(path):
                    data = path.read_bytes()
                    return data[data.index(b'\0', 1) + 1:]
                self.assertEqual(hashlib.sha256(payload(Path(baseline['build']) / 'story.div.osi')).hexdigest(),
                                 hashlib.sha256(payload(live)).hexdigest())
                added = story / 'RawFiles/Goals/BG3_Extension_Verification.txt'
                source = ('Version 1\nSubGoalCombiner SGC_AND\nINITSECTION\nKBSECTION\n\n'
                          'IF\nUsingSpell(_Caster, _, _, _, _)\nTHEN\n\n'
                          'SetArmourSet((CHARACTER)_Caster, ARMOURSET.Normal);\n'
                          'EXITSECTION\nENDEXITSECTION\nParentTargetEdge "__Start"\n')
                tool.write_text(added, source)
                valid = tool.compile_build()
                self.assertTrue(valid['success'], valid.get('diagnostic_tail'))
                tool.write_text(added, source.replace('SetArmourSet((CHARACTER)_Caster, ARMOURSET.Normal);', 'PROC_BG3_Missing_Verification(_Caster);'))
                failed = tool.compile_build()
                self.assertFalse(failed['success'])
                self.assertFalse((Path(failed['build']) / 'story.div.osi').exists())
                tool.locate_diagnostics(failed)
                location = next(d for d in failed['diagnostics'] if 'PROC_BG3_Missing_Verification' in d['message'])
                self.assertEqual(Path(location['file']), added)
                self.assertEqual(location['line'], 10)
                # The user's unsupported HasFlag query uses a different native error format.
                unknown_query=source.replace('THEN\n\n','AND\nNOT HasFlag(_Caster, "CharacterCreationStarted")\nTHEN\n\n',1)
                tool.write_text(added,unknown_query)
                failed_query=tool.compile_build()
                self.assertFalse(failed_query['success'])
                tool.locate_diagnostics(failed_query)
                query_location=next(d for d in failed_query['diagnostics'] if 'HasFlag' in d['message'])
                self.assertEqual(Path(query_location['file']),added)
                self.assertEqual(query_location['line'],unknown_query.splitlines().index('NOT HasFlag(_Caster, "CharacterCreationStarted")')+1)
            tool.write_text(added, source)
            existing = next(p for p in (story / 'RawFiles/Goals').glob('*.txt') if p != added)
            edited = tool.read_text(existing).replace('INITSECTION\n', 'INITSECTION\nDB_BG3_PrepareRegression(1);\n', 1)
            tool.write_text(existing, edited)
            tool.configure(project, self.toolkit, root / 'state-before-prepare-edit')
            with tool.locked():
                metadata = tool.seed()
                self.assertIn(existing.stem, metadata['uncompiled_goals'])
                before_prepare = tool.compile_build()
                self.assertIn('DB_BG3_PrepareRegression', tool.read_text(Path(before_prepare['build']) / 'goals.raw'))
                self.assertEqual(before_prepare['errors'], 0)
                self.assertEqual(before_prepare['warnings'], 1)
                self.assertFalse(before_prepare['success'])
                self.assertIn('native compiler rejected', before_prepare['error'])
                # The native Toolkit compiler refuses an unused database warning.
                tool.write_text(existing, edited.replace('KBSECTION\n', 'KBSECTION\nIF\nDB_BG3_PrepareRegression(1)\nTHEN\nNOT DB_BG3_PrepareRegression(1);\n', 1))
                checked = tool.compile_build()
                self.assertTrue(checked['success'], checked.get('diagnostic_tail'))
            self.assertEqual(tool.sha(live), before)
            print(json.dumps({'baseline_matches_toolkit': True, 'bg3_enum_compiles': True,
                              'invalid_proc_rejected': True, 'diagnostic_line': location['line'],
                              'preparation_preserves_existing_edits': True, 'native_warning_policy_respected': True,
                              'live_story_unchanged': True}))

    def test_section_validation_rejects_missing_markers(self):
        with self.assertRaises(ValueError): tool.source_sections('KBSECTION\nnot a goal')

    def test_os_lock_blocks_competing_build_and_releases_without_deleting_file(self):
        local = (Path(__file__).resolve().parent.parent / '.local').resolve()
        local.mkdir(exist_ok=True)
        previous = tool.ROOT
        with tempfile.TemporaryDirectory(prefix='bg3-lock-test-', dir=local) as temporary:
            root = Path(temporary).resolve()
            assert root.is_relative_to(local)
            tool.ROOT = root
            try:
                script = ('import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); '
                          'import bg3_osiris as t; t.ROOT=Path(sys.argv[2]); '\
                          '\ntry:\n with t.locked(): sys.exit(2)\nexcept RuntimeError: sys.exit(0)\n')
                with tool.locked():
                    result = subprocess.run([sys.executable, '-c', script, str(Path(__file__).parent), str(root)], timeout=5)
                    self.assertEqual(result.returncode, 0)
                with tool.locked():
                    self.assertTrue((root / 'build.lock').exists())
            finally:
                tool.ROOT = previous


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path)
    parser.add_argument('--toolkit', type=Path)
    args, other = parser.parse_known_args()
    NativeBuildTests.project = args.project
    NativeBuildTests.toolkit = args.toolkit
    unittest.main(argv=[__file__, *other])
