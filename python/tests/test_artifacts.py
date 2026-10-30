import json
import unittest
from pathlib import Path
from unittest.mock import patch

from lifemate.artifacts import RunStore, Trace, validate_prediction
from lifemate.contracts import PipelineError, SampleOutcome
from lifemate.metrics import METRICS_SCHEMA_VERSION
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

    def test_refresh_tokens_are_redacted_in_payload_keys_json_and_inline_text(self):
        path = self.fx.root / "refresh.jsonl"
        trace = Trace(path, "run", "train_0001", payloads=True)
        self.addCleanup(trace.close)
        for key in ("refresh_token", "refresh-token", "refreshToken", "REFRESH_TOKEN"):
            with self.subTest(key=key):
                trace.emit("tool_call_result", payload={
                    "nested": [{key: "KEY_VALUE"}],
                    "response": json.dumps({"arguments": {key: "JSON_VALUE"}}),
                    "text": f'{key}=INLINE_VALUE; "{key}": "QUOTED_VALUE"',
                    "status": "ok",
                })
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        for row in rows:
            self.assertTrue(row["payload_redacted"])
            self.assertEqual(row["payload"]["status"], "ok")
            self.assertIn("[REDACTED]", row["payload"]["text"])
        raw = path.read_text(encoding="utf-8")
        for secret in ("KEY_VALUE", "JSON_VALUE", "INLINE_VALUE", "QUOTED_VALUE"):
            self.assertNotIn(secret, raw)

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

    def test_manifest_defaults_effective_prompt_to_null_not_missing(self):
        store = self.store()
        self.assertIn("effective_prompt", store.manifest)
        self.assertIsNone(store.manifest["effective_prompt"])

    def test_manifest_carries_the_metrics_schema_version(self):
        store = self.store()
        self.assertEqual(store.manifest["metrics_schema_version"], METRICS_SCHEMA_VERSION)
        on_disk = json.loads(store.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["metrics_schema_version"], METRICS_SCHEMA_VERSION)

    def test_append_stamps_source_executed_and_stores_optional_measurements(self):
        store = self.store()
        store.append(self.outcome(), measurements={"spans": [], "generations": []})
        record = store.manifest["samples"][0]
        self.assertEqual(record["source"], "executed")
        self.assertEqual(record["measurements"], {"spans": [], "generations": []})

    def test_append_without_measurements_leaves_it_null_not_missing(self):
        store = self.store()
        store.append(self.outcome())
        record = store.manifest["samples"][0]
        self.assertEqual(record["source"], "executed")
        self.assertIsNone(record["measurements"])

    def test_append_rejects_a_non_object_measurements_payload(self):
        store = self.store()
        with self.assertRaises(PipelineError):
            store.append(self.outcome(), measurements="not an object")

    def test_write_prediction_then_record_sample_matches_append(self):
        # cli.py measures the full attempt after this fsync, so it calls the two
        # steps separately; splitting them must not change the persisted result.
        store = self.store()
        outcome = self.outcome()
        store.write_prediction(outcome)
        store.record_sample(outcome, measurements={"spans": [], "generations": []}, full_attempt_seconds=1.5)
        record = store.manifest["samples"][0]
        self.assertEqual(record["source"], "executed")
        self.assertEqual(record["full_attempt_seconds"], 1.5)
        self.assertEqual(json.loads(store.partial_path.read_text(encoding="utf-8")), outcome.result)

    def test_record_sample_without_write_prediction_leaves_no_durable_row(self):
        store = self.store()
        with self.assertRaises(PipelineError):
            store.write_prediction(self.outcome("unknown-id"))
        self.assertEqual(store.partial_path.read_text(encoding="utf-8"), "")

    def test_restore_marks_imported_rows_regardless_of_their_source_tag(self):
        metadata = {"selected_ids": ["train_0001", "train_0002"], "coverage_scope": "subset",
                    "dataset_sha256": "dataset", "catalog_sha256": "catalog"}
        source = RunStore(self.fx.config())
        source.selected(metadata, {})
        source.append(self.outcome("train_0001"), measurements={"spans": [], "generations": []})
        source.sample_failed({"code": "PLANNER_ERROR", "stage": "planner"}, "train_0002")

        target = RunStore(self.fx.config(run_dir=self.fx.root / "run-2"))
        target.selected(metadata, {})
        target.restore(source.directory)
        imported = target.manifest["samples"][0]
        self.assertEqual(imported["id"], "train_0001")
        self.assertEqual(imported["source"], "imported")
        self.assertEqual(imported["source_run_id"], source.run_id)
        # The source's own measurements survive the import unchanged.
        self.assertEqual(imported["measurements"], {"spans": [], "generations": []})

    def test_restore_from_a_legacy_manifest_without_source_or_measurements_still_imports(self):
        metadata = {"selected_ids": ["train_0001"], "coverage_scope": "subset",
                    "dataset_sha256": "dataset", "catalog_sha256": "catalog"}
        source = RunStore(self.fx.config())
        source.selected(metadata, {})
        source.append(self.outcome())
        legacy_sample = {k: v for k, v in source.manifest["samples"][0].items()
                         if k not in ("source", "measurements")}
        source.manifest["samples"] = [legacy_sample]
        source.save()

        target = RunStore(self.fx.config(run_dir=self.fx.root / "run-2"))
        target.selected(metadata, {})
        target.restore(source.directory)
        imported = target.manifest["samples"][0]
        self.assertEqual(imported["source"], "imported")
        # Absence is an explicit null, not an ambiguous missing key.
        self.assertIn("measurements", imported)
        self.assertIsNone(imported["measurements"])
        self.assertIn("full_attempt_seconds", imported)
        self.assertIsNone(imported["full_attempt_seconds"])

    def test_append_rejects_an_invalid_full_attempt_seconds(self):
        store = self.store()
        for bad in (-1.0, "1.0", float("nan"), True):
            with self.subTest(bad=bad):
                with self.assertRaises(PipelineError):
                    store.append(self.outcome(), full_attempt_seconds=bad)

    def test_sample_failed_stores_measurements_and_full_attempt_seconds(self):
        store = self.store(["train_0001"])
        store.sample_failed({"code": "PLANNER_ERROR", "stage": "planner"}, "train_0001",
                            measurements={"spans": [], "generations": []}, full_attempt_seconds=2.5)
        failure = store.manifest["failures"][0]
        self.assertEqual(failure["full_attempt_seconds"], 2.5)
        self.assertEqual(failure["measurements"], {"spans": [], "generations": []})

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
