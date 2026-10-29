"""Prediction isolation, failure denominators, slots and model-free reporting."""
import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lifemate.asr_training.slots import SlotEvaluator, match_counts
from lifemate.asr_training.evaluation import evaluate
from lifemate.asr_training.reporting import compare, status
from lifemate.asr_training.config import DEFAULTS
from lifemate.asr_training.storage import write, write_rows, rows
from asr.pretrained.runner import result_row
from asr.pretrained.metrics import summarize
from asr_training_support import annotation, suite_fixture


class SlotTests(unittest.TestCase):
    def setUp(self):
        self.row={'utterance_id':'s/current','reference':'Gửi 50.000 đồng cho Nam lúc 19:00 tại 5/4 Huế, họp team.'}
        self.gold=[annotation(self.row,[('money','50.000 đồng','50000 vnd'),('proper_name','Nam','nam'),
              ('time','19:00','19:00'),('address','5/4 Huế','5/4 huế'),('english_span','team','team')])]
        self.rules={'source_partition':'train','validated':True,'reviewer':'fixture-only',
              'patterns':[{'type':'money','pattern':r'50\.000 đồng','canonical_map':{'50.000 đồng':'50000 vnd'}},
                          {'type':'proper_name','pattern':'Nam'}, {'type':'time','pattern':r'\d{2}:\d{2}'},
                          {'type':'address','pattern':'5/4 Huế'},{'type':'english_span','pattern':'team'}]}

    def test_all_five_slot_types_and_extra_predictions(self):
        evaluator=SlotEvaluator([self.row],self.gold,self.rules)
        result=evaluator.summarize([self.row|{'prediction':self.row['reference']+' 50.000 đồng','status':'ok'}])
        self.assertEqual(result['critical_slot_accuracy'],1)
        self.assertEqual(result['total']['fp'],1)
        self.assertLess(result['total']['precision'],1)
        self.assertEqual(result['critical_utterance_exact'],0)
        self.assertEqual(set(result['per_type']),{'money','proper_name','time','address','english_span'})

    def test_unreviewed_rules_are_only_proxy(self):
        evaluator=SlotEvaluator([self.row],self.gold,self.rules|{'validated':False})
        result=evaluator.summarize([self.row|{'prediction':self.row['reference'],'status':'ok'}])
        self.assertIsNone(result['critical_slot_accuracy'])
        self.assertEqual(result['CSA_proxy'],1)

    def test_missing_or_partial_gold_is_not_invented(self):
        self.assertEqual(SlotEvaluator([self.row],None,None).summarize([])['status'],'unavailable')
        with self.assertRaises(ValueError):
            SlotEvaluator([self.row],[],self.rules)

    def test_maximum_matching_and_failed_prediction(self):
        gold=[{'type':'english_span','canonical':'a','alternatives':['b']},
              {'type':'english_span','canonical':'a'}]
        self.assertEqual(match_counts(gold,[{'type':'english_span','canonical':'a'},
                                           {'type':'english_span','canonical':'b'}]),(2,0,0))
        evaluator=SlotEvaluator([self.row],self.gold,self.rules)
        result=evaluator.summarize([self.row|{'prediction':'invented','status':'timeout'}])
        self.assertEqual(result['critical_slot_accuracy'],0)
        self.assertEqual(result['total']['fn'],5)


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.suite,self.metadata,self.projected=suite_fixture(self.root)
        self.val=self.projected[2]

    def test_timeout_retains_full_reference_denominator_and_audio_only_requests(self):
        class FakeSession:
            calls=[]
            def __init__(self,job):
                assert 'reference' not in job and 'validation' not in job
            def receive(self,timeout): return {'status':'ready','memory':None}
            def request(self,path,timeout):
                assert isinstance(path,Path) and path.suffix=='.wav'
                self.calls.append(path)
                if len(self.calls)>1: raise TimeoutError('controlled timeout')
                return {'status':'ok','prediction':'warmup','latency_seconds':.01}
            def close(self): return {'memory':{'peak_allocated_gib':.1,'peak_reserved_gib':.2}}
        output=self.root/'evaluation'
        result=evaluate({'config':DEFAULTS},self.val,Path(self.metadata['data_root']),output,
                        SlotEvaluator(self.val,None,None),session_factory=FakeSession)
        self.assertEqual(result['selected'],2)
        self.assertEqual(result['timeouts'],1)
        self.assertEqual(result['not_run'],1)
        self.assertEqual(result['normalized_wer'],1)
        self.assertEqual([r['status'] for r in rows(output/'transcripts.jsonl')],['timeout','not_run'])

    def test_compare_keeps_all_statuses_without_loading_torch_or_models(self):
        base=self.suite/'E0/run-001'
        base.mkdir(parents=True)
        predicted=[result_row(r,{'status':'ok','prediction':r['reference'],'latency_seconds':.01}) for r in self.val]
        (base/'primary').mkdir()
        write_rows(base/'primary/transcripts.jsonl',predicted)
        metrics=summarize(predicted)|{'slots':{'status':'unavailable','critical_slot_accuracy':None}}
        write(base/'manifest.json',{'kind':'run','experiment':'E0','status':'completed','metrics':metrics,
                                    'best_evaluation':str(base/'primary')})
        for experiment,state,kind in [('E1','failed_oom','probe'),('E2','skipped_dependency','skip'),('E3','unsupported','probe')]:
            write(self.suite/experiment/'record-1/manifest.json',{'kind':kind,'experiment':experiment,'status':state,'error':'fixture'})
        with patch.dict('sys.modules',{'torch':None}), patch('lifemate.asr_training.workers.Session',side_effect=AssertionError('No inference in compare')):
            result=compare(self.suite)
        with (Path(result['report_dir'])/'comparison.csv').open(encoding='utf-8-sig') as stream:
            comparisons=list(csv.DictReader(stream))
        self.assertEqual(len(comparisons),5)
        self.assertEqual([r['status'] for r in comparisons],['completed','failed_oom','skipped_dependency','unsupported','not_run'])
        self.assertEqual(comparisons[1]['normalized_wer'],'')
        self.assertEqual(len(status(self.suite)),5)


if __name__=='__main__': unittest.main()
