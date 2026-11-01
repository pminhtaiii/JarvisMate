"""Opt-in visible Train checks for native expansion/history/audit (skipped by default).

Set LIFEMATE_LLM_REAL_DATA_ROOT to the directory containing train/. Reads only the
visible JSONL/catalog and the pure organizer validator; never ToolEnv or *_environment.
This is a development regression, not RV006 audit acceptance.
"""
import os
import unittest
from collections import Counter
from pathlib import Path

ROOT = os.environ.get("LIFEMATE_LLM_REAL_DATA_ROOT")


@unittest.skipUnless(ROOT, "set LIFEMATE_LLM_REAL_DATA_ROOT to enable")
class RealTrainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from lifemate.jsonio import digest
        from lifemate.llm_training.audit import audit_expansion, load_organizer_validator
        from lifemate.llm_training.config import CATALOG_SHA256, DATASET_SHA256
        from lifemate.llm_training.data import expand_source, load_catalog, read_train

        data = Path(ROOT) / "train"
        if digest(data / "train.jsonl") != DATASET_SHA256 or digest(data / "train_tools_catalog.json") != CATALOG_SHA256:
            raise unittest.SkipTest("data root is not the pinned Train release")
        sources = read_train(data / "train.jsonl")
        _, specs = load_catalog(data / "train_tools_catalog.json")
        validator = load_organizer_validator(Path(__file__).resolve().parents[2] / "tools" / "train")
        partition = {"sources": {s.id: {"partition": "fit", "group": "unsplit"} for s in sources}}
        cls.types, cls.expansions, cls.audits = Counter(), {}, {}
        for source in sources:
            expansion = expand_source(source, partition, specs, {"protocol": "qwen3-native-next-action-v1"})
            records = audit_expansion(expansion, specs, validator)
            cls.types.update(r["target_type"] for r in records)
            cls.expansions[source.id], cls.audits[source.id] = expansion, records

    def test_raw_candidate_counts_match_the_reviewed_audit(self):
        self.assertEqual(dict(self.types), {"normal_call": 3324, "ask_missing_info": 217,
                                            "finish_after_calls": 1217, "initial_finish": 111})

    def test_fit_history_anchors_project_text_calls_and_ordered_results(self):
        def history_roles(sample_id):
            messages = self.expansions[sample_id]["candidates"][0]["row"]["input"]["messages"]
            return [(m["role"], len(m.get("tool_calls") or [])) for m in messages[1:-1]]

        self.assertEqual(history_roles("train_0008")[1:3], [("assistant", 1), ("tool", 0)])
        roles = history_roles("train_0069")
        assistants = [i for i, (role, _) in enumerate(roles) if role == "assistant"]
        self.assertEqual(roles[assistants[2]], ("assistant", 2))  # history[5]: tv.guide + tv.tune.
        self.assertEqual(roles[assistants[2] + 1:assistants[2] + 3], [("tool", 0), ("tool", 0)])
        self.assertEqual(roles[assistants[4]], ("assistant", 0))  # history[9]: text only.

    def test_train_1696_dependent_quarantine(self):
        records = self.audits["train_1696"]
        self.assertEqual((records[2]["status"], records[3]["status"]), ("quarantined", "quarantined"))
        self.assertIn("UNGROUNDED_ID", records[2]["reasons"])
        self.assertIn("DEPENDENT_FINISH", records[3]["reasons"])


if __name__ == "__main__":
    unittest.main()
