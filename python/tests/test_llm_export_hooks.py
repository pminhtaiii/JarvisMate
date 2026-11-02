"""Model-free export/acceptance artifact guards; these are not model/Docker results."""
import unittest
from pathlib import Path

from lifemate.llm_training.config import load_config
from lifemate.llm_training.corpus import prepare, load_suite
from lifemate.llm_training.export import export_identity
from lifemate.llm_training.storage import write_json, seal, file_hash
from lifemate.llm_training.tokenization import proof_binding
from lifemate.llm_training.reporting import paired_bootstrap
from llm_support import SuiteFixture


class ExportArtifactTests(unittest.TestCase):
    def setUp(self):
        self.fx = SuiteFixture()
        self.addCleanup(self.fx.close)
        self.config = load_config(self.fx.config_path)
        prepare(self.config, self.fx.suite, expected=self.fx.expected)
        self.directory = self.fx.suite/"exports/controlled"
        model = self.directory/"model"
        model.mkdir(parents=True)
        names = ["config.json", "tokenizer_config.json", "tokenizer.json", "LICENSE", "native-format-contract.json", "model.safetensors"]
        for name in names:
            (model/name).write_bytes(b"controlled artifact fixture, never loaded as weights")
        files = {name:file_hash(model/name) for name in names}
        write_json(self.directory/"export-manifest.json", {"schema":"lifemate-native-export-v1", "representation":"merged_fp16",
            "training_status":"completed_full_budget", "logical_parameters":4022468096,
            "native_binding":proof_binding(self.fx.model), "suite_seal":load_suite(self.fx.suite)["seal"]["identity"],
            "model_files":files, "experiment":"L1", "checkpoint_identity":"c"*64, "base":{"controlled":True},
            "training_binding":{"controlled":True}})
        seal(self.directory,["export-manifest.json",*["model/"+n for n in names]])

    def test_exported_manifest_is_not_fresh_process_verification(self):
        identity = export_identity(self.directory, self.config, self.fx.suite, require_verified=False)
        self.assertEqual(identity["export_status"],"unverified")
        with self.assertRaises(ValueError):
            export_identity(self.directory, self.config, self.fx.suite)

    def test_passed_marker_without_two_workers_is_rejected(self):
        from lifemate.llm_training import export
        identity = export_identity(self.directory,self.config,self.fx.suite,require_verified=False)
        verification = self.fx.suite/"export-verifications/controlled"
        verification.mkdir(parents=True)
        write_json(verification/"reload-check.json", {"status":"passed", "export_identity":identity["identity"],
            "binding":proof_binding(self.fx.model), "independent_reloads":2, "child_exits":[0,0],
            "verification_code_sha256":file_hash(Path(export.__file__))})
        seal(verification,["reload-check.json"])
        with self.assertRaises(ValueError):
            export_identity(self.directory,self.config,self.fx.suite)

    def test_changed_weight_asset_is_detected_before_model_import(self):
        (self.directory/"model/model.safetensors").write_bytes(b"changed")
        with self.assertRaises(Exception):
            export_identity(self.directory,self.config,self.fx.suite,require_verified=False)


class ReportUncertaintyTests(unittest.TestCase):
    def test_deployment_outcomes_must_match_the_hash_bound_asset(self):
        import tempfile
        from unittest.mock import patch
        from lifemate.llm_training.deployment import deployment_check
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_json(root/"asset.json", {"other":"evidence"})
            (root/"outcomes.jsonl").write_text('{}\n', encoding="utf-8")
            assets = {name:{"path":"asset.json", "sha256":file_hash(root/"asset.json")}
                      for name in ("container_manifest","supervisor_record","repeatability_record","submission","outcomes")}
            evidence = {"schema":"lifemate-a30-acceptance-v1", "host":{"gpu":"NVIDIA A30","cpu_cores":16,"ram_bytes":64_000_000_000},
                "offline_network_disabled":True,"container_digest":"fixture", "assets":assets,
                "logical_parameters":{"asr":1,"planner":1},"context_tokens":16384,
                "supervisor":{"hard_deadline_seconds":30,"kills_process_tree":True,"cleanup_verified":True,"implementation_sha256":"fixture"},
                "outcomes":"outcomes.jsonl", "repeatability":{"matched_authoritative_outputs":True,"independent_runs":2}}
            write_json(root/"acceptance.json", evidence)
            with patch("lifemate.llm_training.deployment.coverage", return_value={"full_coverage":True,"failed":0}):
                result = deployment_check(root/"acceptance.json", [])
            self.assertIn("outcomes_not_bound_to_acceptance_asset", result["issues"])
            self.assertFalse(result["submission_ready"])

    def test_group_resampling_preserves_paired_membership(self):
        partition={"validation_ids":["a","b","c"],"sources":{"a":{"group":"x"},"b":{"group":"x"},"c":{"group":"y"}}}
        baseline=[{"id":i,"tool_call_f1":.2} for i in partition["validation_ids"]]
        candidate=[{"id":i,"tool_call_f1":.5} for i in partition["validation_ids"]]
        result=paired_bootstrap(baseline,candidate,partition)
        self.assertEqual(result["available_resamples"],1000)
        self.assertEqual(result["interval_95"],[.3,.3])
        self.assertFalse(result["training_seed_uncertainty"])


if __name__ == "__main__":
    unittest.main()
