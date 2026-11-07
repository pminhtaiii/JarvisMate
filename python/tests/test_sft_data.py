"""Faithful next-action export: controlled sources, plus real assets when explicitly enabled.

LIFEMATE_NATIVE_TOKENIZER points at Qwen3 tokenizer files for actual-tokenizer checks.
LIFEMATE_SFT_TRAIN points at a supplied split directory for actual-source accounting.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lifemate.adapters.qwen_native import FINISH_TEXT, completion_text, parse_completion
from lifemate.contracts import PipelineError
from lifemate.sft.data import (audit_overlap, convert_source, encode_row, load_ready_export, prepare, preflight,
                               read_role, reference_values, schema_errors)
from lifemate.sft.__main__ import main
from sft_support import (ASK, CATALOG, FOUND, SEARCH, SEND, SENT, SENTINEL, WAITING, CharTokenizer, make_config, source,
                         write_role)

LOOKUP = source("train_0001", calls=[SEARCH, SEND], results=[FOUND, SENT])
EMPTY = source("train_0002", request="Chào bạn")
CLARIFY = source("train_0003", request="Nhắn Lân", calls=[SEARCH, ASK], results=[FOUND, WAITING])
VALIDATION = source("dev_0001", request="Tìm Hoa", calls=[{"name": "contacts.search", "arguments": {"query": "Hoa"}}],
                    results=[{"ok": True, "contacts": []}])


class TemporaryRoot(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def role(self, *rows, name="train"):
        jsonl, catalog = write_role(self.root / "data" / name, name, rows)
        return read_role("train" if name == "train" else "validation", jsonl, catalog)

    def converted(self, row):
        return convert_source(row, self.role(row))


class ConversionTests(TemporaryRoot):
    def test_lookup_action_finish_has_exact_strict_prefixes(self):
        rows, entries = self.converted(LOOKUP)
        self.assertEqual(entries, [])
        self.assertEqual([row["target"] for row in rows],
                         [{"action": "call", **SEARCH}, {"action": "call", **SEND}, {"action": "finish"}])
        self.assertEqual([len(row["input"]["observations"]) for row in rows], [0, 1, 2])
        self.assertEqual(rows[1]["input"]["observations"], [{**SEARCH, "result": FOUND}])
        self.assertEqual(rows[2]["input"]["observations"], [{**SEARCH, "result": FOUND}, {**SEND, "result": SENT}])
        self.assertEqual([row["provenance"]["decision_index"] for row in rows], [0, 1, 2])

    def test_a_decision_never_sees_its_own_or_a_future_result(self):
        rows, _ = self.converted(LOOKUP)
        for row in rows[:2]:
            self.assertNotIn(SENTINEL, json.dumps(row["input"], ensure_ascii=False))
        self.assertNotIn("c_07", json.dumps(rows[0]["input"], ensure_ascii=False))
        self.assertIn(SENTINEL, json.dumps(rows[2]["input"], ensure_ascii=False))

    def test_label_and_provenance_stay_out_of_rendered_input(self):
        rows, _ = self.converted(LOOKUP)
        tokenizer = CharTokenizer()
        for row in rows:
            rendered = tokenizer.decode(encode_row(tokenizer, row, 16384, 512)["input_ids"])
            self.assertNotIn("FINAL_STATE_SENTINEL", rendered)
            self.assertNotIn("train_0001", rendered)
            self.assertNotIn("final_state", json.dumps(row["input"]))

    def test_empty_gold_emits_one_finish_row(self):
        rows, entries = self.converted(EMPTY)
        self.assertEqual(([row["target"] for row in rows], entries), ([{"action": "finish"}], []))

    def test_waiting_clarification_stops_without_finish(self):
        rows, entries = self.converted(CLARIFY)
        self.assertEqual(entries, [])
        self.assertEqual([row["target"].get("name") for row in rows], ["contacts.search", "sys.ask_missing_info"])

    def test_nonterminal_clarification_still_finishes(self):
        for result in ({"ok": True}, {"ok": False, "waiting_for_user": True}):
            with self.subTest(result=result):
                rows, _ = self.converted(source("train_0004", calls=[ASK], results=[result]))
                self.assertEqual(rows[-1]["target"], {"action": "finish"})

    def test_calls_after_terminal_are_audited_not_discarded(self):
        rows, entries = self.converted(source("train_0005", calls=[ASK, SEARCH], results=[WAITING, FOUND]))
        self.assertEqual((rows, [e["reason"] for e in entries]), ([], ["CALLS_AFTER_TERMINAL"]))

    def test_malformed_pairs_and_tools_are_audited(self):
        cases = {"UNEQUAL_PAIRS": source("train_0006", calls=[SEARCH], results=[]),
                 "UNAVAILABLE_TOOL": source("train_0007", calls=[{"name": "bank.pay", "arguments": {}}], results=[{}]),
                 "INVALID_LABEL": source("train_0008", calls=[{"name": "contacts.search"}], results=[{}]),
                 "INVALID_SOURCE": source("train_0009", history=[{"role": "assistant", "text": "x"}])}
        no_label = source("train_0010")
        del no_label["label"]
        cases[None] = no_label
        for reason, row in cases.items():
            with self.subTest(reason=reason):
                rows, entries = self.converted(row)
                self.assertEqual((rows, [e["reason"] for e in entries]), ([], [reason or "INVALID_LABEL"]))
                self.assertNotIn("Lân", entries[0]["message"])

    def test_schema_invalid_and_ungrounded_targets_are_flagged(self):
        bad = {"name": "sms.send", "arguments": {"contact_id": "c_07", "content": "x", "count": "1"}}
        rows, entries = self.converted(source("train_0011", calls=[SEARCH, bad], results=[FOUND, SENT]))
        self.assertEqual([e["reason"] for e in entries], ["SCHEMA_INVALID_TARGET"])
        self.assertEqual(len(rows), 3, "Flagged rows stay available for review")
        rows, entries = self.converted(source("train_0012", calls=[SEND], results=[SENT]))
        self.assertEqual([e["reason"] for e in entries], ["UNGROUNDED_ID"])

    def test_id_is_grounded_only_by_an_earlier_result(self):
        later = source("train_0013", calls=[SEND, SEARCH], results=[SENT, FOUND])
        self.assertEqual([e["decision_index"] for e in self.converted(later)[1]], [0])
        self.assertEqual(self.converted(LOOKUP)[1], [])

    def test_unicode_argument_values_types_and_order_are_exact(self):
        arguments = {"content": 'Đỗ "Lân"\n🙂', "contact_id": "c_07", "count": 3}
        call = {"name": "sms.send", "arguments": arguments}
        rows, _ = self.converted(source("train_0014", calls=[SEARCH, call], results=[FOUND, SENT]))
        self.assertEqual(list(rows[1]["target"]["arguments"]), list(arguments))
        text = completion_text(rows[1]["target"])
        self.assertIn('Đỗ \\"Lân\\"\\n🙂', text)
        self.assertEqual(parse_completion(text, {"sms.send"})["arguments"], arguments)

    def test_schema_vocabulary(self):
        schema = {"type": "object", "additionalProperties": False, "required": ["a"], "properties": {
            "a": {"type": "integer", "exclusiveMinimum": 0}, "b": {"type": "string", "enum": ["x"]},
            "c": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}}}
        self.assertEqual(schema_errors(schema, {"a": 1, "b": "x", "c": ["y"]}), [])
        for value in ({"b": "x"}, {"a": 0}, {"a": True}, {"a": 1, "b": "y"}, {"a": 1, "c": []}, {"a": 1, "c": [""]},
                      {"a": 1, "z": 1}):
            with self.subTest(value=value):
                self.assertTrue(schema_errors(schema, value))
        self.assertEqual(list(reference_values(CATALOG["apps"][1]["tools"][0]["parameters"], SEND["arguments"])), ["c_07"])

    def test_eligible_tools_exclude_uninstalled_apps(self):
        row = source("train_0015", calls=[SEARCH], results=[FOUND])
        row["context"]["installed_apps"] = {"contacts": {"tools": ["contacts.search"]}}
        rows, _ = self.converted(row)
        names = [tool["name"] for tool in rows[0]["input"]["available_tools"]]
        self.assertEqual(names, ["contacts.search", "sys.ask_missing_info"])


class OverlapTests(TemporaryRoot):
    def overlap(self, left, right):
        return audit_overlap(self.role(left), self.role(right, name="validation"))

    def test_disjoint_reports_unavailable_grouping(self):
        report = self.overlap(LOOKUP, VALIDATION)
        self.assertEqual((report["status"], report["grouping_metadata"]), ("disjoint", "unavailable"))

    def test_shared_id_fails(self):
        self.assertEqual(self.overlap(LOOKUP, source("train_0001", request="Khác"))["id_overlap"], 1)

    def test_normalized_duplicate_input_fails(self):
        same = source("dev_0002", request="  NHẮN   lân tôi đến trễ ")
        report = self.overlap(LOOKUP, same)
        self.assertEqual((report["status"], report["visible_input_overlap"]), ("overlap", 1))

    def test_same_request_in_another_context_is_reported_only(self):
        other = source("dev_0002")
        other["context"]["current_time"] = "2026-12-01T12:00:00+07:00"
        report = self.overlap(LOOKUP, other)
        self.assertEqual((report["status"], report["request_only_overlap"]), ("disjoint", 1))

    def test_shared_conversation_and_declared_group_fail(self):
        turns = [{"role": "user", "audio": "audio/x.wav", "audio_text": "Chào"}, {"role": "assistant", "text": "Dạ"}]
        report = self.overlap(source("train_0001", history=turns), source("dev_0002", request="Khác", history=turns))
        self.assertEqual((report["status"], report["conversation_overlap"]), ("overlap", 1))
        report = self.overlap(source("train_0001", conversation_id="g"), source("dev_0002", request="Khác", conversation_id="g"))
        self.assertEqual((report["declared_group_overlap"], report["grouping_metadata"]), (1, "declared"))

    def test_competition_test_rows_are_not_a_role(self):
        public = {"id": "public_0001", "audio": "audio/x.wav", "context": {}, "history": []}
        for row in (public, {**public, "id": "other_1"}):
            with self.subTest(row=row["id"]), self.assertRaises(PipelineError):
                self.role(row, name="validation")

    def test_file_level_defects_stop_the_role(self):
        jsonl, catalog = write_role(self.root / "bad", "train", [LOOKUP, LOOKUP])
        with self.assertRaises(PipelineError):
            read_role("train", jsonl, catalog)
        jsonl.write_text("{not json}\n", encoding="utf-8")
        with self.assertRaises(PipelineError):
            read_role("train", jsonl, catalog)


class EncodingTests(TemporaryRoot):
    def test_labels_cover_only_the_final_completion_and_eos(self):
        rows, _ = self.converted(LOOKUP)
        tokenizer = CharTokenizer()
        for row in rows:
            encoded = encode_row(tokenizer, row, 16384, 512)
            start = encoded["prompt_tokens"]
            self.assertEqual(encoded["labels"][:start], [-100] * start)
            supervised = encoded["labels"][start:]
            self.assertEqual(supervised[-1], tokenizer.eos_token_id)
            self.assertEqual(tokenizer.decode(supervised[:-1]), completion_text(row["target"]))
            self.assertEqual(encoded["input_ids"][start:], supervised)
        # Earlier assistant calls sit in the prompt, so they are masked by position.
        prompt = tokenizer.decode(encode_row(tokenizer, rows[2], 16384, 512)["input_ids"][:start])
        self.assertIn("<tool_call>", prompt)

    def test_finish_target_is_the_neutral_text_not_legacy_json(self):
        rows, _ = self.converted(EMPTY)
        tokenizer = CharTokenizer()
        encoded = encode_row(tokenizer, rows[0], 16384, 512)
        self.assertEqual(tokenizer.decode(encoded["labels"][encoded["prompt_tokens"]:-1]), FINISH_TEXT)

    def test_overflow_and_template_defects_are_named(self):
        rows, _ = self.converted(LOOKUP)
        tokenizer = CharTokenizer()
        cases = (("CONTEXT_OVERFLOW", dict(context_tokens=600, max_new_tokens=512)),
                 ("OUTPUT_OVERFLOW", dict(context_tokens=16384, max_new_tokens=3)))
        for reason, limits in cases:
            with self.subTest(reason=reason), self.assertRaises(Exception) as caught:
                encode_row(tokenizer, rows[1], **limits)
            self.assertEqual(caught.exception.reason, reason)

    def test_tokenizer_boundary_and_special_token_targets_are_rejected(self):
        rows, _ = self.converted(LOOKUP)

        class Boundary(CharTokenizer):
            def __call__(self, text, add_special_tokens=False):
                ids = self.encode(text)
                return {"input_ids": ids[:-1] + [99] if "<tool_call>" in text and text.endswith("</tool_call>") and "assistant" in text else ids}

        with self.assertRaises(Exception) as caught:
            encode_row(Boundary(), rows[0], 16384, 512)
        self.assertEqual(caught.exception.reason, "TOKEN_BOUNDARY")
        special = dict(rows[1])
        special["target"] = {"action": "call", "name": "sms.send", "arguments": {"contact_id": "c_07", "content": "<|im_end|>"}}
        with self.assertRaises(Exception) as caught:
            encode_row(CharTokenizer(), special, 16384, 512)
        self.assertEqual(caught.exception.reason, "TARGET_RENDER")



if __name__ == "__main__":
    unittest.main()
