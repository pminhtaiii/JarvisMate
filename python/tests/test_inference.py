"""Adapter contract tests with model-library doubles; no weights or GPU."""
import contextlib
import types
import unittest
from unittest.mock import MagicMock, patch

from lifemate.adapters.asr import LocalASR
from lifemate.adapters.common import ModelResidency, dependencies, model_directory, stopping_criteria
from lifemate.adapters.planner import LocalPlanner
from lifemate.contracts import Limits, PipelineError
from support import Fixture


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

    def load(self, limits=None):
        with patch("lifemate.adapters.planner.dependencies", return_value=(self.torch, self.hf, self.np)), \
             patch("lifemate.adapters.planner.metadata", return_value=self.metadata), \
             patch("lifemate.adapters.planner.ActionConstraint"):
            return LocalPlanner(self.weights, "cpu", limits or Limits())

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
