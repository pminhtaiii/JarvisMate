"""Worker startup binds enabled retrieval to the preflight skill identity."""
import json
import unittest
from types import SimpleNamespace

from lifemate.configuration import load_config
from lifemate.contracts import PipelineError
from lifemate.jsonio import digest, loads
from lifemate.worker import Worker
from integration_support import IntegrationFixture


class WorkerSkillIdentityTests(unittest.TestCase):
    def setUp(self):
        self.fx = IntegrationFixture()
        self.addCleanup(self.fx.close)

    def setup_run(self, *, actual_hash="a" * 64, expected_hash="a" * 64, catalog_hash=None):
        values = self.fx.values()
        values["execution"]["enable_skill_retrieval"] = True
        config = load_config(self.fx.write_config(values))
        root = self.fx.root / "worker-run"
        (root / "workers").mkdir(parents=True)
        (root / "effective-config.json").write_text(json.dumps(config.record()), encoding="utf-8")
        (root / "manifest.json").write_text(json.dumps({"identity": {"skill_library": {
            "version": "skills-v1", "sha256": expected_hash}}}), encoding="utf-8")
        catalog_path = self.fx.data / "train" / "train_tools_catalog.json"
        catalog = loads(catalog_path.read_text(encoding="utf-8"))
        library = SimpleNamespace(
            catalog_fingerprints={"train": {
                "schema_version": catalog["schema_version"],
                "sha256": catalog_hash if catalog_hash is not None else digest(catalog_path)}},
            version="skills-v1", sha256=actual_hash)
        environments = object()

        def factory(_config):
            return {"skill_library": library,
                    "skill_library_identity": {"version": library.version, "sha256": library.sha256},
                    "planner": object(), "metadata": {}, "environment_factory": environments}

        return root, factory

    def test_matching_identity_starts_worker_without_loading_a_model_or_environment(self):
        root, factory = self.setup_run()
        worker = Worker(root, 1, factory, None)
        self.addCleanup(worker.lock.release)
        self.assertEqual(worker.ready["metadata"], {})
        self.assertIsNotNone(worker.environments)

    def test_changed_library_hash_is_rejected_at_worker_startup(self):
        root, factory = self.setup_run(actual_hash="b" * 64)
        with self.assertRaises(PipelineError) as caught:
            Worker(root, 1, factory, None)
        self.assertEqual(caught.exception.code, "RUN_IDENTITY")

    def test_changed_catalog_is_rejected_before_environment_setup(self):
        root, factory = self.setup_run(catalog_hash="b" * 64)
        with self.assertRaises(PipelineError) as caught:
            Worker(root, 1, factory, None)
        self.assertEqual(caught.exception.code, "CATALOG_INVALID")


if __name__ == "__main__":
    unittest.main()
