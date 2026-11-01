"""Shared renderer, completion-only mask and decoder-POC harness (P03 harness/P04/P05/D05).

Uses the controlled FakeQwenTokenizer/WhitelistConstraint doubles. Passing here
exercises the harness and fail-closed logic only; it is NOT the RV002 proof.
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lifemate.adapters import qwen_native as qn
from lifemate.jsonio import digest
from lifemate.llm_training import decoder_poc
from lifemate.llm_training.tokenization import (TokenizationError, flag_equivalent, proof_binding,
                                                supervised, verify_proof)
from lifemate.native_tools import adapt_tools
from lifemate.prompting import SYSTEM, current_user_message
from llm_support import FakeQwenTokenizer, WhitelistConstraint

ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "tools" / "train_tools_catalog.json"
CATALOG = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
SPECS = {t["name"]: t for app in CATALOG["apps"] for t in app["tools"]}


def setup_messages():
    tools, _ = adapt_tools([copy.deepcopy(SPECS[n]) for n in ("alarm.list", "ewallet.transfer", "sys.ask_missing_info")])
    messages = [{"role": "system", "content": SYSTEM}, current_user_message("Báo thức", {"timezone": "Asia/Ho_Chi_Minh"})]
    return tools, messages


class SupervisionTests(unittest.TestCase):
    def setUp(self):
        self.tok = FakeQwenTokenizer()
        self.tools, self.messages = setup_messages()

    def test_call_target_mask_covers_body_and_one_eos_only(self):
        target = qn.native_call_message("ewallet.transfer", {"phone": "0912345678", "amount": 120000})
        sup = supervised(self.tok, self.messages, self.tools, target)
        prompt = sup["prompt_tokens"]
        self.assertTrue(all(label == -100 for label in sup["labels"][:prompt]))
        completion = sup["input_ids"][prompt:]
        self.assertEqual(sup["labels"][prompt:], completion)
        self.assertEqual(completion.count(2), 1)
        self.assertEqual(completion[-1], 2)  # Template newline after EOS is excluded.
        self.assertEqual(self.tok.decode(completion[:-1]), qn.call_completion_text(
            "ewallet.transfer", {"phone": "0912345678", "amount": 120000}))
        _, ids = qn.render_native(self.tok, self.messages, self.tools)
        self.assertEqual(sup["input_ids"][:prompt], ids)  # Exact inference prefix.

    def test_initial_and_post_tool_finals_share_content_with_correct_prefixes(self):
        initial = supervised(self.tok, self.messages, self.tools, qn.native_final_message())
        prefix = self.messages + [qn.native_call_message("alarm.list", {}), qn.tool_message({"ok": True, "alarms": []})]
        post = supervised(self.tok, prefix, self.tools, qn.native_final_message())
        self.assertEqual(initial["completion_text"], "Đã kết thúc.")
        self.assertEqual(post["completion_text"], "Đã kết thúc.")
        self.assertGreater(post["prompt_tokens"], initial["prompt_tokens"])
        rendered = self.tok.apply_chat_template(prefix, tools=self.tools, add_generation_prompt=True)
        self.assertIn("<tool_response>\n{\"alarms\":[],\"ok\":true}\n</tool_response>", rendered)

    def test_budget_overflow_and_template_drift_block_acceptance(self):
        target = qn.native_final_message()
        with self.assertRaises(TokenizationError) as caught:
            supervised(self.tok, self.messages, self.tools, target, context_tokens=600, output_tokens=512)
        self.assertEqual(caught.exception.code, "TOKEN_BUDGET")
        with self.assertRaises(TokenizationError) as caught:
            supervised(FakeQwenTokenizer(drift=True), self.messages, self.tools,
                       qn.native_call_message("alarm.list", {"x": 1}))
        self.assertEqual(caught.exception.code, "SERIALIZATION_MISMATCH")

    def test_render_paths_must_agree_and_flag_equivalence_is_checked(self):
        class Divergent(FakeQwenTokenizer):
            def apply_chat_template(self, *args, tokenize=False, **kwargs):
                value = super().apply_chat_template(*args, tokenize=tokenize, **kwargs)
                return value + [9] if tokenize else value

        with self.assertRaises(ValueError):
            qn.render_native(Divergent(), self.messages, self.tools)
        self.assertTrue(flag_equivalent(self.tok, self.messages, self.tools))
        self.assertFalse(flag_equivalent(FakeQwenTokenizer(thinking_branch=True), self.messages, self.tools))


class DecoderProofHarnessTests(unittest.TestCase):
    def setUp(self):
        self.tok = FakeQwenTokenizer()

    def constraint(self, tokenizer):
        texts = set()
        for case in decoder_poc.fixtures():
            if case["kind"] == "valid":
                calls = case["target"].get("tool_calls")
                texts.add(qn.call_completion_text(calls[0]["function"]["name"], calls[0]["function"]["arguments"])
                          if calls else qn.FINAL_CONTENT)
        return WhitelistConstraint(tokenizer, texts)

    def test_all_nine_groups_walk_and_invalid_cases_fail_closed(self):
        results = decoder_poc.run_cases(self.tok, self.constraint, SPECS)
        failures = [r for r in results if not r["passed"]]
        self.assertEqual(failures, [])
        self.assertEqual(sorted({r["group"] for r in results}), list(range(1, 10)))
        initial = next(r for r in results if r["case"] == "4-initial-final")
        self.assertTrue(initial["walk"]["transitions"][-1]["eos_allowed"])
        call = next(r for r in results if r["case"] == "1-normal-call")
        self.assertFalse(any(t["eos_allowed"] for t in call["walk"]["transitions"][:-1]))  # Partial call forbids EOS.

    def test_permissive_backend_is_detected(self):
        class Permissive:
            def __init__(self, tokenizer):
                pass

            def prefix(self, tools):
                return lambda batch, sent: list(range(0, 1500))

        results = decoder_poc.run_cases(self.tok, Permissive, SPECS)
        self.assertTrue(any(not r["passed"] for r in results if r["kind"] == "invalid"))
        self.assertTrue(any(not r["passed"] for r in results if r["kind"] == "valid"))  # EOS allowed mid-call.

    def test_run_proof_records_blocked_and_binds_passed_outcome(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            blocked = decoder_poc.run_proof(root / "out", None, CATALOG_PATH)
            self.assertEqual(blocked["status"], "blocked")  # Committed catalog is not the pinned one either.
            model = root / "tokenizer files with spaces đ"
            model.mkdir()
            (model / "tokenizer_config.json").write_text('{"chat_template": "controlled"}', encoding="utf-8")
            with patch.object(decoder_poc, "CATALOG_SHA256", digest(CATALOG_PATH)):
                outcome = decoder_poc.run_proof(root / "out", model, CATALOG_PATH,
                                                tokenizer_loader=lambda _: self.tok, constraint_factory=self.constraint)
            self.assertEqual(outcome["status"], "passed", outcome["reason"])
            proof = Path(outcome["directory"])
            for name in ("manifest.json", "cases.jsonl", "token-prefix-checks.json", "outcome.json"):
                self.assertTrue((proof / name).is_file())
            self.assertEqual(verify_proof(proof, model)["status"], "passed")
            (model / "tokenizer_config.json").write_text('{"chat_template": "changed"}', encoding="utf-8")
            self.assertEqual(verify_proof(proof, model)["status"], "blocked_dependency")  # Rebinding needed.
            self.assertEqual(verify_proof(None, model)["status"], "blocked_dependency")

    def test_binding_includes_policy_prompt_code_and_tokenizer(self):
        binding = proof_binding(None)
        self.assertEqual(binding["policy"]["terminal_policy"], "lifemate-native-final-vi-v1")
        self.assertIn("adapters/qwen_native.py", binding["native_code"])
        self.assertIsNone(binding["tokenizer"])


if __name__ == "__main__":
    unittest.main()
