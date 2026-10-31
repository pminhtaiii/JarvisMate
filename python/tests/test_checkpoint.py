import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from lifemate.artifacts import RunStore
from lifemate.checkpoint import read_checkpoint
from lifemate.contracts import PipelineError, SampleOutcome
from lifemate.provenance import execution_identity
from support import Fixture


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.close)
        self.store = RunStore(self.fx.config())
        self.store.selected({"selected_ids": ["train_0001"], "dataset_sha256": "dataset",
                             "catalog_sha256": "catalog"}, {})
        self.row = {"id": "train_0001", "tool_calls": [], "state_hash": "a" * 64}

    def test_invalid_resume_provenance_is_an_input_error(self):
        for value in (None, "invalid", [], 1):
            with self.subTest(value=value):
                self.store.manifest["resume"] = value
                self.store.save()
                with self.assertRaises(PipelineError) as caught:
                    read_checkpoint(self.store.directory, self.store.manifest, allow_mixed=True)
                self.assertEqual((caught.exception.code, caught.exception.stage), ("INPUT_INVALID", "resume"))

    def test_invalid_prediction_has_resume_context_and_preserves_cause(self):
        for row in ({}, self.row | {"state_hash": "bad"}, self.row | {"tool_calls": [{}]}):
            with self.subTest(row=row):
                self.store.partial_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
                with self.assertRaises(PipelineError) as caught:
                    read_checkpoint(self.store.directory, self.store.manifest)
                self.assertEqual((caught.exception.code, caught.exception.stage), ("INPUT_INVALID", "resume"))
                self.assertIsInstance(caught.exception.__cause__, PipelineError)
                self.assertEqual(caught.exception.__cause__.code, "OUTPUT_IO")

    def test_valid_checkpoint_is_unchanged(self):
        self.store.append(SampleOutcome("train_0001", "completed", 0.1, 1, "finish", result=self.row))
        rows, _, provenance = read_checkpoint(self.store.directory, self.store.manifest)
        self.assertEqual(rows, [self.row])
        self.assertFalse(provenance["development_composite"])

    def test_different_effective_prompt_requires_mixed_resume(self):
        self.store.append(SampleOutcome("train_0001", "completed", 0.1, 1, "finish", result=self.row))
        current = self.store.manifest | {"effective_prompt": {"profile": {"profile": "precise-v1"}}}
        with self.assertRaises(PipelineError):
            read_checkpoint(self.store.directory, current)
        rows, _, provenance = read_checkpoint(self.store.directory, current, allow_mixed=True)
        self.assertTrue(provenance["development_composite"])
        self.assertIn("effective_prompt", provenance["configuration_differences"])

    def test_example_overhead_tokens_alone_does_not_require_mixed_resume(self):
        # The source run measured this derived value after its planner loaded;
        # a fresh resuming run sets effective_prompt before any model load.
        self.store.manifest["effective_prompt"] = {
            "profile": {"profile": "baseline"}, "bundle": {"bundle_sha256": "x"},
            "few_shot_token_budget": 1024, "example_overhead_tokens": 12}
        self.store.save()
        self.store.append(SampleOutcome("train_0001", "completed", 0.1, 1, "finish", result=self.row))
        current = self.store.manifest | {"effective_prompt": {
            "profile": {"profile": "baseline"}, "bundle": {"bundle_sha256": "x"},
            "few_shot_token_budget": 1024}}
        rows, _, provenance = read_checkpoint(self.store.directory, current)
        self.assertEqual(rows, [self.row])
        self.assertFalse(provenance["development_composite"])

    def test_mixed_protocol_resume_is_rejected_even_when_mixed_resume_is_allowed(self):
        self.store.append(SampleOutcome("train_0001", "completed", 0.1, 1, "finish", result=self.row))
        current = self.store.manifest | {"planner_protocol": "qwen-native-v1"}
        for allow_mixed in (False, True):
            with self.subTest(allow_mixed=allow_mixed):
                with self.assertRaises(PipelineError) as caught:
                    read_checkpoint(self.store.directory, current, allow_mixed=allow_mixed)
                self.assertIn("planner_protocol", str(caught.exception))

    def test_pre_protocol_manifest_counts_as_structured(self):
        del self.store.manifest["planner_protocol"]
        self.store.save()
        self.store.append(SampleOutcome("train_0001", "completed", 0.1, 1, "finish", result=self.row))
        structured = self.store.manifest | {"planner_protocol": "structured-v1"}
        rows, _, provenance = read_checkpoint(self.store.directory, structured)
        self.assertEqual((rows, provenance["development_composite"]), ([self.row], False))
        with self.assertRaises(PipelineError):
            read_checkpoint(self.store.directory, structured | {"planner_protocol": "qwen-native-v1"},
                            allow_mixed=True)

    def test_changed_chat_template_changes_identity_and_requires_mixed_resume(self):
        weights = self.fx.root / "native-weights"
        weights.mkdir()
        config_path = weights / "tokenizer_config.json"
        config_path.write_text(json.dumps({"chat_template": "{{ v1 }}"}), encoding="utf-8")
        config = replace(self.store.config, planner_model=weights)
        self.store.manifest["execution_identity"] = execution_identity(config)
        self.store.save()
        self.store.append(SampleOutcome("train_0001", "completed", 0.1, 1, "finish", result=self.row))
        config_path.write_text(json.dumps({"chat_template": "{{ v2 }}"}), encoding="utf-8")
        current = self.store.manifest | {"execution_identity": execution_identity(config)}
        with self.assertRaises(PipelineError):
            read_checkpoint(self.store.directory, current)
        _, _, provenance = read_checkpoint(self.store.directory, current, allow_mixed=True)
        self.assertIn("execution_identity", provenance["configuration_differences"])
        self.assertTrue(provenance["development_composite"])

    def test_tokenizers_version_change_requires_recomputation(self):
        with patch("lifemate.provenance.version", return_value="old"):
            self.store.manifest["execution_identity"] = execution_identity(self.store.config)
        self.store.save()
        with patch("lifemate.provenance.version", side_effect=lambda name: "new" if name == "tokenizers" else "old"):
            current = self.store.manifest | {"execution_identity": execution_identity(self.store.config)}
        self.assertEqual(current["execution_identity"]["packages"]["tokenizers"], "new")
        with self.assertRaises(PipelineError) as caught:
            read_checkpoint(self.store.directory, current)
        self.assertEqual(caught.exception.code, "INPUT_INVALID")
