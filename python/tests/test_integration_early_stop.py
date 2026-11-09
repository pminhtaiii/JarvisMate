"""Soft stops and durable acceptance with one shared fake monotonic clock.

No weights, GPU, sleeping, organizer environments or hidden state files.
Real blocked/crashed subprocess coverage remains in test_integration_supervisor.
"""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from lifemate.agent import run_integration_sample
from lifemate.artifacts import RunJournal, publish_predictions
from lifemate.configuration import load_config
from lifemate.contracts import Deadline, Limits, PipelineError
from lifemate.dataset import preflight
from lifemate.integration import summarize
from lifemate.supervisor import Supervisor, WorkerLost
from lifemate.worker import Worker
from integration_support import IntegrationFixture
from support import ControlledASR, ControlledEnvironment, Fixture, MemoryTrace
from test_integration_pipeline import FINISH, NativeDoubles, call


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Environment(ControlledEnvironment):
    """Synthetic state/hash owned by the fake environment, independent of the planner."""
    def __init__(self, response=None):
        super().__init__(response)
        self.hash_reads = 0

    def get_state_hash(self):
        self.hash_reads += 1
        return hashlib.sha256(json.dumps(self.calls, sort_keys=True).encode()).hexdigest()


class EarlyStopTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.close)
        self.clock = Clock()
        self.deadline = Deadline(30, self.clock)
        self.sample = preflight(self.fx.config()).samples[0]
        self.env = Environment()
        self.trace = MemoryTrace()
        self.opened = 0

    def execute(self, decisions, *, asr=None, factory=None):
        self.planner = NativeDoubles(decisions)

        def environment(*args):
            self.opened += 1
            return self.env

        return run_integration_sample(
            self.sample, self.planner, asr, factory or environment, self.trace, Limits(), self.deadline,
            split="train", data_root=self.fx.data, clock=self.clock)

    def assert_partial(self, outcome, count):
        self.assertEqual((outcome.status, outcome.stop_reason), ("partial", "soft_deadline"))
        self.assertIsNone(outcome.error)
        self.assertEqual(outcome.result, {"id": self.sample.id, "tool_calls": self.env.get_tool_calls(),
                                          "state_hash": self.env.get_state_hash()})
        self.assertEqual(len(outcome.result["tool_calls"]), count)
        self.assertEqual(set(outcome.result), {"id", "tool_calls", "state_hash"})
        self.assertEqual(self.opened, 1)

    def test_three_successful_calls_then_soft_deadline_preserves_exact_log_and_hash(self):
        def response(name, arguments):
            self.clock.advance(9)
            return {"ok": True}

        self.env.response = response
        outcome = self.execute([call("contacts.search", query=str(i)) for i in range(3)] + [FINISH])
        self.assert_partial(outcome, 3)
        self.assertEqual(len(self.planner.inputs), 3)
        self.assertEqual(outcome.metrics["deadline"]["finalization_budget_seconds"], 3)

    def test_valid_environment_at_soft_deadline_returns_empty_partial_without_llm(self):
        self.clock.advance(26)
        outcome = self.execute([AssertionError("No LLM after soft deadline")])
        self.assert_partial(outcome, 0)
        self.assertEqual(self.planner.inputs, [])

    def test_asr_time_counts_toward_the_same_soft_deadline(self):
        self.sample = preflight(self.fx.config(input_mode="audio")).samples[0]
        asr = ControlledASR()

        def transcribe(path, remaining):
            self.clock.advance(26)
            return "request"

        asr.transcribe = transcribe
        outcome = self.execute([], asr=asr)
        self.assert_partial(outcome, 0)
        self.assertEqual(outcome.timings["request"], 26)

    def test_planner_finish_before_soft_deadline_is_completed(self):
        outcome = self.execute([FINISH])
        self.assertEqual((outcome.status, outcome.stop_reason), ("completed", "finish"))
        self.assertEqual(outcome.result["state_hash"], self.env.get_state_hash())

    def test_generation_receives_remaining_soft_budget_from_original_attempt_start(self):
        self.clock.advance(10)
        budgets = []

        def decide(planner, prepared, observations, remaining):
            budgets.append(remaining)
            return FINISH, {}

        with patch.object(NativeDoubles, "decide", decide):
            self.assertEqual(self.execute([]).status, "completed")
        self.assertEqual(budgets, [16])

    def test_valid_clarification_returning_at_soft_deadline_keeps_needs_info(self):
        def response(name, arguments):
            self.clock.advance(26)
            return {"ok": True, "waiting_for_user": True}

        self.env.response = response
        outcome = self.execute([call("sys.ask_missing_info", tool_name="sms.send", params=["content"])])
        self.assertEqual((outcome.status, outcome.stop_reason), ("needs_info", "waiting_for_user"))
        self.assertEqual(len(outcome.result["tool_calls"]), 1)

    def test_planner_return_at_soft_deadline_does_not_dispatch_even_ask(self):
        def decide(prepared, observations):
            self.clock.advance(26)
            return call("sys.ask_missing_info", tool_name="sms.send", params=["content"])

        self.assert_partial(self.execute([decide]), 0)

    def test_soft_deadline_checked_immediately_before_dispatch_after_trace(self):
        original = self.trace.emit

        def emit(kind, **fields):
            if kind == "tool_call_started":
                self.clock.advance(26)
            original(kind, **fields)

        self.trace.emit = emit
        self.assert_partial(self.execute([call("contacts.search", query="Lan")]), 0)

    def test_cooperative_planner_soft_timeout_collects_only_the_environment(self):
        def stop(prepared, observations):
            self.clock.advance(26)
            raise PipelineError("TIME_LIMIT", "Generation reached its supplied budget", "planner")

        self.assert_partial(self.execute([stop]), 0)

    def test_planner_errors_before_soft_deadline_remain_failures(self):
        outcome = self.execute([PipelineError("TIME_LIMIT", "Unexpected early generation timeout", "planner")])
        self.assertEqual((outcome.status, outcome.error["code"]), ("failed", "TIME_LIMIT"))
        self.assertIsNone(outcome.result)

    def test_schema_rejected_call_is_preserved_in_partial(self):
        def reject(name, arguments):
            self.clock.advance(26)
            return {"ok": False, "error": "missing contact_id"}

        self.env.response = reject
        outcome = self.execute([call("sms.send", content="x")])
        self.assert_partial(outcome, 1)
        self.assertEqual(outcome.result["tool_calls"][0]["arguments"], {"content": "x"})

    def test_hard_deadline_has_priority_on_tool_return(self):
        def late(*args):
            self.clock.advance(30)
            return {"ok": True}

        self.env.response = late
        outcome = self.execute([call("contacts.search", query="Lan"), FINISH])
        self.assertEqual((outcome.status, outcome.error["code"]), ("failed", "TIME_LIMIT"))
        self.assertIsNone(outcome.result)
        self.assertEqual(len(self.env.calls), 1)
        self.assertEqual(self.opened, 1)

    def test_planner_hard_timeout_cannot_be_demoted_to_soft_stop(self):
        def late(*args):
            self.clock.advance(30)
            raise PipelineError("TIME_LIMIT", "Hard expired", "planner")

        outcome = self.execute([late])
        self.assertEqual((outcome.status, outcome.error["code"]), ("failed", "TIME_LIMIT"))
        self.assertIsNone(outcome.result)
        self.assertEqual(self.env.calls, [])

    def test_invalid_environment_hash_never_supplies_partial(self):
        self.clock.advance(26)
        self.env.get_state_hash = lambda: "invalid"
        outcome = self.execute([])
        self.assertEqual(outcome.status, "failed")
        self.assertIsNone(outcome.result)

    def test_uncertain_tool_exception_at_soft_deadline_never_becomes_partial(self):
        def explode(*args):
            self.clock.advance(26)
            raise RuntimeError("Mutation may have happened")

        self.env.response = explode
        outcome = self.execute([call("contacts.search", query="Lan")])
        self.assertEqual((outcome.status, outcome.error["code"]), ("failed", "EXECUTION_UNCERTAIN"))
        self.assertIsNone(outcome.result)
        self.assertEqual(len(self.env.calls), 1)

    def test_missing_or_invalid_environment_cannot_supply_partial(self):
        def missing(*args):
            self.clock.advance(26)
            raise RuntimeError("Environment initialization failed")

        outcome = self.execute([], factory=missing)
        self.assertEqual((outcome.status, outcome.error["code"]), ("failed", "EXECUTION_UNCERTAIN"))
        self.assertIsNone(outcome.result)

    def test_collection_crossing_hard_deadline_never_returns_prediction(self):
        self.clock.advance(26)
        original = self.env.get_state_hash

        def slow_hash():
            self.clock.advance(4)
            return original()

        self.env.get_state_hash = slow_hash
        outcome = self.execute([])
        self.assertEqual(outcome.error["code"], "TIME_LIMIT")
        self.assertIsNone(outcome.result)


class ControlledHandle:
    """Drive the real worker staging method synchronously; control IPC arrival/crash."""
    generation = 1
    stale_messages = 0

    def __init__(self, worker, clock):
        self.worker, self.clock = worker, clock
        self.dispatch_delay = self.receipt_delay = 0
        self.lost_ack = False
        self.terminated = False

    def send(self, message, deadline, clock):
        self.message = copy.deepcopy(message)
        self.clock.advance(self.dispatch_delay)
        self.result = self.worker.attempt(message)
        return True

    def receive(self, deadline, clock):
        self.clock.advance(self.receipt_delay)
        if self.lost_ack:
            raise WorkerLost("Lost acknowledgement after durable worker staging")
        return self.result

    def terminate(self, clock):
        self.terminated = True
        return {"confirmed": True, "termination_seconds": 0}


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.fx = IntegrationFixture()
        self.addCleanup(self.fx.close)
        self.clock = Clock()
        self.config = load_config(self.fx.write_config())
        self.header = {"run_sha256": "r" * 64, "selected_ids": ["train_0001"]}
        self.journal = RunJournal.create(self.fx.output, self.header)
        self.addCleanup(self.journal.close)
        self.journal.worker_started(1, 1234)
        self.worker = Worker.__new__(Worker)
        self.worker.root, self.worker.generation = self.fx.output, 1
        self.worker.config, self.worker.clock = self.config, self.clock
        sample = preflight(self.fx.config(input_mode="audio")).samples[0]
        self.worker.samples = {sample.id: sample}
        self.env = Environment()
        self.worker.environments = lambda *args: self.env
        self.worker.components = {"asr": ControlledASR(), "planner": NativeDoubles([])}
        self.handle = ControlledHandle(self.worker, self.clock)
        self.handle.dispatch_delay = 26  # Soft time consumed before worker receives dispatch.
        self.supervisor = Supervisor(self.journal, self.config.fingerprint(), 30, 10, 1,
                                     clock=self.clock, worker=self.handle)

    def run_sample(self):
        # Hardware collection is optional and unrelated to these controlled deadlines.
        with patch("lifemate.worker.peak_memory", return_value=None):
            return self.supervisor.run_sample("train_0001")

    def test_timely_partial_worker_ack_is_accepted_published_and_reported(self):
        result = self.run_sample()
        self.assertEqual(result.status, "partial")
        self.assertEqual(self.handle.message["started_monotonic"], 100)
        self.assertEqual(self.handle.result["worker_elapsed"], 26)
        record = self.journal.accepted()["train_0001"]
        self.assertEqual(record["status"], "partial")
        self.assertEqual(record["accepted_monotonic"], 126)
        self.assertTrue(publish_predictions(self.journal, ["train_0001"])["complete"])
        prediction = json.loads((self.fx.output / "predictions.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(prediction, {"id": "train_0001", "tool_calls": [],
                                      "state_hash": self.env.get_state_hash()})
        self.assertEqual(set(prediction), {"id", "tool_calls", "state_hash"})
        report = summarize(self.journal, ["train_0001"])
        self.assertEqual((report["completed"], report["partial"], report["accepted"]), (0, 1, 1))
        self.assertIn("does not establish correctness", report["coverage_note"])
        self.journal.close()
        resumed = RunJournal.resume(self.fx.output, self.header)
        self.addCleanup(resumed.close)
        self.assertEqual(resumed.accepted()["train_0001"]["status"], "partial")

    def test_partial_received_at_hard_deadline_is_quarantined(self):
        self.handle.receipt_delay = 4
        result = self.run_sample()
        self.assertEqual((result.status, result.error["code"]), ("timeout", "TIME_LIMIT"))
        self.assertEqual(self.journal.accepted(), {})
        self.assertTrue(self.handle.terminated)
        self.assertTrue((self.journal.quarantine_root / result.attempt_id / "prediction.json").is_file())
        self.assertFalse(publish_predictions(self.journal, ["train_0001"])["complete"])

    def test_partial_received_after_hard_deadline_is_rejected(self):
        self.handle.receipt_delay = 4.1
        result = self.run_sample()
        self.assertEqual((result.status, result.error["code"]), ("timeout", "TIME_LIMIT"))
        self.assertEqual(self.journal.accepted(), {})
        self.assertTrue(self.handle.terminated)

    def test_timely_ack_with_slow_validation_is_rejected(self):
        original = self.journal.read_staged

        def read(attempt, name):
            value = original(attempt, name)
            if name == "prediction.json":
                self.clock.advance(4)
            return value

        with patch.object(self.journal, "read_staged", side_effect=read):
            result = self.run_sample()
        self.assertEqual(result.status, "timeout")
        self.assertEqual(self.journal.accepted(), {})
        self.assertEqual(result.metrics["attempt_seconds"], 30)

    def test_full_attempt_metric_includes_validation_and_candidate_durability(self):
        original = self.journal.append

        def append(kind, **fields):
            value = original(kind, **fields)
            if kind == "accept_pending":
                self.clock.advance(1)
            return value

        with patch.object(self.journal, "append", side_effect=append):
            result = self.run_sample()
        self.assertEqual(result.status, "partial")
        metrics = self.journal.accepted()["train_0001"]["metrics"]
        self.assertEqual(metrics["receipt_seconds"], 26)
        self.assertEqual(metrics["attempt_seconds"], 27)
        self.assertEqual(metrics["acceptance_decision_seconds"], 1)

    def test_slow_acceptance_candidate_fsync_cannot_be_accepted(self):
        original = self.journal.append

        def append(kind, **fields):
            value = original(kind, **fields)
            if kind == "accept_pending":
                self.clock.advance(4)
            return value

        with patch.object(self.journal, "append", side_effect=append):
            result = self.run_sample()
        self.assertEqual(result.status, "timeout")
        self.assertEqual(self.journal.accepted(), {})
        self.journal.close()
        resumed = RunJournal.resume(self.fx.output, self.header)
        self.addCleanup(resumed.close)
        self.assertEqual(resumed.accepted(), {})
        self.assertIn("train_0001", resumed.attempted())

    def test_lost_ack_quarantines_durable_partial_and_never_recovers_it(self):
        self.handle.lost_ack = True
        result = self.run_sample()
        self.assertEqual((result.status, result.error["code"]), ("failed", "EXECUTION_UNCERTAIN"))
        self.assertEqual(self.journal.accepted(), {})
        self.journal.close()
        resumed = RunJournal.resume(self.fx.output, self.header)
        self.addCleanup(resumed.close)
        self.assertEqual(resumed.accepted(), {})
        self.assertIn("train_0001", resumed.attempted())
        self.assertTrue((self.journal.quarantine_root / result.attempt_id / "prediction.json").is_file())

    def test_crash_after_durable_candidate_before_confirmation_stays_uncertain(self):
        original = self.journal.append

        def append(kind, **fields):
            value = original(kind, **fields)
            if kind == "accept_pending":
                raise SystemExit("Supervisor died before checking candidate durability")
            return value

        with patch.object(self.journal, "append", side_effect=append), self.assertRaises(SystemExit):
            self.run_sample()
        self.journal.close()
        resumed = RunJournal.resume(self.fx.output, self.header)
        self.addCleanup(resumed.close)
        self.assertEqual(resumed.accepted(), {})
        self.assertEqual(resumed.mark_uncertain(), ["train_0001"])
        self.assertEqual(resumed.quarantine_unaccepted(), [self.handle.message["attempt_id"]])


if __name__ == "__main__":
    unittest.main()
