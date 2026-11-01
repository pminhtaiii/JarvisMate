"""Adapter contract tests with model-library doubles; no weights or GPU."""
import contextlib
import hashlib
import json
import types
import unittest
from unittest.mock import MagicMock, patch

from lifemate.adapters.asr import LocalASR
from lifemate.adapters.common import ModelResidency, dependencies, model_directory, stopping_criteria
from lifemate.adapters.planner import LocalPlanner
from lifemate.adapters.qwen_protocol import render_tools
from lifemate.contracts import Limits, PipelineError
from lifemate.metrics import SpanRecorder
from lifemate.prompt_profiles import PRECISE_V1_SYSTEM, resolve_profile
from lifemate.prompting import NATIVE_FINISH_TEXT, NATIVE_PROMPT_HASH, NATIVE_SYSTEM
from support import CATALOG, Fixture


class Tensor:
    def __init__(self, size=10):
        self.shape = (1, size)

    def to(self, *args, **kwargs):
        return self


class Array:
    def astype(self, *_):
        return self

    def __truediv__(self, _):
        return self


class ModelResidencyTests(unittest.TestCase):
    def test_transfer_failure_preserves_cause_and_skips_inference(self):
        adapter = ModelResidency()
        adapter.cpu_offload, adapter.device = True, "cuda"
        adapter.model, adapter.torch = MagicMock(), MagicMock()
        failure = RuntimeError("device unavailable")
        adapter.model.to.side_effect = failure
        with self.assertRaises(PipelineError) as caught:
            with adapter.inference_session():
                self.fail("Inference must not start after a transfer failure")
        self.assertEqual(caught.exception.code, "MODEL_UNAVAILABLE")
        self.assertIs(caught.exception.__cause__, failure)

    def test_successful_session_and_inference_failure_both_offload(self):
        for failure in (None, PipelineError("PLANNER_FORMAT", "invalid action", "planner")):
            with self.subTest(failure=failure):
                adapter = ModelResidency()
                adapter.cpu_offload, adapter.device = True, "cuda"
                adapter.model, adapter.torch = MagicMock(), MagicMock()
                try:
                    with adapter.inference_session():
                        if failure:
                            raise failure
                except PipelineError as exc:
                    self.assertIs(exc, failure)
                self.assertEqual([c.args[0] for c in adapter.model.to.call_args_list], ["cuda", "cpu"])
                adapter.torch.cuda.empty_cache.assert_called_once()


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.close)
        self.weights = self.fx.root / "weights"
        self.weights.mkdir()
        (self.weights / "config.json").write_text('{"model_type":"qwen3"}', encoding="utf-8")
        self.model = MagicMock()
        self.model.to.return_value = self.model
        self.model.parameters.return_value = [types.SimpleNamespace(numel=lambda: 100)]
        self.model.generate.return_value = [list(range(12))]
        self.tokenizer = MagicMock()
        self.tokenizer.apply_chat_template.return_value = "rendered prompt"
        self.tokenizer.return_value = {"input_ids": Tensor(), "attention_mask": Tensor()}
        self.tokenizer.decode.return_value = '{"action":"finish"}'
        self.tokenizer.eos_token_id = 2
        self.processor = MagicMock()
        self.processor.return_value = {"input_features": Tensor(), "attention_mask": Tensor()}
        self.processor.batch_decode.return_value = ["Xin chào"]
        self.hf = types.SimpleNamespace(
            AutoConfig=types.SimpleNamespace(from_pretrained=MagicMock(return_value=types.SimpleNamespace(model_type="qwen3"))),
            AutoTokenizer=types.SimpleNamespace(from_pretrained=MagicMock(return_value=self.tokenizer)),
            AutoModelForCausalLM=types.SimpleNamespace(from_pretrained=MagicMock(return_value=self.model)),
            WhisperProcessor=types.SimpleNamespace(from_pretrained=MagicMock(return_value=self.processor)),
            WhisperForConditionalGeneration=types.SimpleNamespace(from_pretrained=MagicMock(return_value=self.model)),
            StoppingCriteria=object, StoppingCriteriaList=lambda values: values)
        self.torch = types.SimpleNamespace(float32="float32", float16="float16",
                                           inference_mode=contextlib.nullcontext)
        self.np = types.SimpleNamespace(float32="float32", frombuffer=lambda *a, **k: Array())
        self.metadata = {"parameter_count": 100, "test_only": True}
        self.input = {"request": "Chào", "context": {}, "history": [],
                      "available_tools": [], "observations": []}

    def load(self, limits=None, **kwargs):
        with patch("lifemate.adapters.planner.dependencies", return_value=(self.torch, self.hf, self.np)), \
             patch("lifemate.adapters.planner.metadata", return_value=self.metadata), \
             patch("lifemate.adapters.planner.ActionConstraint"):
            return LocalPlanner(self.weights, "cpu", limits or Limits(), **kwargs)

    def test_local_only_load_and_greedy_generation_reuse(self):
        planner = self.load()
        for _ in range(2):
            self.assertEqual(planner.next_action(self.input, 30), '{"action":"finish"}')
        self.hf.AutoModelForCausalLM.from_pretrained.assert_called_once()
        for loader in (self.hf.AutoConfig, self.hf.AutoTokenizer, self.hf.AutoModelForCausalLM):
            kwargs = loader.from_pretrained.call_args.kwargs
            self.assertIs(kwargs["local_files_only"], True)
            self.assertIs(kwargs["trust_remote_code"], False)
        kwargs = self.model.generate.call_args.kwargs
        self.assertIs(kwargs["do_sample"], False)
        self.assertEqual(kwargs["num_beams"], 1)
        self.assertEqual(kwargs["max_new_tokens"], 512)

    def test_prompt_and_output_budget_reject_before_generate(self):
        planner = self.load(Limits(context_tokens=20, output_tokens=15))
        with self.assertRaises(PipelineError) as caught:
            planner.next_action(self.input, 30)
        self.assertEqual(caught.exception.code, "CONTEXT_LIMIT")
        self.model.generate.assert_not_called()

    def test_default_profile_is_baseline_and_recorded_in_metadata(self):
        planner = self.load()
        self.assertEqual(planner.metadata["prompt_profile"]["profile"], "baseline")
        self.assertIsNone(planner.metadata["example_overhead_tokens"])
        self.assertIsNone(planner.metadata["few_shot_token_budget"])

    def test_precise_v1_profile_changes_the_rendered_system_message(self):
        captured = []
        self.tokenizer.apply_chat_template.side_effect = lambda turns, **kw: (captured.append(turns), "rendered")[1]
        planner = self.load(profile=resolve_profile("precise-v1"))
        planner.next_action(self.input, 30)
        self.assertEqual(captured[0][0]["content"], PRECISE_V1_SYSTEM)
        self.assertEqual(planner.metadata["prompt_profile"]["profile"], "precise-v1")

    def test_examples_add_measurable_token_overhead_and_are_recorded(self):
        example = {"input": {"request": "Gửi tin", "context": {}, "history": [], "available_tools": [],
                             "observations": []}, "target": {"action": "finish"}}
        # A deterministic stand-in for real tokenization: render length tracks turn count.
        self.tokenizer.apply_chat_template.side_effect = lambda turns, **kw: "x" * len(turns)
        self.tokenizer.side_effect = lambda text, **kw: {"input_ids": Tensor(len(text))}
        planner = self.load(examples=(example,), few_shot_token_budget=100)
        self.assertEqual(planner.example_overhead_tokens, 2)  # two added demonstration turns
        self.assertEqual(planner.metadata["example_overhead_tokens"], 2)
        self.assertEqual(planner.metadata["few_shot_token_budget"], 100)
        # The real tokenizer returns a plain list without `return_tensors="pt"`,
        # which has no `.shape`; guard against losing that kwarg again.
        for call in self.tokenizer.call_args_list:
            self.assertEqual(call.kwargs.get("return_tensors"), "pt")

    def test_live_few_shot_overhead_is_rechecked_every_decision_not_only_at_init(self):
        example = {"input": {"request": "Gửi tin", "context": {}, "history": [], "available_tools": [],
                             "observations": []}, "target": {"action": "finish"}}
        self.tokenizer.apply_chat_template.side_effect = lambda turns, **kw: "x" * len(turns)
        self.tokenizer.side_effect = lambda text, **kw: {"input_ids": Tensor(len(text))}
        planner = self.load(examples=(example,), few_shot_token_budget=100)
        calls_before = self.tokenizer.apply_chat_template.call_count
        planner.next_action(self.input, 30)
        new_calls = self.tokenizer.apply_chat_template.call_args_list[calls_before:]
        turn_counts = sorted(len(call.args[0]) for call in new_calls)
        # One render includes the two example turns (used for generation), one
        # omits them (the live budget check); the cached init-time probe alone
        # is never trusted again for this decision.
        self.assertEqual(len(new_calls), 2)
        self.assertEqual(turn_counts[-1] - turn_counts[-2], 2)

    def test_examples_exceeding_the_few_shot_token_budget_raise_before_any_sample(self):
        example = {"input": {"request": "Gửi tin", "context": {}, "history": [], "available_tools": [],
                             "observations": []}, "target": {"action": "finish"}}
        self.tokenizer.apply_chat_template.side_effect = lambda turns, **kw: "x" * len(turns)
        self.tokenizer.side_effect = lambda text, **kw: {"input_ids": Tensor(len(text))}
        with self.assertRaises(PipelineError) as caught:
            self.load(examples=(example,), few_shot_token_budget=1)
        self.assertEqual(caught.exception.code, "CONTEXT_LIMIT")
        self.model.generate.assert_not_called()

    def test_missing_local_weights_and_oversized_model_fail(self):
        with self.assertRaises(PipelineError):
            model_directory(self.fx.root / "missing")
        self.model.parameters.return_value = [types.SimpleNamespace(numel=lambda: 5_000_000_000)]
        with self.assertRaises(PipelineError):
            self.load()

    def test_context_limit_cannot_exceed_competition_cap(self):
        with self.assertRaises(PipelineError):
            Limits(context_tokens=16_385)

    def test_expired_deadline_prevents_generation(self):
        planner = self.load()
        with self.assertRaises(PipelineError):
            planner.next_action(self.input, 0)
        self.model.generate.assert_not_called()

    def test_stopping_criterion_observes_remaining_time(self):
        with patch("lifemate.adapters.common.time.monotonic", side_effect=[10, 12]):
            stop = stopping_criteria(self.hf, 1)
            self.assertTrue(stop[0](None, None))

    def test_device_unavailable_does_not_fall_back_to_cpu(self):
        torch = MagicMock()
        torch.cuda.is_available.return_value = False
        modules = {"numpy": MagicMock(), "torch": torch, "transformers": MagicMock()}
        with patch.dict("sys.modules", modules), self.assertRaises(PipelineError):
            dependencies("cuda", 1)
        torch.manual_seed.assert_not_called()

    def test_seed_and_offline_policy(self):
        torch = MagicMock()
        np = MagicMock()
        with patch.dict("sys.modules", {"numpy": np, "torch": torch, "transformers": MagicMock()}), \
             patch.dict("os.environ", {}, clear=False):
            dependencies("cpu", 123)
            import os
            self.assertEqual(os.environ["HF_HUB_OFFLINE"], "1")
            torch.manual_seed.assert_called_once_with(123)
            np.random.seed.assert_called_once_with(123)
            torch.use_deterministic_algorithms.assert_called_once_with(True)

    def test_whisper_uses_wav_data_and_local_vietnamese_generation(self):
        with patch("lifemate.adapters.asr.dependencies", return_value=(self.torch, self.hf, self.np)), \
             patch("lifemate.adapters.asr.metadata", return_value=self.metadata):
            asr = LocalASR(self.weights, "cpu", Limits())
        self.assertEqual(asr.transcribe(self.fx.split / self.fx.rows[0]["audio"], 30), "Xin chào")
        self.assertTrue(self.hf.WhisperProcessor.from_pretrained.call_args.kwargs["local_files_only"])
        kwargs = self.model.generate.call_args.kwargs
        self.assertEqual(kwargs["language"], "vi")
        self.assertEqual(kwargs["task"], "transcribe")
        self.assertFalse(kwargs["do_sample"])

    def test_planner_records_generation_detail_when_recorder_is_attached(self):
        planner = self.load()
        recorder = SpanRecorder()
        planner.set_metrics_recorder(recorder)
        planner.next_action(self.input, 30)
        self.assertEqual([s.stage for s in recorder.spans], ["generation"])
        self.assertEqual(recorder.spans[0].parent_stage, "planner_decision")
        self.assertEqual(len(recorder.generations), 1)
        generation = recorder.generations[0]
        self.assertEqual(generation.role, "planner_action")
        self.assertEqual(generation.index, 0)
        self.assertEqual(generation.input_tokens, 10)
        self.assertEqual(generation.output_tokens, 2)
        self.assertEqual(generation.stop_reason, "eos")

    def test_planner_generation_index_resets_per_sample_and_advances_within_one(self):
        planner = self.load()
        recorder = SpanRecorder()
        planner.set_metrics_recorder(recorder)
        planner.next_action(self.input, 30)
        planner.next_action(self.input, 30)
        self.assertEqual([g.index for g in recorder.generations], [0, 1])
        planner.set_metrics_recorder(SpanRecorder())
        planner.next_action(self.input, 30)
        self.assertEqual(planner._recorder.generations[0].index, 0)

    def test_planner_records_unfinished_generation_on_model_error(self):
        planner = self.load()
        recorder = SpanRecorder()
        planner.set_metrics_recorder(recorder)
        self.model.generate.side_effect = RuntimeError("device error")
        with self.assertRaises(PipelineError):
            planner.next_action(self.input, 30)
        self.assertEqual(len(recorder.spans), 1)
        self.assertEqual(recorder.spans[0].status, "unfinished")
        self.assertEqual(recorder.generations, [])

    def test_no_recorder_attached_records_nothing(self):
        planner = self.load()
        planner.next_action(self.input, 30)  # must not raise with no recorder attached

    def test_asr_records_generation_detail_when_recorder_is_attached(self):
        with patch("lifemate.adapters.asr.dependencies", return_value=(self.torch, self.hf, self.np)), \
             patch("lifemate.adapters.asr.metadata", return_value=self.metadata):
            asr = LocalASR(self.weights, "cpu", Limits())
        self.model.generate.return_value = Tensor(14)
        recorder = SpanRecorder()
        asr.set_metrics_recorder(recorder)
        asr.transcribe(self.fx.split / self.fx.rows[0]["audio"], 30)
        self.assertEqual([s.stage for s in recorder.spans], ["generation"])
        self.assertEqual(recorder.spans[0].parent_stage, "asr_clip")
        self.assertEqual(len(recorder.generations), 1)
        generation = recorder.generations[0]
        self.assertEqual(generation.role, "asr")
        self.assertEqual(generation.output_tokens, 14)
        self.assertEqual(generation.stop_reason, "eos")

    def test_asr_generation_capped_at_max_new_tokens_is_labeled_max_tokens_not_eos(self):
        with patch("lifemate.adapters.asr.dependencies", return_value=(self.torch, self.hf, self.np)), \
             patch("lifemate.adapters.asr.metadata", return_value=self.metadata):
            asr = LocalASR(self.weights, "cpu", Limits())
        self.model.generate.return_value = Tensor(440)  # Hits the generation cap, not the deadline.
        recorder = SpanRecorder()
        asr.set_metrics_recorder(recorder)
        asr.transcribe(self.fx.split / self.fx.rows[0]["audio"], 30)
        self.assertEqual(recorder.generations[0].stop_reason, "max_tokens")

    def test_asr_clip_index_advances_across_calls_and_resets_on_rebind(self):
        with patch("lifemate.adapters.asr.dependencies", return_value=(self.torch, self.hf, self.np)), \
             patch("lifemate.adapters.asr.metadata", return_value=self.metadata):
            asr = LocalASR(self.weights, "cpu", Limits())
        recorder = SpanRecorder()
        asr.set_metrics_recorder(recorder)
        path = self.fx.split / self.fx.rows[0]["audio"]
        asr.transcribe(path, 30)
        asr.transcribe(path, 30)
        self.assertEqual([g.index for g in recorder.generations], [0, 1])
        asr.set_metrics_recorder(SpanRecorder())
        asr.transcribe(path, 30)
        self.assertEqual(asr._recorder.generations[0].index, 0)

    def test_asr_records_unfinished_generation_on_model_error(self):
        with patch("lifemate.adapters.asr.dependencies", return_value=(self.torch, self.hf, self.np)), \
             patch("lifemate.adapters.asr.metadata", return_value=self.metadata):
            asr = LocalASR(self.weights, "cpu", Limits())
        recorder = SpanRecorder()
        asr.set_metrics_recorder(recorder)
        self.model.generate.side_effect = RuntimeError("device error")
        with self.assertRaises(PipelineError):
            asr.transcribe(self.fx.split / self.fx.rows[0]["audio"], 30)
        self.assertEqual(len(recorder.spans), 1)
        self.assertEqual(recorder.spans[0].status, "unfinished")
        self.assertEqual(recorder.generations, [])

    def test_structured_protocol_is_the_default_and_keeps_its_metadata(self):
        planner = self.load()
        self.assertEqual(planner.protocol, "structured-v1")
        self.assertEqual(planner.metadata["adapter"], "qwen3-structured-react")
        self.assertNotIn("native_protocol", planner.metadata)
        planner.next_action(self.input, 30)
        self.assertNotIn("tools", self.tokenizer.apply_chat_template.call_args.kwargs)
        planner.constraint.prefix.assert_called_once()
        planner.constraint.native_prefix.assert_not_called()

    def test_whisper_rejects_truncated_payload(self):
        with patch("lifemate.adapters.asr.dependencies", return_value=(self.torch, self.hf, self.np)), \
             patch("lifemate.adapters.asr.metadata", return_value=self.metadata):
            asr = LocalASR(self.weights, "cpu", Limits())
        target = self.fx.split / self.fx.rows[0]["audio"]
        raw = target.read_bytes()
        target.write_bytes(raw[:-10])
        with self.assertRaises(PipelineError):
            asr.transcribe(target, 30)
        self.model.generate.assert_not_called()


TOOLS = [tool for app in CATALOG["apps"] for tool in app["tools"]]
EOS = 2
CALL = '<tool_call>\n{"name": "contacts.search", "arguments": {"query": "Lan"}}\n</tool_call>'


class NativeAdapterTests(unittest.TestCase):
    """qwen-native-v1 inside LocalPlanner; model, tokenizer and grammar are doubles."""

    setUp_shared = AdapterTests.setUp
    load = AdapterTests.load

    def setUp(self):
        self.setUp_shared()
        self.tokenizer.chat_template = "{{ qwen3 template }}"
        self.input = {"request": "Nhắn Lan", "context": {}, "history": [],
                      "available_tools": TOOLS, "observations": []}
        self.generate(CALL)

    def generate(self, text, tokens=(11, 12, EOS)):
        # Ten prompt tokens followed by the generated ids; decode yields `text`.
        self.model.generate.return_value = [list(range(10)) + list(tokens)]
        self.tokenizer.decode.return_value = text

    def native(self, limits=None, **kwargs):
        return self.load(limits, protocol="qwen-native-v1", **kwargs)

    def rejected(self, planner, code):
        with self.assertRaises(PipelineError) as caught:
            planner.next_action(self.input, 30)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_complete_call_returns_the_canonical_decision(self):
        planner = self.native()
        self.assertEqual(json.loads(planner.next_action(self.input, 30)),
                         {"action": "call", "name": "contacts.search", "arguments": {"query": "Lan"}})

    def test_exact_final_text_returns_canonical_finish(self):
        self.generate(NATIVE_FINISH_TEXT)
        self.assertEqual(json.loads(self.native().next_action(self.input, 30)), {"action": "finish"})

    def test_native_rendering_passes_eligible_tools_through_the_template(self):
        planner = self.native()
        planner.next_action(self.input, 30)
        args, kwargs = self.tokenizer.apply_chat_template.call_args
        self.assertEqual(kwargs["tools"], render_tools(TOOLS))
        self.assertIs(kwargs["add_generation_prompt"], True)
        self.assertIs(kwargs["enable_thinking"], False)
        turns = args[0]
        self.assertEqual(turns[0], {"role": "system", "content": NATIVE_SYSTEM})
        self.assertNotIn("available_tools", json.loads(turns[1]["content"]))
        planner.constraint.native_prefix.assert_called_once_with(TOOLS)
        planner.constraint.prefix.assert_not_called()

    def test_executed_observations_render_as_tool_calls_and_results(self):
        planner = self.native()
        self.input["observations"] = [{"step": 1, "kind": "tool_result", "name": "contacts.search",
                                       "arguments": {"query": "Lan"}, "result": {"ok": True, "items": []}}]
        planner.next_action(self.input, 30)
        turns = self.tokenizer.apply_chat_template.call_args.args[0]
        self.assertEqual([t["role"] for t in turns], ["system", "user", "assistant", "tool"])

    def test_metadata_records_native_protocol_identity(self):
        planner = self.native()
        self.assertEqual(planner.metadata["adapter"], "qwen3-native-tool-call")
        self.assertEqual(planner.metadata["prompt_profile"]["sha256"], NATIVE_PROMPT_HASH)
        self.assertEqual(planner.metadata["native_protocol"], {
            "protocol": "qwen-native-v1", "final_text": NATIVE_FINISH_TEXT, "eos_token_id": EOS,
            "chat_template_sha256": hashlib.sha256(b"{{ qwen3 template }}").hexdigest()})

    def test_unavailable_tool_is_a_format_failure_not_a_decision(self):
        self.generate('<tool_call>\n{"name": "bank.transfer", "arguments": {}}\n</tool_call>')
        planner = self.native()
        self.rejected(planner, "PLANNER_FORMAT")
        self.assertEqual(planner.last_native_outputs[0]["decision"], "rejected")
        self.assertIsNone(planner.last_native_outputs[0]["canonical_action"])

    def test_malformed_output_ended_at_eos_is_a_format_failure(self):
        for text in ("Mình hiểu", "Được.\n" + CALL, CALL + "\n" + CALL, '{"action":"finish"}', ""):
            with self.subTest(text=text):
                self.generate(text)
                self.rejected(self.native(), "PLANNER_FORMAT")

    def test_complete_looking_call_without_eos_at_the_token_budget_is_an_output_limit(self):
        self.generate(CALL, tokens=(11, 12, 13))
        planner = self.native(Limits(context_tokens=100, output_tokens=3))
        self.rejected(planner, "OUTPUT_LIMIT")
        self.assertEqual(planner.last_native_outputs[0]["stop_reason"], "max_tokens")

    def test_stop_without_eos_below_the_budget_is_an_adapter_failure(self):
        self.generate(CALL, tokens=(11, 12))
        self.rejected(self.native(), "PLANNER_ERROR")

    def test_deadline_cut_wins_over_complete_text(self):
        clock = [0.0]

        def generate(**_):
            clock[0] = 100.0
            return [list(range(10)) + [11, 12, EOS]]

        self.model.generate.side_effect = generate
        planner = self.native()
        with patch("time.monotonic", lambda: clock[0]):
            self.rejected(planner, "TIME_LIMIT")
        self.assertEqual(planner.last_native_outputs[0]["stop_reason"], "deadline")

    def test_generation_detail_reports_the_actual_eos(self):
        planner = self.native()
        recorder = SpanRecorder()
        planner.set_metrics_recorder(recorder)
        planner.next_action(self.input, 30)
        self.assertEqual(recorder.generations[0].stop_reason, "eos")
        self.assertEqual(planner.last_native_outputs, [{
            "text": CALL, "stop_reason": "eos", "output_tokens": 3, "decision": "call",
            "canonical_action": {"action": "call", "name": "contacts.search", "arguments": {"query": "Lan"}}}])

    def test_eos_is_inspected_before_special_tokens_are_skipped(self):
        self.native().next_action(self.input, 30)
        self.assertIs(self.tokenizer.decode.call_args.kwargs["skip_special_tokens"], True)
        self.assertEqual(list(self.tokenizer.decode.call_args.args[0])[-1], EOS)

    def test_incompatible_profile_examples_or_template_fail_before_generation(self):
        example = {"input": dict(self.input), "target": {"action": "finish"}}
        for kwargs, code in (({"profile": resolve_profile("precise-v1")}, "INPUT_INVALID"),
                             ({"examples": (example,)}, "INPUT_INVALID")):
            with self.subTest(kwargs=list(kwargs)):
                with self.assertRaises(PipelineError) as caught:
                    self.native(**kwargs)
                self.assertEqual(caught.exception.code, code)
        self.hf.AutoModelForCausalLM.from_pretrained.assert_not_called()
        self.tokenizer.chat_template = None
        with self.assertRaises(PipelineError) as caught:
            self.native()
        self.assertEqual(caught.exception.code, "MODEL_UNAVAILABLE")
        self.model.generate.assert_not_called()

    def test_selection_correction_reaches_the_native_retry_as_correction_data(self):
        tools = [{"name": "tasks.list", "kind": "read", "description": "Liệt kê",
                  "parameters": {"type": "object", "properties": {}}},
                 {"name": "tasks.complete", "kind": "write", "description": "Hoàn thành", "parameters": {
                     "type": "object", "properties": {"task_id": {"type": "string", "x-ref": "tasks.tasks"}}}}]
        self.input = {"request": "Hoàn thành việc phù hợp", "context": {}, "history": [], "available_tools": tools,
                      "observations": [{"step": 1, "kind": "tool_result", "name": "tasks.list", "arguments": {},
                                        "result": {"ok": True, "tasks": [{"id": "older", "title": "ineligible"},
                                                                         {"id": "allowed", "title": "eligible"}]}}]}
        rejected = '<tool_call>\n{"name": "tasks.complete", "arguments": {"task_id": "older"}}\n</tool_call>'
        self.tokenizer.decode.side_effect = [rejected, rejected.replace("older", "allowed")]
        planner = self.native(selection_filter=True)
        planner._select = MagicMock(return_value={"supported": True, "filters": [
            {"field": "title", "operator": "equals", "value": "eligible"}]})
        self.assertEqual(json.loads(planner.next_action(self.input, 30))["arguments"], {"task_id": "allowed"})
        self.assertEqual(self.tokenizer.apply_chat_template.call_count, 2)
        retry = self.tokenizer.apply_chat_template.call_args_list[1].args[0]
        executed = [c["function"] for t in retry for c in t.get("tool_calls", [])]
        self.assertEqual(executed, [{"name": "tasks.list", "arguments": {}}])
        correction = json.loads(retry[-1]["content"])["observation"]
        self.assertEqual((retry[-1]["role"], correction["code"]), ("user", "SELECTION_MISMATCH"))
        # The retry offers only the eligible IDs, so a fixed model reply cannot hide a lost restriction.
        retry_tools = self.tokenizer.apply_chat_template.call_args_list[1].kwargs["tools"]
        complete = next(t["function"] for t in retry_tools if t["function"]["name"] == "tasks.complete")
        self.assertEqual(complete["parameters"]["properties"]["task_id"]["enum"], ["allowed"])
        retry_grammar_tools = planner.constraint.native_prefix.call_args_list[1].args[0]
        self.assertEqual(retry_grammar_tools[1]["parameters"]["properties"]["task_id"]["enum"], ["allowed"])

    def test_unknown_protocol_is_rejected(self):
        with self.assertRaises(PipelineError) as caught:
            self.load(protocol="qwen-native-v2")
        self.assertEqual(caught.exception.code, "INPUT_INVALID")
