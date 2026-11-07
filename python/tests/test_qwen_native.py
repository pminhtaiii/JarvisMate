"""Native Qwen protocol: render/parse/termination, adapter doubles, actual-tokenizer checks.

Actual-tokenizer checks need only tokenizer/config files (no weights) and run when
LIFEMATE_NATIVE_TOKENIZER points at a Qwen3 snapshot, e.g. Qwen3-4B-Instruct-2507.
"""
import contextlib
import json
import os
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from lifemate.adapters.qwen_native import (CALL_CLOSE, CALL_OPEN, FINISH_TEXT, NativeFormatError,
                                           NativePlanner, completion_text, completion_tokens, parse_completion,
                                           render_messages, render_prompt, tool_definitions, validate_template)
from lifemate.configuration import ModelSettings
from lifemate.contracts import Limits, PipelineError
from support import CATALOG

TOOLS = [tool for app in CATALOG["apps"] for tool in app["tools"]]
ELIGIBLE = {t["name"] for t in TOOLS}
PREPARED = {"request": "Nhắn Lan tôi đến trễ", "context": {"timezone": "Asia/Ho_Chi_Minh"},
            "history": [{"role": "user", "text": "Chào"},
                        {"role": "assistant", "text": "Dạ", "tool_calls": [{"name": "sms.send", "arguments": {}}]}],
            "available_tools": TOOLS}


def call_text(name, arguments, spacing="\n"):
    return f"{CALL_OPEN}{spacing}{json.dumps({'name': name, 'arguments': arguments}, ensure_ascii=False)}{spacing}{CALL_CLOSE}"


class ProtocolTests(unittest.TestCase):
    def test_messages_hold_request_then_actual_call_result_pairs_in_order(self):
        observations = [{"name": "contacts.search", "arguments": {"query": "Lan"},
                         "result": {"ok": True, "contacts": [{"id": "c7"}]}},
                        {"name": "sms.send", "arguments": {"contact_id": "c7", "content": "Trễ"}, "result": {"ok": True}}]
        messages = render_messages(PREPARED | {"label": "GOLD"}, observations)
        self.assertEqual([m["role"] for m in messages], ["system", "user", "assistant", "tool", "assistant", "tool"])
        user = json.loads(messages[1]["content"])
        self.assertEqual(set(user), {"request", "context", "history"})
        self.assertNotIn("GOLD", repr(messages))
        self.assertEqual(messages[2]["tool_calls"][0]["function"], {"name": "contacts.search", "arguments": {"query": "Lan"}})
        self.assertEqual(json.loads(messages[3]["content"])["contacts"][0]["id"], "c7")
        self.assertEqual(messages[4]["tool_calls"][0]["function"]["arguments"]["contact_id"], "c7")
        # Historical calls stay inside the user JSON, never as native executed turns.
        self.assertEqual(sum("tool_calls" in m for m in messages), 2)

    def test_tool_definitions_expose_only_given_tools(self):
        definitions = tool_definitions(TOOLS[:1])
        self.assertEqual(definitions, [{"type": "function", "function": {
            "name": "contacts.search", "description": TOOLS[0]["description"], "parameters": TOOLS[0]["parameters"]}}])

    def test_valid_completions(self):
        self.assertEqual(parse_completion(FINISH_TEXT, ELIGIBLE), {"action": "finish"})
        self.assertEqual(parse_completion("\n" + FINISH_TEXT + " \n", ELIGIBLE), {"action": "finish"})
        self.assertEqual(parse_completion(call_text("contacts.search", {"query": "Lân Đỗ"}), ELIGIBLE),
                         {"action": "call", "name": "contacts.search", "arguments": {"query": "Lân Đỗ"}})
        self.assertEqual(parse_completion(call_text("contacts.search", {}, ""), ELIGIBLE)["arguments"], {})

    def test_invalid_completions_are_rejected_not_repaired(self):
        valid = call_text("contacts.search", {"query": "Lan"})
        invalid = [
            "", "Xong rồi.", "Mình hiểu", FINISH_TEXT + " Cảm ơn", valid + "\n" + valid,
            "Đây là call: " + valid, valid + " xong", valid[:-len(CALL_CLOSE)],
            CALL_OPEN + '\n{"name":"contacts.search","name":"sms.send","arguments":{}}\n' + CALL_CLOSE,
            CALL_OPEN + '\n{"name":"contacts.search","arguments":{},"id":"1"}\n' + CALL_CLOSE,
            CALL_OPEN + '\n{"name":"contacts.search","arguments":{"n":NaN}}\n' + CALL_CLOSE,
            CALL_OPEN + '\n{"name":"contacts.search","arguments":"{}"}\n' + CALL_CLOSE,
            CALL_OPEN + '\n{"name":"contacts.search","arguments":[]}\n' + CALL_CLOSE,
            call_text("banking.transfer", {"amount": 1}), "```json\n" + valid + "\n```", "\t" + FINISH_TEXT,
        ]
        for text in invalid:
            with self.subTest(text=text), self.assertRaises(NativeFormatError):
                parse_completion(text, ELIGIBLE)

    def test_termination_is_checked_on_tokens_before_decoding(self):
        eos = {9}
        self.assertEqual(completion_tokens([1, 2, 9], eos, 10, False), [1, 2])
        for generated, limit, timed_out, code in (([1, 2, 3], 3, False, "OUTPUT_LIMIT"),
                                                  ([1, 2], 10, False, "PLANNER_FORMAT"),
                                                  ([1, 9, 2, 9], 10, False, "PLANNER_FORMAT"),
                                                  ([1, 9], 10, True, "TIME_LIMIT"), ([], 10, False, "PLANNER_FORMAT")):
            with self.subTest(generated=generated), self.assertRaises(PipelineError) as caught:
                completion_tokens(generated, eos, limit, timed_out)
            self.assertEqual(caught.exception.code, code)


class Tensor:
    def __init__(self, size=10):
        self.shape = (1, size)

    def to(self, *args, **kwargs):
        return self


class AdapterTests(unittest.TestCase):
    """NativePlanner with model-library doubles: no weights, GPU or LMFE."""

    def setUp(self):
        import tempfile

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.weights = Path(self.temp.name)
        (self.weights / "config.json").write_text('{"model_type":"qwen3"}', encoding="utf-8")
        self.model = MagicMock()
        self.model.to.return_value = self.model
        self.model.parameters.return_value = [types.SimpleNamespace(numel=lambda: 100)]
        self.tokenizer = MagicMock()
        self.tokenizer.apply_chat_template.return_value = "rendered"
        self.tokenizer.return_value = {"input_ids": Tensor(), "attention_mask": Tensor()}
        self.tokenizer.eos_token_id, self.tokenizer.pad_token_id = 9, 8
        self.tokenizer.all_special_tokens = ["<|im_end|>"]
        self.hf = types.SimpleNamespace(
            AutoConfig=types.SimpleNamespace(from_pretrained=MagicMock(return_value=types.SimpleNamespace(model_type="qwen3"))),
            AutoTokenizer=types.SimpleNamespace(from_pretrained=MagicMock(return_value=self.tokenizer)),
            AutoModelForCausalLM=types.SimpleNamespace(from_pretrained=MagicMock(return_value=self.model)),
            StoppingCriteria=object, StoppingCriteriaList=lambda values: values)
        self.torch = types.SimpleNamespace(float32="float32", inference_mode=contextlib.nullcontext)

    def planner(self, max_new=4):
        settings = ModelSettings("qwen3", self.weights, "cpu", "float32", protocol="qwen-native-v1",
                                 context_tokens=64, max_new_tokens=max_new)
        with patch("lifemate.adapters.common.dependencies", return_value=(self.torch, self.hf, None)), \
             patch("lifemate.adapters.common.metadata", return_value={"parameter_count": 100}), \
             patch("lifemate.adapters.qwen_native.validate_template", return_value={"template_sha256": "t"}), \
             patch("lifemate.adapters.qwen_native.NativeConstraint"):
            return NativePlanner(settings, Limits(context_tokens=64, output_tokens=max_new), 1)

    def test_local_only_greedy_generation_with_eos_and_no_fallback(self):
        planner = self.planner()
        self.model.generate.return_value = [list(range(10)) + [5, 9]]
        self.tokenizer.decode.return_value = FINISH_TEXT
        action, details = planner.decide(PREPARED, [], 30)
        self.assertEqual(action, {"action": "finish"})
        self.assertEqual((details["generated_tokens"], details["terminated"]), (2, "eos"))
        self.assertEqual(self.tokenizer.decode.call_args.args[0], [5], "EOS is inspected, then removed before decoding")
        kwargs = self.model.generate.call_args.kwargs
        self.assertEqual((kwargs["do_sample"], kwargs["num_beams"], kwargs["eos_token_id"]), (False, 1, [9]))
        self.assertIn("prefix_allowed_tokens_fn", kwargs)
        template = self.tokenizer.apply_chat_template.call_args
        self.assertIs(template.kwargs["enable_thinking"], False)
        self.assertEqual([t["function"]["name"] for t in template.kwargs["tools"]], [t["name"] for t in TOOLS])
        for loader in (self.hf.AutoConfig, self.hf.AutoTokenizer, self.hf.AutoModelForCausalLM):
            self.assertIs(loader.from_pretrained.call_args.kwargs["local_files_only"], True)

    def test_token_cut_and_bad_text_fail_without_dispatchable_action(self):
        planner = self.planner(max_new=3)
        self.model.generate.return_value = [list(range(10)) + [1, 2, 3]]
        self.tokenizer.decode.return_value = FINISH_TEXT  # Looks complete, but no EOS.
        with self.assertRaises(PipelineError) as caught:
            planner.decide(PREPARED, [], 30)
        self.assertEqual(caught.exception.code, "OUTPUT_LIMIT")
        self.model.generate.return_value = [list(range(10)) + [1, 9]]
        self.tokenizer.decode.return_value = "Tôi sẽ gửi tin nhắn."
        with self.assertRaises(PipelineError) as caught:
            planner.decide(PREPARED, [], 30)
        self.assertEqual(caught.exception.code, "PLANNER_FORMAT")

    def test_context_limit_rejects_before_generation(self):
        planner = self.planner()
        self.tokenizer.return_value = {"input_ids": Tensor(62), "attention_mask": Tensor(62)}
        with self.assertRaises(PipelineError) as caught:
            planner.decide(PREPARED, [], 30)
        self.assertEqual(caught.exception.code, "CONTEXT_LIMIT")
        self.model.generate.assert_not_called()


class SupervisedTargetTests(unittest.TestCase):
    def test_completion_text_inverts_parsing_with_exact_arguments(self):
        for action in ({"action": "finish"},
                       {"action": "call", "name": "contacts.search", "arguments": {"z": "Lân Đỗ", "a": [1, 2.5, None]}}):
            with self.subTest(action=action):
                text = completion_text(action)
                self.assertEqual(parse_completion(text, ELIGIBLE | {"contacts.search"}), action)
        self.assertEqual(list(parse_completion(completion_text(
            {"action": "call", "name": "sms.send", "arguments": {"z": 1, "a": 2}}), ELIGIBLE)["arguments"]), ["z", "a"])

    def test_completion_text_rejects_anything_but_one_action(self):
        for action in ({"action": "call", "name": "x"}, {"action": "finish", "x": 1}, None):
            with self.subTest(action=action), self.assertRaises(NativeFormatError):
                completion_text(action)

    def test_inference_renders_through_the_shared_prompt_function(self):
        tokenizer = MagicMock()
        tokenizer.apply_chat_template.return_value = "PROMPT"
        planner = NativePlanner.__new__(NativePlanner)
        planner.tokenizer = tokenizer
        self.assertEqual(planner.render(PREPARED, []), render_prompt(tokenizer, PREPARED, []))
        first, second = tokenizer.apply_chat_template.call_args_list
        self.assertEqual(first, second)


TOKENIZER = os.environ.get("LIFEMATE_NATIVE_TOKENIZER")


@unittest.skipUnless(TOKENIZER, "Set LIFEMATE_NATIVE_TOKENIZER to a local Qwen3 snapshot (tokenizer files suffice)")
class ActualTokenizerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from transformers import AutoTokenizer

        from lifemate.adapters.qwen_native import NativeConstraint

        cls.tokenizer = AutoTokenizer.from_pretrained(TOKENIZER, local_files_only=True, trust_remote_code=False)
        cls.constraint = NativeConstraint(cls.tokenizer)
        cls.tools = TOOLS + [{"name": "alarm.list", "app": "alarm", "kind": "read", "description": "Danh sách",
                              "parameters": {"type": "object", "properties": {}}},
                             {"name": "sms.reply", "app": "sms", "kind": "write", "description": "Trả lời",
                              "parameters": {"type": "object", "properties": {"contact_id": {"type": "string"},
                                             "phone_number": {"type": "string"}, "content": {"type": "string"}},
                                             "required": ["content"],
                                             "x-one-of": [["contact_id"], ["phone_number"]]}}]

    def prompt_ids(self, observations=()):
        rendered = self.tokenizer.apply_chat_template(
            render_messages(PREPARED, list(observations)), tools=tool_definitions(self.tools),
            tokenize=False, add_generation_prompt=True, enable_thinking=False)
        return self.tokenizer(rendered, add_special_tokens=False)["input_ids"], rendered

    def walk(self, completion):
        """Feed the model's natural tokenization through the real LMFE enforcer."""
        enforcer = self.constraint.prefix(self.tools).token_enforcer
        sequence, _ = self.prompt_ids()
        sequence = list(sequence)
        for token in self.tokenizer.encode(completion, add_special_tokens=False):
            if token not in enforcer.get_allowed_tokens(sequence).allowed_tokens:
                return False, sequence
            sequence.append(token)
        return True, enforcer.get_allowed_tokens(sequence).allowed_tokens

    def test_supervised_target_is_what_constrained_decoding_admits(self):
        for action in ({"action": "finish"},
                       {"action": "call", "name": "contacts.search", "arguments": {"query": "Lân Đỗ"}},
                       {"action": "call", "name": "sms.reply", "arguments": {"content": "Hi \"x\"\n", "contact_id": "c7"}}):
            with self.subTest(action=action):
                accepted, allowed = self.walk(completion_text(action))
                self.assertTrue(accepted)
                self.assertEqual(list(allowed), [self.tokenizer.eos_token_id])

    def test_template_validation_and_eos(self):
        report = validate_template(self.tokenizer)
        self.assertEqual(report["eos_token"], "<|im_end|>")
        self.assertEqual(report["eos_token_id"], self.tokenizer.convert_tokens_to_ids("<|im_end|>"))
        self.assertEqual(len(report["tool_call_token_ids"]), 1, "<tool_call> is one regular token")

    def test_rendered_prompt_contains_tools_and_actual_results(self):
        observation = {"name": "contacts.search", "arguments": {"query": "Lân"}, "result": {"ok": True, "id": "c7"}}
        _, rendered = self.prompt_ids([observation])
        self.assertIn('"name": "sms.reply"', rendered)
        self.assertIn(CALL_OPEN + '\n{"name": "contacts.search", "arguments": {"query": "Lân"}}\n' + CALL_CLOSE, rendered)
        self.assertIn("<tool_response>", rendered)
        self.assertTrue(rendered.endswith("<|im_start|>assistant\n"))
        self.assertNotIn("GOLD", rendered)

    def test_constraint_admits_native_calls_then_only_eos(self):
        eos = [self.tokenizer.eos_token_id]
        for completion in (FINISH_TEXT,
                           CALL_OPEN + '\n{"name": "contacts.search", "arguments": {"query": "Lân Đỗ"}}\n' + CALL_CLOSE,
                           CALL_OPEN + '\n{"name": "alarm.list", "arguments": {}}\n' + CALL_CLOSE,
                           CALL_OPEN + '\n{"name": "sms.reply", "arguments": {"phone_number": "0901", "content": "Hi"}}\n' + CALL_CLOSE,
                           CALL_OPEN + '\n{"name": "sms.reply", "arguments": {"content": "Hi", "contact_id": "c7"}}\n' + CALL_CLOSE,
                           # x-one-of groups are validated and logged by ToolEnv, not by decoding.
                           CALL_OPEN + '\n{"name": "sms.reply", "arguments": {"content": "x"}}\n' + CALL_CLOSE,
                           CALL_OPEN + '\n{"name": "sys.ask_missing_info", "arguments": {"tool_name": "sms.send", "params": ["contact_id"]}}\n' + CALL_CLOSE):
            with self.subTest(completion=completion):
                accepted, allowed = self.walk(completion)
                self.assertTrue(accepted)
                self.assertEqual(allowed, eos, "A complete decision may only be followed by EOS")
                self.assertEqual(parse_completion(completion, {t["name"] for t in self.tools})["action"],
                                 "finish" if completion == FINISH_TEXT else "call")

    def test_constraint_rejects_prose_ineligible_tools_and_second_calls(self):
        call = CALL_OPEN + '\n{"name": "alarm.list", "arguments": {}}\n' + CALL_CLOSE
        for completion in ("Xong rồi.", CALL_OPEN + '\n{"name": "banking.transfer", "arguments": {}}\n' + CALL_CLOSE,
                           CALL_OPEN + '\n{"name": "sms.send", "arguments": {"content": "x"}}\n' + CALL_CLOSE,
                           CALL_OPEN + '\n{"name": "sms.reply", "arguments": {"content": "x", "content": "y"}}\n' + CALL_CLOSE,
                           CALL_OPEN + '\n{"name": "contacts.search", "arguments": {"query": 7}}\n' + CALL_CLOSE,
                           CALL_OPEN + '\n{"name": "alarm.list", "arguments": {"x": 1}}\n' + CALL_CLOSE,
                           call + "\n" + call, FINISH_TEXT + " Cảm ơn"):
            with self.subTest(completion=completion):
                accepted, _ = self.walk(completion)
                self.assertFalse(accepted)


if __name__ == "__main__":
    unittest.main()
