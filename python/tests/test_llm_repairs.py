"""Regressions for the eight reviewed foundation failures; controlled data only."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lifemate.llm_training import cli
from lifemate.llm_training.acceptance import accepted_corpus, audit_corpus, evaluation_readiness, native_acceptance
from lifemate.llm_training.config import DEFAULT_SELECTION_POLICY, load_config
from lifemate.llm_training.corpus import PreparationError, load_suite, prepare, seal_selection_policy
from lifemate.llm_training.model_identity import snapshot_identity
from lifemate.llm_training.storage import file_hash, read_json, read_jsonl, write_json, write_jsonl
from lifemate.llm_training.tokenization import verify_proof
from lifemate.adapters.qwen_native import native_call_message, render_native
from llm_support import FakeQwenTokenizer, SuiteFixture, accept_fixture


class FoundationRepairs(unittest.TestCase):
    def fixture(self):
        fx = SuiteFixture()
        self.addCleanup(fx.close)
        config = load_config(fx.config_path)
        prepare(config, fx.suite, expected=fx.expected)
        return fx, config

    def test_persisted_recursive_tools_and_prior_arguments_render_identically(self):
        tok = FakeQwenTokenizer()
        nested = {"z": {"type": "object", "properties": {"z": {"type": "array", "items": {"type": "string"}},
                  "a": {"type": "integer"}}, "required": ["a", "z"]}, "a": {"type": "string"}}
        tools = [{"type": "function", "function": {"name": "a.b", "description": "đ", "parameters": {
                  "type": "object", "properties": nested}}}]
        messages = [{"role": "system", "content": "test"}, {"role": "user", "content": "y"},
                    native_call_message("a.b", {"z": {"z": ["đ", "01"], "a": 7}, "a": "b"}),
                    {"role": "tool", "content": '{"ok":true}'}, {"role": "user", "content": "next"}]
        before = render_native(tok, messages, tools)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"rows.jsonl"
            write_jsonl(path, [{"input": {"messages": messages, "tools": tools}}])
            after = read_jsonl(path)[0]["input"]
            self.assertEqual(render_native(tok, after["messages"], after["tools"]), before)
            self.assertEqual(list(after["tools"][0]["function"]["parameters"]["properties"]), ["z", "a"])

    def test_evaluation_rejects_missing_acceptance_before_model_loader(self):
        fx, config = self.fixture()
        seal_selection_policy(fx.suite, DEFAULT_SELECTION_POLICY)
        with patch("lifemate.adapters.planner.LocalPlanner") as model:
            with self.assertRaises(PreparationError):
                cli.evaluate(config, cli.parser().parse_args(["evaluate", "--suite-dir", str(fx.suite),
                             "--experiment", "L0", "--mode", "G"]))
            model.assert_not_called()

    def test_l0_g_needs_native_acceptance_but_no_fit_token_corpus(self):
        fx, config = self.fixture()
        native_acceptance(config, fx.suite, FakeQwenTokenizer())
        self.assertIsNone(evaluation_readiness(config, fx.suite)["token_corpus"])
        with self.assertRaises(PreparationError):
            evaluation_readiness(config, fx.suite, teacher_forced=True)

    def test_source_and_catalog_hash_drift_blocks_before_model_load(self):
        for name in ("train.jsonl", "train_tools_catalog.json"):
            fx, config = self.fixture()
            accept_fixture(config, fx.suite)
            path = fx.data/"train"/name
            path.write_bytes(path.read_bytes()+b"\n")
            with self.assertRaises(PreparationError):
                evaluation_readiness(config, fx.suite)

    def test_all_overflow_is_failed_and_quarantined_rows_cannot_feed_nll(self):
        fx, config = self.fixture()
        class Huge(FakeQwenTokenizer):
            def apply_chat_template(self, *a, **kw):
                # Long but internally consistent shared rendering.
                result = super().apply_chat_template(*a, **kw)
                return [1001]*17000+result if isinstance(result, list) else chr(1)*17000+result
        from lifemate.llm_training.tokenization import TokenizationError
        with patch("lifemate.llm_training.tokenization.supervised", side_effect=TokenizationError("TOKEN_BUDGET", "overflow")):
            report = audit_corpus(config, fx.suite, FakeQwenTokenizer())
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["accepted_support"], {"fit": 0, "validation": 0})
        with self.assertRaises(PreparationError):
            accepted_corpus(config, fx.suite)

    def test_pending_reference_stays_out_of_token_valid_inputs(self):
        fx, config = self.fixture()
        accept_fixture(config, fx.suite)
        corpus = accepted_corpus(config, fx.suite)
        rows = corpus["rows"]
        self.assertNotIn("train_0010", {r["provenance"]["source_id"] for r in rows})
        self.assertTrue(all(r["provenance"]["source_id"] != "train_0005" or
                           r["provenance"]["decision_index"] < 2 for r in rows))

    def test_proof_requires_cases_prefix_hashes_and_pinned_backend(self):
        fx = SuiteFixture()
        self.addCleanup(fx.close)
        self.assertEqual(verify_proof(fx.proof, fx.model)["status"], "passed")
        (fx.proof/"cases.jsonl").unlink()
        self.assertEqual(verify_proof(fx.proof, fx.model)["status"], "blocked_dependency")

    def test_proof_rejects_passed_marker_without_token_evidence(self):
        fx = SuiteFixture()
        self.addCleanup(fx.close)
        cases = read_jsonl(fx.proof/"cases.jsonl")
        cases[0]["completion_ids"] = []
        write_jsonl(fx.proof/"cases.jsonl", cases, exclusive=False)
        manifest = read_json(fx.proof/"manifest.json")
        manifest["artifact_hashes"]["cases.jsonl"] = file_hash(fx.proof/"cases.jsonl")
        write_json(fx.proof/"manifest.json", manifest, exclusive=False)
        outcome = read_json(fx.proof/"outcome.json")
        outcome["manifest_sha256"] = file_hash(fx.proof/"manifest.json")
        write_json(fx.proof/"outcome.json", outcome, exclusive=False)
        self.assertEqual(verify_proof(fx.proof, fx.model)["status"], "blocked_dependency")

    def test_arbitrary_qwen_config_is_not_a_verified_pretrained_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root/"config.json", {"model_type": "qwen3", "architectures": ["Qwen3ForCausalLM"]})
            write_json(root/"tokenizer_config.json", {"chat_template": "untrusted"})
            (root/"tokenizer.json").write_text("{}")
            (root/"LICENSE").write_text("controlled")
            (root/"model.safetensors").write_bytes(b"controlled weights")
            with self.assertRaises(ValueError):
                snapshot_identity(root)


if __name__ == "__main__":
    unittest.main()
