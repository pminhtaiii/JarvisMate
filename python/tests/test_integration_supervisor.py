"""Journal ownership/ordering and (later) supervisor deadline behavior."""
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from lifemate.artifacts import FileLock, RunJournal, publish_predictions
from lifemate.contracts import AttemptIdentity, PipelineError

CONFIG = "c" * 64
HEADER = {"run_sha256": "r" * 64, "config_sha256": CONFIG}


def identity(sample_id, generation=1):
    return AttemptIdentity(sample_id, uuid.uuid4().hex, generation, CONFIG)


def row(sample_id):
    return {"id": sample_id, "tool_calls": [], "state_hash": "a" * 64}


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "run"

    def journal(self):
        journal = RunJournal.create(self.root, HEADER)
        self.addCleanup(journal.close)
        journal.worker_started(1, 1234)
        return journal

    def test_reservation_is_durable_before_terminal_records(self):
        journal = self.journal()
        first = identity("train_0001")
        with self.assertRaises(PipelineError):
            journal.accept(first, "completed", row("train_0001"), {})  # No reservation yet.
        journal.reserve(first)
        with self.assertRaises(PipelineError):
            journal.reserve(identity("train_0002"))  # One active attempt at a time.
        journal.accept(first, "completed", row("train_0001"), {"elapsed": 1.0})
        with self.assertRaises(PipelineError):
            journal.reserve(identity("train_0001"))  # A sample is never reserved twice.
        with self.assertRaises(PipelineError):
            journal.fail(first, "timeout", {"code": "TIME_LIMIT"})  # Terminal states are immutable.
        lines = journal.path.read_text(encoding="utf-8").splitlines()
        self.assertEqual([__import__("json").loads(l)["type"] for l in lines],
                         ["run", "worker_started", "reserve", "accept"])

    def test_accepted_prediction_must_match_identity(self):
        journal = self.journal()
        first = identity("train_0001")
        journal.reserve(first)
        with self.assertRaises(PipelineError):
            journal.accept(first, "completed", row("train_0002"), {})
        with self.assertRaises(PipelineError):
            journal.accept(first, "timeout", row("train_0001"), {})

    def test_exclusive_run_ownership(self):
        journal = self.journal()
        with self.assertRaises(PipelineError) as caught:
            RunJournal.resume(self.root, HEADER)
        self.assertEqual(caught.exception.code, "RUN_OWNERSHIP")
        journal.close()
        RunJournal.resume(self.root, HEADER).close()

    def test_lock_is_released_when_the_owner_process_dies(self):
        path = Path(self.temp.name) / "worker.lock"
        script = ("import sys,time; sys.path.insert(0, sys.argv[2]);"
                  "from lifemate.artifacts import FileLock; l=FileLock(__import__('pathlib').Path(sys.argv[1]));"
                  "assert l.acquire(); print('locked', flush=True); time.sleep(60)")
        source = str(Path(__file__).resolve().parents[1] / "src")
        child = subprocess.Popen([sys.executable, "-c", script, str(path), source], stdout=subprocess.PIPE, text=True)
        self.addCleanup(child.stdout.close)
        self.addCleanup(child.kill)
        self.assertEqual(child.stdout.readline().strip(), "locked")
        self.assertFalse(FileLock(path).acquire())
        child.kill()
        child.wait(10)
        lock = FileLock(path)
        deadline = time.monotonic() + 10
        while not lock.acquire() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertIsNotNone(lock.handle)
        lock.release()

    def test_corrupt_or_truncated_journal_blocks_resume(self):
        journal = self.journal()
        journal.reserve(identity("train_0001"))
        journal.close()
        original = journal.path.read_bytes()
        for corrupted in (original[:-5], original.replace(b"train_0001", b"train_0009", 1), b""):
            with self.subTest(size=len(corrupted)):
                journal.path.write_bytes(corrupted)
                with self.assertRaises(PipelineError) as caught:
                    RunJournal.resume(self.root, HEADER)
                self.assertEqual(caught.exception.code, "JOURNAL_INVALID")

    def test_resume_rejects_different_identity(self):
        self.journal().close()
        with self.assertRaises(PipelineError) as caught:
            RunJournal.resume(self.root, {"run_sha256": "x" * 64})
        self.assertEqual(caught.exception.code, "INPUT_INVALID")

    def test_reserved_without_acceptance_becomes_uncertain_and_is_never_eligible(self):
        journal = self.journal()
        journal.reserve(identity("train_0001"))  # Supervisor dies here.
        journal.close()
        resumed = RunJournal.resume(self.root, HEADER)
        self.addCleanup(resumed.close)
        self.assertEqual(resumed.mark_uncertain(), ["train_0001"])
        self.assertIn("train_0001", resumed.attempted())
        self.assertEqual(resumed.failed()["train_0001"]["error"]["code"], "EXECUTION_UNCERTAIN")

    def test_write_failure_stops_further_writes(self):
        journal = self.journal()
        journal.path.unlink()
        journal.path.mkdir()  # Appending now raises OSError.
        with self.assertRaises(PipelineError):
            journal.reserve(identity("train_0001"))
        self.assertTrue(journal.broken)
        self.assertEqual(journal.attempted(), set())

    def test_publication_requires_exact_failure_free_coverage(self):
        journal = self.journal()
        for sample_id in ("train_0001", "train_0002"):
            attempt = identity(sample_id)
            journal.reserve(attempt)
            journal.accept(attempt, "completed", row(sample_id), {})
        partial = publish_predictions(journal, ["train_0001", "train_0002", "train_0003"])
        self.assertFalse(partial["complete"])
        self.assertEqual(partial["missing"], ["train_0003"])
        self.assertFalse((self.root / "predictions.jsonl").exists())
        attempt = identity("train_0003")
        journal.reserve(attempt)
        journal.fail(attempt, "timeout", {"code": "TIME_LIMIT"})
        failed = publish_predictions(journal, ["train_0001", "train_0002", "train_0003"])
        self.assertFalse(failed["complete"])
        self.assertEqual(failed["failed"], ["train_0003"])
        self.assertFalse(publish_predictions(journal, ["train_0001", "train_0002"])["complete"],
                         "Any recorded failure blocks complete publication")

    def test_complete_publication_follows_selection_order_once(self):
        journal = self.journal()
        for sample_id in ("train_0002", "train_0001"):
            attempt = identity(sample_id)
            journal.reserve(attempt)
            journal.accept(attempt, "needs_info" if sample_id.endswith("1") else "completed", row(sample_id), {})
        complete = publish_predictions(journal, ["train_0001", "train_0002"])
        self.assertTrue(complete["complete"])
        lines = (self.root / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([__import__("json").loads(l)["id"] for l in lines], ["train_0001", "train_0002"])
        with self.assertRaises(PipelineError):
            publish_predictions(journal, ["train_0001", "train_0002"])

    def test_unaccepted_staging_is_quarantined(self):
        journal = self.journal()
        attempt = identity("train_0001")
        journal.reserve(attempt)
        staged = journal.staging_dir(attempt.attempt_id)
        staged.mkdir()
        (staged / "prediction.json").write_text("{}", encoding="utf-8")
        self.assertEqual(journal.quarantine_unaccepted(), [attempt.attempt_id])
        self.assertTrue((journal.quarantine_root / attempt.attempt_id / "prediction.json").is_file())

    def test_staged_reads_are_constrained_to_the_attempt(self):
        journal = self.journal()
        for name in ("../journal.json", "Prediction.JSON", "x" * 40 + ".json"):
            with self.subTest(name=name), self.assertRaises(PipelineError):
                journal.read_staged(uuid.uuid4().hex, name)


if __name__ == "__main__":
    unittest.main()
