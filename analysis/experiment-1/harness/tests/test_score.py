import copy
import unittest

from _common import read_json
from score import (aggregate, match_calls, score_experiment, score_sample, timing_summary,
                   token_f1, transition)
from support import Fixture


SPECS={'toy.send': {'parameters':{'properties':{'content':{'x-match':'fuzzy'},'n':{'type':'integer'}}}}}
def call(content, **more):
    return {'name':'toy.send','arguments':{'content':content, **more}}
REF={'status':'valid','gold_reference_state_hash':'a'*64}
def pred(calls, hash='a'*64):
    return {'id':'train_fixture','tool_calls':calls,'state_hash':hash}


class MatchingTests(unittest.TestCase):
    def test_maximum_matching_beats_greedy_and_is_order_independent(self):
        g=[call('a b'),call('b c')];p=[call('a b c'),call('a b')]
        result=match_calls(p,g,SPECS)
        self.assertEqual(result['matched'],2)
        self.assertEqual(result['greedy_matched'],1)
        self.assertTrue(result['matching_ambiguous'])
        self.assertEqual(match_calls(p[::-1],g,SPECS)['call_f1'],1)

    def test_threshold_is_strict_and_diacritics_not_removed(self):
        self.assertEqual(token_f1('a b c d e','a b c x y'),.6)
        self.assertEqual(match_calls([call('a b c d e')],[call('a b c x y')],SPECS)['matched'],0)
        self.assertEqual(token_f1('ĐẾN TRỄ','đến trễ'),1)
        self.assertNotEqual(token_f1('den tre','đến trễ'),1)
        self.assertEqual(token_f1('e\u0301','é'),1)

    def test_duplicates_schema_rejections_and_typed_values(self):
        self.assertAlmostEqual(match_calls([call('x'),call('x')],[call('x')],SPECS)['call_f1'],2/3)
        m=match_calls([call('x')],[call('x')],SPECS,invalid=[0])
        self.assertEqual((m['matched'],m['unmatched'],m['schema_rejected_count']),(0,1,1))
        self.assertEqual(match_calls([call('x',n=True)],[call('x',n=1)],SPECS)['matched'],0)
        self.assertEqual(match_calls([call('x')],[call('x',n=None)],SPECS)['matched'],0)


class SampleScoringTests(unittest.TestCase):
    def test_hash_mismatch_zeroes_perfect_calls(self):
        v=score_sample([call('x')],pred([call('x')], 'b'*64),True,REF,SPECS)
        self.assertEqual(v['match']['call_f1'],1)
        self.assertEqual(v['score'],0)
        self.assertEqual(v['hash_status'],'mismatch')

    def test_empty_gold_special_case(self):
        self.assertEqual(score_sample([],pred([], 'b'*64),True,REF,SPECS)['score'],1)
        self.assertEqual(score_sample([],pred([call('x')]),True,REF,SPECS)['score'],0)
        self.assertEqual(score_sample([],None,False,REF,SPECS)['score'],0)

    def test_missing_prediction_not_empty_or_hash_mismatch(self):
        v=score_sample([call('x')],None,False,REF,SPECS)
        self.assertEqual(v['score'],0)
        self.assertIsNone(v['hash_match'])
        self.assertIsNone(v['call_count'])
        self.assertIsNone(v['match'])
        self.assertEqual(transition(True,v['hash_match']),'unknown_treatment')

    def test_oracle_error_separate_from_inference_failure(self):
        for ref in (None,{'status':'reference_inconsistent'}):
            v=score_sample([call('x')],pred([call('x')]),True,ref,SPECS)
            self.assertIsNone(v['score'])
            self.assertEqual(v['inference_status'],'accepted')
            self.assertEqual(v['hash_status'],'unknown')

    def test_partial_accepted_can_score(self):
        v=score_sample([call('x')],pred([call('x')]),True,REF,SPECS)
        self.assertEqual(v['score'],1)

    def test_transition_directions(self):
        self.assertEqual(transition(True,False),'n10')
        self.assertEqual(transition(False,True),'n01')
        self.assertEqual(transition(False,False),'n00')
        self.assertEqual(transition(True,True),'n11')
        self.assertEqual(transition(None,None),'unknown_both')

    def test_failed_denominators_and_negative_latency_delta(self):
        values=[]
        for i,accepted in enumerate((True,False)):
            v=score_sample([call('x')],pred([call('x')]) if accepted else None,accepted,REF,SPECS)
            v.update(accepted=accepted,status='completed' if accepted else 'timeout',
                     stop_reason='finish' if accepted else None,attempt_seconds=10+i)
            b=copy.deepcopy(v);b['attempt_seconds']-=2
            values.append({'id':str(i),'gold_count':1,'control':v,'treatment':b,
                           'transition':transition(v['hash_match'],b['hash_match'])})
        summary=aggregate(values)
        self.assertEqual(summary['arms']['control']['verified_hash_success_rate'],.5)
        self.assertEqual(summary['arms']['control']['local_macro_score_100'],50)
        self.assertEqual(summary['arms']['control']['hash_unknown'],1)
        self.assertEqual(summary['paired_latency_delta_seconds']['mean'],-2)

    def test_quantile_linear_and_missing_times_not_zero(self):
        v=timing_summary([1,3,None])
        self.assertEqual(v['p50'],2)
        self.assertEqual(v['unknown'],1)


class IncompleteReportTests(unittest.TestCase):
    def test_missing_runs_produce_full_denominator_report_without_faking_empty(self):
        f=Fixture();self.addCleanup(f.close);f.prepare()
        result=score_experiment(f.root,'main')
        self.assertFalse(result['evidence_valid'])
        self.assertEqual(result['samples'],2)
        self.assertEqual(result['arms']['control']['inference_failures_or_missing'],2)
        self.assertEqual(result['arms']['control']['local_macro_score_100'],0)
        saved=read_json(f.root/'reports/main/summary.json')
        self.assertEqual(saved['samples'],2)


if __name__=='__main__':
    unittest.main()
