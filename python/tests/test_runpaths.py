from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lifemate.runpaths import dated_run_path
from lifemate.cli import configuration, parser


class RunPathTests(unittest.TestCase):
    def test_vietnam_execution_time_and_readable_collision_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            now = datetime(2026, 12, 31, 23, 30, 15, 123456, tzinfo=timezone.utc)
            first = dated_run_path(parent, "public-test-e4-normalized", now=now)
            self.assertEqual(first.name, "public-test-e4-normalized-20270101-063015")
            first.mkdir()
            second = dated_run_path(parent, "public-test-e4-normalized", now=now)
            self.assertEqual(second.name, "public-test-e4-normalized-20270101-063015-123456")
            second.mkdir()
            self.assertNotEqual(dated_run_path(parent, "public-test-e4-normalized", now=now), second)

    def test_bad_prefix_and_naive_timestamp_reject(self):
        with self.assertRaises(ValueError):
            dated_run_path(Path("."), "../escape")
        with self.assertRaises(ValueError):
            dated_run_path(Path("."), "run", now=datetime(2026, 1, 1))

    def test_cli_default_is_dated_and_explicit_path_is_preserved(self):
        args = ["run", "--data-root", "data", "--runtime-dir", "runtime", "--split", "train",
                "--input-mode", "transcript", "--id", "synthetic", "--planner-model", "weights", "--device", "cpu"]
        config = configuration(parser().parse_args(args))
        self.assertRegex(config.run_dir.name, r"^train-transcript-\d{8}-\d{6}(-\d{6})?$")
        explicit = configuration(parser().parse_args(args + ["--run-dir", "chosen-output"]))
        self.assertEqual(explicit.run_dir, Path("chosen-output"))

    def test_train_wrapper_uses_dated_directory(self):
        path = Path(__file__).resolve().parents[1] / "run_train.py"
        spec = importlib.util.spec_from_file_location("_test_run_train", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch("sys.argv", [str(path)]), patch.object(module, "main", return_value=0) as main:
            self.assertEqual(module.run(), 0)
        args = main.call_args.args[0]
        self.assertRegex(Path(args[args.index("--run-dir") + 1]).name, r"^train-all-\d{8}-\d{6}(-\d{6})?$")

    def test_e4_wrapper_uses_audio_new_directory_and_local_export(self):
        path = Path(__file__).resolve().parents[1] / "run_e4.py"
        spec = importlib.util.spec_from_file_location("_test_run_e4", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch("sys.argv", [str(path), "--id", "public_synthetic"]), patch.object(module, "main", return_value=0) as main:
            self.assertEqual(module.run(), 0)
        args = main.call_args.args[0]
        self.assertEqual(args[args.index("--input-mode") + 1], "audio")
        self.assertEqual(args[args.index("--id") + 1], "public_synthetic")
        self.assertNotIn("--resume-from", args)
        self.assertNotIn("--all", args)
        self.assertRegex(Path(args[args.index("--run-dir") + 1]).name,
                         r"^public-test-e4-normalized-\d{8}-\d{6}(-\d{6})?$")
        self.assertTrue(Path(args[args.index("--asr-model") + 1]).is_relative_to(path.parents[1]))
