"""Native integration sample loop with controlled adapters (no models, no GPU)."""
import copy
import unittest
from collections import deque

from lifemate.agent import run_integration_sample
from lifemate.contracts import Deadline, Limits, PipelineError
from lifemate.dataset import preflight
from support import ControlledASR, ControlledEnvironment, Fixture, MemoryTrace

FINISH = {"action": "finish"}


def call(name, **arguments):
    return {"action": "call", "name": name, "arguments": arguments}


class NativeDoubles:
    """Controlled ``decide``: records every input, never sees labels or the environment."""

    metadata = {"parameter_count": 100, "controlled_test_only": True}

    def __init__(self, decisions):
        self.decisions, self.inputs = deque(decisions), []

    def decide(self, prepared, observations, remaining_seconds):
        self.inputs.append((copy.deepcopy(prepared), copy.deepcopy(observations)))
        decision = self.decisions.popleft()
        if isinstance(decision, Exception):
            raise decision
        if callable(decision):
            decision = decision(prepared, observations)
        return decision, {"prompt_tokens": 10, "generated_tokens": 3, "terminated": "eos"}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.close)
        row = self.fx.rows[0]
        row["history"] = [{"role": "user", "audio": row["audio"], "audio_text": "Trước đó"},
                          {"role": "assistant", "text": "Đã gửi",
                           "tool_calls": [{"name": "sms.send", "arguments": {"contact_id": "old", "content": "cũ"}}],
                           "tool_results": [{"ok": True}]}]
        self.fx.write()

    def execute(self, decisions, *, mode="audio", env=None, limits=None, deadline=None):
        sample = preflight(self.fx.config(input_mode=mode)).samples[0]
        self.env, self.trace, self.asr = env or ControlledEnvironment(), MemoryTrace(), ControlledASR()
        self.opened, self.planner = [], NativeDoubles(decisions)

        def factory(*args):
            self.opened.append(args)
            return self.env

        return run_integration_sample(sample, self.planner, self.asr, factory, self.trace, limits or Limits(),
                                      deadline or Deadline(30), split="train", data_root=self.fx.data)

    def test_lookup_dependent_second_call_uses_actual_result_and_one_transcription(self):
        def send(prepared, observations):
            observed = observations[0]["result"]["contacts"][0]["id"]
            return call("sms.send", contact_id=observed, content="Đến trễ")

        outcome = self.execute([call("contacts.search", query="Lan"), send, FINISH])
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(outcome.result, {"id": "train_0001", "tool_calls": [
            {"name": "contacts.search", "arguments": {"query": "Lan"}},
            {"name": "sms.send", "arguments": {"contact_id": "observed_77", "content": "Đến trễ"}}],
            "state_hash": "a" * 64})
        self.assertEqual(len(self.opened), 1)
        # History and current request reference the same WAV: one ASR call for three decisions.
        self.assertEqual(len(self.asr.paths), 1)
        self.assertEqual(outcome.metrics["asr"]["asr_calls"], 1)
        self.assertEqual(len(self.planner.inputs), 3)
        self.assertTrue(all(p["request"] == self.planner.inputs[0][0]["request"] for p, _ in self.planner.inputs))
        second_observations = self.planner.inputs[1][1]
        self.assertEqual(second_observations, [{"name": "contacts.search", "arguments": {"query": "Lan"},
                                                "result": {"ok": True, "contacts": [{"id": "observed_77", "name": "Lan"}]}}])
        self.assertEqual([d["action"] for d in outcome.metrics["decisions"]], ["call", "call", "finish"])
        self.assertEqual(len(outcome.metrics["tools"]), 2)

    def test_spans_cover_clips_decisions_tools_and_collection(self):
        outcome = self.execute([call("contacts.search", query="Lan"), FINISH])
        self.assertEqual(set(outcome.timings), {"request", "environment", "planner", "tools", "collection"})
        self.assertTrue(all(value >= 0 for value in outcome.timings.values()))
        clips = outcome.metrics["asr"]["clips"]
        self.assertEqual([c["position"] for c in clips], ["history[0]", "current"])
        self.assertEqual([c["reused"] for c in clips], [False, True])
        self.assertTrue(all({"seconds", "prompt_tokens", "generated_tokens", "terminated"} <= set(d)
                            for d in outcome.metrics["decisions"]))
        self.assertEqual(outcome.metrics["tools"][0]["name"], "contacts.search")
        self.assertGreaterEqual(outcome.elapsed, sum(outcome.timings.values()) - 1e-9)

    def test_history_calls_are_context_never_replayed(self):
        outcome = self.execute([FINISH])
        self.assertEqual(self.env.calls, [])
        self.assertEqual(outcome.result["tool_calls"], [])
        prepared = self.planner.inputs[0][0]
        self.assertEqual(prepared["history"][1]["tool_calls"][0]["arguments"]["contact_id"], "old")
        self.assertNotIn("GOLD_MUST_NOT_ENTER_PROMPT", repr(self.planner.inputs))

    def test_valid_empty_completion_still_uses_environment_log_and_hash(self):
        outcome = self.execute([FINISH], mode="transcript")
        self.assertEqual(outcome.result, {"id": "train_0001", "tool_calls": [], "state_hash": "a" * 64})
        self.assertEqual(len(self.opened), 1)
        self.assertEqual(self.asr.paths, [])

    def test_clarification_after_partial_execution_stops_without_another_turn(self):
        outcome = self.execute([call("contacts.search", query="Lan"),
                                call("sys.ask_missing_info", tool_name="sms.send", params=["content"]),
                                AssertionError("No decision after waiting_for_user")])
        self.assertEqual((outcome.status, outcome.stop_reason), ("needs_info", "waiting_for_user"))
        self.assertEqual([c["name"] for c in outcome.result["tool_calls"]], ["contacts.search", "sys.ask_missing_info"])
        self.assertEqual(len(self.planner.inputs), 2)

    def test_unsuccessful_clarification_returns_to_the_planner(self):
        env = ControlledEnvironment(lambda name, args: {"ok": False, "error": "bad params"})
        outcome = self.execute([call("sys.ask_missing_info", tool_name="sms.send", params=["x"]), FINISH], env=env)
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(len(outcome.result["tool_calls"]), 1)

    def test_schema_rejected_call_stays_in_authoritative_log(self):
        outcome = self.execute([call("sms.send", content="Trễ"),
                                call("sms.send", contact_id="observed_77", content="Trễ"), FINISH])
        self.assertEqual(len(outcome.result["tool_calls"]), 2)
        self.assertIs(self.planner.inputs[1][1][0]["result"]["ok"], False)

    def test_ineligible_or_failed_decisions_never_dispatch(self):
        outcome = self.execute([call("banking.transfer", amount=1)])
        self.assertEqual((outcome.status, outcome.error["code"]), ("failed", "PLANNER_FORMAT"))
        self.assertEqual(self.env.calls, [])
        outcome = self.execute([PipelineError("OUTPUT_LIMIT", "cut", "planner")])
        self.assertEqual(outcome.error["code"], "OUTPUT_LIMIT")
        self.assertIsNone(outcome.result)

    def test_uncertain_execution_is_not_retried_or_reopened(self):
        def explode(name, args):
            raise RuntimeError("possibly mutated")

        outcome = self.execute([call("sms.send", contact_id="c", content="x"), FINISH], env=ControlledEnvironment(explode))
        self.assertEqual((outcome.error["code"], outcome.error["stage"]), ("EXECUTION_UNCERTAIN", "dispatch"))
        self.assertEqual((len(self.env.calls), len(self.opened)), (1, 1))

    def test_deadline_checked_on_tool_return_rejects_late_success(self):
        clock = {"now": 0.0}

        def slow(name, args):
            clock["now"] = 31.0  # The tool returns after expiry.
            return {"ok": True}

        outcome = self.execute([call("contacts.search", query="Lan"), FINISH], env=ControlledEnvironment(slow),
                               deadline=Deadline(30, lambda: clock["now"]))
        self.assertEqual((outcome.status, outcome.error["code"]), ("failed", "TIME_LIMIT"))
        self.assertIsNone(outcome.result)
        self.assertEqual(outcome.diagnostic["tool_calls"], [{"name": "contacts.search", "arguments": {"query": "Lan"}}])

    def test_step_limit(self):
        outcome = self.execute([call("contacts.search", query=str(n)) for n in range(2)], limits=Limits(max_steps=2))
        self.assertEqual((outcome.status, outcome.stop_reason), ("partial", "step_limit"))
        self.assertEqual(outcome.result["tool_calls"], self.env.get_tool_calls())
        self.assertEqual(outcome.result["state_hash"], self.env.get_state_hash())
        self.assertEqual(len(self.planner.inputs), 2)


if __name__ == "__main__":
    unittest.main()
