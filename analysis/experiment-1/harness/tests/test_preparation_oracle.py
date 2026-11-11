import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from _common import (HarnessError, base_inputs, digest, equal, load_experiment, read_json,
                     read_jsonl, visible_rows)
from gold_oracle import oracle, replay_reference
from prepare import grouped_blocks, prepare,validate_model_reference
from support import Fixture, REPO


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        self.addCleanup(self.f.close)

    def test_fixed_text_whitelist_and_paired_toml(self):
        self.f.prepare()
        rec = load_experiment(self.f.root)
        from lifemate.configuration import load_config
        runs = rec['phases']['main']['runs']
        self.assertEqual([r['arm'] for r in runs], ['control', 'treatment', 'treatment', 'control'])
        for index in range(0, len(runs), 2):
            left, right = [load_config(self.f.root / r['config']) for r in runs[index:index+2]]
            self.assertTrue(left.reuse_kv_cache and right.reuse_kv_cache)
            self.assertEqual(left.sample_ids_file, right.sample_ids_file)
            self.assertEqual(left.mode, 'transcript')
            self.assertTrue(left.debug_payloads and right.debug_payloads)
            self.assertNotEqual(left.enable_skill_retrieval, right.enable_skill_retrieval)
        frozen = read_jsonl(self.f.root / 'inputs/base_inputs.jsonl')
        self.assertEqual(len(frozen), 2)
        self.assertTrue(all('label' not in v['prepared'] for v in frozen))
        self.assertEqual(frozen[0]['prepared']['request'], self.f.rows[0]['audio_text'])
        self.assertEqual(rec['profile'], 'local_cpu_only')
        self.assertFalse(rec['model_checked'])
        self.assertFalse((self.f.root / 'runs').exists())
        with self.assertRaises(HarnessError):
            self.f.prepare()

    def test_modified_inputs_or_manifest_rejected(self):
        self.f.prepare()
        p = self.f.data / 'train/train.jsonl'
        p.write_text(p.read_text(encoding='utf-8') + '\n', encoding='utf-8')
        with self.assertRaisesRegex(HarnessError, 'Changed/missing'):
            load_experiment(self.f.root)

    def test_manifest_edit_and_helper_edit_detected(self):
        self.f.prepare()
        p=self.f.root/'experiment.json'
        p.write_text(p.read_text(encoding='utf-8')+'\n',encoding='utf-8')
        with self.assertRaisesRegex(HarnessError,'checksum'):
            load_experiment(self.f.root)

    def test_modified_frozen_helper_detected(self):
        self.f.prepare()
        p=self.f.root/'harness/score.py'
        p.write_text(p.read_text(encoding='utf-8')+'\n',encoding='utf-8')
        with self.assertRaisesRegex(HarnessError,'helper inventory'):
            load_experiment(self.f.root)

    def test_current_gold_test_row_rejected_before_snapshot(self):
        from _common import write_jsonl
        p=self.f.data/'train/train.jsonl';p.unlink()
        rows=copy.deepcopy(self.f.rows);rows[0]['id']='public_0001'
        write_jsonl(p,rows)
        with self.assertRaisesRegex(HarnessError,'Train IDs'):
            self.f.prepare()
        self.assertFalse(self.f.root.exists())

    def test_fixed_history_not_gold_future_and_no_asr(self):
        self.f.prepare()
        from lifemate.contracts import Deadline
        from lifemate.dataset import normalize_visible,prepare_request_once,validate_catalog
        catalog=read_json(self.f.data/'train/train_tools_catalog.json')
        row=copy.deepcopy(self.f.rows[0])
        row['history']=[{'role':'user','audio':'audio/past/past.wav','audio_text':'previous exact text'},
                        {'role':'assistant','text':'past reply','tool_calls':[],'tool_results':[]}]
        sample=normalize_visible(row,validate_catalog(catalog),self.f.data/'train','transcript')
        prepared,stats=prepare_request_once(sample,None,Deadline(30))
        self.assertEqual(prepared['history'][0]['text'],'previous exact text')
        self.assertEqual(stats['asr_calls'],0)
        self.assertNotIn('label',prepared)

    def test_model_reference_digests_are_required_to_match(self):
        lib={'sha256':'x','version':'fixture'};code={'agent.py':'pinned'}
        meta={'parameter_count':123,'template_sha256':'template'};files={'weights.safetensors':'good'}
        ref={'identity':{'code':code,'skill_library':lib,'planner':meta|{'files':files}}}
        validate_model_reference(ref,files,meta,code,lib)
        with self.assertRaisesRegex(HarnessError,'Checkpoint/tokenizer'):
            validate_model_reference(ref,{'weights.safetensors':'changed'},meta,code,lib)

    def test_server_paths_and_skip_model_guard(self):
        with self.assertRaises(HarnessError):
            prepare(self.f.root, REPO, self.f.data, self.f.base / 'no-model', skip_model=True)
        self.assertFalse(self.f.root.exists())

    def test_group_not_split_and_jsonl_order_retained(self):
        rows = [{'id': 'train_b', 'history': [], 'group_id': 'same'},
                {'id': 'train_a', 'history': [], 'group_id': 'same'}]
        blocks, _ = grouped_blocks(rows, 42, 2)
        self.assertEqual(blocks, [['train_b', 'train_a']])
        with self.assertRaises(HarnessError):
            grouped_blocks(rows, 42, 1)

    def test_gold_oracle_post_inference_guard_and_cpu_separation(self):
        self.f.prepare()
        with self.assertRaises(HarnessError):
            oracle(self.f.root, 'smoke')
        factory = FakeFactory()
        audit = oracle(self.f.root, 'smoke', cpu_check=True, factory=factory)
        self.assertEqual(audit['valid'], 2)
        self.assertEqual(factory.opened, ['train_fixture_a', 'train_fixture_b'])
        self.assertFalse((self.f.root / 'gold/smoke').exists())
        self.assertTrue((self.f.root / 'gold/cpu-check-smoke/reference_audit.json').exists())


class FakeEnv:
    def __init__(self):
        self.calls = []
    def get_state_hash(self):
        return ('a' if not self.calls else 'b') * 64
    def call(self, name, arguments):
        self.calls.append({'name': name, 'arguments': copy.deepcopy(arguments)})
        return {'ok': True, 'item': {'id': 'fixture'}}
    def get_tool_calls(self):
        return copy.deepcopy(self.calls)


class FakeFactory:
    def __init__(self):
        self.opened = []
    def __call__(self, split, sid, root):
        if split != 'train' or sid in self.opened:
            raise AssertionError('Wrong split or duplicate environment')
        self.opened.append(sid)
        return FakeEnv()


class OracleTests(unittest.TestCase):
    def row(self):
        return {'id': 'train_fixture', 'label': {'tool_calls': [{'name': 'notes.create', 'arguments': {'content': 'x'}}],
                 'tool_results': [{'ok': True, 'item': {'id': 'fixture'}}], 'final_state': {'incomplete': 'not-hash-input'}}}

    def test_public_api_replay_and_results_validation(self):
        factory = FakeFactory()
        result = replay_reference(self.row(), factory, Path('.'))
        self.assertEqual(result['status'], 'valid')
        self.assertEqual(result['gold_reference_state_hash'], 'b' * 64)
        self.assertEqual(result['initial_state_hash'], 'a' * 64)
        bad = self.row()
        bad['label']['tool_results'][0]['ok'] = False
        self.assertEqual(replay_reference(bad, FakeFactory(), Path('.'))['status'], 'reference_inconsistent')

    def test_empty_gold_still_uses_environment_hash(self):
        row = {'id': 'train_empty', 'label': {'tool_calls': [], 'tool_results': [], 'final_state': {'wrong': 'value'}}}
        result = replay_reference(row, FakeFactory(), Path('.'))
        self.assertEqual(result['gold_reference_state_hash'], 'a' * 64)
        self.assertEqual(result['status'], 'valid')

    def test_public_private_ids_rejected_before_factory(self):
        for sid in ('public_0001', 'private_0001', '../train_x'):
            row = self.row(); row['id'] = sid
            with self.assertRaises(HarnessError):
                replay_reference(row, lambda *args: self.fail('Must not open environment'), Path('.'))

    def test_typed_result_equality(self):
        self.assertFalse(equal({'n': True}, {'n': 1}))
        self.assertFalse(equal({'n': 1}, {'n': 1.0}))

    def test_invalid_toolenv_hash_never_valid_reference(self):
        class BadHash(FakeEnv):
            def get_state_hash(self):return 'not-a-hash'
        with self.assertRaises(HarnessError):
            replay_reference(self.row(),lambda *args:BadHash(),Path('.'))


if __name__ == '__main__':
    unittest.main()
