import unittest
from dataclasses import replace
from unittest.mock import patch

from lifemate.contracts import PipelineError
from lifemate.dataset import preflight
from lifemate.runtime import load_runtime
from support import Fixture


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.close)

    def test_one_factory_open_per_sample_without_reset(self):
        config = self.fx.config()
        factory = load_runtime(config, preflight(config))
        with patch.object(factory.module, "ToolEnv", return_value=object()) as constructor:
            factory("train", "train_0001", self.fx.data)
            with self.assertRaises(PipelineError):
                factory("train", "train_0001", self.fx.data)
            self.assertEqual(constructor.call_count, 1)

    def test_missing_catalog_fails_before_environment_open(self):
        (self.fx.split / "train_tools_catalog.json").unlink()
        with self.assertRaises(PipelineError):
            preflight(self.fx.config())

    def test_runtime_split_mismatch_fails(self):
        config = self.fx.config()
        with self.assertRaises(PipelineError):
            load_runtime(replace(config, runtime_dir=self.fx.runtime.parent / "test"), preflight(config))

    def test_catalog_mismatch_and_missing_implementation_fail(self):
        config = self.fx.config()
        data = preflight(config)
        factory = load_runtime(config, data)
        with patch.dict(factory.module.TOOLS, {}, clear=True), self.assertRaises(PipelineError):
            load_runtime(config, data)
        (self.fx.runtime.parent / "train_tools_catalog.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(PipelineError):
            load_runtime(config, data)

    def test_preflight_package_import_does_not_read_state(self):
        config = self.fx.config()
        data = preflight(config)
        original = type(self.fx.root).open

        def guard(path, *args, **kwargs):
            if "train_environment" in path.parts:
                self.fail("Runtime loader attempted hidden-file access")
            return original(path, *args, **kwargs)

        with patch("pathlib.Path.open", guard):
            load_runtime(config, data)
