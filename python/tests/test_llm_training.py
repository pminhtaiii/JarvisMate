"""Pure sampler, checkpoint selection, profiles and CLI manual boundaries."""
import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from lifemate.llm_training.trainer import BaseSampler, DEFAULTS, training_settings, learning_rate_multiplier
from lifemate.llm_training.checkpoints import checkpoint_key
from lifemate.llm_training.losses import mean_weight, weighted_objective
from lifemate.llm_training.asr_views import ViewSampler, approve_view, coverage_report
from lifemate.llm_training import cli
from llm_support import SuiteFixture, FakeQwenTokenizer
from lifemate.llm_training.config import load_config
from lifemate.llm_training.corpus import prepare
from lifemate.llm_training.storage import read_jsonl


class PureTrainingTests(unittest.TestCase):
    def test_uniform_base_order_partial_windows_and_resume(self):
        a, b = BaseSampler(19), BaseSampler(19)
        first = a.window(16)
        remaining = a.window(16)
        self.assertEqual(len(remaining), 3)
        self.assertEqual(set(first+remaining), set(range(19)))
        b.load_state_dict(a.state_dict())
        self.assertEqual(a.window(16), b.window(16))
        bad = a.state_dict() | {"size": 20}
        with self.assertRaises(ValueError):
            b.load_state_dict(bad)

    def test_global_weight_and_actual_partial_denominator(self):
        rows = [{"target_type": "normal"}, {"target_type": "ask"}]
        weights = {"normal": 1, "ask": 2}
        mu = mean_weight(rows, weights)
        self.assertEqual(mu, 1.5)
        self.assertEqual(weighted_objective(3., 2, mu, 1), 4.)
        self.assertEqual(weighted_objective(3., 2, mu, 2), 2.)
        self.assertEqual(weighted_objective(3., 2, mu, 2), 2*weighted_objective(3., 1, mu, 2))

    def test_nll_tie_prefers_earliest_step(self):
        self.assertLess(checkpoint_key(.1, 100), checkpoint_key(.1, 200))
        with self.assertRaises(ValueError):
            checkpoint_key(float("nan"), 100)

    def test_warmup_has_a_real_first_update_and_reaches_zero_only_after_budget(self):
        rates = [learning_rate_multiplier(i, 500, 25) for i in range(501)]
        self.assertEqual(rates[0], 1/25)
        self.assertEqual(rates[24], 1.)
        self.assertTrue(all(rate > 0 for rate in rates[:500]))
        self.assertEqual(rates[500], 0.)

    def test_wrappers_and_cli_have_no_automatic_dependencies(self):
        args = cli.parser().parse_args(["train", "--suite-dir", "x", "--experiment", "L2"])
        self.assertEqual(args.experiment, "L2")
        self.assertIsNone(args.resume_from)
        with self.assertRaises(cli.UsageError):
            cli.parser().parse_args(["train", "--all"])
        self.assertEqual(training_settings(Path(__file__).resolve().parents[2]/"fine-tune-llm/configs/training.json"), DEFAULTS)
        from lifemate.llm_training.config import load_experiment, EXPERIMENTS
        root = Path(__file__).resolve().parents[2]/"fine-tune-llm/configs"
        for experiment in EXPERIMENTS:
            self.assertEqual(load_experiment(root/(experiment.lower()+".json"),experiment)["weights"],EXPERIMENTS[experiment]["weights"])


class NoisyViewTests(unittest.TestCase):
    def setUp(self):
        self.fx = SuiteFixture()
        self.addCleanup(self.fx.close)
        prepare(load_config(self.fx.config_path), self.fx.suite, expected=self.fx.expected)
        self.clean = read_jsonl(self.fx.suite/"data/fit.clean.jsonl")[0]

    def test_only_surface_changes_auto_accept_and_full_prefix_is_required(self):
        noisy = copy.deepcopy(self.clean)
        result = approve_view(self.clean, noisy, ["chuyển 500"], ["chuyển 5000"])
        self.assertEqual(result["status"], "needs_review")
        result = approve_view(self.clean, noisy, ["Tìm Lan"], [" Tìm  Lan "])
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["category"], "unicode_whitespace")
        from lifemate.llm_training.storage import ordered_hash
        review = {"schema": "lifemate-asr-prefix-review-v1", "base_row_id": self.clean["provenance"]["base_row_id"],
                  "clean_sha256": ordered_hash(self.clean), "noisy_sha256": ordered_hash(noisy), "reviewer": "controlled",
                  "policy": "controlled", "evidence_paths": ["request.recipient"], "affected_slots": ["amount"],
                  "decision": "ACCEPT_UNAFFECTED_ROW", "full_original_prefix_valid": False}
        with self.assertRaises(ValueError):
            approve_view(self.clean, noisy, ["tìm Lan rồi chuyển 500"], ["tìm Lan rồi chuyển 5000"], review)
        review["full_original_prefix_valid"] = True
        review["difference_category"] = "non_surface_preserving"
        result = approve_view(self.clean, noisy, ["tìm Lan rồi chuyển 500"], ["tìm Lan rồi chuyển 5000"], review)
        self.assertEqual(result["decision"], "ACCEPT_UNAFFECTED_ROW")

    def test_view_rng_resume_preserves_base_sequence_and_coverage_is_limited(self):
        bid = self.clean["provenance"]["base_row_id"]
        noisy = copy.deepcopy(self.clean)
        sampler = ViewSampler({bid: [noisy]})
        for _ in range(7):
            sampler.choose(self.clean)
        state = sampler.state_dict()
        expected = [sampler.choose(self.clean)[1]["view"] for _ in range(10)]
        other = ViewSampler({bid: [noisy]})
        other.load_state_dict(state)
        self.assertEqual(expected, [other.choose(self.clean)[1]["view"] for _ in range(10)])
        self.assertEqual(other.counts, sampler.counts)
        self.assertTrue(coverage_report([self.clean], [approve_view(self.clean, noisy, ["a"], ["a"])])["limited_noisy_coverage"])


if __name__ == "__main__":
    unittest.main()
