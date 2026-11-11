"""Independent full-prefill oracle using random, untrained CPU Qwen3 weights.

Actual-tokenizer tests opt in with LIFEMATE_NATIVE_TOKENIZER; no weights/downloads.
"""
import os
import types
import unittest
from importlib.util import find_spec
from unittest.mock import patch

from lifemate.adapters.qwen_kv import ForwardMeasurement, SampleKVCache
from lifemate.adapters.qwen_native import NativeConstraint, NativePlanner, render_messages
from lifemate.contracts import Limits, PipelineError
from lifemate.agent import run_integration_sample
from lifemate.contracts import Deadline
from lifemate.dataset import preflight
from support import Fixture, MemoryTrace
from test_integration_early_stop import Clock, Environment

LIBRARIES = find_spec("torch") and find_spec("transformers")


class FixedGuidancePrefixTests(unittest.TestCase):
    def test_exact_user_guidance_prefix_remains_reusable_without_model_dependencies(self):
        prepared = {"request": "Tìm liên hệ", "context": {}, "history": [], "available_tools": []}
        guidance = ({"branch_id": "S01.B01", "parent_id": "S01", "evidence": "E",
                     "guidance": "Chọn đúng thiết bị.", "shared_instructions": []},)
        first_body = render_messages(prepared, [], skill_guidance=guidance)[1]["content"]
        later_body = render_messages(prepared, [{"name": "contacts.list", "arguments": {},
                                                 "result": {"ok": True}}],
                                     skill_guidance=guidance)[1]["content"]
        self.assertEqual(first_body, later_body)

        class Layer:
            def __init__(self, length):
                self.length = length

            def get_seq_length(self):
                return self.length

        class Cache:
            def __init__(self, config=None, length=0):
                self.length = length
                self.layers = [Layer(length)]

            def get_seq_length(self):
                return self.length

            def crop(self, length):
                self.length = length
                for layer in self.layers:
                    layer.length = length

        torch = types.SimpleNamespace(__version__="2.9.0", arange=lambda start, end, **kwargs: list(range(start, end)))
        hf = types.SimpleNamespace(__version__="4.57.1", DynamicCache=Cache)
        model = types.SimpleNamespace(
            training=False, device="cpu", config=types.SimpleNamespace(
                model_type="qwen3", rope_scaling=None, layer_types=["full_attention"], use_cache=True),
            generation_config=types.SimpleNamespace(use_cache=True, cache_implementation=None))
        cache = SampleKVCache(True, 10_000)
        cache.start_sample("sample")
        cache.compatible = lambda *_args: True
        ids = [ord(char) for char in first_body]
        cache.prepare(ids, model, hf, torch)
        cache.cache = Cache(length=len(ids))
        cache.tokens = ids

        cache_args, reused = cache.prepare(ids + [999], model, hf, torch)

        self.assertEqual(reused, len(ids))
        self.assertEqual(cache_args["cache_position"], [len(ids)])


@unittest.skipUnless(LIBRARIES, "Needs the pinned CPU inference libraries")
class ExactCacheTests(unittest.TestCase):
    def setUp(self):
        import torch
        import transformers as hf

        self.torch, self.hf = torch, hf
        torch.set_num_threads(1)
        torch.manual_seed(73)
        config = hf.Qwen3Config(vocab_size=64, hidden_size=32, intermediate_size=48,
                               num_hidden_layers=2, num_attention_heads=4, num_key_value_heads=2,
                               head_dim=8, max_position_embeddings=256, eos_token_id=63, pad_token_id=63)
        config._attn_implementation = "eager"
        self.model = hf.Qwen3ForCausalLM(config).eval()
        self.kv = SampleKVCache(True, 256)
        self.kv.start_sample("one")
        self.planner = types.SimpleNamespace(model=self.model, torch=torch, hf=hf, device="cpu", kv=self.kv)

    def decide(self, ids):
        torch = self.torch
        tokens = torch.tensor([ids])
        args = dict(attention_mask=torch.ones_like(tokens), max_new_tokens=6,
                    do_sample=False, num_beams=1, pad_token_id=63, eos_token_id=63)
        with torch.inference_mode():
            baseline = self.model.generate(tokens, **args)
            cache_args, reused = self.kv.prepare(ids, self.model, self.hf, torch)
            measure = ForwardMeasurement(self.planner, reused)
            with measure.attach():
                cached = self.model.generate(tokens, **args, **cache_args)
            metrics = measure.finish(ids)
            self.assertEqual(baseline.tolist(), cached.tolist())
            self.assertEqual(metrics["kv_cache_new_prefill_tokens"], len(ids) - reused)
            self.assertEqual(self.kv.tokens, cached[0].tolist()[:self.kv.cache.get_seq_length()])
            # Full forward on the ACTUALLY processed sequence is an independent KV oracle.
            reference = self.model(torch.tensor([self.kv.tokens]), use_cache=True).past_key_values
            for actual, expected in zip(self.kv.cache.layers, reference.layers):
                torch.testing.assert_close(actual.keys, expected.keys, atol=1e-6, rtol=1e-5)
                torch.testing.assert_close(actual.values, expected.values, atol=1e-6, rtol=1e-5)
        return reused, cached

    def test_append_divergence_replay_and_shorter_prompts_match_fresh_prefill(self):
        self.assertEqual(self.decide([5, 6, 7, 8])[0], 0)
        self.assertEqual(self.decide([5, 6, 7, 9, 10])[0], 3)
        self.assertEqual(self.decide([5, 6, 7, 9, 10])[0], 4)
        self.assertEqual(self.decide([5, 6])[0], 1)
        self.assertGreater(self.kv.metrics["kv_cache_invalidations"], 0)
        self.assertGreater(self.kv.metrics["kv_cache_peak_memory_bytes"], 0)

    def test_generated_last_token_is_not_claimed_as_processed(self):
        _, output = self.decide([5, 6, 7])
        self.assertEqual(len(self.kv.tokens), output.shape[-1] - 1)

    def test_no_matching_prefix_and_new_sample_do_not_reuse(self):
        self.decide([5, 6, 7])
        self.assertEqual(self.decide([9, 8, 7])[0], 0)
        self.kv.start_sample("two")
        self.assertEqual(self.kv.metrics["kv_cache_hits"], 0)
        self.assertIsNone(self.kv.cache)
        self.assertEqual(self.decide([9, 8, 7])[0], 0)
        self.kv.end_sample()
        self.assertIsNone(self.kv.cache)
        self.assertEqual(self.kv.tokens, [])

    def test_unsupported_sliding_or_dynamic_rope_falls_back_before_generation(self):
        for change in ({"rope_scaling": {"rope_type": "dynamic"}}, {"layer_types": ["sliding_attention"] * 2}):
            with self.subTest(change=change), patch.dict(self.model.config.__dict__, change):
                args, reused = self.kv.prepare([1, 2], self.model, self.hf, self.torch)
                self.assertEqual((args, reused), ({}, 0))
                self.assertIsNone(self.kv.cache)

    def test_unverifiable_cache_is_discarded(self):
        self.decide([5, 6, 7])
        original = self.kv.cache
        self.kv.tokens.append(12)
        args, reused = self.kv.prepare([5, 6, 7, 8], self.model, self.hf, self.torch)
        self.assertEqual(reused, 0)
        self.assertIn("invalid_cache_length_or_type", self.kv.metrics["kv_cache_invalidation_reasons"])
        self.kv.remember(list(range(self.kv.limit + 1)), original, self.model, self.hf)
        self.assertIsNone(self.kv.cache)
        self.assertEqual(self.kv.tokens, [])


@unittest.skipUnless(LIBRARIES and os.environ.get("LIFEMATE_NATIVE_TOKENIZER"), "Needs local Qwen tokenizer files")
class NativeCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        import transformers as hf

        torch.set_num_threads(1)
        torch.manual_seed(91)
        cls.torch, cls.hf = torch, hf
        cls.tokenizer = hf.AutoTokenizer.from_pretrained(os.environ["LIFEMATE_NATIVE_TOKENIZER"], local_files_only=True)
        config = hf.Qwen3Config(vocab_size=len(cls.tokenizer), hidden_size=16, intermediate_size=32,
                               num_hidden_layers=2, num_attention_heads=2, num_key_value_heads=1,
                               head_dim=8, eos_token_id=cls.tokenizer.eos_token_id,
                               pad_token_id=cls.tokenizer.eos_token_id, max_position_embeddings=16384)
        config._attn_implementation = "eager"
        cls.model = hf.Qwen3ForCausalLM(config).eval()
        cls.constraint = NativeConstraint(cls.tokenizer)
        cls.prepared = {"request": "List contacts", "context": {}, "history": [], "available_tools": [
            {"name": "contacts.list", "description": "List contacts", "parameters": {"type": "object", "properties": {}}}]}

    def planner(self, enabled):
        planner = NativePlanner.__new__(NativePlanner)
        planner.torch, planner.hf, planner.device = self.torch, self.hf, "cpu"
        planner.cpu_offload = False
        planner.model, planner.tokenizer, planner.constraint = self.model, self.tokenizer, self.constraint
        planner.limits, planner.eos_ids = Limits(), {self.tokenizer.eos_token_id}
        planner.kv = SampleKVCache(enabled, 16384)
        planner.start_sample("one")
        return planner

    def test_native_template_boundaries_tokens_actions_and_arguments_match_off(self):
        off, on = self.planner(False), self.planner(True)
        observations = []
        for index in range(3):
            left, lm = off.decide(self.prepared, observations, 28)
            right, rm = on.decide(self.prepared, observations, 28)
            self.assertEqual(left, right)
            self.assertEqual(lm["generated_token_ids"], rm["generated_token_ids"])
            self.assertEqual(lm["kv_cache_reused_tokens"], 0)
            if index:
                self.assertGreater(rm["kv_cache_reused_tokens"], 0)
                self.assertLess(rm["kv_cache_new_prefill_tokens"], rm["prompt_tokens"])
            observations.append({"name": "contacts.list", "arguments": {}, "result": {"ok": True, "page": index}})
        self.assertTrue(on.kv.tokens)
        on.end_sample()
        self.assertIsNone(on.kv.cache)

    def test_fixed_skill_guidance_keeps_an_exact_reusable_prefix(self):
        planner = self.planner(True)
        guidance = ({"branch_id": "S01.B01", "parent_id": "S01", "title": "Device",
                     "evidence": "E", "action_groups": [["contacts.list"]],
                     "conditional_dependencies": [], "conditional_actions": [], "constraints": [],
                     "completion_criteria": "Done", "missing_information": "Ask if needed",
                     "common_refs": [], "shared_instructions": [], "guidance": "Use the listed device."},)
        planner.decide(self.prepared, [], 28, skill_guidance=guidance)
        observation = {"name": "contacts.list", "arguments": {}, "result": {"ok": True, "page": 1}}
        _, second = planner.decide(self.prepared, [observation], 28, skill_guidance=guidance)
        self.assertGreater(second["kv_cache_reused_tokens"], 0)
        planner.end_sample()

    def test_context_and_generation_errors_clear_cache_and_propagate(self):
        planner = self.planner(True)
        planner.decide(self.prepared, [], 28)
        planner.limits = Limits(context_tokens=10, output_tokens=4)
        with self.assertRaises(PipelineError) as caught:
            planner.decide(self.prepared, [], 28)
        self.assertEqual(caught.exception.code, "CONTEXT_LIMIT")
        self.assertIsNone(planner.kv.cache)
        planner.limits = Limits()
        with patch.object(planner.model, "generate", side_effect=RuntimeError("CUDA error")):
            with self.assertRaises(PipelineError) as caught:
                planner.decide(self.prepared, [], 28)
        self.assertEqual(caught.exception.code, "PLANNER_ERROR")
        self.assertIsNone(planner.kv.cache)
        self.assertEqual(len(planner.model._forward_hooks), 0)

    def test_deadline_error_does_not_retain_cache(self):
        planner = self.planner(True)
        planner.decide(self.prepared, [], 28)
        measured_tokens = planner.kv.metrics["kv_cache_reused_tokens"]
        with self.assertRaises(PipelineError) as caught:
            planner.decide(self.prepared, [], 0)
        self.assertEqual(caught.exception.code, "TIME_LIMIT")
        self.assertIsNone(planner.kv.cache)
        self.assertEqual(planner.kv.metrics["kv_cache_reused_tokens"], measured_tokens)

    def test_agent_statuses_logs_hashes_and_lifecycle_match_off(self):
        from lifemate.adapters.qwen_native import completion_text

        fixture = Fixture()
        self.addCleanup(fixture.close)
        sample = preflight(fixture.config()).samples[0]
        search = {"action": "call", "name": "contacts.search", "arguments": {"query": "Lan"}}
        ask = {"action": "call", "name": "sys.ask_missing_info",
               "arguments": {"tool_name": "sms.send", "params": ["content"]}}
        scenarios = [("completed", [search, {"action": "finish"}], 0),
                     ("needs_info", [search, ask], 0), ("partial", [search] * 16, 0),
                     ("partial", [search], 28), ("failed", [search], 30)]
        for status, script, tool_seconds in scenarios:
            outcomes = []
            for enabled in (False, True):
                planner = self.planner(enabled)
                clock, env = Clock(), Environment()
                if tool_seconds:
                    def timed_response(*args):
                        clock.advance(tool_seconds)
                        return {"ok": True}
                    env.response = timed_response
                base_constraint = self.constraint
                tokenizer = self.tokenizer
                actions = iter(script)

                class ScriptConstraint:
                    # Exercise agent terminal paths with real model forwards and real
                    # LMFE eligibility. The independent unconstrained KV oracle above
                    # checks that reuse preserves model numerics, not only forced tokens.
                    def prefix(self, tools):
                        native = base_constraint.prefix(tools)
                        target = tokenizer.encode(completion_text(next(actions)), add_special_tokens=False)
                        target.append(tokenizer.eos_token_id)
                        initial = None

                        def allowed(batch, ids):
                            nonlocal initial
                            initial = len(ids) if initial is None else initial
                            token = target[len(ids) - initial]
                            if token not in native(batch, ids):
                                raise AssertionError("Scripted token violates the native grammar")
                            return [token]
                        return allowed

                planner.constraint = ScriptConstraint()
                outcome = run_integration_sample(sample, planner, None, lambda *args: env, MemoryTrace(),
                                                 Limits(), Deadline(30, clock), split="train",
                                                 data_root=fixture.data, clock=clock)
                self.assertEqual(outcome.status, status, outcome.error)
                self.assertIsNone(planner.kv.cache)
                self.assertIsNone(planner.kv.sample_id)
                if outcome.result is not None:
                    self.assertEqual(outcome.result["tool_calls"], env.get_tool_calls())
                    self.assertEqual(outcome.result["state_hash"], env.get_state_hash())
                else:
                    self.assertEqual(outcome.error["code"], "TIME_LIMIT")
                outcomes.append(outcome)
            self.assertEqual(outcomes[0].result, outcomes[1].result)
            self.assertEqual([d["generated_token_ids"] for d in outcomes[0].metrics["decisions"]],
                             [d["generated_token_ids"] for d in outcomes[1].metrics["decisions"]])
            if len(script) > 1:
                self.assertGreater(outcomes[1].metrics["planner"]["kv_cache_hits"], 0)
            if status == "partial":
                self.assertEqual(outcomes[1].stop_reason, "soft_deadline" if tool_seconds else "step_limit")

    def test_offload_releases_cache_before_model_transfer(self):
        planner = self.planner(True)
        planner.decide(self.prepared, [], 28)
        planner.cpu_offload = True
        transfers = []

        def move(device):
            transfers.append(device)
            if len(transfers) == 2:
                self.assertIsNone(planner.kv.cache)
            return planner.model

        with patch.object(planner.model, "to", side_effect=move), patch.object(self.torch.cuda, "empty_cache"):
            with planner.inference_session():
                pass
        self.assertEqual(transfers, ["cpu", "cpu"])
        self.assertIn("cpu_offload", planner.kv.metrics["kv_cache_invalidation_reasons"])


if __name__ == "__main__":
    unittest.main()
