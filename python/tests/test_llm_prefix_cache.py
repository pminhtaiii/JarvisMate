"""Exact-prefix reuse must be bounded by the real sample/decision lifecycle."""
import unittest
from unittest.mock import patch

from lifemate.adapters.prefix_cache import ExactPrefixCache
from lifemate.adapters.planner import LocalPlanner
from lifemate.contracts import PipelineError


class Past:
    def __init__(self,length):self.length=length
    def crop(self,length):self.length=min(self.length,length)
    def get_seq_length(self):return self.length


class PrefixCacheTests(unittest.TestCase):
    def test_crop_at_the_first_changed_token_and_preserve_full_prompt(self):
        cache=ExactPrefixCache()
        past=Past(5)
        cache.commit([1,2,3,4,5,6],past)
        prompt=[1,2,3,7,8]
        kwargs,shared=cache.prepare(prompt)
        self.assertEqual((shared,past.length),(3,3))
        self.assertIs(kwargs['past_key_values'],past)
        self.assertEqual(prompt,[1,2,3,7,8])
        self.assertTrue(kwargs['use_cache'])

    def test_identical_prompt_still_forwards_at_least_one_token(self):
        cache=ExactPrefixCache()
        cache.commit([1,2,3],Past(3))
        _,shared=cache.prepare([1,2,3])
        self.assertEqual(shared,2)

    def test_different_prefix_or_missing_backend_discards_the_cache(self):
        cache=ExactPrefixCache()
        cache.commit([1,2,3],Past(3))
        kwargs,shared=cache.prepare([9,2,3])
        self.assertEqual(shared,0)
        self.assertNotIn('past_key_values',kwargs)
        self.assertIsNone(cache.past)
        cache.commit([1,2,3],None)
        self.assertEqual(cache.ids,[])
        with self.assertRaisesRegex(ValueError,'inconsistent'):
            cache.commit([1,2],Past(3))

    def test_generation_failures_clear_reusable_state(self):
        for failure in (PipelineError('TIME_LIMIT','expired'),ValueError('decoder failed')):
            cache=ExactPrefixCache()
            cache.commit([1,2,3],Past(3))
            planner=LocalPlanner.__new__(LocalPlanner)
            planner._prefix_cache=cache
            planner.tokenizer=object()
            with patch('lifemate.adapters.planner.render_native',side_effect=failure):
                with self.assertRaises(PipelineError):
                    planner.generate_native([],[],30.)
            self.assertIsNone(cache.past)
            self.assertEqual(cache.ids,[])

    def test_sample_context_also_clears_state_on_tool_failure(self):
        planner=LocalPlanner.__new__(LocalPlanner)
        planner.cpu_offload=False
        planner._selection_filters={}
        planner.start_sample('one')
        with self.assertRaisesRegex(RuntimeError,'tool'):
            with planner.inference_session():
                planner._prefix_cache.commit([1,2,3],Past(3))
                raise RuntimeError('tool failure')
        self.assertIsNone(planner._prefix_cache)
