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


# --- Supervisor: deadlines, IPC, recovery and crash windows (real subprocesses) ---

import contextlib
import io
import json
import os

from lifemate import integration
from lifemate.supervisor import Supervisor, lock_free
from integration_support import IntegrationFixture

TESTS = Path(__file__).resolve().parent
SOURCE = TESTS.parent / "src"
TIMEOUT = 2.0


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.fx = IntegrationFixture(3)
        self.addCleanup(self.fx.close)
        self.markers = self.fx.root / "markers"
        self.markers.mkdir()

    def environment(self, behaviors=None, startup=None):
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(SOURCE), str(TESTS)]),
                   LIFEMATE_TEST_BEHAVIORS=json.dumps(behaviors or {}), LIFEMATE_TEST_MARKERS=str(self.markers))
        env.pop("LIFEMATE_TEST_STARTUP", None)
        if startup:
            env["LIFEMATE_TEST_STARTUP"] = startup
        return env

    def config(self, output=None, **execution):
        values = self.fx.values()
        values["execution"].update(timeout_seconds=TIMEOUT, soft_timeout_seconds=1.75,
                                   startup_timeout_seconds=30)
        values["execution"].update(execution)
        values["output"]["root"] = output or self.fx.output
        return self.fx.write_config(values)

    def run_cli(self, behaviors=None, *, startup=None, resume=False, output=None, **execution):
        argv = ["--config", str(self.config(output, **execution))] + (["--resume"] if resume else [])
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
            code = integration.main(argv, worker_command=[sys.executable, "-m", "lifemate.worker", "--factory",
                                                          "integration_doubles:factory"],
                                    worker_env=self.environment(behaviors, startup))
        return code, json.loads(stdout.getvalue().strip().splitlines()[-1])

    def records(self, output=None):
        path = (output or self.fx.output) / "journal.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def terminal(self, output=None):
        return {r["sample_id"]: r for r in self.records(output) if r["type"] in {"accept", "fail"}}

    def opened(self, sample_id):
        return len(list(self.markers.glob(f"opened-{sample_id}-*")))

    def test_controlled_batch_completes_within_deadline_and_publishes(self):
        code, summary = self.run_cli({"train_0002": "lookup"})
        self.assertEqual((code, summary["status"]), (0, "completed"))
        rows = [json.loads(l) for l in (self.fx.output / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["id"] for r in rows], ["train_0001", "train_0002", "train_0003"])
        self.assertEqual([c["name"] for c in rows[1]["tool_calls"]], ["contacts.search", "sms.send"])
        for record in self.terminal().values():
            self.assertLess(record["metrics"]["attempt_seconds"], TIMEOUT)
            self.assertIn("timings", record["metrics"]["worker"])
        self.assertEqual([self.opened(f"train_000{n}") for n in (1, 2, 3)], [1, 1, 1])
        manifest = json.loads((self.fx.output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["timings"]["startup"]), 1)
        self.assertIsNotNone(manifest["timings"]["total_wall_seconds"])
        self.assertFalse(manifest["submission_ready"])

    def test_partial_batch_publishes_and_manifest_counts_partial_separately(self):
        code, summary = self.run_cli({"train_0001": "soft_planner"}, soft_timeout_seconds=0.25)
        self.assertEqual((code, summary["status"]), (0, "completed"))
        manifest = json.loads((self.fx.output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((manifest["report"]["completed"], manifest["report"]["partial"],
                          manifest["report"]["accepted"]), (2, 1, 3))
        self.assertIn("does not establish correctness", manifest["report"]["coverage_note"])
        rows = [json.loads(l) for l in (self.fx.output / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(set(r) == {"id", "tool_calls", "state_hash"} for r in rows))
        self.assertEqual(self.terminal()["train_0001"]["status"], "partial")
        self.assertEqual([self.opened(f"train_000{n}") for n in (1, 2, 3)], [1, 1, 1])

    def test_blocked_stages_time_out_and_a_later_sample_recovers(self):
        for stage in ("block_asr", "block_planner", "block_tool", "block_output"):
            with self.subTest(stage=stage):
                for path in self.markers.iterdir():
                    path.unlink()
                output = self.fx.root / f"out-{stage}"
                code, summary = self.run_cli({"train_0001": stage}, output=output)
                self.assertEqual(code, 1)
                terminal = self.terminal(output)
                self.assertEqual(terminal["train_0001"]["status"], "timeout")
                self.assertIs(terminal["train_0001"]["metrics"]["termination_confirmed"], True)
                self.assertGreaterEqual(terminal["train_0001"]["metrics"]["attempt_seconds"], TIMEOUT)
                self.assertGreaterEqual(terminal["train_0001"]["metrics"]["overshoot_seconds"], 0)
                self.assertGreaterEqual(terminal["train_0001"]["metrics"]["termination_seconds"], 0)
                self.assertEqual([terminal[i]["status"] for i in ("train_0002", "train_0003")],
                                 ["completed", "completed"])
                generations = {r["sample_id"]: r["generation"] for r in self.records(output) if r["type"] == "reserve"}
                self.assertEqual(generations, {"train_0001": 1, "train_0002": 2, "train_0003": 2})
                self.assertFalse((output / "predictions.jsonl").exists())
                partial = (output / "predictions.partial.jsonl").read_text(encoding="utf-8")
                self.assertNotIn("train_0001", partial)
                self.assertTrue(any((output / "quarantine").iterdir()))
                self.assertLessEqual(self.opened("train_0001"), 1)

    def test_worker_crash_after_mutation_is_uncertain_and_never_retried(self):
        code, _ = self.run_cli({"train_0001": "crash_tool"})
        self.assertEqual(code, 1)
        terminal = self.terminal()
        self.assertEqual((terminal["train_0001"]["status"], terminal["train_0001"]["error"]["code"]),
                         ("failed", "EXECUTION_UNCERTAIN"))
        self.assertEqual(self.opened("train_0001"), 1)
        self.assertEqual(terminal["train_0003"]["status"], "completed")

    def test_worker_reported_failure_keeps_the_healthy_worker(self):
        code, summary = self.run_cli({"train_0002": "fail_planner"})
        self.assertEqual(code, 1)
        self.assertEqual(summary["report"]["failures"], {"train_0002": "PLANNER_FORMAT"})
        self.assertEqual({r["generation"] for r in self.records() if r["type"] == "reserve"}, {1})

    def test_failed_recovery_stops_nonzero_and_keeps_accepted_rows(self):
        code, summary = self.run_cli({"train_0002": "block_planner"}, startup="block_recovery",
                                     startup_timeout_seconds=8)
        self.assertEqual(code, 1)
        self.assertEqual(summary["stop"]["code"], "RECOVERY_FAILED")
        self.assertEqual(summary["report"]["not_attempted"], ["train_0003"])
        partial = (self.fx.output / "predictions.partial.jsonl").read_text(encoding="utf-8")
        self.assertIn("train_0001", partial)

    def test_zero_recovery_attempts_stop_after_a_loss(self):
        code, summary = self.run_cli({"train_0001": "block_planner"}, recovery_attempts=0)
        self.assertEqual((code, summary["stop"]["code"]), (1, "RECOVERY_FAILED"))
        self.assertEqual(summary["report"]["not_attempted"], ["train_0002", "train_0003"])

    def test_reservation_and_acceptance_write_failures_fail_closed(self):
        from unittest.mock import patch

        def broken(*args, **kwargs):
            raise PipelineError("OUTPUT_IO", "Injected journal write failure", "journal")

        with patch.object(RunJournal, "reserve", broken):
            code, summary = self.run_cli()
        self.assertEqual((code, summary["stop"]["code"]), (1, "OUTPUT_IO"))
        self.assertEqual(sum(self.opened(f"train_000{n}") for n in (1, 2, 3)), 0, "Nothing was dispatched")
        output = self.fx.root / "out-accept"
        with patch.object(RunJournal, "accept", broken):
            code, summary = self.run_cli(output=output)
        self.assertEqual(code, 1)
        self.assertEqual([r["sample_id"] for r in self.records(output) if r["type"] == "reserve"], ["train_0001"])
        self.assertEqual(self.terminal(output), {}, "The reservation stays uncertain, never a success")
        self.run_cli(resume=True, output=output)
        self.assertEqual(self.terminal(output)["train_0001"]["error"]["code"], "EXECUTION_UNCERTAIN")
        self.assertEqual(self.opened("train_0001"), 1, "Never reopened on resume")

    def harness(self, point, behaviors=None):
        argv = [sys.executable, "-m", "integration_harness", point, "--", "--config", str(self.config())]
        return subprocess.Popen(argv, env=self.environment(behaviors), stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)

    def test_supervisor_death_at_each_ordering_point_never_replays(self):
        for point, expected_opens in (("reserved", 0), ("dispatched", None), ("received", 1)):
            with self.subTest(point=point):
                for path in self.markers.iterdir():
                    path.unlink()
                if self.fx.output.exists():
                    import shutil
                    shutil.rmtree(self.fx.output)
                process = self.harness(point)
                self.assertEqual(process.wait(60), 9)
                code, summary = self.run_cli(resume=True)
                self.assertEqual(code, 1)
                terminal = self.terminal()
                self.assertEqual((terminal["train_0001"]["status"], terminal["train_0001"]["error"]["code"]),
                                 ("failed", "EXECUTION_UNCERTAIN"))
                self.assertEqual([terminal[i]["status"] for i in ("train_0002", "train_0003")],
                                 ["completed", "completed"])
                if expected_opens is not None:
                    self.assertEqual(self.opened("train_0001"), expected_opens)
                self.assertLessEqual(self.opened("train_0001"), 1)
                self.assertFalse((self.fx.output / "predictions.jsonl").exists())

    def test_supervisor_death_after_mutation_terminates_orphan_and_never_replays(self):
        process = self.harness("none", {"train_0001": "block_tool"})
        deadline = time.monotonic() + 30
        while not list(self.markers.glob("mutated-train_0001-*")) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(list(self.markers.glob("mutated-train_0001-*")))
        process.kill()  # Kills only the supervisor; its worker is in its own process group.
        process.wait(10)
        worker = next(r for r in self.records() if r["type"] == "worker_started")
        self.assertFalse(lock_free(self.fx.output / worker["lock"]), "The orphan worker is alive before resume")
        code, summary = self.run_cli({"train_0001": "block_tool"}, resume=True)
        self.assertEqual(code, 1)
        self.assertEqual(self.terminal()["train_0001"]["error"]["code"], "EXECUTION_UNCERTAIN")
        self.assertEqual(self.opened("train_0001"), 1)
        manifest = json.loads((self.fx.output / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn({"generation": 1, "status": "terminated"}, manifest["resume"]["prior_workers"])

    def test_resume_rejects_changed_model_identity(self):
        self.run_cli()
        (self.fx.planner / "model.safetensors").write_bytes(
            (self.fx.planner / "model.safetensors").read_bytes() + b"\0")
        code, summary = self.run_cli(resume=True)
        self.assertNotEqual(code, 0)
        self.assertEqual(summary["error"]["code"], "INPUT_INVALID")


class ProtocolTests(unittest.TestCase):
    """Raw IPC misbehavior against the real supervisor using a rogue worker."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal = RunJournal.create(Path(self.temp.name) / "run", HEADER)
        self.addCleanup(self.journal.close)
        self.env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(SOURCE), str(TESTS)]))

    def supervisor(self, mode, timeout=1.0, startup=10.0):
        result = Supervisor(self.journal, CONFIG, timeout, startup, 1,
                            command=[sys.executable, "-m", "integration_rogue", mode], env=self.env)
        self.addCleanup(lambda: result.worker and result.worker.terminate())
        return result

    def test_partial_stale_late_and_silent_responses_time_out(self):
        for number, mode in enumerate(("partial", "stale", "late", "never_read"), 1):
            with self.subTest(mode=mode):
                supervisor = self.supervisor(mode)
                supervisor.ensure_worker()
                started = time.monotonic()
                result = supervisor.run_sample(f"train_000{number}")
                self.assertEqual(result.status, "timeout")
                self.assertLess(time.monotonic() - started, 1.0 + 15, "Bounded by deadline plus termination")
                self.assertTrue(result.metrics["termination_confirmed"])
                if mode == "stale":
                    self.assertEqual(result.metrics["stale_messages"], 2)
        self.assertEqual(self.journal.accepted(), {})

    def test_garbage_frame_is_worker_loss(self):
        supervisor = self.supervisor("garbage")
        supervisor.ensure_worker()
        result = supervisor.run_sample("train_0001")
        self.assertEqual((result.status, result.error["code"]), ("failed", "EXECUTION_UNCERTAIN"))

    def test_startup_without_ready_is_bounded(self):
        supervisor = self.supervisor("no_ready", startup=1.0)
        started = time.monotonic()
        with self.assertRaises(PipelineError) as caught:
            supervisor.ensure_worker()
        self.assertEqual(caught.exception.code, "MODEL_UNAVAILABLE")
        self.assertLess(time.monotonic() - started, 1.0 + 15)
        self.assertEqual(self.journal.state.stopped, {1})

    def test_blocked_dispatch_write_is_interrupted_by_the_deadline(self):
        supervisor = self.supervisor("never_read")
        supervisor.ensure_worker()
        handle = supervisor.worker
        started = time.monotonic()
        # Larger than any OS pipe buffer: the write blocks because the worker never reads.
        delivered = handle.send({"type": "padding", "data": "x" * 900_000}, time.monotonic() + 0.5)
        self.assertFalse(delivered)
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertTrue(handle.terminate()["confirmed"])


if __name__ == "__main__":
    unittest.main()
