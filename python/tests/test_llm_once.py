"""Model-free boundaries for the explicitly requested whole L0-L3 entrypoint."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from lifemate.llm_training import once
from lifemate.llm_training.config import load_config
from lifemate.llm_training.storage import write_json
from llm_support import SuiteFixture

ROOT = Path(__file__).resolve().parents[2]


class WholeSuiteTests(unittest.TestCase):
    def setUp(self):
        self.fx = SuiteFixture()
        self.addCleanup(self.fx.close)
        self.directory = self.fx.root/'workflow'
        self.directory.mkdir()
        self.lock = self.fx.root/'fake-full-lock.lock'
        self.lock.write_text('controlled test lock',encoding='utf-8')
        raw = __import__('json').loads(self.fx.config_path.read_text(encoding='utf-8'))
        export = self.fx.root/'asr'
        export.mkdir()
        write_json(export/'llm-handoff.json',{'controlled_presence_only':True})
        raw['asr_model_dir'] = str(export)
        for kind in ('fit','validation'):
            cache = self.fx.root/(kind+'.jsonl')
            cache.write_text('',encoding='utf-8')
            write_json(cache.with_suffix('.manifest.json'),{'controlled_presence_only':True})
            raw[kind+'_asr_cache'] = str(cache)
        write_json(self.fx.config_path,raw,exclusive=False)
        self.config = load_config(self.fx.config_path)
        self.calls = []

    def runner(self, fail=None, weighting=True):
        def run(root,directory,label,argv,accepted):
            self.calls.append((label,argv))
            if label==fail:
                raise once.WorkflowError('controlled failed gate')
            if label=='prepare':
                suite = Path(argv[argv.index('--suite-dir')+1])
                suite.mkdir()
                write_json(suite/'SEAL.json',{'identity':'controlled-suite'})
            if label in {'RV018','final-L0-L3'}:
                return {'comparison_dir':str(directory/label),'rows':[{'valid':True} for _ in range(8)],
                        'weighting_selection':{'status':'decided' if weighting else 'pending','selected_policy':'L1'}}
            if label=='Fit-ASR-views':
                return {'status':'authored_views','directory':str(directory/'views'),'approved':2}
            if label=='L0-audio-pilot':
                return {'status':'completed','evaluation_dir':str(directory/'pilot'),'pilot_status':'locally_feasible'}
            return {'status':next(iter(accepted)) if accepted else 'passed','directory':str(directory/label),
                    'evaluation_dir':str(directory/label)}
        return run

    def execute(self, fail=None, weighting=True, review=lambda _: 'controlled operator review'):
        with patch.object(once,'bootstrap',return_value=self.lock),patch.object(once,'smoke_rows'), \
             patch('lifemate.llm_training.corpus.load_suite',return_value={'partition':{}}), \
             patch('lifemate.llm_training.asr_views.CacheASR'):
            return once.workflow(ROOT,self.directory,self.config,ROOT/'fine-tune-llm/configs/training.json',
                'controlled-operator',run_phase=self.runner(fail,weighting),pilot_review=review)

    def test_complete_plan_trains_each_treatment_once_and_evaluates_all_eight_rows(self):
        self.execute()
        labels=[label for label,_ in self.calls]
        self.assertEqual([l for l in labels if l.endswith('-train')],['L1-train','L2-train','L3-train'])
        self.assertEqual(len([l for l in labels if l.endswith('-closed_loop')]),8)
        self.assertEqual(len([l for l in labels if l.endswith('-teacher_forced')]),8)
        self.assertLess(labels.index('L0-G-closed_loop'),labels.index('L1-train'))
        self.assertLess(labels.index('RV018'),labels.index('L3-train'))
        self.assertEqual(labels[-1],'final-L0-L3')
        self.assertFalse(any('resume' in arg for _,argv in self.calls for arg in argv))
        self.assertFalse(any('deployment' in label for label in labels))

    def test_failed_qualification_stops_before_any_training(self):
        with self.assertRaises(once.WorkflowError):
            self.execute(fail='full-probe')
        self.assertFalse(any(label.endswith('-train') for label,_ in self.calls))

    def test_missing_evaluation_assets_stop_before_preparation_and_gpu_probes(self):
        with self.assertRaises(once.WorkflowError):
            self.execute(fail='evaluation-inputs')
        labels=[label for label,_ in self.calls]
        self.assertEqual(labels[-1],'evaluation-inputs')
        self.assertNotIn('prepare',labels)
        self.assertNotIn('gpu-preflight',labels)
        self.assertNotIn('early-probe',labels)

    def test_unresolved_weighting_does_not_start_l3_or_make_up_a_policy(self):
        with self.assertRaisesRegex(once.WorkflowError,'RV018'):
            self.execute(weighting=False)
        self.assertEqual([l for l,_ in self.calls if l.endswith('-train')],['L1-train','L2-train'])

    def test_operator_refusal_stops_before_training(self):
        def refuse(_):
            raise once.WorkflowError('operator declined')
        with self.assertRaisesRegex(once.WorkflowError,'operator declined'):
            self.execute(review=refuse)
        self.assertFalse(any(label.endswith('-train') for label,_ in self.calls))

    def test_absent_asr_stops_before_package_install_or_prepare(self):
        (self.config.paths['asr_model_dir']/'llm-handoff.json').unlink()
        with patch.object(once,'bootstrap') as install:
            with self.assertRaisesRegex(once.WorkflowError,'certified selected-ASR'):
                once.workflow(ROOT,self.directory,self.config,ROOT/'fine-tune-llm/configs/training.json','operator')
            install.assert_not_called()
        self.assertFalse((self.directory/'suite').exists())

    def test_zero_exit_resource_unverified_is_not_a_pass(self):
        with self.assertRaisesRegex(once.WorkflowError,'unacceptable status'):
            once.phase(ROOT,self.directory,'uncertain',[sys.executable,'-c',
                       'print(\'{"status":"resource_unverified"}\')'],{'passed'})

    def test_lora_oom_reports_the_actual_reason_and_explicit_nf4_option(self):
        code = 'import json; print(json.dumps({"status":"resource_failed","reason":"CUDA out of memory", "binding":{"settings":{"method":"lora"}}})); raise SystemExit(4)'
        with self.assertRaisesRegex(once.WorkflowError,'CUDA out of memory.*-Method nf4'):
            once.phase(ROOT,self.directory,'failed-LoRA',[sys.executable,'-c',code],{'passed'})

    def test_failed_child_with_no_json_keeps_its_exit_and_evidence(self):
        with self.assertRaisesRegex(once.WorkflowError,'failed-child failed \\(exit 2\\)'):
            once.phase(ROOT,self.directory,'failed-child',[sys.executable,'-c',
                       'print("failed before JSON reporting"); raise SystemExit(2)'],{'passed'})

    def test_preview_does_not_read_resources_start_children_or_prompt(self):
        with patch.object(once,'load_config',side_effect=AssertionError('resource read')), \
             patch.object(once.subprocess,'Popen',side_effect=AssertionError('child')), \
             patch('builtins.input',side_effect=AssertionError('prompt')),contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(once.main(['--preview']),0)
        self.assertIn("'L0', 'L1', 'L2', 'L3'",output.getvalue())

    def test_failed_pilot_cannot_be_marked_reviewed(self):
        with patch('builtins.input',side_effect=AssertionError('must stop before asking')):
            with self.assertRaisesRegex(once.WorkflowError,'not locally_feasible'):
                once.review_pilot({'pilot_status':'at_risk'})

    def test_existing_other_nvml_version_is_not_silently_replaced(self):
        from types import SimpleNamespace
        config = SimpleNamespace(source={'environment_profile':'windows-py312-cu128'})
        with patch('lifemate.llm_training.resources.validate_lock'),patch.object(once,'version',return_value='other'):
            with self.assertRaisesRegex(once.WorkflowError,'refusing to change'):
                once.bootstrap(ROOT,self.directory,config,lambda *args:self.fail('package mutation'))

    def test_measurement_profile_preserves_parent_pins_and_records_the_extra_wheel(self):
        from types import SimpleNamespace
        from lifemate.llm_training.storage import read_json,file_hash
        base = ROOT/'fine-tune-llm/locks/windows-py312-cu128.lock'
        before = file_hash(base)
        config = SimpleNamespace(source={'environment_profile':'windows-py312-cu128'},require=lambda _:base)
        calls=[]
        with patch('lifemate.llm_training.resources.validate_lock'),patch.object(once,'version',return_value=once.NVML_VERSION):
            derived = once.bootstrap(ROOT,self.directory,config,lambda *args:calls.append(args[2]))
        metadata = read_json(derived.with_suffix('.manifest.json'))
        parent = read_json(base.with_suffix('.manifest.json'))
        self.assertEqual(metadata['packages'],parent['packages']|{'nvidia-ml-py':once.NVML_VERSION})
        self.assertEqual(metadata['wheels'],38)
        self.assertEqual(metadata['parent_lock_sha256'],before)
        self.assertEqual(metadata['lock_sha256'],file_hash(derived))
        self.assertEqual(file_hash(base),before)
        self.assertEqual(calls,['pip-check'])

    def asr_orchestration(self):
        from lifemate.llm_training.storage import file_hash
        from lifemate.llm_training.config import content_hash
        export=self.config.paths['asr_model_dir']
        (export/'llm-handoff.json').unlink()
        write_json(export/'files.json',{'controlled-source-file':'x'*64})
        approval=self.fx.root/'.agent-work/approval.json'
        approval.parent.mkdir(parents=True,exist_ok=True)
        write_json(approval,{'explicit_user_approval':'E4 cache creation'})
        job=self.fx.root/'.agent-work/llm-asr/explicit-job'
        job.mkdir(parents=True)
        write_json(job/'job.json',{'controlled_resume_binding':True})
        record={'schema':'lifemate-llm-orchestration-v1','prepare_asr_if_missing':True,
            'selection':{'experiment':'E4','accept_provisional':True,'approval_file':str(approval),
                'approval_sha256':file_hash(approval),'source_export':str(export),
                'source_export_files_sha256':content_hash({'controlled-source-file':'x'*64})},
            'resume_asr_job':str(job),'resume_job_sha256':file_hash(job/'job.json')}
        path=self.fx.root/'orchestration.json'
        write_json(path,record)
        return path,record,job

    def test_ready_asr_is_reused_without_repreparation(self):
        ready=once.ensure_asr(self.fx.root,self.directory,self.fx.config_path,self.fx.root/'absent.json',
                              run_phase=lambda *args:self.fail('must reuse ready ASR'))
        self.assertEqual(ready.paths,self.config.paths)

    def test_combined_command_resumes_only_the_explicitly_bound_asr_job(self):
        path,record,job=self.asr_orchestration()
        calls=[]
        def prepare(root,directory,label,argv,accepted):
            calls.append((label,argv))
            write_json(self.config.paths['asr_model_dir']/'llm-handoff.json',{'controlled-ready':True})
        ready=once.ensure_asr(self.fx.root,self.directory,self.fx.config_path,path,run_phase=prepare)
        self.assertEqual(calls[0][0],'prepare-ASR')
        argv=calls[0][1]
        self.assertEqual(argv[argv.index('--resume')+1],str(job))
        self.assertIn('--accept-provisional-e4',argv)
        self.assertEqual(ready.paths['asr_model_dir'],self.config.paths['asr_model_dir'])

    def test_changed_operator_approval_blocks_combined_asr_preparation(self):
        path,record,job=self.asr_orchestration()
        write_json(Path(record['selection']['approval_file']),{'changed':True},exclusive=False)
        with self.assertRaisesRegex(once.WorkflowError,'approval'):
            once.ensure_asr(self.fx.root,self.directory,self.fx.config_path,path,
                            run_phase=lambda *args:self.fail('unapproved ASR execution'))

    def test_changed_resume_job_is_not_replaced_with_an_arbitrary_latest_job(self):
        path,record,job=self.asr_orchestration()
        write_json(job/'job.json',{'changed':True},exclusive=False)
        with self.assertRaisesRegex(once.WorkflowError,'resume job'):
            once.ensure_asr(self.fx.root,self.directory,self.fx.config_path,path,
                            run_phase=lambda *args:self.fail('wrong-job resume'))

    def test_asr_failure_prevents_the_combined_command_from_starting_llm_workflow(self):
        with patch.object(once,'ensure_asr',side_effect=once.WorkflowError('ASR failed')), \
             patch.object(once,'workflow') as models,contextlib.redirect_stderr(io.StringIO()), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(once.main(['--config',str(self.fx.config_path)]),1)
        models.assert_not_called()

    def test_combined_entry_runs_asr_preparation_before_the_whole_llm_workflow(self):
        order=[]
        def prepared(*args):
            order.append('ASR')
            return self.config
        def train(*args,**kwargs):
            order.append('L0-L3')
            return {'controlled-comparison':True}
        with patch.object(once,'ensure_asr',side_effect=prepared),patch.object(once,'workflow',side_effect=train), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(once.main(['--config',str(self.fx.config_path)]),0)
        self.assertEqual(order,['ASR','L0-L3'])


if __name__=='__main__':
    unittest.main()
