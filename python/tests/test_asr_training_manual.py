"""Controlled lifecycle integration: E0/E1 stop and OOM never advances experiments."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lifemate.asr_training import execution
from lifemate.asr_training import orchestration
from lifemate.asr_training.config import DEFAULTS
from lifemate.asr_training.storage import write, write_rows, outcome
from asr.pretrained.runner import result_row
from asr.pretrained.metrics import summarize
from asr_training_support import suite_fixture


class ManualExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.suite,self.metadata,self.projected=suite_fixture(self.root)
        self.val=self.projected[2]
        self.config=self.root/'e0.json'
        self.hardware={'hardware':{'name':'controlled-fixture'},'precision':'float16'}

    def evaluation(self,job,validation,data_root,output,slots):
        output.mkdir(parents=True)
        records=[result_row(r,{'status':'ok','prediction':r['reference'],'latency_seconds':.01}) for r in validation]
        write_rows(output/'transcripts.jsonl',records)
        result=summarize(records)|{'slots':{'status':'unavailable','critical_slot_accuracy':None}}
        write(output/'metrics.json',result)
        return result

    def start(self,experiment,once=None):
        write(self.config,{'experiment':experiment,'max_epochs':1})
        with patch.object(execution,'hardware_binding',return_value=(self.hardware,{'controlled':True})), \
             patch.object(execution,'require_same_baseline'),patch.object(execution,'require_probe'), \
             patch.object(execution,'evaluate',side_effect=self.evaluation), \
             patch.object(execution,'once',side_effect=once or AssertionError('E0 must not train')), \
             patch.object(execution,'export',return_value={'path':str(self.root/'controlled-export'),'parameters':1}):
            return execution.run(self.suite,self.config,experiment)

    def test_e0_evaluates_then_stops_without_e1(self):
        result=self.start('E0')
        self.assertEqual(result['status'],'completed')
        self.assertIsNone(outcome(self.suite,'E1'))
        self.assertIsNone(result['best_checkpoint'])

    def test_e1_uses_fresh_base_and_stops_without_e2(self):
        self.start('E0')
        calls=[]
        def train(job,timeout):
            calls.append(job)
            self.assertIsNone(job['checkpoint'])
            self.assertEqual(job['config']['experiment'],'E1')
            checkpoint=Path(job['output'])/'checkpoints/step-00000001'
            checkpoint.mkdir(parents=True)
            return {'status':'ok','checkpoint':str(checkpoint),'state':{'epoch':1,'step':1,'cursor':0},
                    'adapter':{'adapter_parameters':10},'memory':{'peak_allocated_gib':.1,'peak_reserved_gib':.2}}
        result=self.start('E1',train)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(len(calls),1)
        self.assertIsNone(outcome(self.suite,'E2'))

    def test_e1_oom_records_failure_without_retry_or_e2(self):
        self.start('E0')
        calls=[]
        def oom(job,timeout):
            calls.append(job)
            return {'status':'failed_oom','error':'CUDA out of memory','memory':None}
        result=self.start('E1',oom)
        self.assertEqual(result['status'],'failed_oom')
        self.assertEqual(len(calls),1)
        self.assertIsNone(outcome(self.suite,'E2'))

    def test_e3_resource_failure_is_not_reported_as_quantization_incompatibility(self):
        config=DEFAULTS|{'experiment':'E3','scope':'decoder'}
        for error,expected in [('ResourceLimit: reserved VRAM exceeds headroom','failed'),
                               ('ValueError: unsupported quantized Whisper module','unsupported')]:
            with self.subTest(error=error), \
                 patch.object(orchestration,'resolve',return_value=(self.metadata,self.projected[1],self.val,config)), \
                 patch.object(orchestration,'hardware_binding',return_value=(self.hardware,{'controlled':True})), \
                 patch.object(orchestration,'require_same_baseline'), \
                 patch.object(orchestration,'token_audit',return_value={}), \
                 patch.object(orchestration,'once',return_value={'status':'failed','error':error}):
                result=orchestration.preflight(self.suite,self.config,'E3')
            self.assertEqual(result['status'],expected)


if __name__=='__main__': unittest.main()
