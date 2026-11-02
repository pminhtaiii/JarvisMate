"""Native Qwen protocol rendering/decoding; real-tokenizer grammar checks are opt-in."""
import importlib.util
import json
import os
import unittest

from lifemate.adapters.constrained import native_action_parser
from lifemate.adapters.qwen_protocol import decode_decision, render_messages, render_tools
from lifemate.contracts import PipelineError
from lifemate.prompting import (NATIVE_FINISH_TEXT, NATIVE_SYSTEM, PROMPT_HASH, PROMPT_VERSION,
                                PROTOCOL_PROMPTS)
from support import CATALOG, Fixture

TOOLS = [tool for app in CATALOG["apps"] for tool in app["tools"]]


def block(body: str) -> str:
    return "<tool_call>\n" + body + "\n</tool_call>"


class ProtocolConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.close)

    def test_structured_is_the_default_and_native_is_explicit(self):
        self.assertEqual(self.fx.config().planner_protocol, "structured-v1")
        self.assertEqual(self.fx.config(planner_protocol="qwen-native-v1").planner_protocol, "qwen-native-v1")

    def test_unknown_or_incompatible_selections_are_rejected(self):
        bundle = {"few_shot_bundle": self.fx.root / "b.json", "partition_manifest": self.fx.root / "p.json"}
        for changes in ({"planner_protocol": "qwen-native-v2"},
                        {"planner_protocol": "qwen-native-v1", "prompt_profile": "precise-v1"},
                        {"planner_protocol": "qwen-native-v1", **bundle}):
            with self.subTest(changes=changes):
                with self.assertRaises(PipelineError) as caught:
                    self.fx.config(**changes)
                self.assertEqual(caught.exception.code, "INPUT_INVALID")


class StructuredPromptStabilityTests(unittest.TestCase):
    def test_structured_prompt_identity_is_unchanged_by_the_native_protocol(self):
        self.assertEqual(PROMPT_VERSION, "lifemate-react-v4")
        self.assertEqual(PROMPT_HASH, "0b7633bee24b2fcd17c530b56283eb4b938fd982285c88b81cc78e60ac69697d")
        self.assertEqual(PROTOCOL_PROMPTS["structured-v1"], (PROMPT_VERSION, PROMPT_HASH))
        self.assertNotEqual(PROTOCOL_PROMPTS["qwen-native-v1"][1], PROMPT_HASH)

    def test_native_system_declares_the_exact_final_text(self):
        self.assertIn(f'"{NATIVE_FINISH_TEXT}"', NATIVE_SYSTEM)


class RenderToolsTests(unittest.TestCase):
    def test_eligible_tools_keep_exact_names_descriptions_and_extensions(self):
        tool = {"name": "notes.update", "app": "notes", "kind": "write", "description": "Sửa ghi chú",
                "parameters": {"type": "object", "x-one-of": [["id"], ["title"]],
                               "properties": {"id": {"type": "string", "x-ref": "notes.id"},
                                              "title": {"type": "string"}}}}
        rendered = render_tools([tool])
        self.assertEqual(rendered, [{"type": "function", "function": {
            "name": "notes.update", "description": "Sửa ghi chú", "parameters": tool["parameters"]}}])

    def test_only_the_given_tools_are_rendered_in_order(self):
        self.assertEqual([t["function"]["name"] for t in render_tools(TOOLS[:2])],
                         ["contacts.search", "sms.send"])
        self.assertEqual(render_tools([]), [])


class RenderMessagesTests(unittest.TestCase):
    def value(self, observations=()):
        return {"request": "Nhắn Lan", "context": {"timezone": "Asia/Ho_Chi_Minh"},
                "history": [{"role": "user", "content": "trước đó"}],
                "available_tools": TOOLS, "observations": list(observations)}

    def test_user_turn_carries_request_context_history_but_not_tool_schemas(self):
        turns = render_messages(self.value(), system=NATIVE_SYSTEM)
        self.assertEqual([t["role"] for t in turns], ["system", "user"])
        self.assertEqual(turns[0]["content"], NATIVE_SYSTEM)
        self.assertEqual(json.loads(turns[1]["content"]),
                         {"request": "Nhắn Lan", "context": {"timezone": "Asia/Ho_Chi_Minh"},
                          "history": [{"role": "user", "content": "trước đó"}]})

    def test_executed_call_becomes_one_tool_calls_turn_and_one_tool_result(self):
        result = {"ok": True, "items": [{"id": "c_07", "name": "Lan"}]}
        observation = {"step": 1, "kind": "tool_result", "name": "contacts.search",
                       "arguments": {"query": "Lan"}, "result": result}
        turns = render_messages(self.value([observation]), system=NATIVE_SYSTEM)
        self.assertEqual([t["role"] for t in turns], ["system", "user", "assistant", "tool"])
        self.assertEqual(turns[2]["tool_calls"], [{"type": "function", "function": {
            "name": "contacts.search", "arguments": {"query": "Lan"}}}])
        self.assertEqual(json.loads(turns[3]["content"]), result)

    def test_rejected_proposal_is_correction_data_never_a_tool_result(self):
        rejection = {"step": 2, "kind": "validation_rejection", "code": "SELECTION_MISMATCH",
                     "rejected_response": '{"action":"call","arguments":{"id":"t9"},"name":"tasks.complete"}',
                     "message": "No tool was executed."}
        turns = render_messages(self.value([rejection]), system=NATIVE_SYSTEM)
        self.assertEqual([t["role"] for t in turns], ["system", "user", "user"])
        self.assertFalse(any("tool_calls" in t or t["role"] == "tool" for t in turns))
        self.assertEqual(json.loads(turns[2]["content"]), {"observation": rejection})

    def test_observation_order_is_preserved(self):
        first = {"step": 1, "kind": "tool_result", "name": "contacts.search",
                 "arguments": {"query": "Lan"}, "result": {"ok": True}}
        rejection = {"step": 2, "kind": "validation_rejection", "code": "X", "message": "m"}
        second = {"step": 3, "kind": "tool_result", "name": "sms.send",
                  "arguments": {"contact_id": "c_07", "content": "trễ"}, "result": {"ok": True}}
        turns = render_messages(self.value([first, rejection, second]), system=NATIVE_SYSTEM)
        self.assertEqual([t["role"] for t in turns],
                         ["system", "user", "assistant", "tool", "user", "assistant", "tool"])
        self.assertEqual(turns[5]["tool_calls"][0]["function"]["name"], "sms.send")


class DecodeDecisionTests(unittest.TestCase):
    def test_single_call_maps_to_the_canonical_decision(self):
        decision = decode_decision(block('{"name": "contacts.search", "arguments": {"query": "Lan"}}'))
        self.assertEqual(decision, {"action": "call", "name": "contacts.search", "arguments": {"query": "Lan"}})

    def test_compact_json_is_equally_accepted(self):
        decision = decode_decision(block('{"name":"contacts.search","arguments":{"query":"Lan"}}'))
        self.assertEqual(decision["arguments"], {"query": "Lan"})

    def test_zero_argument_call(self):
        self.assertEqual(decode_decision(block('{"name": "alarm.list", "arguments": {}}')),
                         {"action": "call", "name": "alarm.list", "arguments": {}})

    def test_unicode_arguments_are_preserved_exactly(self):
        decision = decode_decision(block('{"name": "sms.send", "arguments": {"content": "Tôi đến trễ 10 phút"}}'))
        self.assertEqual(decision["arguments"]["content"], "Tôi đến trễ 10 phút")

    def test_exact_final_text_is_finish(self):
        self.assertEqual(decode_decision(NATIVE_FINISH_TEXT), {"action": "finish"})

    def test_rejected_outputs(self):
        valid = '{"name": "contacts.search", "arguments": {"query": "Lan"}}'
        cases = {
            "empty output": "",
            "final text without punctuation": "Mình hiểu",
            "final text with trailing space": NATIVE_FINISH_TEXT + " ",
            "other prose": "Đã xong.",
            "prose before call": "Được.\n" + block(valid),
            "prose after call": block(valid) + "\nXong",
            "two calls": block(valid) + "\n" + block(valid),
            "nested call marker": block('{"name": "a", "arguments": {"x": "<tool_call>"}}'),
            "unfinished delimiter": "<tool_call>\n" + valid,
            "missing open delimiter": valid + "\n</tool_call>",
            "markdown fence": "```json\n" + valid + "\n```",
            "duplicate keys": block('{"name": "a", "name": "b", "arguments": {}}'),
            "non-finite number": block('{"name": "a", "arguments": {"x": NaN}}'),
            "overflowing number": block('{"name": "a", "arguments": {"x": 1e999}}'),
            "string arguments": block('{"name": "a", "arguments": "{}"}'),
            "array arguments": block('{"name": "a", "arguments": []}'),
            "missing arguments": block('{"name": "a"}'),
            "extra key": block('{"name": "a", "arguments": {}, "id": "1"}'),
            "empty name": block('{"name": "", "arguments": {}}'),
            "non-string name": block('{"name": 3, "arguments": {}}'),
            "canonical structured JSON": '{"action":"finish"}',
            "invalid JSON": block('{"name": "a", "arguments": {'),
        }
        for label, text in cases.items():
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    decode_decision(text)

    def test_oversized_output_is_rejected_before_parsing(self):
        with self.assertRaises(ValueError):
            decode_decision(block('{"name": "a", "arguments": {"x": "' + "x" * 100 + '"}}'), max_bytes=64)

    def test_non_text_is_rejected(self):
        with self.assertRaises(ValueError):
            decode_decision(None)


LMFE = importlib.util.find_spec("lmformatenforcer") is not None
ONE_OF_TOOL = {"name": "notes.update", "app": "notes", "kind": "write", "description": "Sửa",
               "parameters": {"type": "object", "x-one-of": [["id"], ["title"]],
                              "properties": {"id": {"type": "string"}, "title": {"type": "string"},
                                             "body": {"type": "string"}}, "required": ["body"]}}
ZERO_ARG_TOOL = {"name": "alarm.list", "app": "alarm", "kind": "read", "description": "Liệt kê",
                 "parameters": {"type": "object", "properties": {}}}


@unittest.skipUnless(LMFE, "Install the inference extra (lm-format-enforcer) to check the native grammar")
class NativeGrammarCharacterTests(unittest.TestCase):
    """Character-level grammar of the pinned LMFE parser; token mapping is checked separately."""

    def parser(self, tools=None):
        from lmformatenforcer import CharacterLevelParserConfig
        from lmformatenforcer.consts import COMPLETE_ALPHABET

        # Same policy as ActionConstraint; Latin/Vietnamese letters stand in for the tokenizer alphabet.
        vietnamese = "".join(map(chr, range(0x00C0, 0x0250))) + "".join(map(chr, range(0x1EA0, 0x1F00)))
        config = CharacterLevelParserConfig(alphabet=COMPLETE_ALPHABET + vietnamese,
                                            max_consecutive_whitespaces=2, force_json_field_order=True,
                                            max_json_array_length=16_384)
        return native_action_parser(TOOLS + [ONE_OF_TOOL, ZERO_ARG_TOOL] if tools is None else tools, config)

    @staticmethod
    def feed(parser, text):
        """Feed text; return (parser, can_end at every proper prefix)."""
        ends = []
        for character in text:
            if character not in parser.get_allowed_characters():
                raise ValueError(f"Grammar rejects {character!r}")
            ends.append(parser.can_end())
            parser = parser.add_character(character)
        return parser, ends

    def assert_complete_only_at_end(self, text):
        parser, ends = self.feed(self.parser(), text)
        self.assertFalse(any(ends), "EOS must not be admitted before the decision completes")
        self.assertTrue(parser.can_end())
        self.assertEqual(parser.get_allowed_characters(), "", "Nothing may follow a complete decision")
        return decode_decision(text)

    def test_schema_call_admits_end_only_after_the_closing_delimiter(self):
        text = block('{"name": "contacts.search", "arguments": {"query": "Lan"}}')
        self.assertEqual(self.assert_complete_only_at_end(text)["arguments"], {"query": "Lan"})

    def test_required_arguments_and_unicode_values(self):
        text = block('{"name": "sms.send", "arguments": {"contact_id": "c_07", "content": "Tôi đến trễ 10 phút"}}')
        self.assertEqual(self.assert_complete_only_at_end(text)["name"], "sms.send")

    def test_zero_argument_tool(self):
        self.assertEqual(self.assert_complete_only_at_end(block('{"name": "alarm.list", "arguments": {}}')),
                         {"action": "call", "name": "alarm.list", "arguments": {}})

    def test_each_one_of_alternative_is_accepted(self):
        # The pinned policy forces required-field order, required fields before the alternative.
        for arguments in ('{"body": "x", "id": "n1"}', '{"body": "x", "title": "Mua sắm"}'):
            with self.subTest(arguments):
                self.assert_complete_only_at_end(block('{"name": "notes.update", "arguments": ' + arguments + '}'))

    def test_final_text_admits_end_only_when_exact(self):
        self.assertEqual(self.assert_complete_only_at_end(NATIVE_FINISH_TEXT), {"action": "finish"})

    def test_grammar_rejections(self):
        cases = {
            "unknown tool": block('{"name": "contacts.delete", "arguments": {}}'),
            "argument of another tool": block('{"name": "contacts.search", "arguments": {"content": "x"}}'),
            "extra argument": block('{"name": "contacts.search", "arguments": {"query": "Lan", "x": "y"}}'),
            "missing required argument": block('{"name": "sms.send", "arguments": {"contact_id": "c_07"}}'),
            "missing one-of alternative": block('{"name": "notes.update", "arguments": {"body": "x"}}'),
            "wrong argument type": block('{"name": "contacts.search", "arguments": {"query": 3}}'),
            "junk keys on zero-argument tool": block('{"name": "alarm.list", "arguments": {"x": 1}}'),
            "second call": block('{"name": "alarm.list", "arguments": {}}') + "\n<tool_call>",
            "prose": "Được, mình sẽ làm.",
            "structured JSON": '{"action":"finish"}',
        }
        for label, text in cases.items():
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    self.feed(self.parser(), text)

    def test_only_eligible_tools_are_reachable(self):
        with self.assertRaises(ValueError):
            self.feed(self.parser(TOOLS[:1]), block('{"name": "sms.send", "arguments": {}}'))


QWEN_TOKENIZER = os.environ.get("LIFEMATE_QWEN_TEST_MODEL")
REAL = bool(QWEN_TOKENIZER) and LMFE and importlib.util.find_spec("transformers") is not None


class TokenIds(list):
    """The prefix function reads generated ids through `.tolist()`, as from a tensor."""

    def tolist(self):
        return list(self)


@unittest.skipUnless(REAL, "Opt in with LIFEMATE_QWEN_TEST_MODEL=<local Qwen3 tokenizer directory> "
                           "and the inference extra installed")
class RealTokenizerNativeProtocolSmoke(unittest.TestCase):
    """Actual checkpoint template, tokenizer and LMFE token mapping; no weights or GPU."""

    @classmethod
    def setUpClass(cls):
        from transformers import AutoTokenizer
        from lifemate.adapters.constrained import ActionConstraint

        cls.tokenizer = AutoTokenizer.from_pretrained(QWEN_TOKENIZER, local_files_only=True, trust_remote_code=False)
        cls.constraint = ActionConstraint(cls.tokenizer)
        cls.tools = TOOLS + [ZERO_ARG_TOOL]
        observation = {"step": 1, "kind": "tool_result", "name": "contacts.search",
                       "arguments": {"query": "Lan"}, "result": {"ok": True, "contacts": [{"id": "c_07"}]}}
        value = {"request": "Nhắn Lan rằng tôi đến trễ 10 phút", "context": {}, "history": [],
                 "available_tools": cls.tools, "observations": [observation]}
        cls.prompt = cls.tokenizer.apply_chat_template(
            render_messages(value, system=NATIVE_SYSTEM), tools=render_tools(cls.tools),
            tokenize=False, add_generation_prompt=True, enable_thinking=False)

    def test_eos_is_im_end_and_call_delimiters_survive_decoding(self):
        self.assertEqual(self.tokenizer.eos_token, "<|im_end|>")
        for marker in ("<tool_call>", "</tool_call>"):
            ids = self.tokenizer.encode(marker, add_special_tokens=False)
            self.assertFalse(set(ids) & set(self.tokenizer.all_special_ids), marker)
            self.assertEqual(self.tokenizer.decode(ids, skip_special_tokens=True), marker)

    def test_template_renders_executed_calls_in_the_constrained_envelope(self):
        self.assertIn(block('{"name": "contacts.search", "arguments": {"query": "Lan"}}'), self.prompt)
        for tool in self.tools:
            self.assertIn(json.dumps(tool["name"]), self.prompt)
        self.assertTrue(self.prompt.endswith("<|im_start|>assistant\n"), self.prompt[-80:])

    def assert_token_path(self, completion, expected):
        prefix = self.constraint.native_prefix(self.tools)
        prompt = self.tokenizer(self.prompt, add_special_tokens=False)["input_ids"]
        target = self.tokenizer.encode(completion, add_special_tokens=False)
        eos = self.tokenizer.eos_token_id
        for index, token in enumerate(target):
            allowed = set(prefix(0, TokenIds(prompt + target[:index])))
            self.assertIn(token, allowed, f"token {index} of {completion!r}")
            self.assertNotIn(eos, allowed, f"EOS admitted before token {index}")
        self.assertEqual(set(prefix(0, TokenIds(prompt + target))), {eos})
        decoded = self.tokenizer.decode(target + [eos], skip_special_tokens=True)
        self.assertEqual(decode_decision(decoded), expected)

    def test_schema_call_token_path_admits_eos_only_at_the_end(self):
        self.assert_token_path(block('{"name": "sms.send", "arguments": {"contact_id": "c_07", '
                                     '"content": "Tôi đến trễ 10 phút"}}'),
                               {"action": "call", "name": "sms.send",
                                "arguments": {"contact_id": "c_07", "content": "Tôi đến trễ 10 phút"}})

    def test_zero_argument_call_token_path(self):
        self.assert_token_path(block('{"name": "alarm.list", "arguments": {}}'),
                               {"action": "call", "name": "alarm.list", "arguments": {}})

    def test_final_text_token_path(self):
        self.assert_token_path(NATIVE_FINISH_TEXT, {"action": "finish"})


if __name__ == "__main__":
    unittest.main()
