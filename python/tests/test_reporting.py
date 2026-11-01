"""reporting.py: offline readers, distributions and report/comparison building (T009-T010)."""
from __future__ import annotations

import json
import shutil
import unittest

from lifemate.artifacts import RunStore
from lifemate.contracts import PipelineError, SampleOutcome
from lifemate.jsonio import digest
from lifemate.prompting import PROTOCOL_PROMPTS
from lifemate.reporting import (
    build_comparison, build_report, distribution, nearest_rank, validate_comparison_output, write_comparison,
    write_report,
)
from support import Fixture


def outcome(sample_id, status="completed", elapsed=1.0, steps=1, stop_reason="finish"):
    return SampleOutcome(sample_id, status, elapsed, steps, stop_reason,
                         result={"id": sample_id, "tool_calls": [], "state_hash": "a" * 64})


class DistributionTests(unittest.TestCase):
    def test_empty_population_is_null_not_zero(self):
        dist = distribution([])
        self.assertEqual(dist["count"], 0)
        self.assertIsNone(dist["p50"])
        self.assertIsNone(dist["max"])

    def test_nearest_rank_matches_a_known_example(self):
        values = [float(i) for i in range(1, 11)]  # 1..10
        self.assertEqual(nearest_rank(values, 0.50), 5.0)
        self.assertEqual(nearest_rank(values, 0.95), 10.0)

    def test_small_sample_flags_descriptive_tails(self):
        dist = distribution([1.0, 2.0, 3.0])
        self.assertTrue(dist["p95_descriptive_tail"])
        self.assertTrue(dist["p99_descriptive_tail"])

    def test_missing_values_are_excluded_not_filled_with_zero(self):
        dist = distribution([1.0, None, 3.0])
        self.assertEqual(dist["count"], 2)
        self.assertEqual(dist["max"], 3.0)


class RunFixture(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture(3)
        self.addCleanup(self.fx.close)

    def metadata(self, ids):
        return {"selected_ids": ids, "coverage_scope": "subset",
                "dataset_sha256": "d", "catalog_sha256": "c"}

    def make_run(self, ids=None, run_dir=None):
        ids = ids or [r["id"] for r in self.fx.rows]
        store = RunStore(self.fx.config(run_dir=run_dir or self.fx.root / "run"))
        store.selected(self.metadata(ids), {})
        return store

    def evaluation_payload(self, store, rows, selected_ids=None):
        prediction_path = store.final_path if store.final_path.exists() else store.partial_path
        return {"evaluation_schema_version": 1, "run_id": store.run_id,
                "prediction_sha256": digest(prediction_path),
                "selected_ids": selected_ids or list(store.manifest["selected_ids"]),
                "evaluator": {"name": "test"}, "rows": rows}

    def write_evaluation(self, payload, name="eval.json"):
        path = self.fx.root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path


class ReportTests(RunFixture):
    def test_small_population_report(self):
        store = self.make_run(ids=["train_0001"])
        store.append(outcome("train_0001"), measurements={"spans": [], "generations": []},
                     full_attempt_seconds=1.5)
        store.finish()
        report = build_report(store.directory)
        self.assertEqual(report["counts"]["selected"], 1)
        self.assertEqual(report["counts"]["executed_completed"], 1)
        self.assertEqual(report["timing"]["sample_total_seconds"]["count"], 1)
        self.assertEqual(report["timing"]["sample_total_seconds"]["p50"], 1.5)

    def test_empty_population_report_has_null_distributions_not_zero(self):
        store = self.make_run(ids=["train_0001"])
        self.assertEqual(store.manifest["not_started_ids"], ["train_0001"])
        report = build_report(store.directory)
        self.assertEqual(report["counts"]["not_started"], 1)
        self.assertEqual(report["timing"]["sample_total_seconds"]["count"], 0)
        self.assertIsNone(report["timing"]["sample_total_seconds"]["p50"])

    def test_unknown_manifest_schema_version_rejected(self):
        store = self.make_run(ids=["train_0001"])
        store.manifest["schema_version"] = 999
        store.save()
        with self.assertRaises(PipelineError):
            build_report(store.directory)

    def test_invalid_artifact_missing_run_dir_rejected(self):
        with self.assertRaises(PipelineError):
            build_report(self.fx.root / "does-not-exist")

    def test_duplicate_sample_id_across_samples_and_failures_rejected(self):
        store = self.make_run(ids=["train_0001"])
        store.append(outcome("train_0001"))
        store.manifest["failures"].append({"id": "train_0001", "error": {"code": "PLANNER_ERROR"},
                                           "measurements": None, "full_attempt_seconds": None,
                                           "agent_loop": None})
        store.save()
        with self.assertRaises(PipelineError):
            build_report(store.directory)

    def test_manifest_sample_without_a_matching_prediction_row_is_rejected(self):
        store = self.make_run(ids=["train_0001"])
        # A damaged manifest claims a completed, timed sample, but its prediction
        # journal was never written for it.
        store.manifest["samples"].append({"id": "train_0001", "status": "completed", "elapsed": 1.0,
                                          "steps": 1, "timings": {}, "stop_reason": "finish",
                                          "source": "executed", "measurements": None, "full_attempt_seconds": 1.0})
        store.manifest["completed_ids"].append("train_0001")
        store.manifest["not_started_ids"] = []
        store.save()
        with self.assertRaises(PipelineError):
            build_report(store.directory)

    def test_incomplete_run_with_a_failure_still_reports(self):
        store = self.make_run(ids=["train_0001", "train_0002", "train_0003"])
        store.append(outcome("train_0001"), full_attempt_seconds=1.0)
        store.fail({"code": "PLANNER_ERROR", "stage": "planner", "message": "x"}, "train_0002",
                  full_attempt_seconds=2.0)
        report = build_report(store.directory)
        self.assertEqual(report["run_status"], "failed")
        self.assertEqual(report["counts"]["failed"], 1)
        self.assertEqual(report["counts"]["not_started"], 1)
        self.assertEqual(report["counts"]["executed_completed"], 1)

    def test_imported_rows_are_counted_but_excluded_from_current_run_timing(self):
        source = self.make_run(ids=["train_0001"])
        source.append(outcome("train_0001"), measurements={"spans": [], "generations": []},
                      full_attempt_seconds=3.0)
        target = RunStore(self.fx.config(run_dir=self.fx.root / "run-2"))
        target.selected(self.metadata(["train_0001"]), {})
        target.restore(source.directory)
        report = build_report(target.directory)
        self.assertEqual(report["counts"]["imported"], 1)
        self.assertEqual(report["counts"]["executed_completed"], 0)
        self.assertEqual(report["timing"]["sample_total_seconds"]["count"], 0)

    def test_imported_rows_are_excluded_from_stage_and_token_aggregation(self):
        measurements = {"spans": [
            {"stage": "tool_call", "index": 0, "parent_stage": None, "start_offset": 0.0,
             "end_offset": 9.0, "duration": 9.0, "status": "completed", "lower_bound_duration": None,
             "unavailable_reason": None}],
            "generations": [{"role": "planner_action", "index": 0, "seconds": 1.0, "input_tokens": 1,
                             "output_tokens": 100, "rate": 100.0, "stop_reason": "eos"}]}
        source = self.make_run(ids=["train_0001"])
        source.append(outcome("train_0001"), measurements=measurements, full_attempt_seconds=3.0)
        target = RunStore(self.fx.config(run_dir=self.fx.root / "run-2"))
        target.selected(self.metadata(["train_0001"]), {})
        target.restore(source.directory)
        report = build_report(target.directory)
        self.assertEqual(report["stages"]["tool_call"]["per_sample_total"]["count"], 0)
        self.assertEqual(report["tokens"]["planner_action"]["eligible_count"], 0)

    def test_full_total_overrun_after_loop_success_is_flagged_but_stays_completed(self):
        store = self.make_run(ids=["train_0001"])
        store.append(outcome("train_0001"), full_attempt_seconds=31.0)
        report = build_report(store.directory)
        self.assertEqual(report["counts"]["known_total_over_or_at_30s"], 1)
        self.assertEqual(store.manifest["samples"][0]["status"], "completed")

    def test_stage_distribution_separates_per_sample_total_from_per_invocation(self):
        store = self.make_run(ids=["train_0001"])
        measurements = {"spans": [
            {"stage": "tool_call", "index": 0, "parent_stage": None, "start_offset": 0.0,
             "end_offset": 1.0, "duration": 1.0, "status": "completed", "lower_bound_duration": None,
             "unavailable_reason": None},
            {"stage": "tool_call", "index": 1, "parent_stage": None, "start_offset": 1.0,
             "end_offset": 2.5, "duration": 1.5, "status": "completed", "lower_bound_duration": None,
             "unavailable_reason": None},
        ], "generations": []}
        store.append(outcome("train_0001"), measurements=measurements, full_attempt_seconds=2.5)
        report = build_report(store.directory)
        tool_call = report["stages"]["tool_call"]
        self.assertEqual(tool_call["per_sample_total"]["count"], 1)
        self.assertEqual(tool_call["per_sample_total"]["max"], 2.5)
        self.assertEqual(tool_call["per_invocation"]["count"], 2)
        self.assertEqual(tool_call["per_invocation"]["max"], 1.5)

    def test_token_rate_is_weighted_not_a_mean_of_individual_rates(self):
        store = self.make_run(ids=["train_0001"])
        measurements = {"spans": [], "generations": [
            {"role": "planner_action", "index": 0, "seconds": 1.0, "input_tokens": 1,
             "output_tokens": 10, "rate": 10.0, "stop_reason": "eos"},
            {"role": "planner_action", "index": 1, "seconds": 4.0, "input_tokens": 1,
             "output_tokens": 4, "rate": 1.0, "stop_reason": "eos"},
        ]}
        store.append(outcome("train_0001"), measurements=measurements, full_attempt_seconds=5.0)
        report = build_report(store.directory)
        # Aggregate = sum(tokens)/sum(time) = 14/5 = 2.8, not mean(10, 1) = 5.5.
        self.assertAlmostEqual(report["tokens"]["planner_action"]["tokens_per_second"], 2.8)

    def test_token_rate_overflow_is_null_not_infinite(self):
        store = self.make_run(ids=["train_0001"])
        measurements = {"spans": [], "generations": [
            {"role": "planner_action", "index": 0, "seconds": 1e-300, "input_tokens": 1,
             "output_tokens": 10**18, "rate": None, "stop_reason": "eos"}]}
        store.append(outcome("train_0001"), measurements=measurements, full_attempt_seconds=1.0)
        # jsonio rejects non-finite values; a null rate must not break report writing.
        report = build_report(store.directory)
        self.assertIsNone(report["tokens"]["planner_action"]["tokens_per_second"])
        write_report(store.directory, report)

    def test_unterminated_final_journal_row_does_not_block_reporting(self):
        store = self.make_run(ids=["train_0001", "train_0002"])
        store.append(outcome("train_0001"), full_attempt_seconds=1.0)
        with store.partial_path.open("a", encoding="utf-8") as stream:
            stream.write('{"id": "train_0002", "tool_calls": []')  # No closing brace/newline.
        report = build_report(store.directory)
        self.assertEqual(report["counts"]["executed_completed"], 1)

    def test_report_regeneration_is_allowed(self):
        store = self.make_run(ids=["train_0001"])
        store.append(outcome("train_0001"), full_attempt_seconds=1.0)
        write_report(store.directory, build_report(store.directory))
        write_report(store.directory, build_report(store.directory))
        self.assertTrue((store.directory / "report.json").exists())
        self.assertTrue((store.directory / "report.md").exists())

    def test_no_model_or_environment_access_is_required(self):
        store = self.make_run(ids=["train_0001"])
        store.append(outcome("train_0001"), full_attempt_seconds=1.0)
        build_report(store.directory)  # Reads only durable files on disk.


class EvaluationTests(RunFixture):
    def test_empty_gold_score_is_accepted_independent_of_hash_match(self):
        store = self.make_run(ids=["train_0001"])
        store.append(outcome("train_0001"))
        store.finish()
        evaluation_path = self.write_evaluation(self.evaluation_payload(store, [
            {"id": "train_0001", "gold_empty": True, "sample_score": 1.0, "state_hash_match": False},
        ]))
        report = build_report(store.directory, evaluation_path)
        self.assertEqual(report["correctness"]["mean_sample_score_diagnostic"], 1.0)
        self.assertTrue(report["correctness"]["full_coverage"])

    def test_unknown_evaluation_schema_version_rejected(self):
        store = self.make_run(ids=["train_0001"])
        store.append(outcome("train_0001"))
        store.finish()
        payload = self.evaluation_payload(store, [])
        payload["evaluation_schema_version"] = 2
        with self.assertRaises(PipelineError):
            build_report(store.directory, self.write_evaluation(payload))

    def test_evaluation_for_a_different_run_is_rejected(self):
        store = self.make_run(ids=["train_0001"])
        store.append(outcome("train_0001"))
        store.finish()
        payload = self.evaluation_payload(store, [])
        payload["run_id"] = "a-different-run"
        with self.assertRaises(PipelineError):
            build_report(store.directory, self.write_evaluation(payload))

    def test_evaluation_with_a_stale_prediction_hash_is_rejected(self):
        store = self.make_run(ids=["train_0001"])
        store.append(outcome("train_0001"))
        store.finish()
        payload = self.evaluation_payload(store, [])
        payload["prediction_sha256"] = "0" * 64
        with self.assertRaises(PipelineError):
            build_report(store.directory, self.write_evaluation(payload))

    def test_out_of_range_sample_score_rejected(self):
        store = self.make_run(ids=["train_0001"])
        store.append(outcome("train_0001"))
        store.finish()
        payload = self.evaluation_payload(store, [
            {"id": "train_0001", "gold_empty": False, "sample_score": 1.5},
        ])
        with self.assertRaises(PipelineError):
            build_report(store.directory, self.write_evaluation(payload))

    def test_duplicate_or_unknown_row_ids_rejected(self):
        store = self.make_run(ids=["train_0001"])
        store.append(outcome("train_0001"))
        store.finish()
        cases = (
            [{"id": "train_0001", "gold_empty": False, "sample_score": 0.5},
             {"id": "train_0001", "gold_empty": False, "sample_score": 0.5}],
            [{"id": "unknown", "gold_empty": False, "sample_score": 0.5}],
        )
        for rows in cases:
            with self.subTest(rows=rows):
                payload = self.evaluation_payload(store, rows)
                with self.assertRaises(PipelineError):
                    build_report(store.directory, self.write_evaluation(payload))

    def test_evaluation_row_outside_its_own_declared_selection_is_rejected(self):
        store = self.make_run(ids=["train_0001", "train_0002"])
        store.append(outcome("train_0001"))
        store.append(outcome("train_0002"))
        store.finish()
        # train_0002 is part of the run's full selection but not of this
        # evaluation's own narrower selected_ids; it must not score anyway.
        payload = self.evaluation_payload(store, [
            {"id": "train_0002", "gold_empty": False, "sample_score": 0.5}], selected_ids=["train_0001"])
        with self.assertRaises(PipelineError):
            build_report(store.directory, self.write_evaluation(payload))

    def test_missing_evaluation_defaults_correctness_to_not_evaluated(self):
        store = self.make_run(ids=["train_0001"])
        store.append(outcome("train_0001"))
        report = build_report(store.directory)
        self.assertEqual(report["correctness"]["status"], "not_evaluated")


class CompareRunsTests(RunFixture):
    def two_runs(self):
        baseline = self.make_run(ids=["train_0001", "train_0002"], run_dir=self.fx.root / "baseline")
        baseline.append(outcome("train_0001"), full_attempt_seconds=10.0)
        baseline.append(outcome("train_0002"), full_attempt_seconds=12.0)
        candidate = RunStore(self.fx.config(run_dir=self.fx.root / "candidate"))
        candidate.selected(self.metadata(["train_0001", "train_0002"]), {})
        candidate.append(outcome("train_0001"), full_attempt_seconds=5.0)
        candidate.append(outcome("train_0002"), full_attempt_seconds=6.0)
        return baseline, candidate

    def test_harness_factor_with_matching_identity_builds_a_comparison(self):
        baseline, candidate = self.two_runs()
        comparison = build_comparison(baseline.directory, candidate.directory, "harness")
        self.assertTrue(comparison["acceptance"]["harness"]["p95_latency_improved"])
        self.assertEqual(comparison["paired"]["rows"][0]["id"], "train_0001")
        self.assertEqual(comparison["paired"]["delta_total_seconds"]["count"], 2)

    def test_incompatible_factor_identity_is_rejected(self):
        baseline, candidate = self.two_runs()
        candidate.manifest["seed"] = baseline.manifest["seed"] + 1
        candidate.save()
        with self.assertRaises(PipelineError):
            build_comparison(baseline.directory, candidate.directory, "harness")

    def test_instructions_factor_requires_identical_execution_code(self):
        baseline, candidate = self.two_runs()
        candidate.manifest["execution_identity"]["code"] = {"different": "hash"}
        candidate.save()
        with self.assertRaises(PipelineError):
            build_comparison(baseline.directory, candidate.directory, "instructions")

    def test_mixed_resume_run_cannot_support_acceptance_comparison(self):
        baseline, candidate = self.two_runs()
        candidate.manifest["resume"] = {"development_composite": True}
        candidate.save()
        with self.assertRaises(PipelineError):
            build_comparison(baseline.directory, candidate.directory, "harness")

    def test_mismatched_evaluation_rejected_alongside_comparison(self):
        baseline, candidate = self.two_runs()
        with self.assertRaises(PipelineError):
            build_comparison(baseline.directory, candidate.directory, "harness",
                             baseline_evaluation=self.fx.root / "missing.json")

    def test_comparison_output_overlapping_a_source_run_is_rejected(self):
        baseline, candidate = self.two_runs()
        baseline_manifest = json.loads(baseline.manifest_path.read_text(encoding="utf-8"))
        candidate_manifest = json.loads(candidate.manifest_path.read_text(encoding="utf-8"))
        with self.assertRaises(PipelineError):
            validate_comparison_output(baseline.directory, baseline_manifest, candidate_manifest,
                                       baseline.directory, candidate.directory)

    def test_comparison_output_under_data_root_is_rejected(self):
        baseline, candidate = self.two_runs()
        baseline_manifest = json.loads(baseline.manifest_path.read_text(encoding="utf-8"))
        candidate_manifest = json.loads(candidate.manifest_path.read_text(encoding="utf-8"))
        with self.assertRaises(PipelineError):
            validate_comparison_output(self.fx.data / "nested", baseline_manifest, candidate_manifest,
                                       baseline.directory, candidate.directory)

    def test_comparison_rejects_a_candidate_from_a_different_dataset(self):
        baseline, candidate = self.two_runs()
        candidate.manifest["dataset_sha256"] = "different"
        candidate.save()
        with self.assertRaises(PipelineError):
            build_comparison(baseline.directory, candidate.directory, "harness")

    def test_not_started_candidate_is_regression_or_incomplete(self):
        baseline = self.make_run(ids=["train_0001", "train_0002"], run_dir=self.fx.root / "baseline")
        baseline.append(outcome("train_0001"), full_attempt_seconds=10.0)
        baseline.append(outcome("train_0002"), full_attempt_seconds=12.0)
        candidate = RunStore(self.fx.config(run_dir=self.fx.root / "candidate"))
        candidate.selected(self.metadata(["train_0001", "train_0002"]), {})
        candidate.append(outcome("train_0001"), full_attempt_seconds=5.0)
        comparison = build_comparison(baseline.directory, candidate.directory, "harness")
        row = next(r for r in comparison["paired"]["rows"] if r["id"] == "train_0002")
        self.assertEqual(row["candidate_outcome"], "not_started")
        self.assertTrue(row["regression_or_incomplete"])

    def test_final_budget_not_ready_when_a_run_has_imported_rows(self):
        baseline, candidate = self.two_runs()
        imported = RunStore(self.fx.config(run_dir=self.fx.root / "candidate-imported"))
        imported.selected(self.metadata(["train_0001", "train_0002"]), {})
        imported.restore(candidate.directory)
        comparison = build_comparison(baseline.directory, imported.directory, "harness")
        self.assertFalse(comparison["acceptance"]["final_budget"]["candidate_ready"])

    def test_harness_correctness_preserved_requires_full_evaluator_coverage(self):
        baseline, candidate = self.two_runs()
        baseline.finish()
        candidate.finish()
        # Only one of the two selected IDs is scored on each side; no regression is
        # observed in that partial overlap, but coverage is incomplete.
        baseline_eval = self.write_evaluation(self.evaluation_payload(
            baseline, [{"id": "train_0001", "gold_empty": False, "sample_score": 1.0}]), "baseline_eval.json")
        candidate_eval = self.write_evaluation(self.evaluation_payload(
            candidate, [{"id": "train_0001", "gold_empty": False, "sample_score": 1.0}]), "candidate_eval.json")
        comparison = build_comparison(baseline.directory, candidate.directory, "harness",
                                      baseline_evaluation=baseline_eval, candidate_evaluation=candidate_eval)
        harness = comparison["acceptance"]["harness"]
        self.assertFalse(harness["full_evaluator_coverage"])
        self.assertFalse(harness["correctness_preserved"])
        self.assertFalse(harness["single_pair_eligible"])

    def test_prompt_recommendation_requires_known_latency(self):
        baseline = self.make_run(ids=["train_0001"], run_dir=self.fx.root / "baseline")
        baseline.manifest["effective_prompt"] = {
            "profile": {"profile": "baseline", "version": "v1", "sha256": "h1"},
            "bundle": None, "few_shot_token_budget": None}
        baseline.save()
        baseline.append(outcome("train_0001"))  # No full_attempt_seconds: p95 stays unknown.
        baseline.finish()
        candidate = RunStore(self.fx.config(run_dir=self.fx.root / "candidate"))
        candidate.selected(self.metadata(["train_0001"]), {})
        candidate.manifest["effective_prompt"] = {
            "profile": {"profile": "precise-v1", "version": "v2", "sha256": "h2"},
            "bundle": None, "few_shot_token_budget": None}
        candidate.save()
        candidate.append(outcome("train_0001"))
        candidate.finish()
        baseline_eval = self.write_evaluation(self.evaluation_payload(
            baseline, [{"id": "train_0001", "gold_empty": False, "sample_score": 0.5}]), "baseline_eval.json")
        candidate_eval = self.write_evaluation(self.evaluation_payload(
            candidate, [{"id": "train_0001", "gold_empty": False, "sample_score": 0.9}]), "candidate_eval.json")
        comparison = build_comparison(baseline.directory, candidate.directory, "instructions",
                                      baseline_evaluation=baseline_eval, candidate_evaluation=candidate_eval)
        prompt = comparison["acceptance"]["prompt"]
        self.assertFalse(prompt["p95_latency_known"])
        self.assertFalse(prompt["default_automatic_recommendation"])

    def test_instructions_factor_requires_fixed_few_shot_configuration(self):
        baseline, candidate = self.two_runs()
        baseline.manifest["effective_prompt"] = {
            "profile": {"profile": "baseline", "version": "v1", "sha256": "h1"},
            "bundle": None, "few_shot_token_budget": None}
        baseline.save()
        candidate.manifest["effective_prompt"] = {
            "profile": {"profile": "precise-v1", "version": "v2", "sha256": "h2"},
            "bundle": {"bundle_sha256": "x", "example_count": 1, "example_ids": ["a"], "partition_sha256": "p"},
            "few_shot_token_budget": 1024}
        candidate.save()
        with self.assertRaises(PipelineError):
            build_comparison(baseline.directory, candidate.directory, "instructions")

    def test_few_shot_factor_requires_fixed_instruction_profile(self):
        baseline, candidate = self.two_runs()
        baseline.manifest["effective_prompt"] = {
            "profile": {"profile": "baseline", "version": "v1", "sha256": "h1"},
            "bundle": None, "few_shot_token_budget": None}
        baseline.save()
        candidate.manifest["effective_prompt"] = {
            "profile": {"profile": "precise-v1", "version": "v2", "sha256": "h2"},
            "bundle": {"bundle_sha256": "x", "example_count": 1, "example_ids": ["a"], "partition_sha256": "p"},
            "few_shot_token_budget": 1024}
        candidate.save()
        with self.assertRaises(PipelineError):
            build_comparison(baseline.directory, candidate.directory, "few-shot")

    def test_existing_factors_reject_a_protocol_change(self):
        # Otherwise an instruction-profile change would hide a protocol change.
        baseline, candidate = self.two_runs()
        baseline.manifest["effective_prompt"] = {
            "profile": {"profile": "precise-v1", "version": "v2", "sha256": "h2"},
            "bundle": None, "few_shot_token_budget": None}
        baseline.save()
        candidate.manifest["planner_protocol"] = "qwen-native-v1"
        candidate.manifest["effective_prompt"] = {
            "profile": {"profile": "baseline", "version": "n1", "sha256": "n1"},
            "bundle": None, "few_shot_token_budget": None}
        candidate.save()
        for factor in ("harness", "instructions", "few-shot"):
            with self.subTest(factor=factor):
                with self.assertRaises(PipelineError) as caught:
                    build_comparison(baseline.directory, candidate.directory, factor)
                self.assertIn("planner_protocol", str(caught.exception))

    def test_pre_protocol_manifest_compares_as_structured(self):
        baseline, candidate = self.two_runs()
        del baseline.manifest["planner_protocol"]
        baseline.save()
        self.assertEqual(build_comparison(baseline.directory, candidate.directory, "harness")["factor"], "harness")
        # The absent protocol means structured-v1, never "whatever the other run used".
        candidate.manifest["planner_protocol"] = "qwen-native-v1"
        candidate.save()
        with self.assertRaises(PipelineError) as caught:
            build_comparison(baseline.directory, candidate.directory, "harness")
        self.assertIn("planner_protocol", str(caught.exception))

    def test_unknown_planner_protocol_in_a_manifest_is_rejected(self):
        baseline, candidate = self.two_runs()
        for value in (None, "qwen-native-v2"):
            with self.subTest(value=value):
                for store in (baseline, candidate):
                    store.manifest["planner_protocol"] = value
                    store.save()
                with self.assertRaises(PipelineError) as caught:
                    build_comparison(baseline.directory, candidate.directory, "harness")
                self.assertIn("planner_protocol", str(caught.exception))

    def model_runs(self, baseline_protocol="structured-v1", candidate_protocol="qwen-native-v1"):
        baseline, candidate = self.two_runs()
        files = {"config.json": "c1", "model.safetensors": "w1", "tokenizer.json": "t1",
                 "tokenizer_config.json": "tc1", "chat_template.jinja": "j1"}
        for store, protocol in ((baseline, baseline_protocol), (candidate, candidate_protocol)):
            version, sha256 = PROTOCOL_PROMPTS[protocol]
            store.manifest.update(planner_protocol=protocol, prompt_version=version, prompt_sha256=sha256)
            store.manifest["effective_prompt"] = {"profile": {"profile": "baseline", "version": version, "sha256": sha256},
                                                  "bundle": None, "few_shot_token_budget": None}
            store.manifest["execution_identity"]["planner"] = {"path": "/models/base", "files": dict(files)}
            store.manifest["models"] = {"planner": {"dtype": "torch.float16", "native_protocol": (
                {"chat_template_sha256": "tpl"} if protocol == "qwen-native-v1" else None)}, "asr": None}
            store.save()
        return baseline, candidate

    def assert_rejected(self, baseline, candidate, factor, phrase):
        with self.assertRaises(PipelineError) as caught:
            build_comparison(baseline.directory, candidate.directory, factor)
        self.assertIn(phrase, str(caught.exception))

    def discard(self, *stores):
        for store in stores:
            shutil.rmtree(store.directory)

    def edit(self, store, change):
        change(store.manifest)
        store.save()

    def test_protocol_factor_accepts_only_the_protocol_change_and_stays_exploratory(self):
        baseline, candidate = self.model_runs()
        comparison = build_comparison(baseline.directory, candidate.directory, "protocol")
        self.assertEqual(set(comparison["acceptance"]), {"protocol", "final_budget"})
        verdict = comparison["acceptance"]["protocol"]
        self.assertEqual((verdict["promotion_status"], verdict["default_automatic_recommendation"]),
                         ("exploratory", False))

    def test_protocol_factor_rejects_any_other_difference(self):
        cases = [
            ("reversed direction", None, "structured-v1 baseline"),
            ("selection filter", lambda m: m.update(selection_filter=True), "selection filter"),
            ("precise profile", lambda m: m["effective_prompt"]["profile"].update(profile="precise-v1"),
             "baseline instruction policy"),
            ("example bundle", lambda m: m["effective_prompt"].update(bundle={"bundle_sha256": "x"}),
             "no examples"),
            ("changed weights", lambda m: m["execution_identity"]["planner"]["files"].update(
                {"model.safetensors": "w2"}), "identical planner checkpoint"),
            ("changed code", lambda m: m["execution_identity"].update(code={"other": "hash"}), "identical execution code"),
            ("changed dtype", lambda m: m["models"]["planner"].update(dtype="torch.float32"), "dtype"),
        ]
        for label, change, phrase in cases:
            with self.subTest(label):
                if change is None:
                    baseline, candidate = self.model_runs("qwen-native-v1", "structured-v1")
                else:
                    baseline, candidate = self.model_runs()
                    if label == "selection filter":
                        self.edit(baseline, change)
                    self.edit(candidate, change)
                self.assert_rejected(baseline, candidate, "protocol", phrase)
                self.discard(baseline, candidate)

    def test_planner_model_factor_accepts_only_changed_weights(self):
        baseline, candidate = self.model_runs("qwen-native-v1", "qwen-native-v1")
        self.edit(candidate, lambda m: m["execution_identity"]["planner"].update(
            path="/models/tuned", files=dict(m["execution_identity"]["planner"]["files"],
                                             **{"model.safetensors": "w2", "config.json": "c2"})))
        comparison = build_comparison(baseline.directory, candidate.directory, "planner-model")
        self.assertEqual(set(comparison["acceptance"]), {"planner-model", "final_budget"})
        self.assertFalse(comparison["acceptance"]["planner-model"]["default_automatic_recommendation"])
        # Existing factors still cannot compare changed planner weights.
        self.assert_rejected(baseline, candidate, "harness", "model identity")

    def test_planner_model_factor_rejects_any_other_difference(self):
        weights = lambda m: m["execution_identity"]["planner"]["files"].update({"model.safetensors": "w2"})
        cases = [
            ("unchanged weights", lambda m: None, "must change the planner weights"),
            ("tokenizer", lambda m: (weights(m), m["execution_identity"]["planner"]["files"].update(
                {"tokenizer.json": "t2"})), "identical tokenizer"),
            ("template file", lambda m: (weights(m), m["execution_identity"]["planner"]["files"].update(
                {"chat_template.jinja": "j2"})), "identical tokenizer"),
            ("loaded template", lambda m: (weights(m), m["models"]["planner"]["native_protocol"].update(
                chat_template_sha256="other")), "loaded chat template"),
            ("context budget", lambda m: (weights(m), m["limits"].update(context_tokens=8192)), "limits"),
            ("instruction policy", lambda m: (weights(m), m["effective_prompt"]["profile"].update(
                profile="precise-v1")), "baseline instruction policy"),
            ("packages", lambda m: (weights(m), m["execution_identity"].update(packages={"torch": "x"})),
             "identical ASR and packages"),
        ]
        for label, change, phrase in cases:
            with self.subTest(label):
                baseline, candidate = self.model_runs("qwen-native-v1", "qwen-native-v1")
                self.edit(candidate, change)
                self.assert_rejected(baseline, candidate, "planner-model", phrase)
                self.discard(baseline, candidate)
        baseline, candidate = self.model_runs("structured-v1", "structured-v1")
        self.edit(candidate, weights)
        self.assert_rejected(baseline, candidate, "planner-model", "native-protocol runs")

    def test_factor_comparison_with_an_unchanged_prompt_is_rejected(self):
        baseline, candidate = self.two_runs()
        identical = {"profile": {"profile": "baseline", "version": "v1", "sha256": "h1"},
                    "bundle": None, "few_shot_token_budget": None}
        baseline.manifest["effective_prompt"] = identical
        baseline.save()
        candidate.manifest["effective_prompt"] = dict(identical)
        candidate.save()
        with self.assertRaises(PipelineError):
            build_comparison(baseline.directory, candidate.directory, "instructions")

    def test_comparison_writes_json_and_markdown(self):
        baseline, candidate = self.two_runs()
        comparison = build_comparison(baseline.directory, candidate.directory, "harness")
        output_dir = self.fx.root / "comparison"
        output_dir.mkdir()
        write_comparison(output_dir, comparison)
        self.assertTrue((output_dir / "comparison.json").exists())
        self.assertTrue((output_dir / "comparison.md").exists())
