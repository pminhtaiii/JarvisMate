import unittest

from lifemate.agent import parse_action, run_sample
from lifemate.contracts import Limits
from lifemate.dataset import preflight
from support import (FINISH, ControlledEnvironment, ControlledPlanner,
                     Fixture, MemoryTrace, call)


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.close)
        self.sample = preflight(self.fx.config()).samples[0]

    def execute(self, actions, env=None, trace=None, limits=None, clock=None):
        self.env, self.trace = env or ControlledEnvironment(), trace or MemoryTrace()
        self.opened = []

        def factory(*args):
            self.opened.append(args)
            return self.env

        self.planner = ControlledPlanner(actions)
        options = {"clock": clock} if clock else {}
        return run_sample(self.sample, self.planner, None, factory, self.trace, limits or Limits(),
                          split="train", data_root=self.fx.data, **options)

    def test_lookup_result_binds_the_action_id(self):
        def send(value):
            observed = value["observations"][0]["result"]["contacts"][0]["id"]
            return call("sms.send", contact_id=observed, content="Đến trễ")

        outcome = self.execute([call("contacts.search", query="Lan"), send, FINISH])
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(self.env.calls[1]["arguments"]["contact_id"], "observed_77")
        self.assertEqual(outcome.result["tool_calls"], self.env.calls)
        self.assertEqual(len(self.opened), 1)
        self.assertNotIn("GOLD_MUST_NOT_ENTER_PROMPT", repr(self.planner.inputs))

    def test_strict_parser_rejects_wrappers_duplicates_nonfinite_and_extra_fields(self):
        invalid = ['```json\n{"action":"finish"}\n```', '{"action":"finish","action":"finish"}',
                   '{"action":"finish","extra":1}', '{"action":"call","name":"sms.send","arguments":{"n":NaN}}',
                   '{"action":"call","name":"sms.send","arguments":{"n":1e999}}',
                   '{"action":"finish"} {"action":"finish"}', '[]',
                   '{"action":"call","name":"sms.send","arguments":[]}']
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises((ValueError, TypeError)):
                parse_action(raw)

    def test_malformed_and_unavailable_actions_do_not_dispatch(self):
        outcome = self.execute(['invalid', call("banking.transfer", amount=1), FINISH])
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(self.env.calls, [])
        self.assertEqual(len(self.planner.inputs[2]["observations"]), 2)

    def test_schema_invalid_allowed_call_is_logged_then_corrected(self):
        outcome = self.execute([call("sms.send", content="Trễ"),
                                call("sms.send", contact_id="observed_77", content="Trễ"), FINISH])
        self.assertEqual(len(outcome.result["tool_calls"]), 2)
        self.assertFalse(self.planner.inputs[1]["observations"][0]["result"]["ok"])

    def test_done_false_is_observed_instead_of_failing_batch(self):
        env = ControlledEnvironment(lambda *_: {"ok": True, "done": False})
        outcome = self.execute([call("contacts.search"), FINISH], env=env)
        self.assertEqual(outcome.status, "completed")
        self.assertFalse(self.planner.inputs[1]["observations"][0]["result"]["done"])

    def test_missing_info_terminal_requires_both_explicit_true_fields(self):
        for response, expected_steps in (({"ok": True, "waiting_for_user": True}, 1),
                                         ({"ok": True, "waiting_for_user": False}, 2),
                                         ({"ok": True}, 2), ({"ok": False}, 2)):
            with self.subTest(response=response):
                env = ControlledEnvironment(lambda *_: response)
                outcome = self.execute([call("sys.ask_missing_info", tool_name="sms.send", params=["contact_id"]), FINISH], env=env)
                self.assertEqual(outcome.steps, expected_steps)
                self.assertEqual(outcome.status, "needs_info" if expected_steps == 1 else "completed")

    def test_empty_finish_is_a_valid_authoritative_result(self):
        outcome = self.execute([FINISH])
        self.assertEqual(outcome.result, {"id": self.sample.id, "tool_calls": [], "state_hash": "a" * 64})

    def test_missing_info_preserves_preceding_calls(self):
        outcome = self.execute([call("contacts.search", query="Lan"),
                                call("sys.ask_missing_info", tool_name="sms.send", params=["content"])])
        self.assertEqual(outcome.status, "needs_info")
        self.assertEqual([c["name"] for c in outcome.result["tool_calls"]],
                         ["contacts.search", "sys.ask_missing_info"])

    def test_uncertain_call_is_not_repeated_or_reset(self):
        def explode(*_):
            raise RuntimeError("Possibly changed state")

        outcome = self.execute([call("sms.send", contact_id="c1", content="x"), FINISH],
                               env=ControlledEnvironment(explode))
        self.assertEqual(outcome.error["code"], "EXECUTION_UNCERTAIN")
        self.assertIsNone(outcome.result)
        self.assertEqual(len(self.env.calls), 1)
        self.assertEqual(len(self.opened), 1)

    def test_trace_failure_prevents_dispatch(self):
        outcome = self.execute([call("contacts.search")], trace=MemoryTrace("tool_call_started"))
        self.assertEqual(outcome.error["code"], "TRACE_IO")
        self.assertEqual(self.env.calls, [])

    def test_step_and_deadline_exhaustion_have_no_fake_success(self):
        outcome = self.execute(['bad'], limits=Limits(max_steps=1))
        self.assertEqual(outcome.error["code"], "STEP_LIMIT")
        self.assertIsNone(outcome.result)
        ticks = iter([0, 0, 100, 100, 100, 100])
        outcome = self.execute([FINISH], clock=lambda: next(ticks, 100))
        self.assertEqual(outcome.error["code"], "TIME_LIMIT")
        self.assertEqual(self.opened, [])
