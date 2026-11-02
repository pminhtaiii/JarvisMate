"""Manual lifecycle CLI, strict config/paths and storage (W01/W03, LL001-LL005)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lifemate.jsonio import dumps
from lifemate.llm_training import cli
from lifemate.llm_training.config import BASE_MODEL, ConfigError, load_config
from lifemate.llm_training.inventory import preflight, resource_report
from lifemate.llm_training.storage import (StorageError, create_fresh, new_directory, seal, verify_seal,
                                           write_json, write_jsonl)
from llm_support import SuiteFixture

SRC = Path(__file__).resolve().parents[1] / "src"
MODEL_LIBRARIES = ("torch", "transformers", "lmformatenforcer", "peft", "bitsandbytes", "numpy")


def run_isolated(argv, cwd):
    """Run the CLI in a fresh interpreter and report which model libraries were imported."""
    code = ("import sys, json; from lifemate.llm_training.cli import main; status = main(%r); "
            "print(json.dumps({'exit': status, 'loaded': sorted(m for m in sys.modules "
            "if m.split('.')[0] in %r)}), file=sys.stderr)") % (argv, MODEL_LIBRARIES)
    env = dict(os.environ, PYTHONPATH=str(SRC), PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, "-c", code], cwd=cwd, env=env, capture_output=True,
                            text=True, encoding="utf-8", timeout=300)
    summary = json.loads(result.stdout.strip().splitlines()[-1])
    report = json.loads(result.stderr.strip().splitlines()[-1])
    return report["exit"], summary, report["loaded"]


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fx = SuiteFixture()
        self.addCleanup(self.fx.close)

    def test_model_free_commands_import_no_model_libraries(self):
        from lifemate.llm_training.corpus import prepare

        config = str(self.fx.config_path)
        other = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, other, True)
        # The CLI uses the pinned dataset/split hashes, so controlled data fails preflight.
        expectations = [(["status"], 0, "ok"),
                        (["evaluation-inputs", "--config", config], 1, "failed"),
                        (["verify-resources", "--config", config, "--phase", "prepare"], 4, "blocked"),
                        (["prepare", "--config", config, "--suite-dir", str(self.fx.suite)], 2, "failed_preflight")]
        for argv, code, state in expectations:
            with self.subTest(argv=argv[0]):
                status, summary, loaded = run_isolated(argv, other)  # Unrelated working directory.
                self.assertEqual(loaded, [])
                self.assertEqual((status, summary["status"]), (code, state))
        prepare(load_config(self.fx.config_path), self.fx.suite, expected=self.fx.expected)
        status, summary, loaded = run_isolated(["status", "--suite-dir", str(self.fx.suite)], other)
        self.assertEqual((status, summary["status"], summary["sealed"], loaded), (0, "sealed", True, []))

    def test_l0_training_all_experiments_and_out_of_scope_phases(self):
        self.assertEqual(cli.main(["train", "--experiment", "L0"]), 2)
        self.assertEqual(cli.main(["train", "--experiment", "L1"]), 2)
        self.assertEqual(cli.main(["probe", "--experiment", "L1"]), 2)
        self.assertEqual(cli.main(["train", "--all"]), 2)
        self.assertEqual(cli.main(["evaluate", "--suite-dir", "x"]), 2)  # Experiment/mode are mandatory.

    def test_decoder_poc_without_tokenizer_is_blocked_with_a_record(self):
        output = self.fx.root / ".agent-work" / "llm-finetune" / "poc output"
        status, summary, loaded = run_isolated(
            ["token-audit", "--config", str(self.fx.config_path), "--scope", "decoder-poc",
             "--output-root", str(output), "--model-dir", str(self.fx.root / "missing model")], str(self.fx.root))
        self.assertEqual((status, summary["status"]), (4, "blocked"))
        self.assertTrue((Path(summary["directory"]) / "outcome.json").is_file())
        self.assertEqual(loaded, [])

    def test_preflight_rejects_l0_and_blocks_l1_on_missing_evidence(self):
        config = load_config(self.fx.config_path)
        self.assertEqual(preflight(config, self.fx.suite, "L0")["status"], "failed_preflight")
        report = preflight(config, self.fx.suite, "L1")
        self.assertEqual(report["status"], "blocked_dependency")
        self.assertTrue(report["missing"])
        self.assertFalse(report["model_libraries_imported"])

    def test_inventory_distinguishes_resource_classes_and_optional_asr(self):
        report = resource_report(load_config(self.fx.config_path), "prepare", hash_weights=False)
        resources = report["resources"]
        self.assertEqual(resources["dataset"]["status"], "mismatch")  # Controlled data is not the pinned dataset.
        self.assertEqual(resources["asr_export"]["status"], "not_configured")
        self.assertFalse(resources["asr_export"]["required"])
        self.assertEqual(resources["weights"]["status"], "not_required")
        self.assertFalse(resources["audio"]["enumerated"])
        self.assertIn("dataset", report["blocking"])
        self.assertNotIn("asr_export", report["blocking"])


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.fx = SuiteFixture()
        self.addCleanup(self.fx.close)
        self.raw = json.loads(self.fx.config_path.read_text(encoding="utf-8"))

    def write(self, **changes):
        self.fx.config_path.write_text(dumps(self.raw | changes), encoding="utf-8")
        return load_config(self.fx.config_path)

    def test_floating_mixed_unknown_and_traversal_configs_are_rejected(self):
        cases = [{"base_model": BASE_MODEL | {"revision": "main"}},
                 {"identities": self.raw["identities"] | {"prompt": "lifemate-react-v4"}},
                 {"seeds": self.raw["seeds"] | {"split": 20261027}},
                 {"unexpected": 1}, {"data_root": "../outside"}, {"output_root": "resources/data/out"}]
        for change in cases:
            with self.subTest(change=list(change)), self.assertRaises(ConfigError):
                self.write(**change)

    def test_project_relative_resolution_relocation_and_overrides(self):
        config = self.write()
        self.assertEqual(config.paths["data_root"], (self.fx.root / "resources" / "data").resolve())
        moved = Path(tempfile.mkdtemp()) / "nơi mới có dấu cách"
        self.addCleanup(shutil.rmtree, moved.parent, True)
        shutil.copytree(self.fx.root, moved, ignore=shutil.ignore_patterns("*_environment", "*_enviroment"))
        relocated = load_config(moved / "configs" / "suite.json")
        self.assertEqual(relocated.paths["data_root"], (moved / "resources" / "data").resolve())
        self.assertEqual(relocated.identity(), config.identity())  # Content identity excludes local roots.
        override = load_config(self.fx.config_path, overrides={"data_root": moved / "resources" / "data"})
        self.assertEqual(override.paths["data_root"], (moved / "resources" / "data").resolve())
        self.assertEqual(override.portable["data_root"], {"external": True, "name": "data"})
        with self.assertRaises(Exception):
            load_config(self.fx.config_path, overrides={"data_root": self.fx.data / "train_environment"})

    def test_sealed_suite_rebinds_internal_paths_after_relocation(self):
        from lifemate.llm_training.config import config_from_suite
        from lifemate.llm_training.corpus import prepare, load_suite
        original = load_config(self.fx.config_path)
        prepare(original,self.fx.suite,expected=self.fx.expected)
        moved = Path(tempfile.mkdtemp()) / "relocated project có dấu"
        self.addCleanup(shutil.rmtree,moved.parent,True)
        shutil.copytree(self.fx.root,moved,ignore=shutil.ignore_patterns("*_environment","*_enviroment"))
        suite = moved/self.fx.suite.relative_to(self.fx.root)
        rebound = config_from_suite(load_suite(suite)["suite"],project_root=moved)
        self.assertEqual(rebound.require("model_dir"),moved/"resources/model")
        self.assertEqual(rebound.require("data_root"),moved/"resources/data")
        self.assertEqual(rebound.identity(),original.identity())


class StorageTests(unittest.TestCase):
    def test_atomic_exclusive_writes_seal_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_json(root / "a.json", {"x": 1})
            with self.assertRaises(StorageError):
                write_json(root / "a.json", {"x": 2})
            (root / "sub").mkdir()
            write_jsonl(root / "sub" / "rows.jsonl", [{"r": 1}])
            seal(root, ["a.json", "sub/rows.jsonl"])
            verify_seal(root)
            with self.assertRaises(StorageError):
                write_json(root / "sub" / "new.json", {})
            (root / "a.json").write_text('{"x":3}\n', encoding="utf-8")
            with self.assertRaises(StorageError):
                verify_seal(root)
            first, second = new_directory(root / "runs", "eval"), new_directory(root / "runs", "eval")
            self.assertNotEqual(first, second)
            with self.assertRaises(StorageError):
                create_fresh(first)
            self.assertFalse(list(root.glob(".*.tmp")))


if __name__ == "__main__":
    unittest.main()
