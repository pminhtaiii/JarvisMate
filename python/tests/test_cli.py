import contextlib
import io
import json
import unittest
from unittest.mock import patch

from lifemate.cli import main
from lifemate.contracts import PipelineError
from lifemate.runtime import load_runtime
from support import FINISH, ControlledASR, ControlledEnvironment, ControlledPlanner, Fixture, call


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

    def test_model_load_failure_never_fabricates_result(self):
        with patch.object(self, "load_planner", side_effect=PipelineError("MODEL_UNAVAILABLE", "missing", "model_load")):
            self.assertEqual(self.execute(self.arguments()), 1)
        self.assertEqual(self.opened, [])
        self.assertEqual((self.fx.config().run_dir / "predictions.partial.jsonl").read_text(), "")

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
