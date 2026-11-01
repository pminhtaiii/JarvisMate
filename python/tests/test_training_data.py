"""Frozen grouped Train partition and native SFT export (spec 003 T014/T015, T020).

Controlled rows and a character-level Qwen-like tokenizer; no model or environment. The
native grammar is the pinned LMFE parser when installed, otherwise a schema stand-in.
"""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import lifemate
from lifemate.adapters import qwen_protocol
from lifemate.adapters.constrained import grammar_ordered_arguments, native_action_parser
from lifemate.contracts import Limits, PipelineError
from lifemate.jsonio import dumps
from lifemate.prompt_profiles import validate_partition_manifest
from lifemate.prompting import NATIVE_FINISH_TEXT, NATIVE_PROMPT_HASH, NATIVE_SYSTEM, planner_input
from lifemate.training import data as training_data
from lifemate.training.__main__ import main
from lifemate.training.data import IGNORE_INDEX, SMOKE_FIT_IDS, build_partition, export, token_labels
from support import CATALOG, Fixture

CONTACTS = {"contacts": {"tools": ["contacts.search"]}, "sms": {"tools": ["sms.send"]}}
ALARM = {"alarm": {"tools": ["alarm.create"]}}


def row(sample_id, request, history=(), apps=None, calls=()):
    turns = []
    for text in history:
        turns += [{"role": "user", "audio": f"audio/{sample_id}/h.wav", "audio_text": text},
                  {"role": "assistant", "text": "Đã xong."}]
    return {"id": sample_id, "audio": f"audio/{sample_id}/{sample_id}.wav", "audio_text": request,
            "context": {"current_time": "2026-11-01T12:00:00+07:00", "timezone": "Asia/Ho_Chi_Minh",
                        "installed_apps": apps or CONTACTS},
            "history": turns, "label": {"tool_calls": [{"name": n, "arguments": {}} for n in calls],
                                        "tool_results": [{"ok": True} for _ in calls], "final_state": {}}}


def unrelated(count, start=1):
    """Distinct word triples without digits, so no exact, near-duplicate or skeleton link exists."""
    words = ["mưa", "nắng", "gió", "biển", "núi", "sông", "rừng", "phố", "chợ", "trường", "sách", "đèn"]
    return [row(f"train_{i:04d}", f"tìm {words[i % 12]} {words[i // 12 % 12]} {words[i // 144 % 12]}")
            for i in range(start, start + count)]


def split(rows, **kwargs):
    return build_partition(rows, dataset_sha256="d" * 64, catalog_sha256="c" * 64, **kwargs)


def group_of(manifest):
    return {m["id"]: m["group_id"] for m in manifest["members"]}


def side_of(manifest):
    return {m["id"]: m["partition"] for m in manifest["members"]}


class PartitionShapeTests(unittest.TestCase):
    def test_manifest_is_partition_v1_with_every_sample_once_and_canonical_source_hashes(self):
        rows = unrelated(20)
        manifest = split(rows)
        self.assertEqual(set(validate_partition_manifest(manifest)), {r["id"] for r in rows})
        expected = {r["id"]: hashlib.sha256(dumps(r).encode("utf-8")).hexdigest() for r in rows}
        self.assertEqual({m["id"]: m["source_sha256"] for m in manifest["members"]}, expected)
        self.assertEqual((manifest["dataset_sha256"], manifest["catalog_sha256"], manifest["seed"]),
                         ("d" * 64, "c" * 64, 20261027))
        self.assertEqual(manifest["grouping_method"], "lifemate-train-grouping-v1")

    def test_partition_is_deterministic_and_close_to_the_requested_fraction(self):
        rows = unrelated(50)
        first, second = split(rows), split(rows)
        self.assertEqual(first, second)
        self.assertEqual(first["counts"]["validation"], 10)
        self.assertEqual(first["counts"]["fit"], 40)

    def test_groups_never_straddle_partitions(self):
        rows = unrelated(30) + [row("train_0900", "Nhắn Lan"), row("train_0901", "nhắn   LAN")]
        manifest = split(rows, validation_fraction=0.5)
        sides = {}
        for member in manifest["members"]:
            sides.setdefault(member["group_id"], set()).add(member["partition"])
        self.assertTrue(all(len(s) == 1 for s in sides.values()))

    def test_smoke_ids_and_their_related_samples_stay_fit_side(self):
        rows = unrelated(20) + [row(i, f"kiểm tra khói {i[-1]} riêng biệt") for i in SMOKE_FIT_IDS]
        rows.append(row("train_0950", "tiếp theo", history=["kiểm tra khói 8 riêng biệt"]))
        for fraction in (0.2, 0.9):
            with self.subTest(fraction=fraction):
                sides = side_of(split(rows, validation_fraction=fraction))
                self.assertEqual({sides[i] for i in (*SMOKE_FIT_IDS, "train_0950")}, {"fit"})
        manifest = split(unrelated(5))
        self.assertEqual(manifest["smoke_ids"]["absent"], list(SMOKE_FIT_IDS))

    def test_invalid_inputs_are_rejected(self):
        bad = unrelated(3)
        tool_dict = dict(bad[0], context=dict(bad[0]["context"], installed_apps={"x": {"tools": [{"n": 1}]}}))
        cases = {"duplicate id": (bad + [bad[0]], {}), "fraction 1": (bad, {"validation_fraction": 1.0}),
                 "fraction 0": (bad, {"validation_fraction": 0}), "no rows": ([], {}),
                 "blank request": ([dict(bad[0], audio_text="  ")], {}),
                 "non-string tool": ([tool_dict] + bad[1:], {}),
                 "non-object history entry": ([dict(bad[0], history=["text turn"])] + bad[1:], {})}
        for label, (rows, kwargs) in cases.items():
            with self.subTest(label):
                with self.assertRaises(PipelineError) as caught:
                    split(rows, **kwargs)
                self.assertEqual(caught.exception.code, "INPUT_INVALID")

    def test_a_split_without_validation_members_is_rejected(self):
        # Two groups of five; neither fits a validation target of round(0.2 * 10) = 2.
        rows = [row(f"train_{i:04d}", "đặt xe về nhà" if i <= 5 else "bật đèn phòng khách") for i in range(1, 11)]
        with self.assertRaises(PipelineError) as caught:
            split(rows)
        self.assertIn("validation", str(caught.exception))


class GroupingTests(unittest.TestCase):
    def test_exact_duplicates_after_normalization_share_a_group_but_diacritics_matter(self):
        rows = unrelated(10) + [row("train_0901", "Nhắn  Lan rằng TÔI đến trễ"),
                                row("train_0902", "nhắn lan rằng tôi đến trễ"),
                                row("train_0903", "Nhan Lan rang toi den tre"),
                                row("train_0904", "nhắn lan rằng tôi đến trễ", apps=ALARM)]
        groups = group_of(split(rows))
        self.assertEqual(groups["train_0901"], groups["train_0902"])
        self.assertNotEqual(groups["train_0901"], groups["train_0903"])
        # Exact duplicates are grouped regardless of installed tools.
        self.assertEqual(groups["train_0901"], groups["train_0904"])

    def test_conversation_continuations_and_shared_openers_are_grouped_transitively(self):
        rows = unrelated(10) + [
            row("train_0901", "đặt xe về nhà"),
            row("train_0902", "đổi sang xe bảy chỗ", history=["đặt xe về nhà"]),
            row("train_0903", "hủy chuyến", history=["đặt xe về nhà", "đổi sang xe bảy chỗ"]),
            row("train_0904", "thêm điểm đón", history=["đặt xe về nhà"]),
            row("train_0905", "Thêm  điểm ĐÓN", history=["đặt xe về nhà"]),
        ]
        manifest = split(rows)
        groups = group_of(manifest)
        self.assertEqual(len({groups[f"train_090{i}"] for i in range(1, 6)}), 1)
        self.assertGreater(manifest["grouping"]["deterministic_links"]["conversation"], 0)

    def test_near_duplicates_are_candidates_only_within_one_tool_signature(self):
        base = "nhắn cho chị lan rằng tối nay tôi sẽ về muộn khoảng mười phút nhé"
        rows = unrelated(10) + [row("train_0901", base), row("train_0902", base + " ạ"),
                                row("train_0903", base + " nha", apps=ALARM)]
        manifest = split(rows)
        groups = group_of(manifest)
        near = [c for c in manifest["candidates"] if c["kind"] == "near_duplicate"]
        self.assertEqual([c["ids"] for c in near], [["train_0901", "train_0902"]])
        self.assertGreaterEqual(near[0]["similarity"], 0.8)
        self.assertEqual(groups["train_0901"], groups["train_0902"])
        self.assertNotEqual(groups["train_0902"], groups["train_0903"])

    def test_request_skeletons_mask_numbers_and_names(self):
        rows = unrelated(10) + [row("train_0901", "Đặt báo thức lúc 7h30", apps=ALARM),
                                row("train_0902", "Đặt báo thức lúc 9h", apps=ALARM),
                                row("train_0903", "Gọi cho Lan ngay", apps=ALARM),
                                row("train_0904", "Gọi cho Minh ngay", apps=ALARM)]
        manifest = split(rows)
        pairs = [c["ids"] for c in manifest["candidates"] if c["kind"] == "request_skeleton"]
        self.assertIn(["train_0901", "train_0902"], pairs)
        self.assertIn(["train_0903", "train_0904"], pairs)
        groups = group_of(manifest)
        self.assertEqual(groups["train_0901"], groups["train_0902"])

    def test_unrelated_requests_with_the_same_tools_stay_separate(self):
        rows = [row("train_0901", "tìm số điện thoại của anh Bình"),
                row("train_0902", "nhắn tin chúc mừng sinh nhật mẹ"),
                row("train_0903", "gửi lời xin lỗi tới đồng nghiệp vì họp muộn")]
        manifest = split(rows)
        self.assertEqual(manifest["candidates"], [])
        self.assertEqual(manifest["counts"]["groups"], 3)

    def test_review_decisions_separate_candidates_group_links_and_reject_bad_overrides(self):
        rows = unrelated(10) + [row("train_0901", "Đặt báo thức lúc 7h30", apps=ALARM),
                                row("train_0902", "Đặt báo thức lúc 9h", apps=ALARM),
                                row("train_0903", "Nhắn Lan"), row("train_0904", "nhắn lan")]
        separate = {"ids": ["train_0901", "train_0902"], "decision": "separate", "reason": "different alarms"}
        joined = {"ids": ["train_0001", "train_0002"], "decision": "group", "reason": "same scenario"}
        manifest = split(rows, decisions={"decisions": [separate, joined]})
        groups = group_of(manifest)
        self.assertNotEqual(groups["train_0901"], groups["train_0902"])
        self.assertEqual(groups["train_0001"], groups["train_0002"])
        self.assertEqual([d["decision"] for d in manifest["decisions"]], ["separate", "group"])
        candidate = next(c for c in manifest["candidates"] if c["ids"] == ["train_0901", "train_0902"])
        self.assertEqual(candidate["decision"], "separate")
        for bad in ({"ids": ["train_0903", "train_0904"], "decision": "separate", "reason": "exact link"},
                    {"ids": [["train_0901"], "train_0902"], "decision": "group", "reason": "nested id"},
                    {"ids": ["train_0901", "train_9999"], "decision": "group", "reason": "unknown"},
                    {"ids": ["train_0901", "train_0901"], "decision": "group", "reason": "self"},
                    {"ids": ["train_0901", "train_0902"], "decision": "merge", "reason": "bad kind"},
                    {"ids": ["train_0901", "train_0902"], "decision": "group", "reason": " "}):
            with self.subTest(bad=bad):
                with self.assertRaises(PipelineError):
                    split(rows, decisions={"decisions": [bad]})

    def test_separate_decision_overridden_by_other_links_is_recorded(self):
        rows = unrelated(10) + [row("train_0901", "Đặt báo thức lúc 7h30", apps=ALARM),
                                row("train_0902", "Đặt báo thức lúc 9h", apps=ALARM),
                                row("train_0903", "Đặt báo thức lúc 8h", apps=ALARM)]
        separate = {"ids": ["train_0901", "train_0902"], "decision": "separate", "reason": "different alarms"}
        links = [{"ids": ["train_0901", "train_0903"], "decision": "group", "reason": "same alarm request"},
                 {"ids": ["train_0903", "train_0902"], "decision": "group", "reason": "same alarm request"}]
        manifest = split(rows, decisions={"decisions": [separate, *links]})
        groups = group_of(manifest)
        self.assertEqual(groups["train_0901"], groups["train_0902"])
        self.assertEqual(manifest["separate_decisions_overridden_by_other_links"], [["train_0901", "train_0902"]])

    def test_limitations_and_parameters_are_recorded(self):
        grouping = split(unrelated(5))["grouping"]
        self.assertEqual(grouping["parameters"]["jaccard_threshold"], 0.8)
        self.assertTrue(any("paraphrase" in item for item in grouping["limitations"]))


class CoverageTests(unittest.TestCase):
    def test_coverage_counts_categories_per_partition_and_reports_gaps(self):
        rows = unrelated(8)
        rows += [row("train_0901", "hỏi lại giờ hẹn", calls=["sys.ask_missing_info"]),
                 row("train_0902", "gửi cho Lan", calls=["contacts.search", "sms.send"]),
                 row("train_0903", "kể chuyện cười", calls=[]),
                 dict(row("train_0904", "không có nhãn", history=["câu một", "câu hai"]), label=None)]
        manifest = split(rows)
        coverage = manifest["coverage"]
        totals = {key: coverage["fit"][key] + coverage["validation"][key]
                  for key in ("samples", "missing_info", "multi_app", "label_missing", "long_history")}
        # long_history is visible-input coverage, so a label-missing row still counts.
        self.assertEqual(totals, {"samples": 12, "missing_info": 1, "multi_app": 1, "label_missing": 1,
                                  "long_history": 1})
        self.assertEqual(coverage["fit"]["empty_gold"] + coverage["validation"]["empty_gold"], 9)
        # Validation holds at most 2 of these 12, so some category must be missing there.
        self.assertTrue(coverage["categories_missing_from_validation"])
        for key in coverage["categories_missing_from_validation"]:
            self.assertGreater(coverage["fit"][key], 0)
            self.assertEqual(coverage["validation"][key], 0)


class PartitionCommandTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.close)
        self.fx.rows = unrelated(10)
        self.fx.write()
        self.output = self.fx.root / "experiments" / "partition.json"

    def run_command(self, *extra, output=None):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["partition", "--data-root", str(self.fx.data), "--output", str(output or self.output), *extra])
        return code, json.loads(stdout.getvalue())

    def test_command_writes_a_frozen_partition_and_refuses_to_overwrite_it(self):
        code, summary = self.run_command()
        self.assertEqual((code, summary["status"], summary["counts"]["samples"]), (0, "completed", 10))
        written = self.output.read_bytes()
        manifest = json.loads(written)
        self.assertEqual(len(manifest["dataset_sha256"]), 64)
        code, summary = self.run_command("--seed", "7")
        self.assertEqual((code, summary["status"]), (2, "failed"))
        self.assertEqual(self.output.read_bytes(), written)

    def test_output_inside_the_organizer_data_root_is_rejected(self):
        code, summary = self.run_command(output=self.fx.data / "partition.json")
        self.assertEqual((code, summary["error"]["code"]), (2, "INPUT_INVALID"))
        self.assertFalse((self.fx.data / "partition.json").exists())

    def test_environment_files_are_never_opened(self):
        opened, real_open = [], Path.open

        def recording_open(path, *args, **kwargs):
            opened.append(str(path))
            return real_open(path, *args, **kwargs)

        with patch.object(Path, "open", recording_open):
            code, _ = self.run_command()
        self.assertEqual(code, 0)
        # Read once: the recorded digest describes exactly the parsed bytes.
        self.assertEqual(sum(p.endswith("train.jsonl") for p in opened), 1)
        self.assertFalse([p for p in opened if "_environment" in p])
        manifest = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(manifest["dataset_sha256"],
                         hashlib.sha256((self.fx.split / "train.jsonl").read_bytes()).hexdigest())

    def test_failed_write_leaves_no_partial_partition(self):
        real_open = Path.open

        class FailingStream:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.stream.close()

            def write(self, data):
                raise OSError("disk full")

        def failing_open(path, *args, **kwargs):
            stream = real_open(path, *args, **kwargs)
            return FailingStream(stream) if path == self.output else stream

        with patch.object(Path, "open", failing_open):
            code, summary = self.run_command()
        self.assertEqual((code, summary["error"]["code"]), (1, "OUTPUT_IO"))
        self.assertFalse(self.output.exists())
        self.assertEqual(self.run_command()[0], 0)

    def test_decisions_file_is_applied_and_invalid_arguments_fail(self):
        decisions = self.fx.root / "decisions.json"
        decisions.write_text(json.dumps({"decisions": [
            {"ids": ["train_0001", "train_0002"], "decision": "group", "reason": "reviewed"}]}), encoding="utf-8")
        code, _ = self.run_command("--decisions", str(decisions))
        self.assertEqual(code, 0)
        groups = group_of(json.loads(self.output.read_text(encoding="utf-8")))
        self.assertEqual(groups["train_0001"], groups["train_0002"])
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(["partition", "--data-root", str(self.fx.data)]), 2)
        # A supplied file that parses to null is an error, never "no decisions".
        empty = self.fx.root / "null-decisions.json"
        empty.write_text("null", encoding="utf-8")
        code, summary = self.run_command("--decisions", str(empty), output=self.fx.root / "other.json")
        self.assertEqual((code, summary["error"]["code"]), (2, "INPUT_INVALID"))
        self.assertFalse((self.fx.root / "other.json").exists())

    def test_malformed_tool_entries_fail_with_a_structured_error_not_a_traceback(self):
        self.fx.rows[0]["context"]["installed_apps"] = {"contacts": {"tools": [{"name": "contacts.search"}]}}
        self.fx.write()
        code, summary = self.run_command()
        self.assertEqual((code, summary["status"], summary["error"]["code"]), (2, "failed", "INPUT_INVALID"))

    def test_partition_imports_no_training_or_inference_libraries(self):
        source = Path(lifemate.__file__).resolve().parents[1]
        probe = ("import sys, lifemate.training.__main__; "
                 "print([m for m in ('torch','transformers','numpy','lmformatenforcer','peft','trl','bitsandbytes') "
                 "if m in sys.modules])")
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True,
                                env={**os.environ, "PYTHONPATH": str(source)})
        self.assertEqual(result.stdout.strip(), "[]")


# ---------------------------------------------------------------------------
# Native next-action SFT export (T020)
# ---------------------------------------------------------------------------

SPECIAL_IDS = {"<|im_start|>": 1, "<|im_end|>": 2}
FUTURE_ID, SENT_SENTINEL, FINAL_STATE = "c_07_FUTURE", "m_SENT_SENTINEL", "FINAL_STATE_SENTINEL"
EXPORT_CATALOG = copy.deepcopy(CATALOG)
EXPORT_CATALOG["apps"][1]["tools"][0]["parameters"]["properties"]["contact_id"]["x-ref"] = "contacts.id"
CONTEXT = {"current_time": "2026-11-01T12:00:00+07:00", "timezone": "Asia/Ho_Chi_Minh",
           "location": {"lat": 21, "lng": 105},
           "user_profile": {"name": "An", "home_address": "Nhà", "work_address": "Công ty", "city": "Hà Nội"},
           "installed_apps": {"contacts": {"tools": ["contacts.search"]}, "sms": {"tools": ["sms.send"]}}}
SEARCH = ("contacts.search", {"query": "Lan"})
FOUND = {"ok": True, "contacts": [{"id": FUTURE_ID, "name": "Lan"}]}
# Deliberately not in grammar order: the required contact_id must be generated first.
SEND = ("sms.send", {"content": "Tôi đến trễ 10 phút", "contact_id": FUTURE_ID})
SENT = {"ok": True, "message_id": SENT_SENTINEL}


class QwenLikeTokenizer:
    """Character-level stand-in that renders Qwen3's tool-call chat template; specials are single ids."""

    eos_token, eos_token_id = "<|im_end|>", 2
    chat_template = "qwen-like test template"
    generation_marker = "<|im_start|>assistant\n"

    def apply_chat_template(self, turns, tools=None, tokenize=True, add_generation_prompt=False,
                            enable_thinking=True):
        assert tokenize is False and enable_thinking is False
        system = turns[0]["content"]
        if tools:
            system += "\n\n# Tools\n<tools>\n" + "\n".join(json.dumps(t, ensure_ascii=False) for t in tools)
        text = f"<|im_start|>system\n{system}<|im_end|>\n"
        for turn in turns[1:]:
            if turn["role"] == "assistant":
                text += "<|im_start|>assistant\n" + turn["content"]
                for index, call in enumerate(turn.get("tool_calls", [])):
                    text += "\n" if index or turn["content"] else ""
                    function = call["function"]
                    text += ('<tool_call>\n{"name": "' + function["name"] + '", "arguments": '
                             + json.dumps(function["arguments"], ensure_ascii=False) + "}\n</tool_call>")
                text += "<|im_end|>\n"
            elif turn["role"] == "tool":
                text += "<|im_start|>user\n<tool_response>\n" + turn["content"] + "\n</tool_response><|im_end|>\n"
            else:
                text += f"<|im_start|>{turn['role']}\n{turn['content']}<|im_end|>\n"
        return text + (self.generation_marker if add_generation_prompt else "")

    def encode(self, text):
        ids, index = [], 0
        while index < len(text):
            special = next((s for s in SPECIAL_IDS if text.startswith(s, index)), None)
            ids.append(SPECIAL_IDS[special] if special else 1000 + ord(text[index]))
            index += len(special) if special else 1
        return ids

    def __call__(self, text, add_special_tokens=True):
        assert add_special_tokens is False
        return {"input_ids": self.encode(text)}

    def decode(self, ids, skip_special_tokens=False):
        names = {v: k for k, v in SPECIAL_IDS.items()}
        return "".join(("" if skip_special_tokens else names[i]) if i in names else chr(i - 1000) for i in ids)


class MergingTokenizer(QwenLikeTokenizer):
    """Merges a newline with the following '<', so the prompt/completion boundary is not separable."""

    def encode(self, text):
        ids = super().encode(text)
        merged, newline, bracket = [], 1000 + ord("\n"), 1000 + ord("<")
        for token in ids:
            if merged and merged[-1] == newline and token == bracket:
                merged[-1] = 3
            else:
                merged.append(token)
        return merged


class ThinkingTokenizer(QwenLikeTokenizer):
    """Adds an empty think block only to the generation prompt, as a hybrid-thinking template would."""

    generation_marker = "<|im_start|>assistant\n<think>\n\n</think>\n\n"


LMFE = importlib.util.find_spec("lmformatenforcer") is not None


def grammar(tools, text):
    """The pinned native grammar when installed; otherwise a schema stand-in for the same checks."""
    if LMFE:
        from lmformatenforcer import CharacterLevelParserConfig
        from lmformatenforcer.consts import COMPLETE_ALPHABET

        vietnamese = "".join(map(chr, range(0x00C0, 0x0250))) + "".join(map(chr, range(0x1EA0, 0x1F00)))
        parser = native_action_parser(tools, CharacterLevelParserConfig(
            alphabet=COMPLETE_ALPHABET + vietnamese, max_consecutive_whitespaces=2,
            force_json_field_order=True, max_json_array_length=16_384))
        for character in text:
            if character not in parser.get_allowed_characters():
                return False
            parser = parser.add_character(character)
        return parser.can_end()
    decision = qwen_protocol.decode_decision(text)
    if decision["action"] == "finish":
        return True
    tool = next((t for t in tools if t["name"] == decision["name"]), None)
    if tool is None:
        return False
    parameters, arguments = tool["parameters"], decision["arguments"]
    required = parameters.get("required", [])
    return (set(required) <= set(arguments) and set(arguments) <= set(parameters["properties"])
            and list(arguments)[:len(required)] == required)


def sample(sample_id, request="Nhắn Lan rằng tôi đến trễ 10 phút", calls=(), results=None, history=(), **label):
    calls = [{"name": name, "arguments": arguments} for name, arguments in calls]
    gold = {"tool_calls": calls, "tool_results": list(results or []), "final_state": {"marker": FINAL_STATE}}
    return {"id": sample_id, "audio": f"audio/{sample_id}/{sample_id}.wav", "audio_text": request,
            "context": copy.deepcopy(CONTEXT), "history": list(history), "label": gold | label}


class ExportCase(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture(0)
        self.addCleanup(self.fx.close)
        self.model = self.fx.root / "models" / "qwen"
        self.model.mkdir(parents=True)
        for name in ("config.json", "tokenizer_config.json"):
            (self.model / name).write_text("{}", encoding="utf-8")
        self.tokenizer = QwenLikeTokenizer()
        self.exports = 0

    def write(self, rows, validation=()):
        self.fx.rows = rows
        self.fx.write()
        catalog = self.fx.split / "train_tools_catalog.json"
        catalog.write_text(json.dumps(EXPORT_CATALOG, ensure_ascii=False), encoding="utf-8")
        members = [{"id": r["id"], "group_id": "g-" + r["id"], "partition": "validation" if r["id"] in validation
                    else "fit", "source_sha256": hashlib.sha256(dumps(r).encode("utf-8")).hexdigest()}
                   for r in rows]
        manifest = {"partition_schema_version": 1, "grouping_method": "test", "members": members,
                    "dataset_sha256": hashlib.sha256((self.fx.split / "train.jsonl").read_bytes()).hexdigest(),
                    "catalog_sha256": hashlib.sha256(catalog.read_bytes()).hexdigest()}
        self.partition = self.fx.root / "partition.json"
        self.partition.write_text(dumps(manifest), encoding="utf-8")

    def export(self, rows=None, validation=(), tokenizer=None, **kwargs):
        if rows is not None:
            self.write(rows, validation)
        self.exports += 1
        output = self.fx.root / "exports" / f"sft-{self.exports}"
        manifest = export(self.fx.data, self.partition, self.model, output, tokenizer=tokenizer or self.tokenizer,
                          admits=grammar, **kwargs)
        files = {path.name: path.read_text(encoding="utf-8") for path in output.iterdir()}
        rows_of = {name: [json.loads(line) for line in text.splitlines()]
                   for name, text in files.items() if name.endswith(".jsonl")}
        return manifest, rows_of

    def fit_rows(self, rows, **kwargs):
        manifest, files = self.export(rows, **kwargs)
        return {r["row_id"]: r for r in files["fit.jsonl"]}, files["exclusions.jsonl"], manifest

    def reasons(self, exclusions):
        return {(e["source_id"], e["step"], e["reason"]) for e in exclusions}


class StrictPrefixTests(ExportCase):
    def test_lookup_then_action_rows_see_only_earlier_results(self):
        rows, exclusions, _ = self.fit_rows([sample("train_0001", calls=[SEARCH, SEND], results=[FOUND, SENT])])
        self.assertEqual(exclusions, [])
        self.assertEqual(list(rows), ["train_0001:0", "train_0001:1", "train_0001:2"])
        prompts = [rows[f"train_0001:{k}"]["prompt"] for k in range(3)]
        # Future-result sentinels are absent at their own and earlier steps.
        self.assertNotIn(FUTURE_ID, prompts[0])
        self.assertIn(FUTURE_ID, prompts[1])
        self.assertNotIn(SENT_SENTINEL, prompts[1])
        self.assertIn(SENT_SENTINEL, prompts[2])
        self.assertEqual([rows[f"train_0001:{k}"]["provenance"]["target_origin"] for k in range(3)],
                         ["gold_call", "gold_call", "policy_finish"])

    def test_labels_provenance_and_final_state_never_enter_prompts(self):
        rows, _, _ = self.fit_rows([sample("train_0001", calls=[SEARCH, SEND], results=[FOUND, SENT],
                                           secret_gold="GOLD_MUST_NOT_ENTER_PROMPT")])
        for row in rows.values():
            for leaked in (FINAL_STATE, "GOLD_MUST_NOT_ENTER_PROMPT", "train_0001", "g-train_0001", "label"):
                self.assertNotIn(leaked, row["prompt"])

    def test_prompt_is_the_runtime_native_prompt_for_the_same_prefix(self):
        rows, _, _ = self.fit_rows([sample("train_0001", calls=[SEARCH, SEND], results=[FOUND, SENT])])
        tools = [t for app in EXPORT_CATALOG["apps"] for t in app["tools"]]
        prepared = {"request": "Nhắn Lan rằng tôi đến trễ 10 phút", "history": [],
                    "context": {k: CONTEXT[k] for k in ("current_time", "timezone", "location", "user_profile",
                                                        "installed_apps")},
                    "available_tools": tools}
        # Executed calls come back to the runner as canonical sorted-key JSON.
        observation = {"step": 1, "kind": "tool_result", "name": "contacts.search",
                       "arguments": {"query": "Lan"}, "result": FOUND}
        expected = qwen_protocol.render_prompt(self.tokenizer, planner_input(prepared, [observation]),
                                               system=NATIVE_SYSTEM)
        self.assertEqual(rows["train_0001:1"]["prompt"], expected)
        self.assertTrue(expected.endswith("<|im_start|>assistant\n"))

    def test_history_is_context_only_and_never_a_target(self):
        history = [{"role": "user", "audio": "audio/train_0001/h.wav", "audio_text": "Tìm Lan giúp tôi"},
                   {"role": "assistant", "text": "Đã tìm.", "tool_calls": [{"name": "contacts.search",
                    "arguments": {"query": "HISTORY_QUERY"}}], "tool_results": [{"ok": True}]}]
        rows, _, _ = self.fit_rows([sample("train_0001", calls=[SEND], results=[SENT], history=history,
                                           request="Nhắn Lan " + FUTURE_ID + " rằng tôi đến trễ 10 phút")])
        self.assertEqual(list(rows), ["train_0001:0", "train_0001:1"])
        first = rows["train_0001:0"]["prompt"]
        self.assertIn("HISTORY_QUERY", first)
        self.assertNotIn("<tool_call>", first.split("<|im_start|>user\n", 1)[1])

    def test_empty_gold_is_one_policy_finish_row(self):
        rows, exclusions, _ = self.fit_rows([sample("train_0001", request="Kể chuyện cười")])
        self.assertEqual(exclusions, [])
        row = rows["train_0001:0"]
        self.assertEqual(row["completion"], NATIVE_FINISH_TEXT + "<|im_end|>")
        self.assertEqual(row["canonical_target"], {"action": "finish"})
        self.assertEqual(row["provenance"]["target_origin"], "policy_finish")
        self.assertNotIn("<tool_call>", row["prompt"].split("<|im_start|>user\n", 1)[1])


class ClarificationTests(ExportCase):
    ASK = ("sys.ask_missing_info", {"tool_name": "sms.send", "params": ["content"]})

    def test_terminal_waiting_call_ends_rows_without_a_finish(self):
        rows, _, _ = self.fit_rows([sample("train_0001", calls=[SEARCH, self.ASK],
                                           results=[FOUND, {"ok": True, "waiting_for_user": True}])])
        self.assertEqual(list(rows), ["train_0001:0", "train_0001:1"])
        self.assertEqual(rows["train_0001:1"]["canonical_target"]["name"], "sys.ask_missing_info")

    def test_nonterminal_missing_info_results_are_observations_followed_by_finish(self):
        for result in ({"ok": False, "error": "schema"}, {"ok": True, "waiting_for_user": False}, {"ok": True}):
            with self.subTest(result=result):
                rows, _, _ = self.fit_rows([sample("train_0001", calls=[self.ASK], results=[result])])
                self.assertEqual(list(rows), ["train_0001:0", "train_0001:1"])
                self.assertEqual(rows["train_0001:1"]["canonical_target"], {"action": "finish"})

    def test_gold_continuing_after_a_terminal_wait_is_quarantined(self):
        rows, exclusions, _ = self.fit_rows([
            sample("train_0001", calls=[self.ASK, SEARCH], results=[{"ok": True, "waiting_for_user": True}, FOUND]),
            sample("train_0002", request="Kể chuyện cười")])
        self.assertNotIn("train_0001:0", rows)
        self.assertEqual(self.reasons(exclusions), {("train_0001", 0, "continues_after_terminal_wait")})


class NativeTargetTests(ExportCase):
    def test_call_target_is_the_grammar_ordered_native_block_plus_eos(self):
        rows, _, _ = self.fit_rows([sample("train_0001", calls=[SEARCH, SEND], results=[FOUND, SENT])])
        send = rows["train_0001:1"]
        self.assertEqual(send["completion"], '<tool_call>\n{"name": "sms.send", "arguments": {"contact_id": "'
                         + FUTURE_ID + '", "content": "Tôi đến trễ 10 phút"}}\n</tool_call><|im_end|>')
        self.assertEqual(send["canonical_target"], {"action": "call", "name": "sms.send", "arguments": SEND[1]})
        self.assertTrue(grammar(EXPORT_CATALOG["apps"][1]["tools"], send["completion"][:-len("<|im_end|>")]))
        # The executed call is shown as the runner re-reads it (sorted keys), not in gold order.
        self.assertIn('"arguments": {"contact_id": "' + FUTURE_ID + '", "content": "Tôi đến trễ 10 phút"}',
                      rows["train_0001:2"]["prompt"])
        self.assertEqual(list(SEND[1]), ["content", "contact_id"])

    def test_grammar_order_puts_required_keys_first_and_keeps_values(self):
        tool = {"name": "notes.update", "parameters": {"type": "object", "x-one-of": [["id"], ["title"]],
                "required": ["body"], "properties": {"id": {"type": "string"}, "title": {"type": "string"},
                                                     "tags": {"type": "array", "items": {"type": "string"}},
                                                     "body": {"type": "string"}}}}
        ordered = grammar_ordered_arguments(tool, {"tags": ["b", "a"], "title": "T", "body": "x"})
        self.assertEqual(list(ordered), ["body", "title", "tags"])
        self.assertEqual(ordered["tags"], ["b", "a"])

    def test_completion_mask_trains_only_the_target_and_its_eos(self):
        rows, _, _ = self.fit_rows([sample("train_0001", calls=[SEARCH], results=[FOUND])])
        for row in rows.values():
            input_ids, labels = token_labels(self.tokenizer, row["prompt"], row["completion"])
            trained = [token for token in labels if token != IGNORE_INDEX]
            self.assertEqual(labels[:row["prompt_tokens"]], [IGNORE_INDEX] * row["prompt_tokens"])
            self.assertEqual(len(trained), row["completion_tokens"])
            self.assertEqual(trained[-1], self.tokenizer.eos_token_id)
            self.assertEqual(self.tokenizer.decode(trained), row["completion"])
            self.assertEqual(input_ids, self.tokenizer.encode(row["prompt"] + row["completion"]))

    def test_inseparable_token_boundary_is_quarantined(self):
        with self.assertRaises(ValueError):
            token_labels(MergingTokenizer(), "a\n", "<tool_call>")
        with self.assertRaises(ValueError):
            token_labels(self.tokenizer, "a", "Mình hiểu.")  # no EOS
        # A call completion starts with '<' after the prompt's newline; the finish text does not.
        rows, exclusions, _ = self.fit_rows([sample("train_0001", calls=[SEARCH], results=[FOUND])],
                                            tokenizer=MergingTokenizer())
        self.assertEqual(list(rows), ["train_0001:1"])
        self.assertEqual(self.reasons(exclusions), {("train_0001", 0, "token_boundary_mismatch")})

    def test_template_that_does_not_extend_the_generation_prompt_is_quarantined(self):
        with self.assertRaises(PipelineError) as caught:
            self.export([sample("train_0001", request="Kể chuyện cười")], tokenizer=ThinkingTokenizer())
        self.assertIn("template_prefix_mismatch", str(caught.exception))


class InvalidGoldTests(ExportCase):
    def test_invalid_gold_is_quarantined_with_explicit_reasons(self):
        other_app = sample("train_0005", calls=[("alarm.create", {})], results=[{"ok": True}])
        bad_shape = sample("train_0003", calls=[SEARCH], results=[FOUND])
        bad_shape["label"]["tool_calls"][0]["arguments"] = "Lan"
        unlabeled = sample("train_0004")
        unlabeled.pop("label")
        rows, exclusions, manifest = self.fit_rows([
            sample("train_0001", request="Kể chuyện cười"),
            sample("train_0002", calls=[SEARCH, SEND], results=[FOUND]),
            bad_shape, unlabeled, other_app])
        self.assertEqual(list(rows), ["train_0001:0"])
        self.assertEqual(self.reasons(exclusions), {
            ("train_0002", None, "pairing_mismatch"), ("train_0003", 0, "invalid_gold_shape"),
            ("train_0004", None, "label_missing"), ("train_0005", 0, "unavailable_tool")})
        self.assertEqual(manifest["exclusions"]["fit_samples_without_rows"], 4)

    def test_schema_invalid_and_ungrounded_targets_drop_only_their_own_row(self):
        missing_content = ("sms.send", {"contact_id": FUTURE_ID})
        invented = ("sms.send", {"contact_id": "c_99", "content": "trễ"})
        rows, exclusions, manifest = self.fit_rows([
            sample("train_0001", calls=[SEARCH, missing_content], results=[FOUND, {"ok": False}]),
            sample("train_0002", calls=[SEARCH, invented], results=[FOUND, SENT])])
        self.assertEqual(sorted(rows), ["train_0001:0", "train_0001:2", "train_0002:0", "train_0002:2"])
        self.assertEqual(self.reasons(exclusions), {("train_0001", 1, "grammar_rejected_target"),
                                                    ("train_0002", 1, "ungrounded_reference")})
        # The failed call stays in the later prefix as an executed observation.
        self.assertIn('{"ok":false}', rows["train_0001:2"]["prompt"])
        self.assertEqual(manifest["exclusions"]["by_tool"], {"sms.send": 2})

    def test_overflowing_prompts_and_targets_are_excluded_not_truncated(self):
        # The character-level stand-in renders these prompts at about 2,800-4,400 tokens.
        limits = Limits(context_tokens=4000, output_tokens=128)
        long_content = ("sms.send", {"contact_id": FUTURE_ID, "content": "trễ " * 40})
        rows, exclusions, _ = self.fit_rows(
            [sample("train_0001", request="Kể chuyện cười"), sample("train_0002", request="Nhắn Lan " + "rất " * 400),
             sample("train_0003", calls=[SEARCH, long_content], results=[FOUND, SENT])], limits=limits)
        self.assertEqual(sorted(rows), ["train_0001:0", "train_0003:0", "train_0003:2"])
        self.assertEqual(self.reasons(exclusions), {("train_0002", 0, "context_overflow"),
                                                    ("train_0003", 1, "target_overflow")})
        for row in rows.values():
            self.assertLessEqual(row["prompt_tokens"] + limits.output_tokens, limits.context_tokens)


class ExportArtifactTests(ExportCase):
    def rows(self):
        return [sample("train_0001", calls=[SEARCH, SEND], results=[FOUND, SENT]),
                sample("train_0002", request="Kể chuyện cười"),
                sample("train_0003", calls=[SEARCH], results=[FOUND])]

    def test_validation_rows_never_enter_fit_and_diagnostics_are_separate(self):
        manifest, files = self.export(self.rows(), validation={"train_0003"})
        self.assertEqual(sorted(files), ["exclusions.jsonl", "fit.jsonl"])
        self.assertEqual({r["provenance"]["source_id"] for r in files["fit.jsonl"]}, {"train_0001", "train_0002"})
        manifest, files = self.export(validation_diagnostics=True)
        diagnostics = files["validation.next_action.jsonl"]
        self.assertEqual({r["provenance"]["source_id"] for r in diagnostics}, {"train_0003"})
        self.assertEqual({r["use"] for r in diagnostics}, {"teacher_forced_diagnostic"})
        self.assertEqual({r["use"] for r in files["fit.jsonl"]}, {"fit"})
        self.assertEqual(manifest["audits"]["partition"]["shared_groups"], 0)

    def test_manifest_records_identities_distributions_and_file_digests(self):
        manifest, files = self.export(self.rows())
        self.assertEqual(manifest["protocol"]["protocol"], "qwen-native-v1")
        self.assertEqual(manifest["protocol"]["prompt"]["sha256"], NATIVE_PROMPT_HASH)
        self.assertEqual(manifest["source"]["dataset_sha256"],
                         hashlib.sha256((self.fx.split / "train.jsonl").read_bytes()).hexdigest())
        self.assertEqual(manifest["partition"]["sha256"], hashlib.sha256(self.partition.read_bytes()).hexdigest())
        self.assertEqual(manifest["base_model"]["chat_template_sha256"],
                         hashlib.sha256(b"qwen-like test template").hexdigest())
        self.assertEqual(set(manifest["base_model"]["files"]), {"config.json", "tokenizer_config.json"})
        fit = manifest["rows"]["fit"]
        self.assertEqual((fit["rows"], fit["samples"]), (6, 3))
        self.assertEqual(fit["targets"], {"calls": 3, "policy_finish": 3, "missing_info": 0,
                                          "by_tool": {"contacts.search": 2, "sms.send": 1}})
        self.assertEqual(fit["rows_per_sample"], {"1": 1, "2": 1, "3": 1})
        self.assertEqual(fit["lengths"]["completion_tokens"]["count"], 6)
        self.assertEqual(manifest["supervision"]["ignore_index"], IGNORE_INDEX)
        self.assertFalse(manifest["supervision"]["packing"])
        self.assertEqual(manifest["audits"]["leakage"], {"rows_checked": 6, "failures": 0})
        output = Path(manifest["partition"]["path"]).parent / "exports" / "sft-1"
        self.assertEqual(manifest["files"]["fit.jsonl"]["sha256"],
                         hashlib.sha256((output / "fit.jsonl").read_bytes()).hexdigest())
        self.assertEqual(json.loads((output / "export_manifest.json").read_text(encoding="utf-8")), manifest)

    def test_export_is_deterministic(self):
        first = self.export(self.rows())[1]
        self.assertEqual(self.export()[1], first)

    def test_mismatched_partition_or_source_is_rejected(self):
        self.write(self.rows())
        manifest = json.loads(self.partition.read_text(encoding="utf-8"))
        for change in ({"dataset_sha256": "0" * 64}, {"catalog_sha256": "0" * 64},
                       {"members": manifest["members"][:-1]},
                       {"members": [dict(manifest["members"][0], source_sha256="0" * 64)] + manifest["members"][1:]}):
            with self.subTest(change=list(change)):
                self.partition.write_text(dumps(manifest | change), encoding="utf-8")
                with self.assertRaises(PipelineError) as caught:
                    self.export()
                self.assertEqual(caught.exception.code, "INPUT_INVALID")

    def test_zero_accepted_fit_rows_fail_without_artifacts(self):
        with self.assertRaises(PipelineError) as caught:
            self.export([sample("train_0001", calls=[SEARCH], results=[])])
        self.assertIn("pairing_mismatch", str(caught.exception))
        self.assertFalse((self.fx.root / "exports").exists() and any((self.fx.root / "exports").iterdir()))


class ExportCommandTests(ExportCase):
    def setUp(self):
        super().setUp()
        self.write([sample("train_0001", calls=[SEARCH, SEND], results=[FOUND, SENT]),
                    sample("train_0002", request="Kể chuyện cười")])
        for row in self.fx.rows:
            state = self.fx.split / "train_environment" / row["id"] / "state.json"
            state.parent.mkdir(parents=True)
            state.write_text("{}", encoding="utf-8")
        self.output = self.fx.root / "experiments" / "sft"

    def run_command(self, *extra, output=None):
        stdout = io.StringIO()
        with patch.object(training_data, "load_tokenizer", return_value=self.tokenizer), \
                patch.object(training_data, "native_grammar", return_value=grammar), \
                contextlib.redirect_stdout(stdout):
            code = main(["export", "--data-root", str(self.fx.data), "--partition", str(self.partition),
                         "--base-model", str(self.model), "--output", str(output or self.output), *extra])
        return code, json.loads(stdout.getvalue())

    def test_command_writes_immutable_artifacts_and_refuses_to_overwrite(self):
        code, summary = self.run_command()
        self.assertEqual((code, summary["status"], summary["rows"]), (0, "completed", {"fit": 4}))
        self.assertEqual(sorted(p.name for p in self.output.iterdir()),
                         ["exclusions.jsonl", "export_manifest.json", "fit.jsonl"])
        written = (self.output / "fit.jsonl").read_bytes()
        code, summary = self.run_command("--validation-diagnostics")
        self.assertEqual((code, summary["error"]["code"]), (2, "INPUT_INVALID"))
        self.assertEqual((self.output / "fit.jsonl").read_bytes(), written)
        self.assertEqual([p.name for p in self.output.parent.iterdir()], ["sft"])

    def test_outputs_inside_the_data_root_or_base_model_are_rejected(self):
        for output in (self.fx.data / "sft", self.model / "sft"):
            with self.subTest(output=output):
                code, summary = self.run_command(output=output)
                self.assertEqual((code, summary["error"]["code"]), (2, "INPUT_INVALID"))
                self.assertFalse(output.exists())

    def test_invalid_budgets_are_rejected(self):
        code, summary = self.run_command("--output-tokens", "20000")
        self.assertEqual((code, summary["error"]["code"]), (2, "INPUT_INVALID"))

    def test_environment_files_are_never_touched(self):
        touched = []
        real = {name: getattr(Path, name) for name in ("open", "is_file", "exists", "read_bytes")}

        def recorder(name):
            def method(path, *args, **kwargs):
                touched.append(str(path))
                return real[name](path, *args, **kwargs)
            return method

        with contextlib.ExitStack() as stack:
            for name in real:
                stack.enter_context(patch.object(Path, name, recorder(name)))
            code, _ = self.run_command()
        self.assertEqual(code, 0)
        self.assertTrue(touched)
        self.assertFalse([p for p in touched if "_environment" in p])


if __name__ == "__main__":
    unittest.main()
