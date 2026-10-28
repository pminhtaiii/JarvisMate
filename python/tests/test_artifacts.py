import json
import unittest
from pathlib import Path
from unittest.mock import patch

from lifemate.artifacts import RunStore, Trace, validate_prediction
from lifemate.contracts import PipelineError, SampleOutcome
from support import Fixture


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.close)

    def outcome(self, sample_id="train_0001"):
        return SampleOutcome(sample_id, "completed", 0.1, 1, "finish",
                             result={"id": sample_id, "tool_calls": [], "state_hash": "a" * 64})

    def store(self, ids=None):
        store = RunStore(self.fx.config())
        ids = ids or ["train_0001"]
        store.selected({"selected_ids": ids, "coverage_scope": "subset"}, {})
        return store

    def test_utf8_order_and_default_payload_omission(self):
        path = self.fx.root / "trace.jsonl"
        trace = Trace(path, "run", "train_0001")
        trace.emit("request_prepared", payload={"request": "Nhắn mẹ"})
        trace.emit("sample_finished", status="completed")
        trace.close()
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["sequence"] for r in rows], [1, 2])
        self.assertTrue(rows[0]["payload_omitted"])
        self.assertNotIn("Nhắn mẹ", path.read_text(encoding="utf-8"))

    def test_debug_payload_redaction_and_bounding(self):
        path = self.fx.root / "debug.jsonl"
        trace = Trace(path, "run", "train_0001", payloads=True, event_limit=2048, total_limit=16384)
        trace.emit("tool_call_result", payload={"password": "DO_NOT_EXPOSE", "text": "Hà Nội" * 2000})
        trace.close()
        raw = path.read_text(encoding="utf-8")
        row = json.loads(raw)
        self.assertNotIn("DO_NOT_EXPOSE", raw)
        self.assertTrue(row["payload_redacted"])
        self.assertTrue(row["payload_truncated"])
        self.assertLessEqual(len(raw.encode("utf-8")), 2048)

    def test_prediction_arguments_are_never_trace_redacted_or_truncated(self):
        store = self.store()
        outcome = self.outcome()
        outcome.result["tool_calls"] = [{"name": "sms.send", "arguments": {"content": "Đúng " * 5000}}]
        store.append(outcome)
        store.finish()
        self.assertEqual(json.loads(store.final_path.read_text(encoding="utf-8")), outcome.result)
        manifest = json.loads(store.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "completed")
        self.assertFalse(manifest["submission_ready"])

    def test_raw_planner_json_string_has_nested_credentials_redacted(self):
        path = self.fx.root / "planner.jsonl"
        trace = Trace(path, "run", "train_0001", payloads=True)
        trace.emit("planner_action", payload={"response": json.dumps({"arguments": {"api_key": "TOP_SECRET_VALUE"}})})
        trace.close()
        self.assertNotIn("TOP_SECRET_VALUE", path.read_text(encoding="utf-8"))

    def test_extra_prediction_fields_rejected(self):
        row = self.outcome().result | {"trace": "not a submission field"}
        with self.assertRaises(PipelineError):
            validate_prediction(row)

    def test_write_failure_is_visible(self):
        trace = Trace(self.fx.root / "trace.jsonl", "run", "train_0001")
        self.addCleanup(trace.close)
        with patch("lifemate.artifacts.sync_write", side_effect=OSError("full")), self.assertRaises(PipelineError):
            trace.emit("tool_call_started", payload={"content": "test"})

    def test_existing_directory_is_preserved(self):
        self.fx.config().run_dir.mkdir()
        marker = self.fx.config().run_dir / "keep"
        marker.write_text("original", encoding="utf-8")
        with self.assertRaises(PipelineError):
            RunStore(self.fx.config())
        self.assertEqual(marker.read_text(encoding="utf-8"), "original")

    def test_partial_output_survives_second_sample_failure(self):
        store = self.store(["train_0001", "train_0002", "train_0003"])
        store.append(self.outcome())
        store.fail({"code": "PLANNER_ERROR", "stage": "planner", "message": "failure"}, "train_0002")
        self.assertEqual(json.loads(store.partial_path.read_text(encoding="utf-8"))["id"], "train_0001")
        self.assertFalse(store.final_path.exists())
        self.assertEqual(store.manifest["not_started_ids"], ["train_0003"])

    def test_ordered_journal_is_published_without_rewriting(self):
        store = self.store()
        store.append(self.outcome())
        inode = store.partial_path.stat().st_ino
        # An ordered journal must publish even if the rewrite path is unavailable.
        ordered = store.partial_path.with_suffix(".ordered.tmp")
        ordered.write_text("unrelated marker", encoding="utf-8")
        store.finish()
        self.assertEqual(store.final_path.stat().st_ino, inode)
        self.assertEqual(ordered.read_text(encoding="utf-8"), "unrelated marker")

    def test_journal_with_resumed_holes_is_published_in_selected_order(self):
        store = self.store(["train_0001", "train_0002", "train_0003"])
        for sample_id in ("train_0001", "train_0003", "train_0002"):
            store.append(self.outcome(sample_id))
        store.finish()
        rows = [json.loads(line) for line in store.final_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["id"] for row in rows], store.manifest["selected_ids"])
        self.assertEqual(store.manifest["status"], "completed")

    def test_incomplete_selection_and_publication_failure_do_not_complete(self):
        store = self.store(["train_0001", "train_0002"])
        store.append(self.outcome())
        with self.assertRaises(PipelineError):
            store.finish()
        self.assertEqual(store.manifest["status"], "running")
        store.append(self.outcome("train_0002"))
        with patch("lifemate.artifacts.os.replace", side_effect=OSError("publish failed")), self.assertRaises(PipelineError):
            store.finish()
        self.assertTrue(store.partial_path.exists())
        self.assertFalse(store.final_path.exists())

    def test_manifest_failure_after_file_publish_needs_explicit_failed_state(self):
        store = self.store()
        store.append(self.outcome())
        with patch.object(store, "save", side_effect=PipelineError("OUTPUT_IO", "failed")), self.assertRaises(PipelineError):
            store.finish()
        # A final filename alone must not establish successful publication.
        self.assertEqual(json.loads(store.manifest_path.read_text(encoding="utf-8"))["status"], "running")

    def test_capacity_failure_still_allows_terminal_metadata(self):
        trace = Trace(self.fx.root / "trace.jsonl", "run", "train_0001", event_limit=1024, total_limit=4096)
        self.addCleanup(trace.close)
        for _ in range(100):
            try:
                trace.emit("planner_action", payload={"response": "x"})
            except PipelineError:
                break
        else:
            self.fail("Trace limit was not enforced")
        trace.emit("sample_failed", error={"code": "TRACE_IO"})
