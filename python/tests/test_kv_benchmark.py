"""Benchmark orchestration/reporting without loading weights, tools or a GPU."""
import json
import unittest
import uuid
from pathlib import Path

from lifemate.artifacts import RunJournal
from lifemate.configuration import load_config
from lifemate.contracts import AttemptIdentity, PipelineError
from lifemate.kv_benchmark import SMOKE16, compare, prepare
from integration_support import IntegrationFixture


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.fixture = IntegrationFixture()
        self.addCleanup(self.fixture.close)
        self.ids = self.fixture.root / "ids.txt"
        self.ids.write_text("\n".join(SMOKE16) + "\n", encoding="utf-8")
        values = self.fixture.values()
        values["data"]["split"] = "public_test"
        self.base = self.fixture.write_config(values)
        self.root = self.fixture.root / "benchmark"

    def test_prepare_changes_only_cache_selection_and_new_output_roots(self):
        baseline = load_config(self.base).record()
        paths = prepare(self.base, self.ids, self.root)
        for path, enabled in zip(paths, (False, True)):
            record = load_config(path).record()
            self.assertEqual(record["execution"]["reuse_kv_cache"], enabled)
            self.assertEqual(record["planner"], baseline["planner"])
            self.assertEqual(record["asr"], baseline["asr"])
            self.assertTrue(Path(record["output"]["root"]).is_relative_to(self.root))
            self.assertEqual(Path(record["data"]["sample_ids_file"]).read_text(encoding="utf-8"),
                             self.ids.read_text(encoding="utf-8"))
        self.assertEqual(load_config(self.base).record(), baseline)
        with self.assertRaises(FileExistsError):
            prepare(self.base, self.ids, self.root)

    def test_refuse_any_selection_except_the_requested_16(self):
        self.ids.write_text(SMOKE16[0] + "\n", encoding="utf-8")
        with self.assertRaises(PipelineError):
            prepare(self.base, self.ids, self.root)
        self.assertFalse(self.root.exists())

    def make_trial(self, mode, *, altered=False, missing_tokens=False):
        root = self.root / mode
        journal = RunJournal.create(root, {"run_sha256": "r" * 64})
        journal.worker_started(1, 1)
        try:
            for sample_id in SMOKE16:
                attempt = AttemptIdentity(sample_id, uuid.uuid4().hex, 1, "c" * 64)
                journal.reserve(attempt)
                decision = {"canonical_action": {"action": "finish"}, "generated_token_ids": [3, 9],
                            "planner_prefill_seconds": 0.2, "planner_decode_seconds": 0.3}
                if missing_tokens:
                    del decision["generated_token_ids"]
                metrics = {"attempt_seconds": 0.8, "worker": {"metrics": {
                    "planner": {"kv_cache_reused_tokens": 50, "kv_cache_new_prefill_tokens": 50},
                    "decisions": [decision]}, "peak_memory_bytes": {"cuda:0": 1234}}}
                prediction = {"id": sample_id, "tool_calls": [], "state_hash": ("b" if altered else "a") * 64}
                journal.accept(attempt, "completed", prediction, metrics)
        finally:
            journal.close()
        config = load_config(self.root / f"{mode}.toml").record()
        identity = {"planner": {}, "asr": {}, "dataset": {"selected_ids": list(SMOKE16)},
                    "code": {}, "packages": {}, "runtime_source_sha256": "r"}
        manifest = {"identity": identity, "effective_config": config, "timings": {"startup": []},
                    "host": {"visible_devices": "same-gpu", "nvidia_smi": ["same-uuid"]}, "report": {"completed": 16}}
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_comparison_uses_tokens_actions_authoritative_rows_and_measured_times(self):
        prepare(self.base, self.ids, self.root)
        self.make_trial("off")
        self.make_trial("on")
        report = compare(self.root)
        self.assertTrue(report["outputs_equivalent"])
        self.assertTrue(report["compatible_inputs"])
        sample = report["on"]["samples"][SMOKE16[0]]
        self.assertEqual(sample["sample_seconds"], 0.8)
        self.assertEqual(sample["reused_token_ratio"], 0.5)
        self.assertEqual(sample["peak_gpu_memory_bytes"], {"cuda:0": 1234})

    def test_different_output_or_missing_token_measurement_is_not_equivalence(self):
        prepare(self.base, self.ids, self.root)
        self.make_trial("off")
        self.make_trial("on", altered=True, missing_tokens=True)
        report = compare(self.root)
        self.assertFalse(report["outputs_equivalent"])
        self.assertIsNone(report["comparison"][SMOKE16[0]]["tokens_equal"])
        self.assertFalse(report["comparison"][SMOKE16[0]]["prediction_equal"])
