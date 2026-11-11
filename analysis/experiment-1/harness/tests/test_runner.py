from pathlib import Path
import sys
import unittest

from _common import HarnessError,digest,read_json,read_jsonl,write_json,write_jsonl
from gold_oracle import oracle
from run_pair import child_environment,run_phase
from score import score_experiment
from support import FakeIntegration,Fixture
from test_preparation_oracle import FakeFactory


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.f=Fixture();self.addCleanup(self.f.close);self.f.prepare()

    def test_local_profile_never_launches_real_inference(self):
        with self.assertRaisesRegex(HarnessError,'CPU-local'):
            run_phase(self.f.root,'smoke',sys.executable)
        self.assertFalse((self.f.root/'evidence/smoke-driver-started.json').exists())

    def test_metadata_preflight_does_not_consume_phase(self):
        fake=FakeIntegration(self.f.root)
        v=run_phase(self.f.root,'smoke',sys.executable,check_only=True,executor=fake)
        self.assertEqual(v['returncode'],0)
        self.assertEqual(fake.inferences,0)
        self.assertFalse((self.f.root/'evidence/smoke-driver-started.json').exists())

    def test_partner_runs_after_nonzero_and_phase_cannot_retry(self):
        fake=FakeIntegration(self.f.root,fail_first=True)
        v=run_phase(self.f.root,'smoke',sys.executable,executor=fake)
        self.assertEqual(v['returncode'],1)
        self.assertEqual(fake.inferences,2)
        with self.assertRaises(HarnessError):
            run_phase(self.f.root,'smoke',sys.executable,executor=fake)

    def test_main_requires_smoke_evidence(self):
        with self.assertRaises(OSError):
            run_phase(self.f.root,'main',sys.executable,executor=FakeIntegration(self.f.root))

    def test_isolated_child_environment(self):
        env=child_environment(self.f.root)
        self.assertEqual(env['PYTHONPATH'],str(self.f.root/'src/python/src'))
        self.assertEqual(env['HF_HUB_OFFLINE'],'1')
        self.assertEqual(env['PYTHONNOUSERSITE'],'1')

    def test_full_cpu_artifact_flow_and_oracle_source_tag(self):
        fake=FakeIntegration(self.f.root)
        self.assertEqual(run_phase(self.f.root,'smoke',sys.executable,executor=fake)['returncode'],0)
        audit=oracle(self.f.root,'smoke',factory=FakeFactory())
        self.assertEqual(audit['valid'],2)
        # The real scorer deliberately does not accept an injected-test oracle as real evidence.
        result=score_experiment(self.f.root,'smoke')
        self.assertFalse(result['evidence_valid'])
        self.assertTrue(any('real Train runtime' in e for e in result['errors']))
        self.assertEqual(result['arms']['control']['local_macro_score_100'],100)
        self.assertEqual(result['arms']['control']['tool_calls_unknown'],0)
        traces=read_json(self.f.root/'reports/smoke/trace_audit.json')
        self.assertTrue(all(v['control']['payload_complete'] for v in traces.values()))

    def test_nonempty_tool_results_preserved_and_trace_truncation_blocks_evidence(self):
        fake=FakeIntegration(self.f.root,predicted_calls=[{'name':'ewallet.get_balance','arguments':{}}])
        self.assertEqual(run_phase(self.f.root,'smoke',sys.executable,executor=fake)['returncode'],0)
        oracle(self.f.root,'smoke',factory=FakeFactory())
        path=next((self.f.root/'runs/smoke/block-000/control/staging').glob('*/trace.jsonl'))
        events=read_jsonl(path)
        self.assertEqual(sum(e['kind']=='tool_call_result' for e in events),1)
        for e in events:
            if e['kind']=='tool_call_result':e['payload_truncated']=True
        path.unlink();write_jsonl(path,events)
        result=score_experiment(self.f.root,'smoke')
        self.assertFalse(result['evidence_valid'])
        self.assertTrue(any('truncated payload' in e for e in result['errors']))
        trace=read_json(self.f.root/'reports/smoke/trace_audit.json')
        self.assertTrue(any(v['treatment']['result_count']==1 for v in trace.values()))

    def test_out_of_budget_acceptance_never_receives_credit(self):
        fake=FakeIntegration(self.f.root)
        run_phase(self.f.root,'smoke',sys.executable,executor=fake)
        from lifemate.artifacts import _check
        path=self.f.root/'runs/smoke/block-000/control/journal.jsonl'
        rows=read_jsonl(path)
        for row in rows:
            if row['type']=='accept':
                row['metrics']['attempt_seconds']=30.01
                row.pop('check');row['check']=_check(row)
        path.unlink();write_jsonl(path,rows)
        result=score_experiment(self.f.root,'smoke')
        self.assertEqual(result['arms']['control']['local_macro_score_100'],0)
        self.assertEqual(result['arms']['control']['inference_failures_or_missing'],2)
        self.assertFalse(result['evidence_valid'])


if __name__=='__main__':unittest.main()
