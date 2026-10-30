import contextlib
import io
import json
import unittest
from unittest.mock import MagicMock, patch

from lifemate.adapters.common import ModelResidency
from lifemate.artifacts import sync_write
from lifemate.cli import main
from lifemate.contracts import PipelineError
from lifemate.example_audit import AUDIT_SCHEMA_VERSION
from lifemate.jsonio import digest
from lifemate.runtime import load_runtime
from support import CATALOG, FINISH, ControlledASR, ControlledEnvironment, ControlledPlanner, Fixture, call


class CLITests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture(3)
        self.addCleanup(self.fx.close)
        self.model_loads, self.opened = [], []
        self.planner = ControlledPlanner([FINISH, FINISH, FINISH])
        self.stdout, self.stderr = io.StringIO(), io.StringIO()

    def arguments(self, command="run", ids=None):
        args = [command, "--data-root", str(self.fx.data), "--runtime-dir", str(self.fx.runtime),
                "--split", "train", "--input-mode", "transcript"]
        for sample_id in ids or ["train_0001"]:
            args += ["--id", sample_id]
        if command == "run":
            args += ["--planner-model", str(self.fx.root / "weights"), "--device", "cpu",
                     "--run-dir", str(self.fx.config().run_dir)]
        return args

    def load_planner(self, *args):
        self.model_loads.append(args)
        return self.planner

    def runtime(self, config, data):
        # Check trusted package loading but inject execution, not a fake CLI backend.
        factory = load_runtime(config, data)
        case = self

        class Wrapper:
            metadata = factory.metadata

            def __call__(self, split, sample_id, root):
                case.opened.append(sample_id)
                return ControlledEnvironment()

        return Wrapper()

    def execute(self, args):
        with contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr):
            return main(args, planner_factory=self.load_planner, asr_factory=lambda *_: ControlledASR(),
                        runtime_loader=self.runtime)

    def test_check_data_has_no_models_environments_or_run_artifacts(self):
        code = self.execute(self.arguments("check-data"))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(self.stdout.getvalue())["status"], "validated")
        self.assertEqual(self.model_loads, [])
        self.assertEqual(self.opened, [])
        self.assertFalse(self.fx.config().run_dir.exists())

    def test_single_run_authoritative_output_and_clean_stdout(self):
        self.assertEqual(self.execute(self.arguments()), 0)
        summary = json.loads(self.stdout.getvalue())
        self.assertEqual(summary["count"], 1)
        row = json.loads((self.fx.config().run_dir / "predictions.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(set(row), {"id", "tool_calls", "state_hash"})
        self.assertEqual(row["state_hash"], "a" * 64)
        self.assertNotIn("GOLD_MUST_NOT_ENTER_PROMPT", self.stdout.getvalue() + self.stderr.getvalue())

    def test_model_is_reused_and_batch_uses_dataset_order(self):
        self.assertEqual(self.execute(self.arguments(ids=["train_0002", "train_0001"])), 0)
        self.assertEqual(len(self.model_loads), 1)
        self.assertEqual(self.opened, ["train_0001", "train_0002"])

    def test_audio_model_is_loaded_once_for_selected_batch(self):
        args = self.arguments(ids=["train_0001", "train_0002"])
        args[args.index("transcript")] = "audio"
        asr = ControlledASR()
        asr_loads = []

        def load_asr(*values):
            asr_loads.append(values)
            return asr

        with contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr):
            code = main(args, planner_factory=self.load_planner, asr_factory=load_asr,
                        runtime_loader=self.runtime)
        self.assertEqual(code, 0)
        self.assertEqual(len(asr_loads), 1)
        self.assertEqual([p.stem for p in asr.paths], ["train_0001", "train_0002"])

    def test_successful_run_records_full_attempt_seconds_and_spans(self):
        self.assertEqual(self.execute(self.arguments()), 0)
        manifest = json.loads((self.fx.config().run_dir / "manifest.json").read_text(encoding="utf-8"))
        record = manifest["samples"][0]
        self.assertIsInstance(record["full_attempt_seconds"], float)
        self.assertGreaterEqual(record["full_attempt_seconds"], 0.0)
        self.assertEqual(record["measurements"]["metrics_schema_version"], 1)
        stages = [s["stage"] for s in record["measurements"]["spans"]]
        self.assertEqual(stages, ["request", "environment_open", "planner_decision", "final_collection"])
        # ControlledPlanner has no set_metrics_recorder; generation detail stays unavailable.
        self.assertEqual(record["measurements"]["generations"], [])

    def test_fatal_failure_records_full_attempt_seconds_and_partial_spans(self):
        self.planner = ControlledPlanner([FINISH, RuntimeError("injected")])
        self.assertEqual(self.execute(self.arguments(ids=[r["id"] for r in self.fx.rows])), 1)
        manifest = json.loads((self.fx.config().run_dir / "manifest.json").read_text(encoding="utf-8"))
        failure = manifest["failures"][0]
        self.assertEqual(failure["id"], "train_0002")
        self.assertIsInstance(failure["full_attempt_seconds"], float)
        self.assertGreaterEqual(failure["full_attempt_seconds"], 0.0)
        stages = [(s["stage"], s["status"]) for s in failure["measurements"]["spans"]]
        self.assertEqual(stages, [("request", "completed"), ("environment_open", "completed"),
                                  ("planner_decision", "unfinished")])

    def test_continue_on_error_failure_also_records_full_attempt_seconds(self):
        self.planner = ControlledPlanner([FINISH, RuntimeError("injected"), FINISH])
        args = self.arguments(ids=[r["id"] for r in self.fx.rows]) + ["--continue-on-error"]
        # continue-on-error still processes every sample, but a batch with any
        # failure still exits nonzero overall.
        self.assertEqual(self.execute(args), 1)
        manifest = json.loads((self.fx.config().run_dir / "manifest.json").read_text(encoding="utf-8"))
        failure = manifest["failures"][0]
        self.assertEqual(failure["id"], "train_0002")
        self.assertIsInstance(failure["full_attempt_seconds"], float)
        self.assertIn("measurements", failure)
        # The third sample still completes with its own full_attempt_seconds.
        completed_ids = [s["id"] for s in manifest["samples"]]
        self.assertEqual(completed_ids, ["train_0001", "train_0003"])
        self.assertIsInstance(manifest["samples"][1]["full_attempt_seconds"], float)

    def test_output_write_failure_after_loop_success_marks_agent_loop_completed(self):
        def fail_prediction_write_only(stream, content):
            if "predictions.partial" in getattr(stream, "name", ""):
                raise OSError("disk full")
            return sync_write(stream, content)

        with patch("lifemate.artifacts.sync_write", side_effect=fail_prediction_write_only):
            self.assertEqual(self.execute(self.arguments()), 1)
        manifest = json.loads((self.fx.config().run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["samples"], [])  # no durable row for this attempt
        failure = manifest["failures"][0]
        self.assertEqual(failure["id"], "train_0001")
        self.assertEqual(failure["error"]["code"], "OUTPUT_IO")
        self.assertEqual(failure["agent_loop"]["status"], "completed")
        self.assertIsInstance(failure["full_attempt_seconds"], float)
        self.assertEqual(failure["measurements"]["spans"][-1]["stage"], "final_collection")

    def test_mid_loop_failure_has_no_agent_loop_summary(self):
        self.planner = ControlledPlanner([RuntimeError("injected")])
        self.assertEqual(self.execute(self.arguments()), 1)
        manifest = json.loads((self.fx.config().run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertIsNone(manifest["failures"][0]["agent_loop"])

    def test_sample_total_over_30_seconds_still_persists_as_completed(self):
        import itertools
        counter = itertools.count(0.0, 5.0)
        clock = lambda: next(counter)
        args = self.arguments() + ["--sample-timeout-seconds", "1000"]
        with contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr):
            code = main(args, planner_factory=self.load_planner, asr_factory=lambda *_: ControlledASR(),
                       runtime_loader=self.runtime, clock=clock)
        self.assertEqual(code, 0)
        manifest = json.loads((self.fx.config().run_dir / "manifest.json").read_text(encoding="utf-8"))
        record = manifest["samples"][0]
        self.assertEqual(record["status"], "completed")
        self.assertGreaterEqual(record["full_attempt_seconds"], 30.0)
        self.assertTrue((self.fx.config().run_dir / "predictions.jsonl").exists())
        # No retroactive TIME_LIMIT: the row is published exactly as produced.
        self.assertNotIn("error", manifest)

    def test_second_sample_failure_never_invokes_third(self):
        self.planner = ControlledPlanner([FINISH, RuntimeError("injected")])
        self.assertEqual(self.execute(self.arguments(ids=[r["id"] for r in self.fx.rows])), 1)
        self.assertEqual(self.opened, ["train_0001", "train_0002"])
        directory = self.fx.config().run_dir
        self.assertFalse((directory / "predictions.jsonl").exists())
        self.assertEqual(json.loads((directory / "predictions.partial.jsonl").read_text(encoding="utf-8"))["id"], "train_0001")
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["not_started_ids"], ["train_0003"])

    def test_bad_preflight_records_manifest_before_any_sample_or_model(self):
        code = self.execute(self.arguments(ids=["unknown"]))
        self.assertEqual(code, 2)
        directory = self.fx.config().run_dir
        self.assertEqual(list((directory / "traces").iterdir()), [])
        self.assertEqual(self.model_loads, [])
        self.assertEqual(self.opened, [])
        self.assertEqual(json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["status"], "failed")

    def test_truncated_audio_fails_before_loading_models_or_creating_sample_traces(self):
        target = self.fx.split / self.fx.rows[0]["audio"]
        target.write_bytes(target.read_bytes()[:-1])
        args = self.arguments()
        args[args.index("transcript")] = "audio"
        with patch("lifemate.cli.LocalASR") as asr_factory:
            with contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr):
                code = main(args, planner_factory=self.load_planner, asr_factory=asr_factory,
                            runtime_loader=self.runtime)
        self.assertEqual(code, 2)
        self.assertEqual(self.model_loads, [])
        asr_factory.assert_not_called()
        self.assertEqual(self.opened, [])
        directory = self.fx.config().run_dir
        self.assertEqual(list((directory / "traces").iterdir()), [])
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["error"]["code"], "INPUT_INVALID")

    def test_model_load_failure_never_fabricates_result(self):
        with patch.object(self, "load_planner", side_effect=PipelineError("MODEL_UNAVAILABLE", "missing", "model_load")):
            self.assertEqual(self.execute(self.arguments()), 1)
        self.assertEqual(self.opened, [])
        self.assertEqual((self.fx.config().run_dir / "predictions.partial.jsonl").read_text(), "")

    def test_model_file_change_during_loading_prevents_execution(self):
        weights = self.fx.root / "weights"
        weights.mkdir()
        snapshot = weights / "config.json"
        snapshot.write_text('{}', encoding="utf-8")

        def load_changed_model(*args):
            snapshot.write_text('{"changed": true}', encoding="utf-8")
            return self.planner

        with patch.object(self, "load_planner", side_effect=load_changed_model):
            self.assertEqual(self.execute(self.arguments()), 2)
        self.assertEqual(json.loads(self.stdout.getvalue())["error"]["code"], "INPUT_INVALID")
        self.assertEqual(self.opened, [])
        self.assertEqual((self.fx.config().run_dir / "predictions.partial.jsonl").read_text(), "")

    def test_offload_transfer_failure_stops_continue_on_error_batch(self):
        class OffloadedPlanner(ModelResidency, ControlledPlanner):
            pass

        self.planner = OffloadedPlanner([FINISH, FINISH])
        self.planner.cpu_offload, self.planner.device = True, "cuda"
        self.planner.model, self.planner.torch = MagicMock(), MagicMock()
        failure = RuntimeError("transfer failed")

        def transfer(device):
            if device == "cuda":
                raise failure

        self.planner.model.to.side_effect = transfer
        args = self.arguments(ids=["train_0001", "train_0002"]) + ["--continue-on-error"]
        self.assertEqual(self.execute(args), 1)
        summary = json.loads(self.stdout.getvalue())
        self.assertEqual(summary["error"]["code"], "MODEL_UNAVAILABLE")
        self.assertEqual(summary["failed_ids"], ["train_0001"])
        self.assertEqual(self.opened, [])

    def test_trace_failure_prevents_tool_call_and_success_publication(self):
        self.planner = ControlledPlanner([call("contacts.search"), FINISH])
        with patch("lifemate.artifacts.Trace.emit", side_effect=PipelineError("TRACE_IO", "full", "trace")):
            self.assertEqual(self.execute(self.arguments()), 1)
        self.assertEqual(self.opened, [])
        self.assertFalse((self.fx.config().run_dir / "predictions.jsonl").exists())

    def test_invalid_arguments_exit_two_without_loading(self):
        self.assertEqual(self.execute(["run"]), 2)
        self.assertEqual(self.model_loads, [])

    def test_existing_run_is_refused_without_reopening_environment(self):
        self.fx.config().run_dir.mkdir()
        marker = self.fx.config().run_dir / "marker"
        marker.touch()
        self.assertEqual(self.execute(self.arguments()), 1)
        self.assertTrue(marker.exists())
        self.assertEqual(self.opened, [])


class ReportAndCompareCLITests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture(2)
        self.addCleanup(self.fx.close)
        self.stdout, self.stderr = io.StringIO(), io.StringIO()

    def runtime(self, config, data):
        factory = load_runtime(config, data)

        class Wrapper:
            metadata = factory.metadata

            def __call__(self, split, sample_id, root):
                return ControlledEnvironment()

        return Wrapper()

    def run_batch(self, run_dir):
        args = ["run", "--data-root", str(self.fx.data), "--runtime-dir", str(self.fx.runtime),
                "--split", "train", "--input-mode", "transcript",
                "--id", "train_0001", "--id", "train_0002",
                "--planner-model", str(self.fx.root / "weights"), "--device", "cpu",
                "--run-dir", str(run_dir)]
        with contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr):
            code = main(args, planner_factory=lambda *_: ControlledPlanner([FINISH, FINISH]),
                        asr_factory=lambda *_: ControlledASR(), runtime_loader=self.runtime)
        self.assertEqual(code, 0)

    def execute(self, args):
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr):
            return main(args)

    def test_report_command_writes_json_and_markdown(self):
        run_dir = self.fx.root / "run"
        self.run_batch(run_dir)
        code = self.execute(["report", "--run-dir", str(run_dir)])
        self.assertEqual(code, 0)
        self.assertTrue((run_dir / "report.json").exists())
        self.assertTrue((run_dir / "report.md").exists())
        self.assertEqual(json.loads(self.stdout.getvalue())["status"], "completed")

    def test_report_command_on_an_invalid_run_dir_returns_nonzero_without_a_traceback(self):
        code = self.execute(["report", "--run-dir", str(self.fx.root / "missing")])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(self.stdout.getvalue())["status"], "failed")

    def test_compare_runs_writes_outputs_and_rejects_output_overlapping_a_source_run(self):
        baseline_dir, candidate_dir = self.fx.root / "baseline", self.fx.root / "candidate"
        self.run_batch(baseline_dir)
        self.run_batch(candidate_dir)
        output_dir = self.fx.root / "comparison"
        code = self.execute(["compare-runs", "--baseline-run", str(baseline_dir),
                             "--candidate-run", str(candidate_dir), "--factor", "harness",
                             "--output-dir", str(output_dir)])
        self.assertEqual(code, 0)
        self.assertTrue((output_dir / "comparison.json").exists())
        self.assertTrue((output_dir / "comparison.md").exists())

        code = self.execute(["compare-runs", "--baseline-run", str(baseline_dir),
                             "--candidate-run", str(candidate_dir), "--factor", "harness",
                             "--output-dir", str(baseline_dir)])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(self.stdout.getvalue())["status"], "failed")


class FewShotCLITests(unittest.TestCase):
    """Few-shot/prompt-profile preflight wiring (T015): rejections before any model load."""

    def setUp(self):
        self.fx = Fixture(2)
        self.addCleanup(self.fx.close)
        self.model_loads = []
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        self.dataset_sha256 = digest(self.fx.split / "train.jsonl")
        self.partition_path = self.fx.root / "partition.json"
        self.partition_path.write_text(json.dumps({
            "partition_schema_version": 1, "dataset_sha256": self.dataset_sha256, "grouping_method": "m",
            "members": [
                {"id": "train_0001", "group_id": "g1", "partition": "fit", "source_sha256": "s1"},
                {"id": "train_0002", "group_id": "g2", "partition": "validation", "source_sha256": "s2"}]}),
            encoding="utf-8")

    def write_bundle(self, catalog_fingerprint=None, audited=True):
        bundle_path = self.fx.root / "bundle.json"
        catalog_sha256 = catalog_fingerprint or digest(self.fx.split / "train_tools_catalog.json")
        bundle = {
            "bundle_schema_version": 1, "bundle_id": "b1",
            "partition_manifest_sha256": digest(self.partition_path), "split": "train",
            "catalog_fingerprint": catalog_sha256,
            "examples": [{"id": "train_0001", "group_id": "g1", "source_sha256": "s1", "prefix_index": 0,
                         "rationale": "r", "input": {"request": "x", "context": {}, "history": [],
                                                      "available_tools": [], "observations": []},
                         "target": {"action": "finish"}}]}
        if audited:
            # A run only ever consumes the output of `audit-examples`; mirror that
            # proof here instead of a hand-written bundle the pipeline must reject.
            bundle |= {
                "audit_schema_version": AUDIT_SCHEMA_VERSION, "conversion_version": "lifemate-sft-conversion-v1",
                "source_dataset_sha256": self.dataset_sha256, "catalog_sha256": catalog_sha256,
                "partition_sha256": digest(self.partition_path),
            }
        bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
        return bundle_path

    def runtime(self, config, data):
        factory = load_runtime(config, data)

        class Wrapper:
            metadata = factory.metadata

            def __call__(self, split, sample_id, root):
                return ControlledEnvironment()

        return Wrapper()

    def load_planner(self, *args, **kwargs):
        self.model_loads.append((args, kwargs))
        return ControlledPlanner([FINISH])

    def arguments(self, sample_id, *extra):
        return ["run", "--data-root", str(self.fx.data), "--runtime-dir", str(self.fx.runtime),
                "--split", "train", "--input-mode", "transcript", "--id", sample_id,
                "--planner-model", str(self.fx.root / "weights"), "--device", "cpu",
                "--run-dir", str(self.fx.root / "run"), *extra]

    def execute(self, args):
        with contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr):
            return main(args, planner_factory=self.load_planner, asr_factory=lambda *_: ControlledASR(),
                        runtime_loader=self.runtime)

    def test_bundle_without_partition_manifest_is_rejected_before_model_load(self):
        code = self.execute(self.arguments("train_0002", "--few-shot-bundle", str(self.fx.root / "bundle.json")))
        self.assertEqual(code, 2)
        self.assertEqual(self.model_loads, [])

    def test_fit_partition_id_in_selection_is_rejected_before_model_load(self):
        bundle_path = self.write_bundle()
        code = self.execute(self.arguments("train_0001", "--few-shot-bundle", str(bundle_path),
                                           "--partition-manifest", str(self.partition_path)))
        self.assertEqual(code, 2)
        self.assertEqual(self.model_loads, [])

    def test_mismatched_catalog_fingerprint_is_rejected_before_model_load(self):
        bundle_path = self.write_bundle(catalog_fingerprint="0" * 64)
        code = self.execute(self.arguments("train_0002", "--few-shot-bundle", str(bundle_path),
                                           "--partition-manifest", str(self.partition_path)))
        self.assertEqual(code, 2)
        self.assertEqual(self.model_loads, [])

    def test_valid_validation_selection_with_bundle_proceeds_to_model_load(self):
        bundle_path = self.write_bundle()
        code = self.execute(self.arguments("train_0002", "--few-shot-bundle", str(bundle_path),
                                           "--partition-manifest", str(self.partition_path)))
        self.assertEqual(code, 0)
        self.assertEqual(len(self.model_loads), 1)
        _, kwargs = self.model_loads[0]
        self.assertEqual(kwargs["few_shot_token_budget"], 1024)  # contract default when a bundle is supplied
        self.assertEqual(len(kwargs["examples"]), 1)
        manifest = json.loads((self.fx.root / "run" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["effective_prompt"]["few_shot_token_budget"], 1024)
        self.assertEqual(manifest["effective_prompt"]["bundle"]["example_count"], 1)

    def test_unaudited_bundle_is_rejected_before_model_load(self):
        bundle_path = self.write_bundle(audited=False)
        code = self.execute(self.arguments("train_0002", "--few-shot-bundle", str(bundle_path),
                                           "--partition-manifest", str(self.partition_path)))
        self.assertEqual(code, 2)
        self.assertEqual(self.model_loads, [])

    def test_partition_from_a_different_dataset_is_rejected_before_model_load(self):
        other_partition = self.fx.root / "other_partition.json"
        other_partition.write_text(json.dumps({
            "partition_schema_version": 1, "dataset_sha256": "0" * 64, "grouping_method": "m", "members": [
                {"id": "train_0002", "group_id": "g2", "partition": "validation", "source_sha256": "s2"}]}),
            encoding="utf-8")
        bundle_path = self.fx.root / "bundle.json"
        bundle_path.write_text(json.dumps({
            "bundle_schema_version": 1, "bundle_id": "b1",
            "partition_manifest_sha256": digest(other_partition), "split": "train",
            "catalog_fingerprint": digest(self.fx.split / "train_tools_catalog.json"),
            "audit_schema_version": AUDIT_SCHEMA_VERSION, "conversion_version": "lifemate-sft-conversion-v1",
            "source_dataset_sha256": self.dataset_sha256,
            "catalog_sha256": digest(self.fx.split / "train_tools_catalog.json"),
            "partition_sha256": digest(other_partition),
            "examples": []}), encoding="utf-8")
        code = self.execute(self.arguments("train_0002", "--few-shot-bundle", str(bundle_path),
                                           "--partition-manifest", str(other_partition)))
        self.assertEqual(code, 2)
        self.assertEqual(self.model_loads, [])

    def test_explicit_over_cap_budget_is_rejected_at_argument_validation(self):
        bundle_path = self.write_bundle()
        code = self.execute(self.arguments("train_0002", "--few-shot-bundle", str(bundle_path),
                                           "--partition-manifest", str(self.partition_path),
                                           "--few-shot-token-budget", "4096"))
        self.assertEqual(code, 2)
        self.assertEqual(self.model_loads, [])

    def test_precise_v1_profile_is_passed_to_the_planner_and_recorded(self):
        code = self.execute(self.arguments("train_0001", "--prompt-profile", "precise-v1"))
        self.assertEqual(code, 0)
        _, kwargs = self.model_loads[0]
        self.assertEqual(kwargs["profile"]["profile"], "precise-v1")
        manifest = json.loads((self.fx.root / "run" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["effective_prompt"]["profile"]["profile"], "precise-v1")
        self.assertIsNone(manifest["effective_prompt"]["bundle"])

    def test_baseline_run_keeps_legacy_prompt_fields_and_omits_the_profile_kwarg(self):
        code = self.execute(self.arguments("train_0001"))
        self.assertEqual(code, 0)
        self.assertNotIn("profile", self.model_loads[0][1])
        manifest = json.loads((self.fx.root / "run" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["prompt_version"], "lifemate-react-v4")
        self.assertEqual(manifest["effective_prompt"]["profile"]["profile"], "baseline")
        self.assertIsNone(manifest["effective_prompt"]["bundle"])


class AuditExamplesCLITests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture(1)
        self.addCleanup(self.fx.close)
        self.fx.rows[0]["label"] = {"tool_calls": [], "tool_results": []}
        self.fx.write()
        self.catalog_path = self.fx.split / "train_tools_catalog.json"
        self.partition_path = self.fx.root / "partition.json"
        self.partition_path.write_text(json.dumps({
            "partition_schema_version": 1, "dataset_sha256": "d", "grouping_method": "m", "members": [
                {"id": "train_0001", "group_id": "g1", "partition": "fit", "source_sha256": "s"}]}),
            encoding="utf-8")
        row = self.fx.rows[0]
        self.bundle_path = self.fx.root / "bundle.json"
        self.bundle_path.write_text(json.dumps({
            "bundle_schema_version": 1, "bundle_id": "b1",
            "partition_manifest_sha256": digest(self.partition_path), "split": "train",
            "catalog_fingerprint": digest(self.catalog_path),
            "examples": [{"id": "train_0001", "group_id": "g1", "source_sha256": "s", "prefix_index": 0,
                         "rationale": "r", "input": {"request": row["audio_text"], "context": row["context"],
                                                      "history": [],
                                                      "available_tools": [CATALOG["apps"][0]["tools"][0],
                                                                          CATALOG["apps"][1]["tools"][0],
                                                                          CATALOG["apps"][2]["tools"][0]],
                                                      "observations": []},
                         "target": {"action": "finish"}}]}, ensure_ascii=False), encoding="utf-8")
        self.stdout, self.stderr = io.StringIO(), io.StringIO()

    def execute(self, args):
        with contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr):
            return main(args)

    def test_audit_examples_writes_a_new_immutable_output(self):
        output_path = self.fx.root / "audited.json"
        args = ["audit-examples", "--bundle", str(self.bundle_path),
                "--partition-manifest", str(self.partition_path), "--train-jsonl", str(self.fx.split / "train.jsonl"),
                "--catalog", str(self.catalog_path), "--output", str(output_path)]
        self.assertEqual(self.execute(args), 0)
        self.assertTrue(output_path.exists())
        self.assertEqual(json.loads(self.stdout.getvalue())["status"], "completed")

        self.stdout = io.StringIO()
        # Audited bundles are immutable; rerunning into the same output must not overwrite it.
        self.assertEqual(self.execute(args), 1)
        self.assertEqual(json.loads(self.stdout.getvalue())["status"], "failed")
