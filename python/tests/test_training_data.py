"""Frozen grouped Train partition (spec 003 T014/T015); controlled rows, no model or environment."""
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import lifemate
from lifemate.contracts import PipelineError
from lifemate.jsonio import dumps
from lifemate.prompt_profiles import validate_partition_manifest
from lifemate.training.__main__ import main
from lifemate.training.data import SMOKE_FIT_IDS, build_partition
from support import Fixture

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


if __name__ == "__main__":
    unittest.main()
