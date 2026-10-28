"""Opt-in organizer integration, never part of an ordinary model-free run."""
import os
import tempfile
import unittest
from pathlib import Path

from lifemate.agent import run_sample
from lifemate.artifacts import Trace
from lifemate.contracts import Limits, RunConfig
from lifemate.dataset import preflight
from lifemate.runtime import load_runtime
from support import FINISH, ControlledPlanner, call

ENABLED = all(os.environ.get(k) for k in (
    "LIFEMATE_REAL_DATA_ROOT", "LIFEMATE_REAL_SAMPLE_ID", "LIFEMATE_RUNTIME_DIR"))


@unittest.skipUnless(ENABLED, "Opt in with all three LIFEMATE_REAL_* / LIFEMATE_RUNTIME_DIR variables")
class SuppliedRuntimeSmoke(unittest.TestCase):
    def test_one_read_call_has_authoritative_log_hash_and_terminal_trace(self):
        config = RunConfig(data_root=Path(os.environ["LIFEMATE_REAL_DATA_ROOT"]).resolve(),
                           runtime_dir=Path(os.environ["LIFEMATE_RUNTIME_DIR"]).resolve(),
                           split="train", input_mode="transcript",
                           selected_ids=(os.environ["LIFEMATE_REAL_SAMPLE_ID"],))
        dataset = preflight(config)
        factory = load_runtime(config, dataset)
        sample = dataset.samples[0]
        candidates = [t for t in sample.tools if t["kind"] == "read"
                      and not t["parameters"].get("required")
                      and not t["parameters"].get("x-one-of")]
        if not candidates:
            self.skipTest("Select a Train sample with an allowed parameter-free read")
        planner = ControlledPlanner([call(candidates[0]["name"]), FINISH])
        with tempfile.TemporaryDirectory() as directory:
            trace = Trace(Path(directory) / "trace.jsonl", "runtime-smoke", sample.id, payloads=True)
            try:
                outcome = run_sample(sample, planner, None, factory, trace, Limits(),
                                     split="train", data_root=config.data_root)
            finally:
                trace.close()
            self.assertEqual(outcome.status, "completed", outcome.error)
            self.assertEqual(len(outcome.result["tool_calls"]), 1)
            self.assertEqual(outcome.result["tool_calls"][0]["name"], candidates[0]["name"])
            self.assertEqual(len(outcome.result["state_hash"]), 64)
            self.assertEqual(factory.opened, {sample.id})
            self.assertIn('"kind":"sample_finished"', (Path(directory) / "trace.jsonl").read_text(encoding="utf-8"))
