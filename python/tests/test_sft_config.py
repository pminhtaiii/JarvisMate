"""Strict planner SFT configuration: no model library, no input file is touched."""
import copy
import tempfile
import tomllib
import unittest
from pathlib import Path

from lifemate.contracts import PipelineError
from lifemate.sft import RECIPE, load_config, parse_config
from lifemate.sft.__main__ import main

REPOSITORY = Path(__file__).resolve().parents[2]
VALID = {
    "schema_version": 1,
    "data": {"train_jsonl": "data/train/train.jsonl", "train_catalog": "data/train/catalog.json",
             "train_role": "train", "validation_jsonl": "data/validation/validation.jsonl",
             "validation_catalog": "data/train/catalog.json", "validation_role": "validation",
             "permitted_use": "development"},
    "model": {"base_path": "models/base"},
    "training": {"recipe": "qlora-baseline-v1", "device": "cuda:0", "seed": 20261027,
                 "microbatch": 1, "accumulation": 16},
    "limits": {"context_tokens": 16384, "max_new_tokens": 512},
    "output": {"experiment_dir": "runs/one"},
}


def changed(section=None, **values):
    raw = copy.deepcopy(VALID)
    (raw if section is None else raw[section]).update(values)
    return raw


class ConfigurationTests(unittest.TestCase):
    def rejected(self, raw, fragment):
        with self.assertRaises(PipelineError) as caught:
            parse_config(raw, Path.cwd())
        self.assertEqual(caught.exception.code, "INPUT_INVALID")
        self.assertIn(fragment, str(caught.exception))

    def test_valid_configuration_resolves_paths_against_its_directory(self):
        config = parse_config(VALID, Path.cwd())
        self.assertEqual(config.train_jsonl, (Path.cwd() / "data/train/train.jsonl").resolve())
        self.assertEqual(config.record()["recipe"], RECIPE)

    def test_shipped_example_is_valid(self):
        raw = tomllib.loads((REPOSITORY / "configs/planner-sft.example.toml").read_text(encoding="utf-8"))
        self.assertEqual(parse_config(raw, REPOSITORY).microbatch * parse_config(raw, REPOSITORY).accumulation, 16)

    def test_unknown_fields_and_wrong_types_are_rejected(self):
        self.rejected(changed(extra=1), "Unknown configuration section")
        self.rejected(changed("training", learning_rate=1e-3), "Unknown key")
        self.rejected(changed("training", microbatch=True), "Invalid type")

    def test_recipe_and_seed_are_fixed(self):
        self.rejected(changed("training", recipe="other"), "training.recipe")
        self.rejected(changed("training", seed=1), "training.seed")

    def test_batch_product_must_be_sixteen(self):
        self.rejected(changed("training", microbatch=2, accumulation=4), "16")
        self.rejected(changed("training", microbatch=0, accumulation=16), "16")
        self.assertEqual(parse_config(changed("training", microbatch=4, accumulation=4), Path.cwd()).accumulation, 4)

    def test_test_roles_and_test_paths_are_rejected(self):
        self.rejected(changed("data", validation_role="public_test"), "roles")
        self.rejected(changed("data", validation_jsonl="data/public_test/public_test.jsonl"), "test data")
        self.rejected(changed("data", validation_jsonl="data/x/private_test.jsonl"), "test data")
        self.rejected(changed("data", train_jsonl="data/train_environment/x.jsonl"), "environment")

    def test_supplied_bundle_directory_name_is_not_mistaken_for_test_data(self):
        raw = changed("data", train_jsonl="data_unz/train+public_test/train/train.jsonl")
        self.assertEqual(parse_config(raw, Path.cwd()).train_jsonl.name, "train.jsonl")

    def test_aliased_data_and_nested_output_are_rejected(self):
        self.rejected(changed("data", validation_jsonl="data/train/../train/train.jsonl"), "different datasets")
        self.rejected(changed("output", experiment_dir="models/base/run"), "outside")
        self.rejected(changed("output", experiment_dir="data/train/run"), "outside")

    def test_context_budget_is_bounded(self):
        self.rejected(changed("limits", context_tokens=20000), "16384")
        self.rejected(changed("limits", max_new_tokens=16384), "16384")

    def test_device_must_select_one_gpu(self):
        self.rejected(changed("training", device="cpu"), "one GPU")

    def test_identity_ignores_hosts_but_not_run_settings(self):
        one = parse_config(VALID, Path.cwd())
        moved = parse_config(changed("training", device="cuda:1", microbatch=4, accumulation=4), Path("elsewhere").resolve())
        self.assertEqual(one.identity(), moved.identity())
        self.assertNotEqual(one.identity(), parse_config(changed("limits", max_new_tokens=256), Path.cwd()).identity())


class CommandLineTests(unittest.TestCase):
    def test_bad_configuration_exits_nonzero_with_bounded_record(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "config.toml"
            path.write_text("schema_version = 2\n", encoding="utf-8")
            self.assertEqual(main(["preflight", "--config", str(path)]), 1)

    def test_override_reaches_only_declared_fields(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "config.toml"
            example = (REPOSITORY / "configs/planner-sft.example.toml").read_text(encoding="utf-8")
            path.write_text(example, encoding="utf-8")
            config = load_config(path, {"device": "cuda:1", "microbatch": 4, "accumulation": 4})
            self.assertEqual((config.device, config.microbatch, config.accumulation), ("cuda:1", 4, 4))
            with self.assertRaises(PipelineError):
                load_config(path, {"learning_rate": 1})


if __name__ == "__main__":
    unittest.main()
