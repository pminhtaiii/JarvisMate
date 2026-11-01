"""Artifact-only comparison: exclusion gates, units, source preservation and cases."""
import copy
import csv
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from asr_training_support import suite_fixture, saved_run, annotation
from asr.pretrained.runner import result_row
from lifemate.asr_training.reporting import compare
from lifemate.asr_training.storage import read, write, rows, write_rows, identity, seal, tree_hashes
from lifemate.asr_training.comparison_examples import choose_cases, highlight, word_diff, hints


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.suite, self.metadata, projected = suite_fixture(Path(self.temp.name))
        self.validation = projected[2]
        self.base, _ = saved_run(self.suite, self.metadata, self.validation, predictions=['' for r in self.validation])
        self.candidate, self.manifest = saved_run(self.suite, self.metadata, self.validation, 'E1')

    def output(self):
        result = compare(self.suite)
        path = Path(result['report_dir'])
        return result, path, read(path/'details.json')

    def test_full_outputs_units_deltas_and_no_model_or_source_mutation(self):
        before = {p:tree_hashes(p) for p in (self.suite/'data',self.base,self.candidate)}
        with patch.dict('sys.modules',{'torch':None,'transformers':None,'peft':None}), \
             patch('socket.socket.connect',side_effect=AssertionError('No network')), \
             patch('lifemate.asr_training.workers.Session',side_effect=AssertionError('No inference')):
            result, report, details = self.output()
        self.assertEqual(result['valid_runs'],2)
        self.assertEqual(before,{p:tree_hashes(p) for p in before})
        self.assertTrue({'comparison.csv','comparison.md','examples_10.csv','examples_10.md','details.json','report.md'} <= {p.name for p in report.iterdir()})
        with (report/'comparison.csv').open(encoding='utf-8-sig',newline='') as stream:
            table = list(csv.DictReader(stream))
        self.assertEqual(float(table[0]['normalized_wer']),1)
        self.assertEqual(float(table[0]['normalized_wer_pct']),100)
        self.assertEqual(float(table[1]['delta_normalized_wer_pp']),-100)
        self.assertEqual(table[0]['train_peak_allocated_gib'],'N/A')
        self.assertEqual(table[1]['slot_recall'],'N/A')
        self.assertEqual(table[1]['method'],'Decoder LoRA')
        self.assertEqual(details['decisions']['E1']['status'],'provisional')

    def test_mismatched_provenance_is_excluded_without_relabeling_it(self):
        for field in ('split_identity','selection_identity','source','evaluation_policy','hardware','train_memory'):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.manifest)
                changed[field] = 'wrong'
                write(self.candidate/'manifest.json',changed)
                _, _, details = self.output()
                entry = details['rows'][1]
                self.assertFalse(entry['comparison_eligible'])
                self.assertEqual(entry['status'],'completed')
                self.assertIsNone(entry['normalized_wer_pct'])
                self.assertIn('Excluded',entry['reason'])
                self.assertNotIn('E1',details['decisions'])

    def test_changed_prediction_and_missing_reference_are_excluded(self):
        path = self.candidate/'primary/transcripts.jsonl'
        original = rows(path)
        altered = copy.deepcopy(original)
        altered[0]['prediction'] = 'tampered'
        write_rows(path,altered)
        _, _, details = self.output()
        self.assertIn('edit counts',details['rows'][1]['reason'])
        write_rows(path,original[:-1])
        _, _, details = self.output()
        self.assertIn('IDs/reference/audio/order',details['rows'][1]['reason'])

    def test_wrong_representation_or_inference_dtype_is_not_ranked(self):
        config_path = self.candidate/'resolved-config.json'
        config = read(config_path)
        write(config_path,config|{'inference_dtype':'bfloat16'})
        _, _, details = self.output()
        self.assertFalse(details['rows'][1]['comparison_eligible'])
        write(config_path,config)
        metrics_path = self.candidate/'primary/metrics.json'
        write(metrics_path,read(metrics_path)|{'representation':'native_nf4'})
        _, _, details = self.output()
        self.assertIn('representation',details['rows'][1]['reason'])

    def test_running_manifest_cannot_leak_previous_epoch_metrics(self):
        write(self.candidate/'manifest.json',self.manifest|{'status':'running'})
        _, _, details = self.output()
        self.assertEqual(details['rows'][1]['status'],'running')
        self.assertIsNone(details['rows'][1]['normalized_wer_pct'])
        self.assertEqual(details['valid_runs'],1)

    def test_nonimproving_candidate_does_not_replace_e0(self):
        saved_run(self.suite,self.metadata,self.validation)
        saved_run(self.suite,self.metadata,self.validation,'E1',predictions=['' for r in self.validation])
        _, _, details = self.output()
        self.assertEqual(details['recommendation']['experiment'],'E0')
        self.assertEqual(details['recommendation']['status'],'retain_E0')

    def test_frozen_gold_enables_slot_recall_precision_and_promotion(self):
        gold = [annotation(r,[('proper_name',r['reference'].split()[0],r['reference'].split()[0].lower())]) for r in self.validation]
        rules = {'source_partition':'train','validated':True,'reviewer':'fixture-only',
                 'patterns':[{'type':'proper_name','pattern':re.escape(r['reference'].split()[0])} for r in self.validation]}
        write_rows(self.suite/'data/slots.jsonl',gold)
        write(self.suite/'data/slot-rules.json',rules)
        seal(self.suite/'data')
        metadata = copy.deepcopy(self.metadata)
        metadata.update(annotation_identity=identity(gold),rules_identity=identity(rules))
        metadata['identity'] = identity({k:v for k,v in metadata.items() if k!='identity'})
        write(self.suite/'suite.json',metadata)
        saved_run(self.suite,metadata,self.validation,predictions=['' for r in self.validation])
        saved_run(self.suite,metadata,self.validation,'E1')
        _, _, details = self.output()
        row = details['rows'][1]
        self.assertEqual(row['slot_recall'],1)
        self.assertEqual(row['slot_precision'],1)
        self.assertEqual(row['slot_f1'],1)
        self.assertEqual(details['decisions']['E1']['status'],'candidate_supported')

    def test_examples_are_unique_deterministic_and_escape_markdown(self):
        validation=[]
        for i in range(12):
            validation.append({'utterance_id':f's{i:02d}/current','reference':f'Gửi {i} đồng cho Lan Anh lúc 7 giờ qua email | [x]',
                               'duration_seconds':1})
        base={r['utterance_id']:result_row(r,{'status':'ok','prediction':'sai','latency_seconds':.1}) for r in validation}
        candidate={r['utterance_id']:result_row(r,{'status':'ok','prediction':r['reference'],'latency_seconds':.1}) for r in validation}
        first=choose_cases(validation,{'E0':base,'E1':candidate},'E1')
        second=choose_cases(validation,{'E1':dict(reversed(list(candidate.items()))),'E0':base},'E1')
        self.assertEqual(first,second)
        self.assertEqual(len({r['utterance_id'] for r,_ in first}),10)
        marked=highlight('a b | [x]','a c | [x]')
        self.assertIn('**c**',marked)
        self.assertIn('&#124;',marked)
        self.assertNotIn('|',marked)
        self.assertEqual([op for op,_,_ in word_diff('a b','a')],['equal','delete'])
        self.assertNotIn('money',hints('Vé Đồng Nai'))
        self.assertIn('money',hints('Chuyển hai triệu đồng'))


if __name__ == '__main__':
    unittest.main()
