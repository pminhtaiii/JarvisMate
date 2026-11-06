"""Strict integration configuration and metadata preflight (no models, no ToolEnv)."""
import unittest

from lifemate.configuration import (apply_overrides, check_parameter_budget, load_config,
                                    parse_config, preflight)
from lifemate.contracts import PipelineError
from lifemate.runtime import load_runtime
from integration_support import IntegrationFixture, snapshot


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.fx = IntegrationFixture()
        self.addCleanup(self.fx.close)

    def rejects(self, values=None, code="INPUT_INVALID", **kwargs):
        with self.assertRaises(PipelineError) as caught:
            load_config(self.fx.write_config(values, **kwargs))
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def changed(self, section, **changes):
        values = self.fx.values()
        values[section].update(changes)
        return values

    def test_valid_config_resolves_paths_and_has_stable_fingerprint(self):
        config = load_config(self.fx.write_config())
        self.assertEqual(config.planner.model_path, self.fx.planner.resolve())
        self.assertEqual(config.limits.timeout, 30)
        self.assertEqual(config.fingerprint(), load_config(self.fx.write_config()).fingerprint())
        self.assertEqual(parse_config(config.record(), self.fx.root).record(), config.record())

    def test_unknown_sections_keys_and_wrong_schema_version_are_rejected(self):
        values = self.fx.values()
        values["planner"]["temperature"] = 0.7
        self.assertIn("planner", str(self.rejects(values)))
        values = self.fx.values()
        values["serving"] = {"port": 8080}
        self.rejects(values)
        self.rejects(header="schema_version = 2")
        self.rejects(header="")

    def test_invalid_devices_dtypes_types_and_limits_are_rejected(self):
        cases = [
            ("planner", {"device": "gpu"}), ("asr", {"device": "cuda:x"}),
            ("planner", {"dtype": "int4"}), ("planner", {"dtype": "float16"}),  # float16 on CPU
            ("planner", {"offload": True}),  # offload without CUDA
            ("planner", {"context_tokens": 16385}), ("planner", {"max_new_tokens": 16384}),
            ("planner", {"protocol": "lifemate-react-v4"}), ("asr", {"backend": "wav2vec"}),
            ("execution", {"timeout_seconds": 30.5}), ("execution", {"timeout_seconds": 0}),
            ("execution", {"timeout_seconds": True}), ("execution", {"max_steps": 0}),
            ("execution", {"recovery_attempts": 2}), ("execution", {"seed": -1}),
            ("execution", {"startup_timeout_seconds": 0}), ("data", {"split": "private_test"}),
            ("data", {"mode": "video"}), ("output", {"debug_payloads": "yes"}),
        ]
        for section, change in cases:
            with self.subTest(section=section, change=change):
                self.rejects(self.changed(section, **change))

    def test_selection_and_mode_contradictions_are_rejected(self):
        self.rejects(self.changed("data", select_all=True))  # Both file and all.
        values = self.fx.values()
        del values["data"]["sample_ids_file"]
        self.rejects(values)  # Neither.
        values = self.fx.values()
        del values["asr"]
        self.rejects(values)  # Audio needs ASR.
        self.rejects(self.changed("data", split="public_test", mode="transcript"))

    def test_output_inside_inputs_is_rejected(self):
        self.rejects(self.changed("output", root=self.fx.data / "out"))
        self.rejects(self.changed("output", root=self.fx.planner / "out"))

    def test_cli_overrides_only_known_fields_and_take_precedence(self):
        other = snapshot(self.fx.root / "models" / "planner-b", planner=True)
        config = load_config(self.fx.write_config(), {"planner_model": other, "device": "cuda:1"})
        self.assertEqual(config.planner.model_path, other.resolve())
        self.assertEqual((config.planner.device, config.asr.device), ("cuda:1", "cuda:1"))
        with self.assertRaises(PipelineError):
            apply_overrides(self.fx.values(), {"temperature": 1})
        values = self.fx.values()
        del values["asr"]
        with self.assertRaises(PipelineError):
            apply_overrides(values, {"asr_model": "x"})

    def test_parameter_budget(self):
        self.assertEqual(check_parameter_budget(4_000_000_000, 1_000_000_000)["status"], "checked_from_headers")
        self.assertEqual(check_parameter_budget(4_000_000_000, None)["status"], "verified_after_load")
        for planner, asr in ((5_000_000_000, 1), (4_500_000_000, 1_500_000_000)):
            with self.subTest(planner=planner, asr=asr), self.assertRaises(PipelineError):
                check_parameter_budget(planner, asr)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.fx = IntegrationFixture(2)
        self.addCleanup(self.fx.close)
        self.loaded = []

    def loader(self, config, dataset):
        self.loaded.append(config)
        return load_runtime(config, dataset)

    def check(self, values=None):
        return preflight(load_config(self.fx.write_config(values)), runtime_loader=self.loader)

    def assert_rejected_before_runtime(self, values, code="MODEL_UNAVAILABLE"):
        with self.assertRaises(PipelineError) as caught:
            self.check(values)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.loaded, [], "Invalid settings must fail before runtime/ToolEnv setup")

    def test_valid_preflight_records_identity_without_environment(self):
        result = self.check()
        self.assertEqual(result.identity["planner"]["parameter_count"], 100)
        self.assertEqual(result.identity["parameter_budget"]["status"], "checked_from_headers")
        self.assertIn("model.safetensors", result.identity["planner"]["files"])
        self.assertEqual(len(result.identity["planner"]["template_sha256"]), 64)
        self.assertEqual(result.identity["dataset"]["selected_ids"], ["train_0001", "train_0002"])
        self.assertEqual(len(result.run_sha256), 64)
        self.assertEqual(result.runtime.opened, set(), "Preflight must not open a ToolEnv")

    def test_absent_snapshot_incompatible_template_and_wrong_family(self):
        values = self.fx.values()
        values["planner"]["model_path"] = self.fx.root / "missing"
        self.assert_rejected_before_runtime(values)
        legacy = snapshot(self.fx.root / "models" / "legacy", planner=True, template="{{ messages }}")
        values = self.fx.values()
        values["planner"]["model_path"] = legacy
        self.assert_rejected_before_runtime(values)
        llama = snapshot(self.fx.root / "models" / "llama", planner=True, model_type="llama")
        values = self.fx.values()
        values["planner"]["model_path"] = llama
        self.assert_rejected_before_runtime(values)
        values = self.fx.values()
        values["asr"]["model_path"] = self.fx.planner
        self.assert_rejected_before_runtime(values)

    def test_context_and_parameter_limits(self):
        short = snapshot(self.fx.root / "models" / "short", planner=True, positions=8192)
        values = self.fx.values()
        values["planner"]["model_path"] = short
        self.assert_rejected_before_runtime(values)
        big = snapshot(self.fx.root / "models" / "big", planner=True, parameters=5_000_000_000)
        values = self.fx.values()
        values["planner"]["model_path"] = big
        self.assert_rejected_before_runtime(values)

    def test_invalid_selection_fails_before_runtime(self):
        self.fx.selection.write_text("train_0001\ntrain_0001\n", encoding="utf-8")
        self.assert_rejected_before_runtime(None, "INPUT_INVALID")
        self.fx.selection.write_text("train_9999\n", encoding="utf-8")
        self.assert_rejected_before_runtime(None, "INPUT_INVALID")

    def test_model_change_changes_run_identity(self):
        first = self.check()
        (self.fx.planner / "model.safetensors").write_bytes(
            (self.fx.planner / "model.safetensors").read_bytes() + b"\0")
        self.assertNotEqual(first.run_sha256, self.check().run_sha256)


if __name__ == "__main__":
    unittest.main()
