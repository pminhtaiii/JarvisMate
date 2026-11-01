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
from llm_support import SuiteFixture

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

    def run_loop(self, actions, **options):
        self.factory, self.planner = Factory(), Planner(actions)
        return run_closed_loop(config=self.config, suite_dir=self.fx.suite, experiment="L0", mode="G",
                               planner=self.planner, runtime_loader=lambda c, d: self.factory,
                               model_identity={"training_status": "pretrained"}, **options)

    def test_requires_preregistered_policy(self):
        with self.assertRaises(PreparationError):
            self.run_loop([FINISH, FINISH])

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
        seal_selection_policy(fx.suite, DEFAULT_SELECTION_POLICY)

        class Backend:
            def decide(self, messages, tools, allowed):
                return qn.parse_native_text("Đã kết thúc.", allowed)

        summary = run_teacher_forced(suite_dir=fx.suite, experiment="L0", mode="G", backend=Backend(),
                                     model_identity={"training_status": "pretrained"})
        self.assertEqual(summary["denominators"]["raw_candidates"], 3)  # train_0009 call+finish, train_0010 finish.
        self.assertEqual(summary["next_action_accuracy"]["numerator"], 2)
        with self.assertRaises(Exception):
            run_teacher_forced(suite_dir=fx.suite, experiment="L0", mode="A", backend=Backend(),
                               model_identity={})


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.fx = SuiteFixture()
        self.addCleanup(self.fx.close)
        prepare(load_config(self.fx.config_path), self.fx.suite, expected=self.fx.expected)
        self.policy = seal_selection_policy(self.fx.suite, DEFAULT_SELECTION_POLICY)

    def fake_run(self, experiment, mode, f1, *, failed=0, timed_out=0, partial=False, training="completed_full_budget"):
        """Fabricate a saved evaluation (controlled artifact, not a model result)."""
        from lifemate.llm_training.config import native_identities
        from lifemate.llm_training.corpus import load_suite
        from lifemate.llm_training.storage import new_directory, now

        suite = load_suite(self.fx.suite)
        directory = new_directory(self.fx.suite / "evaluations", f"{experiment}-{mode}")
        ids = suite["partition"]["validation_ids"]
        outcomes = [{"id": i, "status": "not_attempted" if partial and n else "completed", "attempted_calls": []}
                    for n, i in enumerate(ids)]
        counts = {"expected": len(ids), "attempted": len(ids) - (1 if partial else 0), "completed": len(ids) - failed,
                  "failed": failed, "timed_out": timed_out, "not_attempted": 1 if partial else 0,
                  "full_coverage": not partial}
        metric = lambda value, **extra: {"value": value, **extra}  # noqa: E731
        metrics = {"counts": counts, "metrics": {
            "tool_call_f1": metric(f1), "state_gated_tool_call_f1": metric(None),
            "ask_strict_recall": metric(1.0, counts={"matched": 1, "predicted": 1, "gold": 1}),
            "ask_strict_precision": metric(1.0), "no_action_recall": metric(1.0, confusion={"tp": 1, "fp": 0, "fn": 0, "tn": 1}),
            "no_action_precision": metric(1.0), "latency_p95": metric(2.0, scope="planner_tools_gold_transcripts")}}
        hashes = {"outcomes": write_jsonl(directory / "outcomes.jsonl", outcomes),
                  "per_sample_metrics": write_jsonl(directory / "per-sample-metrics.jsonl", []),
                  "errors": write_jsonl(directory / "errors.jsonl", []),
                  "fixed_cases": write_json(directory / "fixed-10-cases.json", []),
                  "metrics": write_json(directory / "metrics.json", metrics),
                  "predictions": write_jsonl(directory / "predictions.jsonl", [])}
        write_json(directory / "manifest.json", {
            "experiment": experiment, "mode": mode, "protocol": "closed_loop", "started_at": now(),
            "suite_seal": suite["seal"]["identity"], "selection_policy_sha256": self.policy["policy_sha256"],
            "identities": native_identities(), "limits": {}, "seed": 20261027, "decode": {}, "runtime": {},
            "evaluator": "v1", "artifact_hashes": hashes, "predictions_file": "predictions.jsonl",
            "model": {"training_status": "pretrained" if experiment == "L0" else training, "export_status": "verified"}})
        return {"experiment": experiment, "mode": mode, "evaluation": directory.name}

    def selection(self, l1a, l2a, **l2):
        runs = [self.fake_run("L0", "G", 0.3), self.fake_run("L0", "A", 0.2),
                self.fake_run("L1", "G", 0.5), self.fake_run("L1", "A", l1a), self.fake_run("L2", "G", 0.5)]
        runs.append(self.fake_run("L2", "A", l2a, **l2))
        return {"runs": runs}

    def test_one_extra_timeout_is_not_an_automatic_veto(self):
        report = compare(self.fx.suite, self.selection(0.40, 0.42, failed=1, timed_out=1))
        self.assertTrue(all(row["valid"] for row in report["rows"]))
        self.assertEqual(report["weighting_selection"]["selected_policy"], "L2")
        self.assertEqual(report["weighting_selection"]["metric_status"], "provisional_ungated")
        self.assertIn("critical_argument_errors", report["weighting_selection"]["unverified"])
        self.assertAlmostEqual(report["rows"][3]["delta_vs_L0"], 0.2)
        self.assertNotIn("torch", sys.modules)

    def test_crossed_tolerance_and_ties_retain_l1(self):
        crossed = compare(self.fx.suite, self.selection(0.40, 0.45, failed=2))
        self.assertEqual(crossed["weighting_selection"]["selected_policy"], "L1")
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
        row = compare(self.fx.suite, selection)["rows"][-1]
        self.assertIn("artifact_hash:outcomes", row["issues"])

    def test_missing_mandatory_support_is_pending(self):
        decision = performance_decision({"metrics": {"metrics": {"tool_call_f1": {"value": None}}, "counts": {}}},
                                        {"metrics": {"metrics": {"tool_call_f1": {"value": 0.5}}, "counts": {}}},
                                        None, None, DEFAULT_SELECTION_POLICY)
        self.assertEqual(decision["status"], "pending")
        self.assertEqual(read_json(self.fx.suite / "suite.json")["status"], "sealed")


if __name__ == "__main__":
    unittest.main()
