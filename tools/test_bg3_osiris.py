"""Integration checks against copied local module inputs; never installs a story."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import bg3_osiris as tool


class NativeBuildTests(unittest.TestCase):
    project = None
    toolkit = None

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
