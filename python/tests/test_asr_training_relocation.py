"""Imported evidence keeps its bytes while consumers use explicitly relocated paths."""
import json
import tempfile
import unittest
from pathlib import Path

from lifemate.asr_training.relocation import operational_view, resolve_path
from lifemate.asr_training.comparison_artifacts import owned_evaluation
from lifemate.jsonio import digest
from lifemate.contracts import PipelineError


class RelocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'new project with spaces'
        self.suite = self.root/'.agent-work/asr-finetune/suite-01'
        self.suite.mkdir(parents=True)
        self.original = 'D:/old-project'
        self.metadata = self.suite/'suite.json'
        self.metadata.write_text('{"identity":"original-evidence"}\n', encoding='utf-8')
        self.mapping = {'schema':'lifemate-asr-relocation-v1','source_roots':[self.original],
                        'project_root':'../../..','suite_sha256':digest(self.metadata)}
        (self.suite/'relocation.json').write_text(json.dumps(self.mapping),encoding='utf-8')

    def test_path_remap_does_not_modify_original_evidence(self):
        before = self.metadata.read_bytes()
        value = self.original+'/.agent-work/asr-finetune/suite-01/E4/run/export'
        expected = self.suite/'E4/run/export'
        self.assertEqual(resolve_path(value,self.suite),expected)
        self.assertEqual(self.metadata.read_bytes(),before)
        self.assertEqual(operational_view({'export':value,'sha256':'unchanged'},self.suite),
                         {'export':str(expected),'sha256':'unchanged'})

    def test_prefix_boundary_and_relative_paths_are_preserved(self):
        other = self.original+'-other/model'
        self.assertEqual(resolve_path(other,self.suite),Path(other))
        self.assertEqual(resolve_path('relative/model',self.suite),Path('relative/model'))

    def test_changed_suite_invalidates_registered_mapping(self):
        self.metadata.write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'suite hash'):
            resolve_path(self.original+'/model',self.suite)

    def test_mapping_cannot_escape_or_open_hidden_environments(self):
        for value in (self.original+'/../../outside',self.original+'/train_environment/state.json',
                      self.original+'/train_enviroment/state.json'):
            with self.assertRaises((ValueError, PipelineError)):
                resolve_path(value,self.suite)

    def test_comparison_uses_owning_relocated_run(self):
        run = self.suite/'E4/run'
        run.mkdir(parents=True)
        original = self.original+'/.agent-work/asr-finetune/suite-01/E4/run/primary'
        self.assertEqual(owned_evaluation(self.suite,run,original),run/'primary')
        with self.assertRaises(ValueError):
            owned_evaluation(self.suite,run,self.original+'/.agent-work/asr-finetune/suite-01/E1/run/primary')


if __name__=='__main__':
    unittest.main()
