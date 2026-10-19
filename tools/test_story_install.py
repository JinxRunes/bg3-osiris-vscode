from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import story_install as install


class StoryInstallTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]/'.local';root.mkdir(exist_ok=True)
        self.temporary=tempfile.TemporaryDirectory(prefix='story-install-',dir=root)
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name);self.project=self.root/'Mod';self.story=self.project/'Story'
        self.goal=self.story/'RawFiles/Goals/Test.txt';self.goal.parent.mkdir(parents=True);self.goal.write_text('initial source')
        self.old=b'\x00Osiris save file dd.old\x00'+b'x'*300
        (self.story/'story.div.osi').write_bytes(self.old)
        self.build=self.root/'build';self.build.mkdir()
        (self.build/'story.div.osi').write_bytes(b'\x00Osiris save file dd.new\x00'+b'y'*300)
        (self.build/'goals.raw').write_text('new compiled sources')
        self.inputs=install.inventory(self.project);self.outputs=install.working_hashes(self.project)
        self.report={'success':True,'compiled_osi_sha256':install.sha(self.build/'story.div.osi')}

    def test_success_is_installed_last_and_can_be_rolled_back(self):
        report=install.install(self.project,self.build,self.report,self.inputs,self.outputs)
        self.assertTrue(report['installed']);self.assertNotEqual((self.story/'story.div.osi').read_bytes(),self.old)
        install.rollback(self.project,self.build)
        self.assertEqual((self.story/'story.div.osi').read_bytes(),self.old)
        self.assertFalse((self.story/'goals.raw').exists())

    def test_stale_sources_and_competing_builds_cannot_replace_the_working_story(self):
        self.goal.write_text('changed while compiler ran')
        with self.assertRaisesRegex(RuntimeError,'inputs changed'):install.install(self.project,self.build,self.report,self.inputs,self.outputs)
        self.assertEqual((self.story/'story.div.osi').read_bytes(),self.old)
        self.inputs=install.inventory(self.project);(self.story/'story.div.osi').write_bytes(b'later build')
        with self.assertRaisesRegex(RuntimeError,'Another build'):install.install(self.project,self.build,self.report,self.inputs,self.outputs)
        self.assertEqual((self.story/'story.div.osi').read_bytes(),b'later build')

    def test_changed_artifacts_and_later_editor_changes_are_preserved(self):
        (self.build/'story.div.osi').write_bytes(b'\x00Osiris save file dd.changed\x00'+b'z'*300)
        with self.assertRaisesRegex(ValueError,'staged story changed'):install.install(self.project,self.build,self.report,self.inputs,self.outputs)
        self.report['compiled_osi_sha256']=install.sha(self.build/'story.div.osi')
        install.install(self.project,self.build,self.report,self.inputs,self.outputs)
        (self.story/'story.div.osi').write_bytes(b'new editor build')
        with self.assertRaisesRegex(RuntimeError,'later build'):install.rollback(self.project,self.build)
        self.assertEqual((self.story/'story.div.osi').read_bytes(),b'new editor build')

    def test_partial_copy_failure_restores_already_installed_outputs(self):
        original=install.os.replace
        def broken(source,target):
            if Path(target).name=='story.div.osi':raise OSError('locked story')
            return original(source,target)
        with patch.object(install.os,'replace',side_effect=broken):
            with self.assertRaisesRegex(OSError,'locked story'):install.install(self.project,self.build,self.report,self.inputs,self.outputs)
        self.assertEqual((self.story/'story.div.osi').read_bytes(),self.old)
        self.assertFalse((self.story/'goals.raw').exists())


if __name__=='__main__':unittest.main()
