"""Closed-loop runner, native repair, teacher-forced and read-only comparison (E01/W02).

Controlled planners/environments only; no weights, ToolEnv package or replay.
"""
import json
import sys
import unittest
from collections import deque

from lifemate.adapters import qwen_native as qn
from lifemate.llm_training.config import DEFAULT_SELECTION_POLICY, load_config
from lifemate.llm_training.corpus import PreparationError, prepare, seal_selection_policy
from lifemate.llm_training.evaluation import run_closed_loop, run_teacher_forced
from lifemate.llm_training.reporting import compare, performance_decision
from lifemate.llm_training.storage import read_json, read_jsonl, write_json, write_jsonl
from llm_support import SuiteFixture, accept_fixture

FINISH = json.dumps({"action": "finish"})


def call(name, **arguments):
    return json.dumps({"action": "call", "name": name, "arguments": arguments}, ensure_ascii=False)


class Planner:
    metadata = {"parameter_count": 1, "controlled_test_only": True}

    def __init__(self, actions):
        self.actions, self.inputs = deque(actions), []

    def next_action(self, value, remaining):
        self.inputs.append(json.loads(json.dumps(value)))
        action = self.actions.popleft()
        if isinstance(action, Exception):
            raise action
        return action


class Environment:
    def __init__(self, sample_id):
        self.sample_id, self.calls = sample_id, []

    def call(self, name, arguments):
        self.calls.append({"name": name, "arguments": arguments})
        return {"ok": True, "contacts": [{"id": "c_lan", "name": "Lan"}]}

    def get_tool_calls(self):
        return list(self.calls)

    def get_state_hash(self):
        return "a" * 64


class Factory:
    metadata = {"directory": "controlled", "source_sha256": {}}

    def __init__(self):
        self.opened = []

    def __call__(self, split, sample_id, root):
        self.opened.append(sample_id)
        return Environment(sample_id)

    def schema_precheck(self, sample, name, arguments):
        return {"status": "valid", "error": None}


def rejected(code="NATIVE_JSON_INVALID", stop="eos", eos=True):
    record = qn.rejection_record(1, code, "<tool_call>\n{bad", stop_reason=stop, eos_observed=eos)
    return qn.NativeProposalRejected(record, full_output_sha256=qn.fingerprint(code, "<tool_call>\n{bad"))


class ClosedLoopTests(unittest.TestCase):
    def setUp(self):
        self.fx = SuiteFixture()
        self.addCleanup(self.fx.close)
        self.config = load_config(self.fx.config_path)
        prepare(self.config, self.fx.suite, expected=self.fx.expected)
        accept_fixture(self.config, self.fx.suite)

    def run_loop(self, actions, **options):
        self.factory, self.planner = Factory(), Planner(actions)
        return run_closed_loop(config=self.config, suite_dir=self.fx.suite, experiment="L0", mode="G",
                               planner=self.planner, runtime_loader=lambda c, d: self.factory,
                               model_identity={"training_status": "pretrained"}, **options)

    def test_requires_preregistered_policy(self):
        with self.assertRaises(PreparationError):
            self.run_loop([FINISH, FINISH])

    def test_missing_environment_assets_stop_before_runtime_or_planner(self):
        from lifemate.contracts import PipelineError
        seal_selection_policy(self.fx.suite, DEFAULT_SELECTION_POLICY)
        # Empty synthetic existence markers only; never access organizer state.
        for sid in ('train_0009','train_0010'):
            (self.fx.data/'train/train_environment'/sid/'state.json').unlink()
        with self.assertRaisesRegex(PipelineError,'ToolEnv'):
            self.run_loop([FINISH,FINISH],continue_on_error=True)
        self.assertEqual(self.factory.opened,[])
        self.assertEqual(self.planner.inputs,[])
        self.assertFalse((self.fx.suite/'evaluations').exists())

    def test_input_preflight_imports_runtime_but_does_not_open_environments(self):
        from lifemate.llm_training.evaluation import evaluation_input_preflight
        from lifemate.llm_training.corpus import load_suite
        factory = Factory()
        report = evaluation_input_preflight(self.config,partition=load_suite(self.fx.suite)['partition'],
            runtime_loader=lambda c,d:factory,input_mode='transcript')
        self.assertEqual((report['status'],report['expected'],report['prepared']),('ready',2,2))
        self.assertEqual(factory.opened,[])
        self.assertFalse(report['models_loaded'])
        self.assertFalse(report['environment_contents_read'])

    def test_missing_assets_block_cli_and_audio_pilot_before_model_loading(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from lifemate.contracts import PipelineError
        from lifemate.llm_training import cli,pilot
        seal_selection_policy(self.fx.suite,DEFAULT_SELECTION_POLICY)
        args=SimpleNamespace(experiment='L0',export=None,suite_dir=self.fx.suite,full_audio=False,
            protocol='closed_loop',mode='G',device='cuda',continue_on_error=False,trace_payloads=False)
        with patch('lifemate.llm_training.evaluation.evaluation_input_preflight',
                   side_effect=PipelineError('ASSET_MISSING','ToolEnv assets missing','preflight')), \
             patch('lifemate.adapters.planner.LocalPlanner') as planner, \
             patch('lifemate.adapters.asr.LocalASR') as asr, \
             patch('lifemate.llm_training.resources.validate_lock'):
            with self.assertRaisesRegex(PipelineError,'ToolEnv'):
                cli.evaluate(self.config,args)
            with self.assertRaisesRegex(PipelineError,'ToolEnv'):
                pilot.run_audio(self.config,self.fx.suite,experiment='L0',pilot=True)
            planner.assert_not_called()
            asr.assert_not_called()

    def test_complete_run_scores_all_sources_with_one_environment_each(self):
        seal_selection_policy(self.fx.suite, DEFAULT_SELECTION_POLICY)
        summary = self.run_loop([call("contacts.search", query="Lan"), FINISH, FINISH])
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(self.factory.opened, ["train_0009", "train_0010"])
        directory = self.fx.suite / "evaluations" / summary["evaluation_dir"].split("\\")[-1].split("/")[-1]
        self.assertTrue((directory / "predictions.jsonl").is_file())
        self.assertEqual(summary["tool_call_f1"]["value"], 1.0)
        prompts = json.dumps(self.planner.inputs, ensure_ascii=False)
        self.assertNotIn("FINAL_STATE_SENTINEL", prompts)
        self.assertNotIn("label", prompts)

    def test_fail_fast_marks_remaining_not_attempted_and_continue_scores_failures(self):
        seal_selection_policy(self.fx.suite, DEFAULT_SELECTION_POLICY)
        summary = self.run_loop([rejected("NATIVE_TRUNCATED", "max_tokens", False)])
        self.assertEqual((summary["status"], summary["counts"]["not_attempted"]), ("partial", 1))
        self.assertIsNone(summary["tool_call_f1"]["value"])
        directory = self.fx.suite / "evaluations"
        partial = [p for p in directory.iterdir() if (p / "predictions.partial.jsonl").is_file()]
        self.assertEqual(len(partial), 1)
        outcome = read_jsonl(partial[0] / "outcomes.jsonl")[0]
        self.assertEqual((outcome["error_code"], outcome["attempted_calls"]), ("OUTPUT_LIMIT", []))
        summary = self.run_loop([rejected("NATIVE_TRUNCATED", "max_tokens", False), FINISH], continue_on_error=True)
        self.assertEqual((summary["status"], summary["counts"]["failed"]), ("completed", 1))
        self.assertEqual(summary["tool_call_f1"]["value"], 0.5)  # Failure scores 0, empty gold scores 1.

    def test_native_repair_preserves_prefix_and_total_cap_fails_closed(self):
        seal_selection_policy(self.fx.suite, DEFAULT_SELECTION_POLICY)
        summary = self.run_loop([call("contacts.search", query="Lan"), rejected(), FINISH, FINISH])
        self.assertEqual(summary["counts"]["completed"], 2)
        repaired = self.planner.inputs[2]["observations"]
        self.assertEqual([o["kind"] for o in repaired], ["tool_result", "native_rejection"])
        self.assertEqual(repaired[1]["record"]["step"], 2)
        summary = self.run_loop([rejected(), rejected(), rejected(), FINISH], continue_on_error=True)
        outcomes = read_jsonl(next(p for p in sorted((self.fx.suite / "evaluations").iterdir())
                                   if p.name.endswith(summary["evaluation_dir"][-8:])) / "outcomes.jsonl")
        self.assertEqual((outcomes[0]["status"], outcomes[0]["error_code"], outcomes[0]["attempted_calls"]),
                         ("failed", "PLANNER_FORMAT", []))


class TeacherForcedTests(unittest.TestCase):
    def test_gold_prefix_diagnostics_keep_denominators(self):
        fx = SuiteFixture()
        self.addCleanup(fx.close)
        prepare(load_config(fx.config_path), fx.suite, expected=fx.expected)
        accept_fixture(load_config(fx.config_path), fx.suite)
        seal_selection_policy(fx.suite, DEFAULT_SELECTION_POLICY)

        class Backend:
            def decide(self, messages, tools, allowed):
                return qn.parse_native_text("Đã kết thúc.", allowed)

        summary = run_teacher_forced(suite_dir=fx.suite, experiment="L0", mode="G", backend=Backend(),
                                     model_identity={"training_status": "pretrained"})
        self.assertEqual(summary["denominators"]["raw_candidates"], 3)  # train_0009 call+finish, train_0010 finish.
        self.assertEqual(summary["next_action_accuracy"]["numerator"], 1)  # Pending negation/finish is excluded.
        self.assertEqual(summary["denominators"]["usable"], 2)
        with self.assertRaises(Exception):
            run_teacher_forced(suite_dir=fx.suite, experiment="L0", mode="A", backend=Backend(),
                               model_identity={})


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.fx = SuiteFixture()
        self.addCleanup(self.fx.close)
        raw = read_json(self.fx.config_path)
        cache = self.fx.root / "resources/validation-cache.jsonl"
        cache.write_text("", encoding="utf-8")
        cache.with_suffix(".manifest.json").write_text("{}", encoding="utf-8")
        asr = self.fx.root / "resources/mock-asr"
        asr.mkdir()
        (asr / "llm-handoff.json").write_text("{}", encoding="utf-8")
        raw["validation_asr_cache"] = "resources/validation-cache.jsonl"
        raw["asr_model_dir"] = "resources/mock-asr"
        self.fx.config_path.write_text(json.dumps(raw), encoding="utf-8")
        prepare(load_config(self.fx.config_path), self.fx.suite, expected=self.fx.expected)
        accept_fixture(load_config(self.fx.config_path), self.fx.suite)
        self.policy = seal_selection_policy(self.fx.suite, DEFAULT_SELECTION_POLICY)

    def fake_run(self, experiment, mode, f1, *, failed=0, timed_out=0, partial=False, training="completed_full_budget"):
        """Fabricate a saved evaluation (controlled artifact, not a model result)."""
        from lifemate.llm_training.config import native_identities
        from lifemate.llm_training.corpus import load_suite
        from lifemate.llm_training.storage import new_directory, now
        from lifemate.llm_training.metrics import coverage
        from lifemate.llm_training.acceptance import evaluation_readiness, input_identity
        from lifemate.llm_training.evaluation import EVALUATION_SCHEMA, EVALUATOR_VERSION, evaluator_binding, limits
        from lifemate.llm_training.trainer import DEFAULTS
        from lifemate.llm_training.config import BASE_MODEL

        suite = load_suite(self.fx.suite)
        directory = new_directory(self.fx.suite / "evaluations", f"{experiment}-{mode}")
        ids = suite["partition"]["validation_ids"]
        outcomes = [{"id": i, "status": "not_attempted" if partial and n else "failed" if n < failed else "completed", "attempted_calls": [],
                     "elapsed": None if partial and n else 2.0, "state_hash": "a"*64,
                     "error_code": "TIME_LIMIT" if n < timed_out else None}
                    for n, i in enumerate(ids)]
        counts = coverage(outcomes, ids)
        successes = [o for o in outcomes if o["status"] == "completed"]
        # Controlled metric artifacts; compare reconciles totals and failure penalties.
        per_source = [{"id": o["id"], "status": o["status"], "predicted_calls": 0,
                       "tool_call_f1": None if o["status"] == "not_attempted" else 0. if o["status"] == "failed" else
                           f1 * len(ids) / max(1, len(successes))} for o in outcomes]
        metric = lambda value, **extra: {"value": value, **extra}  # noqa: E731
        metrics = {"schema": EVALUATION_SCHEMA, "status": "completed" if not partial else "partial",
                   "experiment": experiment, "mode": mode, "protocol": "closed_loop", "counts": counts, "metrics": {
            "tool_call_f1": metric(f1, numerator=f1*len(ids), denominator=len(ids)), "state_gated_tool_call_f1": metric(None),
            "ask_strict_recall": metric(1.0, counts={"matched": 1, "predicted": 1, "gold": 1}),
            "ask_strict_precision": metric(1.0), "no_action_recall": metric(1.0, confusion={"tp": 1, "fp": 0, "fn": 0, "tn": 1}),
            "no_action_precision": metric(1.0), "latency_p95": metric(2.0, denominator=counts["attempted"], scope="planner_tools_gold_transcripts"),
            "latency_mean": metric(2.0, denominator=counts["attempted"], scope="planner_tools_gold_transcripts")}}
        hashes = {"outcomes": write_jsonl(directory / "outcomes.jsonl", outcomes),
                  "per_sample_metrics": write_jsonl(directory / "per-sample-metrics.jsonl", per_source),
                  "errors": write_jsonl(directory / "errors.jsonl", []),
                  "fixed_cases": write_json(directory / "fixed-10-cases.json", []),
                  "metrics": write_json(directory / "metrics.json", metrics),
                  "predictions": write_jsonl(directory / "predictions.jsonl", [
                      {"id": o["id"], "tool_calls": [], "state_hash": o["state_hash"]} for o in successes])}
        write_json(directory / "manifest.json", {
            "schema": EVALUATION_SCHEMA, "status": metrics["status"], "counts": counts,
            "input_identity": input_identity(load_config(self.fx.config_path), suite, mode=mode),
            "readiness": evaluation_readiness(load_config(self.fx.config_path), self.fx.suite, mode=mode),
            "experiment": experiment, "mode": mode, "protocol": "closed_loop", "started_at": now(),
            "suite_seal": suite["seal"]["identity"], "selection_policy_sha256": self.policy["policy_sha256"],
            "identities": native_identities(), "limits": vars(limits()), "seed": 20261027,
            "decode": {"do_sample":False,"num_beams":1,"selection_filter":False}, "runtime": {},
            "evaluator": EVALUATOR_VERSION, "evaluator_code": evaluator_binding(), "execution_profile": {"controlled": True},
            "artifact_hashes": hashes, "predictions_file": "predictions.jsonl",
            "model": {"training_status": "pretrained" if experiment == "L0" else training, "export_status": "verified",
                      "base_model": __import__('lifemate.llm_training.config', fromlist=['BASE_MODEL']).BASE_MODEL,
                      "verified_weights": True, "identity": "controlled", "files": {"model.safetensors": "a"*64},
                      "logical_parameters":4022468096,"checkpoint_identity":"c"*64,
                      "base":{"base_model":BASE_MODEL,"files":{"model.safetensors":"a"*64}},
                      "training_binding":{"settings":DEFAULTS,"corpus":"c"*64,"readiness":{"token_corpus":"c"*64},"code":{"controlled":"a"*64}}}})
        return {"experiment": experiment, "mode": mode, "evaluation": directory.name}

    def selection(self, l1a, l2a, **l2):
        runs = [self.fake_run("L0", "G", 0.3), self.fake_run("L0", "A", 0.2),
                self.fake_run("L1", "G", 0.5), self.fake_run("L1", "A", l1a), self.fake_run("L2", "G", 0.5)]
        runs.append(self.fake_run("L2", "A", l2a, **l2))
        return {"runs": runs}

    def test_one_extra_timeout_is_not_an_automatic_veto(self):
        report = compare(self.fx.suite, self.selection(0.40, 0.42, failed=1, timed_out=1))
        self.assertTrue(all(row["valid"] for row in report["rows"] if row["evaluation"] is not None))
        self.assertEqual(len(report["rows"]), 8)
        self.assertEqual(report["weighting_selection"]["selected_policy"], "L2")
        self.assertEqual(report["weighting_selection"]["metric_status"], "provisional_ungated")
        self.assertIn("critical_argument_errors", report["weighting_selection"]["unverified"])
        self.assertAlmostEqual(report["rows"][3]["delta_vs_L0"], 0.2)
        self.assertNotIn("torch", sys.modules)

    def test_crossed_tolerance_and_ties_retain_l1(self):
        # Two extra failures violate performance policy even when coverage is complete.
        from lifemate.llm_training.reporting import performance_decision
        def run(score, failed):
            return {"metrics": {"counts": {"failed": failed, "timed_out": 0}, "metrics": {
                "tool_call_f1": {"value": score}, "ask_strict_recall": {"counts": {"matched": 1, "gold": 1, "predicted": 1}},
                "ask_strict_precision": {"value": 1}, "no_action_recall": {"confusion": {"tp": 1, "fp": 0, "fn": 0, "tn": 1}},
                "no_action_precision": {"value": 1}}}}
        crossed = performance_decision(run(.4, 0), run(.45, 2), run(.5, 0), run(.5, 0), DEFAULT_SELECTION_POLICY)
        self.assertFalse(crossed["candidate_qualifies"])
        tie = compare(self.fx.suite, self.selection(0.40, 0.4000001))
        self.assertEqual(tie["weighting_selection"]["selected_policy"], "L1")

    def test_partial_or_incomplete_runs_are_invalid_not_scored(self):
        report = compare(self.fx.suite, self.selection(0.40, 0.90, partial=True))
        l2a = next(r for r in report["rows"] if (r["experiment"], r["mode"]) == ("L2", "A"))
        self.assertIn("partial_coverage", l2a["issues"])
        self.assertEqual(report["weighting_selection"]["status"], "blocked_dependency")
        report = compare(self.fx.suite, self.selection(0.40, 0.90, training="interrupted"))
        l2a = next(r for r in report["rows"] if (r["experiment"], r["mode"]) == ("L2", "A"))
        self.assertIn("incomplete_training_budget", l2a["issues"])
        with self.assertRaises(ValueError):
            compare(self.fx.suite, {"runs": [self.fake_run("L0", "G", 0.1)] * 2})

    def test_tampered_artifact_is_a_hard_validity_failure(self):
        selection = self.selection(0.40, 0.42)
        target = self.fx.suite / "evaluations" / selection["runs"][-1]["evaluation"] / "outcomes.jsonl"
        target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        row = next(r for r in compare(self.fx.suite, selection)["rows"] if (r["experiment"], r["mode"]) == ("L2", "A"))
        self.assertIn("artifact_hash:outcomes", row["issues"])

    def test_missing_mandatory_support_is_pending(self):
        decision = performance_decision({"metrics": {"metrics": {"tool_call_f1": {"value": None}}, "counts": {}}},
                                        {"metrics": {"metrics": {"tool_call_f1": {"value": 0.5}}, "counts": {}}},
                                        None, None, DEFAULT_SELECTION_POLICY)
        self.assertEqual(decision["status"], "pending")
        self.assertEqual(read_json(self.fx.suite / "suite.json")["status"], "sealed")

    def test_full_coverage_marker_cannot_hide_unattempted_outcomes(self):
        selection = self.selection(.40, .42)
        path = self.fx.suite / "evaluations" / selection["runs"][-1]["evaluation"]
        outcomes = read_jsonl(path / "outcomes.jsonl")
        for outcome in outcomes:
            outcome.update(status="not_attempted", elapsed=None)
        manifest = read_json(path / "manifest.json")
        manifest["artifact_hashes"]["outcomes"] = write_jsonl(path / "outcomes.jsonl", outcomes, exclusive=False)
        write_json(path / "manifest.json", manifest, exclusive=False)
        report = compare(self.fx.suite, selection)
        row = next(r for r in report["rows"] if (r["experiment"], r["mode"]) == ("L2", "A"))
        self.assertFalse(row["valid"])
        self.assertIn("partial_coverage", row["issues"])
        self.assertIn("coverage_counts_inconsistent", row["issues"])
        self.assertEqual(report["weighting_selection"]["status"], "blocked_dependency")

    def test_rehashed_timing_artifact_is_reconciled_with_metric_support(self):
        selection = self.selection(.40, .42)
        path = self.fx.suite / "evaluations" / selection["runs"][-1]["evaluation"]
        outcomes = read_jsonl(path / "outcomes.jsonl")
        outcomes[0]["elapsed"] = 200.
        manifest = read_json(path / "manifest.json")
        manifest["artifact_hashes"]["outcomes"] = write_jsonl(path / "outcomes.jsonl", outcomes, exclusive=False)
        write_json(path / "manifest.json", manifest, exclusive=False)
        row = next(r for r in compare(self.fx.suite, selection)["rows"] if (r["experiment"], r["mode"]) == ("L2", "A"))
        self.assertTrue(any("timing support mismatch" in issue for issue in row["issues"]))

    def test_rv018_policy_is_recomputed_before_l3_not_trusted_as_a_flag(self):
        from lifemate.llm_training.reporting import verify_weighting_report
        report=compare(self.fx.suite,self.selection(.40,.42))
        self.assertEqual(verify_weighting_report(self.fx.suite,report),"L2")
        report["weighting_selection"]["selected_policy"]="L1"
        with self.assertRaises(ValueError):
            verify_weighting_report(self.fx.suite,report)


if __name__ == "__main__":
    unittest.main()
