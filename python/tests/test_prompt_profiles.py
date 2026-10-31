"""prompt_profiles.py profiles/bundle/partition validation and example_audit.py (T013)."""
from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from lifemate.contracts import Deadline, PipelineError, RunConfig
from lifemate.dataset import normalize_record, prepare_request, validate_catalog
from lifemate.example_audit import audit_bundle, verified_content_sha256, write_audited_bundle
from lifemate.jsonio import digest, dumps
from lifemate.prompt_profiles import (
    bundle_identity, profile_identity, reject_fit_in_selection, resolve_profile, validate_bundle,
    validate_partition_manifest,
)
from lifemate.prompting import PROMPT_HASH, PROMPT_VERSION, SYSTEM, messages
from support import CATALOG

PARTITION = {
    "partition_schema_version": 1, "dataset_sha256": "d" * 8, "grouping_method": "conversation_group_v1",
    "members": [
        {"id": "train_fit_0001", "group_id": "g1", "partition": "fit", "source_sha256": "s1"},
        {"id": "train_fit_0002", "group_id": "g3", "partition": "fit", "source_sha256": "s3"},
        {"id": "train_val_0001", "group_id": "g2", "partition": "validation", "source_sha256": "s2"},
    ],
}
EXAMPLE_INPUT = {"request": "Nhắn Lan tôi đến trễ", "context": {
    "current_time": "2026-01-01T00:00:00+00:00", "timezone": "Asia/Ho_Chi_Minh",
    "location": {"lat": 10, "lng": 106},
    "user_profile": {"name": "An", "home_address": "x", "work_address": "y", "city": "z"},
    "installed_apps": {"contacts": {"tools": ["contacts.search"]}}},
    "history": [], "available_tools": [CATALOG["apps"][0]["tools"][0]], "observations": []}
EXAMPLE_TARGET = {"action": "call", "name": "contacts.search", "arguments": {"query": "Lan"}}


class ProfileTests(unittest.TestCase):
    def test_baseline_profile_matches_existing_prompt_identity(self):
        profile = resolve_profile("baseline")
        self.assertEqual(profile["version"], PROMPT_VERSION)
        self.assertEqual(profile["sha256"], PROMPT_HASH)
        self.assertEqual(profile["system"], SYSTEM)

    def test_precise_v1_profile_has_its_own_frozen_identity(self):
        profile = resolve_profile("precise-v1")
        self.assertNotEqual(profile["sha256"], PROMPT_HASH)
        self.assertEqual(profile_identity(profile),
                         {"profile": "precise-v1", "version": profile["version"], "sha256": profile["sha256"]})

    def test_unsupported_profile_rejected(self):
        with self.assertRaises(PipelineError):
            resolve_profile("fancy-v2")


class MessagesTests(unittest.TestCase):
    def value(self, **extra):
        return {"request": "Nhắn Lan", "context": {}, "history": [], "available_tools": [],
                "observations": []} | extra

    def test_baseline_rendering_is_exactly_unchanged_without_examples(self):
        turns = messages(self.value())
        self.assertEqual(turns, [{"role": "system", "content": SYSTEM},
                                 {"role": "user", "content": dumps({"request": "Nhắn Lan", "context": {},
                                                                    "history": [], "available_tools": []})}])

    def test_examples_are_inserted_between_system_and_the_live_request(self):
        example = {"input": EXAMPLE_INPUT, "target": EXAMPLE_TARGET}
        turns = messages(self.value(), examples=(example,))
        self.assertEqual(len(turns), 4)
        self.assertIn("demonstration", turns[0]["content"])  # Guard text only appears with examples.
        demonstration = json.loads(turns[1]["content"])
        self.assertTrue(demonstration["demonstration"])
        self.assertEqual(demonstration["request"], EXAMPLE_INPUT["request"])
        self.assertEqual(json.loads(turns[2]["content"]), EXAMPLE_TARGET)
        self.assertEqual(json.loads(turns[3]["content"])["request"], "Nhắn Lan")

    def test_custom_system_text_is_used_as_is(self):
        turns = messages(self.value(), system="Different system text")
        self.assertEqual(turns[0]["content"], "Different system text")


class PartitionManifestTests(unittest.TestCase):
    def test_valid_manifest_indexes_members_by_id(self):
        members = validate_partition_manifest(PARTITION)
        self.assertEqual(set(members), {"train_fit_0001", "train_fit_0002", "train_val_0001"})

    def test_group_straddling_both_partitions_is_rejected(self):
        payload = json.loads(dumps(PARTITION))
        payload["members"][2]["group_id"] = "g1"  # Same group as a fit member, different partition.
        with self.assertRaises(PipelineError):
            validate_partition_manifest(payload)

    def test_duplicate_member_id_rejected(self):
        payload = json.loads(dumps(PARTITION))
        payload["members"].append(dict(payload["members"][0]))
        with self.assertRaises(PipelineError):
            validate_partition_manifest(payload)

    def test_unsupported_schema_version_rejected(self):
        with self.assertRaises(PipelineError):
            validate_partition_manifest(PARTITION | {"partition_schema_version": 2})


class SelectionEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.members = validate_partition_manifest(PARTITION)

    def test_fit_id_in_selection_rejected(self):
        with self.assertRaises(PipelineError):
            reject_fit_in_selection(["train_fit_0001"], self.members)

    def test_unknown_id_in_selection_rejected(self):
        with self.assertRaises(PipelineError):
            reject_fit_in_selection(["unknown"], self.members)

    def test_validation_only_selection_is_accepted(self):
        reject_fit_in_selection(["train_val_0001"], self.members)  # Does not raise.


def bundle_payload(partition_sha256, catalog_fingerprint, **overrides):
    payload = {
        "bundle_schema_version": 1, "bundle_id": "bundle-1", "partition_manifest_sha256": partition_sha256,
        "split": "train", "catalog_fingerprint": catalog_fingerprint,
        "examples": [{"id": "train_fit_0001", "group_id": "g1", "source_sha256": "s1", "prefix_index": 0,
                     "rationale": "Illustrates a contact lookup.", "input": EXAMPLE_INPUT, "target": EXAMPLE_TARGET}],
    }
    payload.update(overrides)
    return payload


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.members = validate_partition_manifest(PARTITION)
        self.partition_sha256, self.catalog_fingerprint = "p-hash", "c-hash"

    def test_valid_bundle_is_accepted(self):
        validate_bundle(bundle_payload(self.partition_sha256, self.catalog_fingerprint),
                        self.members, self.partition_sha256, self.catalog_fingerprint)

    def test_bundle_referencing_a_validation_partition_id_is_rejected(self):
        payload = bundle_payload(self.partition_sha256, self.catalog_fingerprint)
        payload["examples"][0].update(id="train_val_0001", group_id="g2")
        with self.assertRaises(PipelineError):
            validate_bundle(payload, self.members, self.partition_sha256, self.catalog_fingerprint)

    def test_bundle_example_with_a_source_hash_not_matching_its_partition_member_is_rejected(self):
        payload = bundle_payload(self.partition_sha256, self.catalog_fingerprint)
        payload["examples"][0]["source_sha256"] = "not-the-partition-hash"
        with self.assertRaises(PipelineError):
            validate_bundle(payload, self.members, self.partition_sha256, self.catalog_fingerprint)

    def test_bundle_with_mismatched_partition_hash_is_rejected(self):
        with self.assertRaises(PipelineError):
            validate_bundle(bundle_payload("other-hash", self.catalog_fingerprint),
                            self.members, self.partition_sha256, self.catalog_fingerprint)

    def test_bundle_with_mismatched_catalog_fingerprint_is_rejected(self):
        with self.assertRaises(PipelineError):
            validate_bundle(bundle_payload(self.partition_sha256, "other-catalog"),
                            self.members, self.partition_sha256, self.catalog_fingerprint)

    def test_too_many_examples_rejected(self):
        payload = bundle_payload(self.partition_sha256, self.catalog_fingerprint)
        payload["examples"] = payload["examples"] * 4
        with self.assertRaises(PipelineError):
            validate_bundle(payload, self.members, self.partition_sha256, self.catalog_fingerprint)

    def test_duplicate_example_provenance_rejected(self):
        payload = bundle_payload(self.partition_sha256, self.catalog_fingerprint)
        payload["examples"] = payload["examples"] * 2
        with self.assertRaises(PipelineError):
            validate_bundle(payload, self.members, self.partition_sha256, self.catalog_fingerprint)

    def test_target_with_invalid_grammar_rejected(self):
        payload = bundle_payload(self.partition_sha256, self.catalog_fingerprint)
        payload["examples"][0]["target"] = {"action": "call", "name": "contacts.search"}  # missing arguments
        with self.assertRaises(PipelineError):
            validate_bundle(payload, self.members, self.partition_sha256, self.catalog_fingerprint)

    def test_input_with_extra_field_rejected(self):
        payload = bundle_payload(self.partition_sha256, self.catalog_fingerprint)
        payload["examples"][0]["input"] = dict(EXAMPLE_INPUT, extra_field=True)
        with self.assertRaises(PipelineError):
            validate_bundle(payload, self.members, self.partition_sha256, self.catalog_fingerprint)

    def test_deterministic_identity_is_order_sensitive(self):
        payload = bundle_payload(self.partition_sha256, self.catalog_fingerprint)
        payload["examples"].append({"id": "train_fit_0002", "group_id": "g3", "source_sha256": "s3",
                                    "prefix_index": 0, "rationale": "second", "input": EXAMPLE_INPUT,
                                    "target": {"action": "finish"}})
        forward = bundle_identity(payload)
        backward = bundle_identity(payload | {"examples": list(reversed(payload["examples"]))})
        self.assertEqual(forward["example_ids"], ["train_fit_0001", "train_fit_0002"])
        self.assertEqual(backward["example_ids"], ["train_fit_0002", "train_fit_0001"])
        self.assertNotEqual(forward["bundle_sha256"], backward["bundle_sha256"])
        # Same payload, computed twice, is exactly reproducible.
        self.assertEqual(forward, bundle_identity(payload))


class AuditFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.split = self.root / "train"
        self.split.mkdir()
        self.catalog_path = self.split / "train_tools_catalog.json"
        self.catalog_path.write_text(dumps(CATALOG), encoding="utf-8")
        self.train_jsonl = self.split / "train.jsonl"
        self.rows: dict[str, dict] = {}
        self.partition = {"partition_schema_version": 1, "dataset_sha256": "d", "grouping_method": "m",
                          "members": []}
        self.partition_path = self.root / "partition.json"

    def add_row(self, sample_id, group_id, tool_calls, tool_results, partition="fit"):
        state = self.split / "train_environment" / sample_id / "state.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.touch()
        row = {"id": sample_id, "audio": f"audio/{sample_id}/{sample_id}.wav",
               "audio_text": "Nhắn Lan tôi đến trễ",
               "context": {"current_time": "2026-01-01T00:00:00+07:00", "timezone": "Asia/Ho_Chi_Minh",
                           "location": {"lat": 10, "lng": 106},
                           "user_profile": {"name": "An", "home_address": "a", "work_address": "b", "city": "c"},
                           "installed_apps": {"contacts": {"tools": ["contacts.search"]}}},
               "history": [], "label": {"tool_calls": tool_calls, "tool_results": tool_results}}
        self.rows[sample_id] = row
        self.train_jsonl.write_text("".join(dumps(r) + "\n" for r in self.rows.values()), encoding="utf-8")
        self.partition["dataset_sha256"] = digest(self.train_jsonl)
        self.partition["members"].append({"id": sample_id, "group_id": group_id, "partition": partition,
                                          "source_sha256": "s-" + sample_id})
        self.partition_path.write_text(dumps(self.partition), encoding="utf-8")
        return row

    def prepared(self, row):
        specs = validate_catalog(json.loads(self.catalog_path.read_text(encoding="utf-8")))
        config = RunConfig(data_root=self.root, runtime_dir=self.root, split="train", input_mode="transcript",
                           selected_ids=(row["id"],))
        sample = normalize_record(row, config, specs)
        return prepare_request(sample, None, Deadline(10 ** 6), None)

    def example(self, row, group_id, prefix_index, target, input_override=None):
        if input_override is None:
            prepared = self.prepared(row)
            calls, results = row["label"]["tool_calls"], row["label"]["tool_results"]
            observations = [{"step": i + 1, "kind": "tool_result", "name": calls[i]["name"],
                             "arguments": calls[i]["arguments"], "result": results[i]}
                            for i in range(prefix_index)]
            input_override = {"request": prepared["request"], "context": prepared["context"],
                              "history": prepared["history"], "available_tools": prepared["available_tools"],
                              "observations": observations}
        return {"id": row["id"], "group_id": group_id, "source_sha256": "s-" + row["id"],
                "prefix_index": prefix_index, "rationale": "r", "input": input_override, "target": target}

    def write_bundle(self, examples):
        payload = {"bundle_schema_version": 1, "bundle_id": "b1",
                  "partition_manifest_sha256": digest(self.partition_path), "split": "train",
                  "catalog_fingerprint": digest(self.catalog_path), "examples": examples}
        path = self.root / "bundle.json"
        path.write_text(dumps(payload), encoding="utf-8")
        return path

    def audit(self, bundle_path):
        return audit_bundle(bundle_path, self.partition_path, self.train_jsonl, self.catalog_path)


class AuditBundleTests(AuditFixture):
    def test_valid_prefix_zero_call_target_is_accepted(self):
        row = self.add_row("train_0001", "g1", [{"name": "contacts.search", "arguments": {"query": "Lan"}}],
                           [{"ok": True, "contacts": [{"id": "c1", "name": "Lan"}]}])
        example = self.example(row, "g1", 0, {"action": "call", "name": "contacts.search",
                                              "arguments": {"query": "Lan"}})
        audited = self.audit(self.write_bundle([example]))
        self.assertEqual(audited["conversion_version"], "lifemate-sft-conversion-v1")
        self.assertEqual(audited["source_dataset_sha256"], digest(self.train_jsonl))
        self.assertEqual(audited["catalog_sha256"], digest(self.catalog_path))
        self.assertEqual(audited["verified_content_sha256"], verified_content_sha256(audited["examples"]))
        # Editing the content after auditing must change the bound digest, so a
        # run-path recheck against the (unedited) current content would catch it.
        edited = [dict(audited["examples"][0], target={"action": "finish"})]
        self.assertNotEqual(audited["verified_content_sha256"], verified_content_sha256(edited))

    def test_valid_terminal_finish_target_is_accepted(self):
        row = self.add_row("train_0001", "g1", [{"name": "contacts.search", "arguments": {"query": "Lan"}}],
                           [{"ok": True, "contacts": []}])
        example = self.example(row, "g1", 1, {"action": "finish"})
        self.audit(self.write_bundle([example]))  # Does not raise.

    def test_empty_gold_trajectory_emits_exactly_one_finish_row(self):
        row = self.add_row("train_0001", "g1", [], [])
        example = self.example(row, "g1", 0, {"action": "finish"})
        self.audit(self.write_bundle([example]))  # Does not raise.

    def test_changed_target_is_rejected(self):
        row = self.add_row("train_0001", "g1", [{"name": "contacts.search", "arguments": {"query": "Lan"}}],
                           [{"ok": True, "contacts": []}])
        example = self.example(row, "g1", 0, {"action": "finish"})
        with self.assertRaises(PipelineError):
            self.audit(self.write_bundle([example]))

    def test_fabricated_input_is_rejected(self):
        row = self.add_row("train_0001", "g1", [{"name": "contacts.search", "arguments": {"query": "Lan"}}],
                           [{"ok": True, "contacts": []}])
        example = self.example(row, "g1", 0, {"action": "call", "name": "contacts.search",
                                              "arguments": {"query": "Lan"}})
        example["input"]["request"] = "Totally different request"
        with self.assertRaises(PipelineError):
            self.audit(self.write_bundle([example]))

    def test_leaked_future_observation_in_the_prefix_is_rejected(self):
        row = self.add_row("train_0001", "g1", [{"name": "contacts.search", "arguments": {"query": "Lan"}}],
                           [{"ok": True, "contacts": [{"id": "c1"}]}])
        example = self.example(row, "g1", 0, {"action": "call", "name": "contacts.search",
                                              "arguments": {"query": "Lan"}})
        example["input"]["observations"] = [{"step": 1, "kind": "tool_result", "name": "contacts.search",
                                             "arguments": {"query": "Lan"},
                                             "result": {"ok": True, "contacts": [{"id": "c1"}]}}]
        with self.assertRaises(PipelineError):
            self.audit(self.write_bundle([example]))

    def test_prefix_index_beyond_trajectory_is_rejected(self):
        row = self.add_row("train_0001", "g1", [{"name": "contacts.search", "arguments": {"query": "Lan"}}],
                           [{"ok": True, "contacts": []}])
        prepared = self.prepared(row)
        placeholder_input = {"request": prepared["request"], "context": prepared["context"],
                             "history": prepared["history"], "available_tools": prepared["available_tools"],
                             "observations": []}
        example = self.example(row, "g1", 5, {"action": "finish"}, input_override=placeholder_input)
        with self.assertRaises(PipelineError):
            self.audit(self.write_bundle([example]))

    def test_partition_from_a_different_train_revision_is_rejected(self):
        row = self.add_row("train_0001", "g1", [], [])
        example = self.example(row, "g1", 0, {"action": "finish"})
        self.partition["dataset_sha256"] = "0" * 64  # No longer the actual train.jsonl digest.
        self.partition_path.write_text(dumps(self.partition), encoding="utf-8")
        with self.assertRaises(PipelineError):
            self.audit(self.write_bundle([example]))

    def test_unknown_bundle_example_id_absent_from_train_jsonl_is_rejected(self):
        row = self.add_row("train_0001", "g1", [], [])
        example = self.example(row, "g1", 0, {"action": "finish"})
        example["id"], example["group_id"] = "train_9999", "g9"
        self.partition["members"].append({"id": "train_9999", "group_id": "g9", "partition": "fit",
                                          "source_sha256": "s9"})
        self.partition_path.write_text(dumps(self.partition), encoding="utf-8")
        with self.assertRaises(PipelineError):
            self.audit(self.write_bundle([example]))

    def test_terminal_missing_info_call_cannot_be_followed_by_finish(self):
        row = self.add_row("train_0001", "g1",
                           [{"name": "sys.ask_missing_info", "arguments": {"tool_name": "sms.send", "params": ["content"]}}],
                           [{"ok": True, "waiting_for_user": True}])
        example = self.example(row, "g1", 1, {"action": "finish"})
        with self.assertRaises(PipelineError):
            self.audit(self.write_bundle([example]))

    def test_terminal_missing_info_call_itself_is_a_valid_target(self):
        row = self.add_row("train_0001", "g1",
                           [{"name": "sys.ask_missing_info", "arguments": {"tool_name": "sms.send", "params": ["content"]}}],
                           [{"ok": True, "waiting_for_user": True}])
        example = self.example(row, "g1", 0, {"action": "call", "name": "sys.ask_missing_info",
                                              "arguments": {"tool_name": "sms.send", "params": ["content"]}})
        self.audit(self.write_bundle([example]))  # Does not raise.

    def test_audit_output_must_be_a_new_file(self):
        row = self.add_row("train_0001", "g1", [], [])
        example = self.example(row, "g1", 0, {"action": "finish"})
        audited = self.audit(self.write_bundle([example]))
        output_path = self.root / "audited.json"
        write_audited_bundle(output_path, audited)
        with self.assertRaises(PipelineError):
            write_audited_bundle(output_path, audited)

    def test_failed_write_leaves_no_partial_output_for_a_rerun(self):
        row = self.add_row("train_0001", "g1", [], [])
        example = self.example(row, "g1", 0, {"action": "finish"})
        audited = self.audit(self.write_bundle([example]))
        output_path = self.root / "audited.json"
        with patch("lifemate.example_audit.sync_write", side_effect=OSError("disk full")):
            with self.assertRaises(PipelineError):
                write_audited_bundle(output_path, audited)
        self.assertFalse(output_path.exists())
        # A rerun with the same --output must succeed once the failure clears.
        write_audited_bundle(output_path, audited)

    def test_write_failure_cleanup_never_deletes_a_different_file_at_the_same_path(self):
        row = self.add_row("train_0001", "g1", [], [])
        example = self.example(row, "g1", 0, {"action": "finish"})
        audited = self.audit(self.write_bundle([example]))
        output_path = self.root / "audited.json"

        def swap_then_fail(stream, content):
            # Simulate another process replacing this exact path with a
            # different, complete file between our create and our write.
            stream.close()
            output_path.unlink()
            output_path.write_text("someone else's bundle", encoding="utf-8")
            raise OSError("disk full")

        with patch("lifemate.example_audit.sync_write", side_effect=swap_then_fail):
            with self.assertRaises(PipelineError):
                write_audited_bundle(output_path, audited)
        # The cleanup must leave the replacement alone: it is not the file this
        # call created, even though it sits at the same pathname.
        self.assertEqual(output_path.read_text(encoding="utf-8"), "someone else's bundle")
