"""Model-free policy, provenance, data, memory and manual lifecycle checks."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lifemate.jsonio import dumps
from lifemate.model_budget import check_budget
from lifemate.asr_training.config import DEFAULTS, load_config, prerequisites, binding
from lifemate.asr_training.data import project, load_suite
from lifemate.asr_training.storage import write, read, seal, verify, suite_lock, outcome
from lifemate.asr_training.resources import Memory, ResourceLimit, hardware
from lifemate.asr_training.checkpoints import load as load_checkpoint
from lifemate.asr_training.cli import parser, process_alive
from lifemate.asr_training.selection import checkpoint_key, promotion
from asr_training_support import fixture, suite_fixture, make_audio


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_logical_budget_boundaries_and_quantization(self):
        self.assertEqual(check_budget(1_550_000_000,4_000_000_000)["total_parameters"],5_550_000_000)
        for args, kwargs in (((2_000_000_000,4_000_000_000),{}),((1,5_000_000_000),{}),
                             ((1,4_000_000_000),{"extra":2_000_000_000}),((1,),{"context_tokens":16385})):
            with self.assertRaises(ValueError):
                check_budget(*args,**kwargs)
        self.assertEqual(check_budget(1_550_000_000)["status"],"planner_unverified")

    def test_fit_and_validation_keep_source_group_and_whitelist(self):
        _, _, _, projected, _ = fixture(self.root)
        _, fit, validation, history, audit = projected
        self.assertEqual(len(fit),6)
        self.assertEqual(len(validation),2)
        self.assertFalse({r['sample_id'] for r in fit} & {r['sample_id'] for r in history})
        self.assertTrue(all(r['partition']=='train' for r in fit))
        for sentinel in ('CONTEXT_DO_NOT_EXPORT','GOLD_TOOLS_DO_NOT_EXPORT'):
            self.assertNotIn(sentinel,dumps(fit+history))

    def test_mutated_manifest_and_wav_are_rejected(self):
        data, path, split, projected, _ = fixture(self.root)
        corrupted = copy.deepcopy(split)
        corrupted['samples'][0]['utterances'][0]['reference']='wrong pairing'
        write(path,corrupted)
        with self.assertRaises(ValueError):
            project(data,path,expected_identity=split['identity'],expected_validation=2)
        write(path,split)
        make_audio(data/'train'/projected[1][0]['audio'],123)
        with self.assertRaises(ValueError):
            project(data,path,expected_identity=split['identity'],expected_validation=2)

    def test_user_history_uses_its_own_transcript_and_stays_in_source_partition(self):
        from asr.pretrained.data import make_split
        from lifemate.asr_training.storage import rows
        data,path,_,_,_=fixture(self.root)
        records=rows(data/'train/train.jsonl')
        make_audio(data/'train/audio/s0/user.wav',99)
        records[0]['history']=[{'role':'assistant','text':'ASSISTANT_SENTINEL'},
             {'role':'user','audio':'audio/s0/user.wav','audio_text':'Đọc ghi chú trước đó'}]
        (data/'train/train.jsonl').write_text(''.join(dumps(r)+'\n' for r in records),encoding='utf-8')
        split=make_split(data)
        write(path,split)
        _,fit,val,history,_=project(data,path,expected_identity=split['identity'],expected_validation=2)
        found=[r for r in fit+history if r['utterance_id']=='s0/history_001']
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]['reference'],'Đọc ghi chú trước đó')
        self.assertNotIn('ASSISTANT_SENTINEL',dumps(fit+val+history))
        partitions={r['partition'] for r in fit+history if r['sample_id']=='s0'}
        self.assertEqual(len(partitions),1)

    def test_suite_integrity_and_large_snapshot_acceptance(self):
        suite, metadata, _ = suite_fixture(self.root)
        actual, fit, val = load_suite(suite)
        self.assertEqual(actual,metadata)
        self.assertEqual(actual['model']['provenance']['parameter_count'],1_550_000_000)
        (suite/'data/fit.jsonl').write_text('{}\n',encoding='utf-8')
        with self.assertRaises(Exception):
            load_suite(suite,assets=False)

    def test_nested_lock_cannot_remove_outer_lock(self):
        with suite_lock(self.root):
            with self.assertRaises(FileExistsError):
                with suite_lock(self.root):
                    pass
            self.assertTrue((self.root/'active.lock').exists())
        self.assertFalse((self.root/'active.lock').exists())

    def test_original_split_change_is_rejected_after_prepare(self):
        suite, metadata, _ = suite_fixture(self.root)
        split = Path(metadata['split_manifest'])
        split.write_text(split.read_text(encoding='utf-8')+'\n',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'split manifest changed'):
            load_suite(suite)

    def test_resume_binding_and_file_hashes(self):
        write(self.root/'state.json',{'binding':{'config':'original'},'training':{'step':1}})
        (self.root/'adapter').mkdir()
        (self.root/'adapter/weights').write_bytes(b'synthetic')
        seal(self.root)
        with self.assertRaisesRegex(ValueError,'Resume rejected'):
            load_checkpoint(self.root,{'config':'different'})
        (self.root/'adapter/weights').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            load_checkpoint(self.root,{'config':'original'})

    def test_configs_reject_unsafe_values(self):
        path=self.root/'e1.json'
        for change in ({'micro_batch':2},{'vram_cap_gib':13},{'probe_updates':1},{'unknown':True}):
            write(path,{'experiment':'E1'}|change)
            with self.assertRaises(ValueError):
                load_config(path,'E1')

    def test_manual_gate_does_not_treat_preflight_as_e0_completion(self):
        write(self.root/'E0/probe-1/manifest.json',{'kind':'probe','status':'passed','experiment':'E0'})
        with self.assertRaisesRegex(ValueError,'complete E0'):
            prerequisites(self.root,DEFAULTS|{'experiment':'E1'})
        self.assertIsNone(outcome(self.root,'E0'))

    def test_latest_outcome_uses_time_not_probe_run_skip_prefix(self):
        write(self.root/'E1/skip-old/manifest.json',{'kind':'skip','status':'skipped_resource','created':'2026-01-01'})
        write(self.root/'E1/run-new/manifest.json',{'kind':'run','status':'completed','created':'2026-01-02'})
        self.assertEqual(outcome(self.root,'E1')[1]['status'],'completed')

    def test_e3_requires_e2_terminal_record(self):
        write(self.root/'E0/run-1/manifest.json',{'kind':'run','status':'completed','experiment':'E0'})
        write(self.root/'E1/probe-1/manifest.json',{'kind':'probe','status':'failed_oom','experiment':'E1'})
        with self.assertRaisesRegex(ValueError,'E1 and E2'):
            prerequisites(self.root,DEFAULTS|{'experiment':'E3'})
        write(self.root/'E2/skip-1/manifest.json',{'kind':'skip','status':'skipped_dependency','experiment':'E2'})
        self.assertEqual(prerequisites(self.root,DEFAULTS|{'experiment':'E3'})['scope'],'decoder')

    def test_e4_freezes_best_lora_control_scope_and_update_budget(self):
        write(self.root/'E0/run-1/manifest.json',{'kind':'run','status':'completed','experiment':'E0'})
        for name,wer,scope,updates in (('E1',.3,'decoder',100),('E2',.2,'encoder_decoder',150)):
            path=self.root/name/'run-1'
            write(path/'manifest.json',{'kind':'run','status':'completed','experiment':name,'best_step':5,
                'updates':updates,'best_checkpoint':str(path/'checkpoints/best'),
                'metrics':{'coverage':1,'normalized_wer':wer,'normalized_cer':.1,'mean_latency_seconds':1,
                           'slots':{'critical_slot_accuracy':None}}})
            write(path/'resolved-config.json',DEFAULTS|{'experiment':name,'scope':scope,'rank':4})
        write(self.root/'E3/skip-1/manifest.json',{'kind':'skip','status':'skipped_not_needed','experiment':'E3'})
        config=prerequisites(self.root,DEFAULTS|{'experiment':'E4'})
        self.assertEqual(config['rank'],4)
        self.assertEqual(config['scope'],'encoder_decoder')
        self.assertEqual(config['update_budget'],150)

    def test_no_automatic_all_mode(self):
        with self.assertRaises(SystemExit):
            parser().parse_args(['run','--suite-dir','x','--experiment','all'])

    def test_selection_does_not_promote_proxy_or_incomplete(self):
        metric={'coverage':1,'normalized_wer':.2,'normalized_cer':.1,'mean_latency_seconds':1,
                'slots':{'critical_slot_accuracy':None}}
        self.assertEqual(promotion(metric,metric)['status'],'provisional')
        self.assertEqual(promotion(metric,metric|{'coverage':.5})['status'],'rejected')
        self.assertLess(checkpoint_key(metric,1),checkpoint_key(metric,2))


class FakeCuda:
    def synchronize(self): pass
    def reset_peak_memory_stats(self): pass
    def mem_get_info(self): return 100,1000
    def max_memory_allocated(self): return 200
    def max_memory_reserved(self): return 400


class MemoryTests(unittest.TestCase):
    def test_peak_includes_resident_memory_and_enforces_budget(self):
        class Torch: cuda=FakeCuda()
        memory=Memory(Torch(),399)
        with self.assertRaises(ResourceLimit):
            with memory.phase('training'):
                pass
        self.assertEqual(memory.report()['phases'][0]['peak_reserved_bytes'],400)

    def test_no_cuda_fails_before_model_loading(self):
        class Torch:
            class cuda:
                @staticmethod
                def is_available(): return False
        with self.assertRaisesRegex(ResourceLimit,'CUDA unavailable'):
            hardware(Torch(),DEFAULTS)


if __name__=='__main__': unittest.main()
