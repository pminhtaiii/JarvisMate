"""Frozen split, strict-prefix expansion, three-level audit and sealed preparation.

Controlled visible fixtures only: no ToolEnv, environment-file reads, tokenizer or
weights. The train_1696-like source is a labeled controlled mutation, not raw data.
"""
import json
import unittest

from lifemate.jsonio import dumps, loads
from lifemate.llm_training.audit import audit_expansion, load_organizer_validator, load_reviews
from lifemate.llm_training.config import content_hash, load_config
from lifemate.llm_training.corpus import (PreparationError, load_suite, prepare, seal_selection_policy,
                                          sealed_policy)
from lifemate.llm_training.config import DEFAULT_SELECTION_POLICY
from lifemate.llm_training.data import (DataContractError, expand_source, load_catalog, read_train,
                                        validate_split)
from lifemate.llm_training.storage import StorageError, read_jsonl, verify_seal, write_json
from llm_support import CATALOG, REPO, SuiteFixture


class DataFixture(unittest.TestCase):
    def setUp(self):
        self.fx = SuiteFixture()
        self.addCleanup(self.fx.close)
        self.train = self.fx.data / "train" / "train.jsonl"
        self.catalog = self.fx.data / "train" / "train_tools_catalog.json"
        self.sources = read_train(self.train)
        self.partition = validate_split(self.fx.split_manifest, self.train, self.catalog, self.sources, self.fx.expected)
        _, self.specs = load_catalog(self.catalog)
        self.schema_error = load_organizer_validator(REPO / "tools" / "train")

    def expansion(self, sample_id):
        source = next(s for s in self.sources if s.id == sample_id)
        return expand_source(source, self.partition, self.specs, {"protocol": "qwen3-native-next-action-v1"})

    def audited(self, sample_id, reviews=None):
        expansion = self.expansion(sample_id)
        return expansion, audit_expansion(expansion, self.specs, self.schema_error, reviews)


class SplitTests(DataFixture):
    def test_manifest_train_maps_to_fit_and_groups_stay_disjoint(self):
        self.assertEqual(len(self.partition["fit_ids"]), 8)
        self.assertEqual(self.partition["validation_ids"], ["train_0009", "train_0010"])
        self.assertEqual(self.partition["sources"]["train_0001"]["partition"], "fit")

    def test_identity_membership_and_group_drift_fail_without_resplitting(self):
        manifest = loads(self.fx.split_manifest.read_text(encoding="utf-8"))
        mutations = []
        changed = json.loads(json.dumps(manifest))
        changed["samples"][0]["partition"] = "validation"  # Identity no longer matches.
        mutations.append(changed)
        crossing = json.loads(json.dumps(manifest))
        crossing["samples"][1]["group"] = crossing["samples"][-1]["group"]
        body = {k: v for k, v in crossing.items() if k != "identity"}
        crossing["identity"] = content_hash(body)
        mutations.append(crossing)
        for index, mutated in enumerate(mutations):
            with self.subTest(index=index):
                self.fx.split_manifest.write_text(dumps(mutated), encoding="utf-8")
                expected = self.fx.expected if index == 0 else type(self.fx.expected)(
                    mutated["identity"], self.fx.expected.dataset_sha256, self.fx.expected.catalog_sha256,
                    self.fx.expected.counts, ())
                with self.assertRaises(DataContractError):
                    validate_split(self.fx.split_manifest, self.train, self.catalog, self.sources, expected)
        self.fx.split_manifest.unlink()
        with self.assertRaises(DataContractError):
            validate_split(self.fx.split_manifest, self.train, self.catalog, self.sources, self.fx.expected)

    def test_smoke_ids_must_remain_fit(self):
        expected = type(self.fx.expected)(self.fx.expected.identity, self.fx.expected.dataset_sha256,
                                          self.fx.expected.catalog_sha256, self.fx.expected.counts, ("train_0009",))
        with self.assertRaises(DataContractError):
            validate_split(self.fx.split_manifest, self.train, self.catalog, self.sources, expected)


class ExpansionTests(DataFixture):
    def test_strict_prefixes_both_final_types_and_no_future_results(self):
        rows = [c["row"] for c in self.expansion("train_0002")["candidates"]]
        self.assertEqual([r["target_type"] for r in rows], ["normal_call", "normal_call", "finish_after_calls"])
        for k, row in enumerate(rows):
            roles = [m["role"] for m in row["input"]["messages"]]
            self.assertEqual(roles.count("tool"), k)  # Only results j<k.
            rendered = dumps(row["input"])
            self.assertNotIn("FINAL_STATE_SENTINEL", rendered)
            self.assertNotIn("secret_gold", rendered)
            if k < 2:
                self.assertNotIn("SECRET_FUTURE_RESULT_SENTINEL", rendered)
        self.assertEqual(rows[2]["target"], {"role": "assistant", "content": "Đã kết thúc."})
        self.assertEqual(rows[0]["provenance"]["decision_index"], 0)
        initial = self.expansion("train_0001")["candidates"]
        self.assertEqual([c["row"]["target_type"] for c in initial], ["initial_finish"])
        self.assertEqual([m["role"] for m in initial[0]["row"]["input"]["messages"]], ["system", "user"])
        current = json.loads(rows[0]["input"]["messages"][-1]["content"])
        self.assertEqual(set(current), {"request", "context"})
        self.assertNotIn("audio", dumps(current))

    def test_terminal_ask_has_no_extra_final_and_continuation_is_quarantined(self):
        ask = self.expansion("train_0003")["candidates"]
        self.assertEqual([c["row"]["target_type"] for c in ask], ["normal_call", "ask_missing_info"])
        _, records = self.audited("train_0004")
        self.assertEqual([r["status"] for r in records], ["quarantined"])
        self.assertIn("TERMINAL_CONTINUATION", records[0]["reasons"])

    def test_row_identity_is_content_based_and_views_share_base_identity(self):
        first = self.expansion("train_0002")["candidates"][0]["row"]
        again = self.expansion("train_0002")["candidates"][0]["row"]
        self.assertEqual(first["row_id"], again["row_id"])
        self.assertEqual(first["provenance"]["view"], "clean")
        self.assertNotEqual(first["row_id"], first["provenance"]["base_row_id"])


class AuditTests(DataFixture):
    def test_train_1696_like_dependency_quarantine_keeps_earlier_rows(self):
        _, records = self.audited("train_0005")
        self.assertEqual([r["status"] for r in records], ["accepted", "accepted", "quarantined", "quarantined"])
        self.assertIn("UNGROUNDED_ID", records[2]["reasons"])
        self.assertIn("DEPENDENT_FINISH", records[3]["reasons"])
        self.assertEqual(records[2]["dependent_row_ids"], [records[3]["row_id"]])
        self.assertEqual(records[0]["acceptance_basis"], "organizer_gold_screened")

    def test_unsupported_history_and_malformed_pairs_are_visible_not_dropped(self):
        expansion, records = self.audited("train_0006")
        self.assertEqual(expansion["history_error"]["code"], "HISTORY_PAIR_UNSUPPORTED")
        self.assertTrue(all(r["status"] == "needs_review" for r in records))
        self.assertTrue(all(c["row"]["input"] is None for c in expansion["candidates"]))
        _, records = self.audited("train_0007")
        self.assertEqual([r["target_type"] for r in records], ["normal_call", "finish_after_calls"])
        self.assertTrue(all(r["status"] == "quarantined" and "PAIR_MISMATCH" in r["reasons"] for r in records))

    def test_critical_transaction_needs_matching_manual_review(self):
        expansion, records = self.audited("train_0008")
        self.assertEqual(records[0]["status"], "needs_review")
        self.assertIn("MANUAL_REVIEW_REQUIRED", records[0]["reasons"])
        self.assertEqual(records[1]["status"], "needs_review")  # Dependent finish stays pending.
        review = {"schema": "lifemate-native-manual-review-v1", "row_id": records[0]["row_id"], "decision": "accept",
                  "reviewer": "reviewer-1", "policy": "manual-v1", "evidence_paths": ["evidence.history[1]"],
                  "affected_slots": ["account_id", "amount"], "prefix_valid": True,
                  "original_target_sha256": records[0]["original_target_sha256"]}
        _, reviewed = self.audited("train_0008", load_reviews([review]))
        self.assertEqual((reviewed[0]["status"], reviewed[0]["acceptance_basis"], reviewed[0]["audit_level"]),
                         ("accepted", "manual_review", 3))
        self.assertEqual(reviewed[1]["status"], "accepted")
        stale = dict(review, original_target_sha256="0" * 64)
        _, ignored = self.audited("train_0008", load_reviews([stale]))
        self.assertEqual(ignored[0]["status"], "needs_review")  # A review cannot certify a different target.
        with self.assertRaises(ValueError):
            load_reviews([review, review])


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.fx = SuiteFixture()
        self.addCleanup(self.fx.close)
        self.config = load_config(self.fx.config_path)

    def test_sealed_suite_contains_only_accepted_fit_rows_and_all_audits(self):
        summary = prepare(self.config, self.fx.suite, expected=self.fx.expected)
        self.assertEqual(summary["status"], "sealed")
        verify_seal(self.fx.suite)
        fit = read_jsonl(self.fx.suite / "data" / "fit.clean.jsonl")
        audits = {r["row_id"]: r for r in read_jsonl(self.fx.suite / "data" / "quality-audit.jsonl")}
        self.assertTrue(fit)
        self.assertTrue(all(r["provenance"]["partition"] == "fit" and audits[r["row_id"]]["status"] == "accepted"
                            for r in fit))
        validation = read_jsonl(self.fx.suite / "data" / "validation.teacher-forced.jsonl")
        self.assertEqual({r["provenance"]["source_id"] for r in validation}, {"train_0009", "train_0010"})
        self.assertTrue(all(set(r) == {"schema", "row_id", "provenance", "input", "target", "target_type", "token_audit"}
                            for r in fit + validation))
        manifest = json.loads((self.fx.suite / "data" / "dataset-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["counts"]["rows"], len(audits))
        self.assertEqual(manifest["closed_loop_expected_sources"], 2)
        suite = load_suite(self.fx.suite)["suite"]
        self.assertNotIn(str(self.fx.root), json.dumps(suite["portable_paths"]))
        with self.assertRaises(StorageError):
            write_json(self.fx.suite / "data" / "extra.json", {})  # Sealed core is immutable.
        (self.fx.suite / "data" / "fit.clean.jsonl").write_text("tampered\n", encoding="utf-8")
        with self.assertRaises(PreparationError):
            load_suite(self.fx.suite)

    def test_missing_proof_blocks_export_and_draft_is_never_usable(self):
        fx = SuiteFixture(proof=False)
        self.addCleanup(fx.close)
        config = load_config(fx.config_path)
        with self.assertRaises(PreparationError) as caught:
            prepare(config, fx.suite, expected=fx.expected)
        self.assertEqual(caught.exception.status, "blocked_dependency")
        self.assertFalse(fx.suite.exists())
        self.assertEqual(prepare(config, fx.suite, draft=True, expected=fx.expected)["status"], "draft")
        with self.assertRaises(PreparationError):
            load_suite(fx.suite)
        with self.assertRaises(StorageError):
            prepare(config, fx.suite, draft=True, expected=fx.expected)  # Never overwrite a suite.

    def test_selection_policy_is_sealed_once_before_outcomes(self):
        prepare(self.config, self.fx.suite, expected=self.fx.expected)
        sealed = seal_selection_policy(self.fx.suite, DEFAULT_SELECTION_POLICY)
        self.assertEqual(sealed_policy(self.fx.suite)["policy_sha256"], sealed["policy_sha256"])
        with self.assertRaises(PreparationError):
            seal_selection_policy(self.fx.suite, DEFAULT_SELECTION_POLICY)
        partial = dict(DEFAULT_SELECTION_POLICY)
        partial.pop("tolerances")
        with self.assertRaises(ValueError):
            from lifemate.llm_training.config import validate_selection_policy
            validate_selection_policy(partial)


class CatalogFixtureTests(unittest.TestCase):
    def test_fixture_catalog_validates(self):
        from lifemate.dataset import validate_catalog
        self.assertIn("chat.send_message", validate_catalog(CATALOG))


if __name__ == "__main__":
    unittest.main()
