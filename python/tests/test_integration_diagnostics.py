"""Offline empty/clarification diagnostics with controlled journals and references."""
import json
import tempfile
import unittest
import uuid
from pathlib import Path

from lifemate.artifacts import RunJournal
from lifemate.contracts import AttemptIdentity
from lifemate.diagnostics import match_calls, paired, report, token_f1

CONFIG = "c" * 64
ASK = "sys.ask_missing_info"


def call(name, **arguments):
    return {"name": name, "arguments": arguments}


SEARCH = call("contacts.search", query="Lan")
SEND = call("sms.send", contact_id="c7", content="Đến trễ nhé")
ASK_CONTENT = call(ASK, tool_name="sms.send", params=["content"])
# id -> (gold calls, history turns, runtime status, predicted calls)
CASES = {
    "s01": ([], 0, "completed", []),                                   # valid empty
    "s02": ([], 0, "timeout", None),                                   # timeout is never an empty success
    "s03": ([SEARCH, SEND], 2, "completed", []),                       # false empty
    "s04": ([SEARCH, ASK_CONTENT], 0, "needs_info", [SEARCH, ASK_CONTENT]),  # clarification after calls
    "s05": ([SEND], 0, "completed", [call(ASK, tool_name="sms.send", params=["x"])]),  # unnecessary + unsuccessful
    "s06": ([ASK_CONTENT], 0, "needs_info", [call(ASK, tool_name="sms.send", params=["contact_id"])]),
    "s07": ([SEND], 0, "completed", [call("sms.send", contact_id="c7", content="đến trễ nhé!")]),  # fuzzy match
    "s08": ([SEARCH, SEND], 0, "failed", None),
}
CATALOG = {"apps": [{"id": "sms", "tools": [{"name": "sms.send", "parameters": {"type": "object", "properties": {
    "contact_id": {"type": "string"}, "content": {"type": "string", "x-match": "fuzzy"}}}}]}]}


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.references = self.root / "train.jsonl"
        self.references.write_text("".join(json.dumps({
            "id": i, "history": [{"role": "user"}, {"role": "assistant"}][:turns], "audio_text": "x",
            "label": {"tool_calls": gold, "tool_results": [], "final_state": {}}}, ensure_ascii=False) + "\n"
            for i, (gold, turns, _, _) in CASES.items()), encoding="utf-8")
        self.catalog = self.root / "catalog.json"
        self.catalog.write_text(json.dumps(CATALOG), encoding="utf-8")

    def run_root(self, name="run", cases=None):
        cases = cases or CASES
        journal = RunJournal.create(self.root / name, {"run_sha256": "r" * 64, "selected_ids": list(cases)})
        journal.worker_started(1, 1)
        for sample_id, (_, _, status, predicted) in cases.items():
            identity = AttemptIdentity(sample_id, uuid.uuid4().hex, 1, CONFIG)
            journal.reserve(identity)
            if predicted is None:
                journal.fail(identity, status, {"code": "TIME_LIMIT" if status == "timeout" else "PLANNER_FORMAT"})
            else:
                journal.accept(identity, status, {"id": sample_id, "tool_calls": predicted, "state_hash": "a" * 64}, {})
        journal.close()
        return self.root / name

    def test_empty_and_failure_denominators(self):
        summary = report(self.run_root(), self.references, self.catalog)["summary"]
        self.assertEqual(summary["empty"]["empty_gold_correct"], {"count": 1, "denominator": 2, "rate": 0.5})
        self.assertEqual(summary["empty"]["empty_gold_failed_or_timeout"], 1)
        self.assertEqual(summary["empty"]["false_empty"]["count"], 1)
        self.assertEqual(summary["empty"]["false_empty"]["denominator"], 6)
        self.assertEqual(summary["runtime_failures"]["timeout"], 1)
        self.assertEqual(summary["runtime_failures"]["failed"], 1)
        self.assertEqual(summary["samples"], 8)

    def test_clarification_presence_intended_tool_params_and_unnecessary(self):
        summary = report(self.run_root(), self.references, self.catalog)["summary"]["clarification"]
        self.assertEqual(summary["precision"], {"count": 2, "denominator": 3, "rate": 2 / 3})
        self.assertEqual(summary["recall"], {"count": 2, "denominator": 2, "rate": 1.0})
        self.assertEqual(summary["intended_tool_correct"]["count"], 2)
        self.assertEqual(summary["missing_params_correct"], {"count": 1, "denominator": 2, "rate": 0.5})
        self.assertEqual(summary["unnecessary"]["count"], 1)
        self.assertEqual(summary["unsuccessful"], 1, "Clarification without waiting_for_user is not success")

    def test_overlapping_groups_keep_their_own_denominators(self):
        groups = report(self.run_root(), self.references, self.catalog)["summary"]["groups"]
        self.assertEqual(groups["clarification_after_calls"]["exact_calls"], {"count": 1, "denominator": 1, "rate": 1.0})
        self.assertEqual(groups["multi_call"]["samples"], 3)
        self.assertEqual(groups["multi_call"]["failed_or_timeout"], 1)
        self.assertEqual(groups["history"]["samples"], 1)
        self.assertEqual(groups["single_call"]["exact_calls"], {"count": 1, "denominator": 2, "rate": 0.5})

    def test_unavailable_metrics_are_explicit(self):
        summary = report(self.run_root(), self.references, self.catalog)["summary"]
        self.assertIn("state_hash_match", summary["unavailable"])
        self.assertNotIn("score", summary)

    def test_partial_is_accepted_but_counted_separately_from_completion(self):
        cases = dict(CASES, s03=([SEARCH, SEND], 2, "partial", [SEARCH]))
        result = report(self.run_root(cases=cases), self.references, self.catalog)
        sample = next(r for r in result["samples"] if r["id"] == "s03")
        self.assertEqual((sample["status"], sample["accepted"], sample["exact_calls"]), ("partial", True, False))
        self.assertEqual(result["summary"]["accepted_statuses"], {"completed": 3, "needs_info": 2, "partial": 1})
        self.assertEqual(result["summary"]["accepted"], 6)

    def test_benchmark_call_matching(self):
        fuzzy = {"sms.send": {"content"}}
        self.assertGreater(token_f1("Đến trễ nhé!", "đến trễ nhé"), 0.6)
        self.assertEqual(match_calls([SEND, SEND], [SEND], fuzzy)["matched"], 1, "A gold call matches once")
        self.assertEqual(match_calls([call("sms.send", contact_id="c8", content="Đến trễ nhé")], [SEND], fuzzy)["matched"], 0)
        self.assertEqual(match_calls([], [], fuzzy)["f1_without_state_gate"], 1.0)
        self.assertEqual(match_calls([SEARCH], [], fuzzy)["f1_without_state_gate"], 0.0)

    def test_paired_transcript_audio_attribution(self):
        transcript = report(self.run_root("transcript"), self.references, self.catalog)["samples"]
        degraded = dict(CASES, s07=([SEND], 0, "completed", [call("sms.send", contact_id="c9", content="x")]))
        audio = report(self.run_root("audio", degraded), self.references, self.catalog)["samples"]
        result = paired(transcript, audio)
        self.assertEqual(result["speech_attributed_ids"], ["s07"])
        self.assertEqual(result["counts"]["failure_in_either"], 2)

    def test_inference_modules_never_import_diagnostics_or_labels(self):
        source = Path(__file__).resolve().parents[1] / "src" / "lifemate"
        for name in ("agent.py", "worker.py", "supervisor.py", "integration.py", "dataset.py",
                     "adapters/qwen_native.py", "configuration.py"):
            text = (source / name).read_text(encoding="utf-8")
            with self.subTest(module=name):
                self.assertNotRegex(text, r"(from \.|import lifemate\.|from lifemate\.)diagnostics")
                self.assertNotIn('["label"]', text)


if __name__ == "__main__":
    unittest.main()
