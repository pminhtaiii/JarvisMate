"""Strict integration configuration and metadata preflight (no models, no ToolEnv)."""
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from lifemate.configuration import (apply_overrides, check_parameter_budget, load_config,
                                    parse_config, preflight)
from lifemate.contracts import PipelineError
from lifemate.jsonio import canonical_sha256, digest, loads
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
        self.assertEqual(config.soft_timeout_seconds, 28)
        self.assertFalse(config.reuse_kv_cache)
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

    def test_kv_switch_is_strict_and_changes_effective_identity(self):
        baseline = load_config(self.fx.write_config())
        enabled = load_config(self.fx.write_config(self.changed("execution", reuse_kv_cache=True)))
        self.assertTrue(enabled.reuse_kv_cache)
        self.assertTrue(enabled.record()["execution"]["reuse_kv_cache"])
        self.assertNotEqual(baseline.fingerprint(), enabled.fingerprint())
        self.assertTrue(parse_config(enabled.record(), self.fx.root).reuse_kv_cache)
        from unittest.mock import patch
        from lifemate.integration import build_components

        with patch("lifemate.adapters.asr.LocalASR") as asr, patch("lifemate.adapters.qwen_native.NativePlanner") as planner:
            asr.return_value.metadata = {"parameter_count": 50}
            planner.return_value.metadata = {"parameter_count": 100}
            build_components(enabled)
            self.assertIs(planner.call_args.kwargs["reuse_kv_cache"], True)
        for value in (0, 1, "true", "false", None):
            with self.subTest(value=value):
                raw = baseline.record()
                raw["execution"]["reuse_kv_cache"] = value
                with self.assertRaises(PipelineError):
                    parse_config(raw, self.fx.root)

    def test_skill_retrieval_is_opt_in_and_false_keeps_the_legacy_record(self):
        baseline = load_config(self.fx.write_config())
        explicit_false = load_config(self.fx.write_config(self.changed("execution", enable_skill_retrieval=False)))
        enabled = load_config(self.fx.write_config(self.changed("execution", enable_skill_retrieval=True)))

        self.assertFalse(baseline.enable_skill_retrieval)
        self.assertFalse(explicit_false.enable_skill_retrieval)
        self.assertNotIn("enable_skill_retrieval", baseline.record()["execution"])
        self.assertEqual(baseline.record(), explicit_false.record())
        self.assertEqual(baseline.fingerprint(), explicit_false.fingerprint())
        self.assertTrue(enabled.enable_skill_retrieval)
        self.assertTrue(enabled.record()["execution"]["enable_skill_retrieval"])
        self.assertNotEqual(baseline.fingerprint(), enabled.fingerprint())
        self.assertTrue(parse_config(enabled.record(), self.fx.root).enable_skill_retrieval)
        for value in (0, 1, "true", "false", None):
            with self.subTest(value=value):
                raw = baseline.record()
                raw["execution"]["enable_skill_retrieval"] = value
                with self.assertRaises(PipelineError):
                    parse_config(raw, self.fx.root)

    def test_invalid_devices_dtypes_types_and_limits_are_rejected(self):
        cases = [
            ("planner", {"device": "gpu"}), ("asr", {"device": "cuda:x"}),
            ("planner", {"dtype": "int4"}), ("planner", {"dtype": "float16"}),  # float16 on CPU
            ("planner", {"offload": True}),  # offload without CUDA
            ("planner", {"context_tokens": 16385}), ("planner", {"max_new_tokens": 16384}),
            ("planner", {"protocol": "lifemate-react-v4"}), ("asr", {"backend": "wav2vec"}),
            ("execution", {"timeout_seconds": 30.5}), ("execution", {"timeout_seconds": 0}),
            ("execution", {"timeout_seconds": True}), ("execution", {"max_steps": 0}),
            ("execution", {"soft_timeout_seconds": 0}), ("execution", {"soft_timeout_seconds": -1}),
            ("execution", {"soft_timeout_seconds": 30}), ("execution", {"soft_timeout_seconds": 31}),
            ("execution", {"soft_timeout_seconds": True}), ("execution", {"soft_timeout_seconds": "26"}),
            ("execution", {"soft_timeout_seconds": float("nan")}),
            ("execution", {"soft_timeout_seconds": float("inf")}),
            ("execution", {"timeout_seconds": 28}),  # Omitted soft budget still defaults to 28.
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

    def test_documented_example_matches_the_strict_schema(self):
        import tomllib
        from pathlib import Path

        example = Path(__file__).resolve().parents[2] / "configs" / "integration.example.toml"
        config = parse_config(tomllib.loads(example.read_text(encoding="utf-8")), self.fx.root)
        self.assertEqual((config.planner.protocol, config.timeout_seconds, config.recovery_attempts),
                         ("qwen-native-v1", 30.0, 1))
        self.assertEqual(config.planner.device, "cuda:0")
        self.assertEqual(config.soft_timeout_seconds, 28)
        self.assertFalse(config.enable_skill_retrieval)

    def test_explicit_soft_budget_overrides_default_and_round_trips(self):
        config = load_config(self.fx.write_config(self.changed("execution", soft_timeout_seconds=26)))
        self.assertEqual(config.soft_timeout_seconds, 26)
        self.assertEqual(parse_config(config.record(), self.fx.root).soft_timeout_seconds, 26)

    def test_integration_dataclass_default_is_28(self):
        from lifemate.configuration import IntegrationConfig

        settings = dict(vars(load_config(self.fx.write_config(self.changed("execution", soft_timeout_seconds=26)))))
        del settings["soft_timeout_seconds"]
        self.assertEqual(IntegrationConfig(**settings).soft_timeout_seconds, 28)

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

    def test_invalid_soft_budget_fails_preflight_before_runtime(self):
        values = self.fx.values()
        values["execution"]["soft_timeout_seconds"] = 30
        self.assert_rejected_before_runtime(values, "INPUT_INVALID")

    def test_model_change_changes_run_identity(self):
        first = self.check()
        (self.fx.planner / "model.safetensors").write_bytes(
            (self.fx.planner / "model.safetensors").read_bytes() + b"\0")
        self.assertNotEqual(first.run_sha256, self.check().run_sha256)

    def test_enabled_run_identity_binds_skill_library_version_and_hash(self):
        values = self.fx.values()
        values["execution"]["enable_skill_retrieval"] = True
        module = ModuleType("lifemate.skills")
        catalog_path = self.fx.data / "train" / "train_tools_catalog.json"
        catalog = loads(catalog_path.read_text(encoding="utf-8"))
        fingerprints = {"train": {"schema_version": catalog["schema_version"],
                                  "sha256": digest(catalog_path),
                                  "canonical_sha256": canonical_sha256(catalog)}}
        module.load_library = lambda: SimpleNamespace(version="skills-v1", sha256="a" * 64,
                                                       catalog_fingerprints=fingerprints)

        with patch.dict(sys.modules, {"lifemate.skills": module}):
            first = self.check(values)
            self.assertEqual(first.identity["skill_library"], {"version": "skills-v1", "sha256": "a" * 64})
            module.load_library = lambda: SimpleNamespace(version="skills-v1", sha256="b" * 64,
                                                           catalog_fingerprints=fingerprints)
            second = self.check(values)

        self.assertNotEqual(first.run_sha256, second.run_sha256)
        from lifemate.artifacts import RunJournal

        root = self.fx.root / "skill-identity-run"
        journal = RunJournal.create(root, {"run_sha256": first.run_sha256})
        journal.close()
        with self.assertRaises(PipelineError) as caught:
            RunJournal.resume(root, {"run_sha256": second.run_sha256})
        self.assertEqual(caught.exception.code, "INPUT_INVALID")
        self.assertNotIn("skill_library", self.check(self.fx.values()).identity)

    def test_skill_catalog_mismatch_fails_before_runtime_load(self):
        values = self.fx.values()
        values["execution"]["enable_skill_retrieval"] = True
        module = ModuleType("lifemate.skills")
        module.load_library = lambda: SimpleNamespace(
            version="skills-v1", sha256="a" * 64,
            catalog_fingerprints={"train": {"schema_version": 1, "sha256": "b" * 64}})
        with patch.dict(sys.modules, {"lifemate.skills": module}):
            with self.assertRaises(PipelineError) as caught:
                self.check(values)
        self.assertEqual(caught.exception.code, "CATALOG_INVALID")
        self.assertEqual(self.loaded, [])

    def test_equivalent_catalog_bytes_keep_validation_but_change_run_provenance(self):
        import json

        values = self.fx.values()
        values["execution"]["enable_skill_retrieval"] = True
        catalog_path = self.fx.data / "train" / "train_tools_catalog.json"
        catalog = loads(catalog_path.read_text(encoding="utf-8"))
        module = ModuleType("lifemate.skills")
        module.load_library = lambda: SimpleNamespace(
            version="skills-v1", sha256="a" * 64, catalog_fingerprints={"train": {
                "schema_version": catalog["schema_version"], "sha256": digest(catalog_path),
                "canonical_sha256": canonical_sha256(catalog)}})
        with patch.dict(sys.modules, {"lifemate.skills": module}):
            first = self.check(values)
            catalog_path.write_text(json.dumps(catalog, ensure_ascii=True, indent=4), encoding="utf-8")
            second = self.check(values)
        self.assertEqual(first.identity["dataset"]["catalog_canonical_sha256"],
                         second.identity["dataset"]["catalog_canonical_sha256"])
        self.assertNotEqual(first.identity["dataset"]["catalog_sha256"],
                            second.identity["dataset"]["catalog_sha256"])
        self.assertNotEqual(first.run_sha256, second.run_sha256)



class CommandTests(unittest.TestCase):
    """CLI precedence, check-config, checkpoint switching and provenance (controlled worker)."""

    def setUp(self):
        import json
        import os
        import sys
        from pathlib import Path

        self.fx = IntegrationFixture(2)
        self.addCleanup(self.fx.close)
        tests = Path(__file__).resolve().parent
        markers = self.fx.root / "markers"
        markers.mkdir()
        self.worker = [sys.executable, "-m", "lifemate.worker", "--factory", "integration_doubles:factory"]
        self.env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(tests.parent / "src"), str(tests)]),
                        LIFEMATE_TEST_BEHAVIORS="{}", LIFEMATE_TEST_MARKERS=str(markers))
        self.json = json

    def run_cli(self, *extra, output=None):
        import contextlib
        import io

        from lifemate import integration

        values = self.fx.values()
        values["execution"]["timeout_seconds"] = 5
        values["execution"]["soft_timeout_seconds"] = 4
        if output is not None:
            values["output"]["root"] = output
        argv = ["--config", str(self.fx.write_config(values)), *map(str, extra)]
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
            code = integration.main(argv, worker_command=self.worker, worker_env=self.env)
        return code, self.json.loads(stdout.getvalue().strip().splitlines()[-1])

    def test_check_config_validates_without_run_artifacts_or_workers(self):
        code, result = self.run_cli("--check-config")
        self.assertEqual((code, result["status"]), (0, "validated"))
        self.assertFalse(self.fx.output.exists(), "check-config creates no run, worker or ToolEnv")
        self.assertEqual(result["effective_config"]["planner"]["protocol"], "qwen-native-v1")
        self.assertIn("template_sha256", result["identity"]["planner"])

    def test_invalid_override_fails_before_any_run_directory(self):
        code, result = self.run_cli("--device", "gpu0")
        self.assertEqual((code, result["error"]["code"]), (2, "INPUT_INVALID"))
        self.assertFalse(self.fx.output.exists())

    def test_compatible_checkpoint_switch_needs_no_code_change_and_changes_identity(self):
        other = snapshot(self.fx.root / "models" / "planner-finetuned", planner=True, parameters=200)
        first_code, first = self.run_cli(output=self.fx.root / "run-a")
        second_code, second = self.run_cli("--planner-model", other, output=self.fx.root / "run-b")
        self.assertEqual((first_code, second_code), (0, 0))
        manifests = [self.json.loads((self.fx.root / name / "manifest.json").read_text(encoding="utf-8"))
                     for name in ("run-a", "run-b")]
        self.assertEqual(manifests[1]["effective_config"]["planner"]["model_path"], other.resolve().as_posix())
        self.assertNotEqual(manifests[0]["run_sha256"], manifests[1]["run_sha256"])
        for manifest in manifests:
            self.assertIn("platform", manifest["host"])
            startup = manifest["timings"]["startup"][0]
            self.assertEqual(startup["status"], "ready")
            self.assertIn("cpu_count", startup["hardware"])
            self.assertIn("planner", startup["models"])
            self.assertIn("packaging_seconds", manifest["timings"])

    def test_resume_with_switched_model_is_rejected(self):
        other = snapshot(self.fx.root / "models" / "planner-other", planner=True, parameters=300)
        self.assertEqual(self.run_cli()[0], 0)
        code, result = self.run_cli("--resume", "--planner-model", other)
        self.assertEqual((code, result["error"]["code"]), (2, "INPUT_INVALID"))


if __name__ == "__main__":
    unittest.main()
