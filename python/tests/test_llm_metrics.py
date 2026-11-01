"""Hand-checked native metric fixtures (E02/E03). Pure; no models or environments."""
import unittest

from lifemate.llm_training import metrics as m

FUZZY = {"notes.create": frozenset({"content"}), "sms.send": frozenset({"content"})}


def call(name, **arguments):
    return {"name": name, "arguments": arguments}


class MatchingTests(unittest.TestCase):
    def test_maximum_matching_beats_greedy_order_and_handles_duplicates(self):
        gold = [call("notes.create", content="mua sữa tươi"), call("notes.create", content="mua sữa tươi và bánh mì")]
        predicted = [call("notes.create", content="mua sữa tươi và bánh"), call("notes.create", content="mua sữa tươi")]
        self.assertEqual(m.max_matching(predicted, gold, FUZZY), 2)
        duplicate = [call("contacts.search", query="Lan")] * 2
        self.assertEqual(m.max_matching(duplicate, [call("contacts.search", query="Lan")], FUZZY), 1)

    def test_exact_non_fuzzy_types_and_fuzzy_threshold(self):
        self.assertFalse(m.call_matches(call("banking.transfer", amount=1.0), call("banking.transfer", amount=1), FUZZY))
        self.assertFalse(m.call_matches(call("x.y", flag=1), call("x.y", flag=True), FUZZY))
        self.assertTrue(m.call_matches(call("sms.send", content="TÔI ĐẾN TRỄ"), call("sms.send", content="tôi đến trễ"), FUZZY))
        self.assertFalse(m.call_matches(call("sms.send", content="tôi"), call("sms.send", content="tôi đến trễ nhé"), FUZZY))
        self.assertFalse(m.call_matches(call("sms.send", content="a", extra=1), call("sms.send", content="a"), FUZZY))

    def test_source_scores_empty_gold_and_failures(self):
        self.assertEqual(m.source_score("completed", [], [], FUZZY)["score"], 1.0)
        self.assertEqual(m.source_score("failed", [], [], FUZZY)["score"], 0.0)  # Never a successful empty.
        self.assertEqual(m.source_score("completed", [call("a.b")], [], FUZZY)["score"], 0.0)
        self.assertEqual(m.source_score("completed", [], [call("a.b")], FUZZY)["score"], 0.0)
        half = m.source_score("completed", [call("a.b"), call("a.c")], [call("a.b")], FUZZY)
        self.assertAlmostEqual(half["score"], 2 * 0.5 * 1 / 1.5)
        self.assertEqual(m.source_score("failed", [call("a.b")], [call("a.b")], FUZZY)["score"], 0.0)


class ClosedLoopTests(unittest.TestCase):
    ids = ["s1", "s2", "s3", "s4"]
    references = {"s1": [], "s2": [call("sys.ask_missing_info", tool_name="sms.send", params=["contact_id", "content"])],
                  "s3": [call("contacts.search", query="Lan")], "s4": []}

    def outcomes(self, **changes):
        base = {"s1": {"status": "completed", "stop_reason": "finish", "attempted_calls": [], "elapsed": 1.0},
                "s2": {"status": "needs_info", "stop_reason": "waiting_for_user", "elapsed": 2.0,
                       "attempted_calls": [call("sys.ask_missing_info", tool_name="sms.send", params=["content", "contact_id"])]},
                "s3": {"status": "completed", "stop_reason": "finish", "elapsed": 3.0,
                       "attempted_calls": [call("contacts.search", query="Lan")]},
                "s4": {"status": "failed", "stop_reason": "TIME_LIMIT", "error_code": "TIME_LIMIT", "elapsed": 30.0,
                       "attempted_calls": []}}
        base.update(changes)
        return [{"id": i, **base[i]} for i in self.ids]

    def test_full_coverage_with_failure_is_scoreable(self):
        report, rows = m.closed_loop_metrics(self.outcomes(), self.references, self.ids, FUZZY)
        counts = report["counts"]
        self.assertEqual((counts["attempted"], counts["completed"], counts["failed"], counts["timed_out"]), (4, 3, 1, 1))
        self.assertTrue(counts["full_coverage"])
        f1 = report["metrics"]["tool_call_f1"]
        self.assertEqual((f1["numerator"], f1["denominator"]), (2.0, 4))  # s2 ask params order differs -> 0.
        self.assertEqual(f1["value"], 0.5)
        strict = report["metrics"]["ask_strict_recall"]
        self.assertEqual((strict["value"], strict["counts"]["matched"]), (0.0, 0))
        presence = report["metrics"]["ask_presence_recall"]
        self.assertEqual((presence["value"], presence["confusion"]["tp"]), (1.0, 1))
        no_action = report["metrics"]["no_action_recall"]
        self.assertEqual((no_action["confusion"]["tp"], no_action["confusion"]["fn"]), (1, 1))  # Failure is not empty success.
        self.assertIsNone(report["metrics"]["final_state_match"]["value"])
        self.assertEqual(report["metrics"]["final_state_match"]["missing_reason"], "trusted_reference_unavailable")
        self.assertEqual(report["metrics"]["latency_p95"]["value"], 30.0)
        self.assertEqual(report["metrics"]["latency_p95_success_only"]["value"], 3.0)
        self.assertEqual(rows[3]["tool_call_f1"], 0.0)

    def test_partial_coverage_withholds_complete_scores(self):
        outcomes = self.outcomes(s4={"status": "not_attempted", "attempted_calls": [], "elapsed": None})
        report, _ = m.closed_loop_metrics(outcomes, self.references, self.ids, FUZZY)
        self.assertFalse(report["counts"]["full_coverage"])
        self.assertIsNone(report["metrics"]["tool_call_f1"]["value"])
        self.assertEqual(report["metrics"]["tool_call_f1"]["missing_reason"], "partial_coverage")
        with self.assertRaises(ValueError):
            m.closed_loop_metrics(outcomes[:3], self.references, self.ids, FUZZY)
        with self.assertRaises(ValueError):
            m.closed_loop_metrics(outcomes + outcomes[:1], self.references, self.ids, FUZZY)

    def test_trusted_state_gating_only_with_full_references(self):
        outcomes = [dict(o, state_hash="a" * 64) for o in self.outcomes()]
        report, _ = m.closed_loop_metrics(outcomes, self.references, self.ids, FUZZY,
                                          trusted_state={"s1": "a" * 64, "s2": "a" * 64})
        self.assertIsNone(report["metrics"]["state_gated_tool_call_f1"]["value"])  # Partial references.
        trusted = {i: ("b" * 64 if i == "s3" else "a" * 64) for i in self.ids}
        report, _ = m.closed_loop_metrics(outcomes, self.references, self.ids, FUZZY, trusted_state=trusted)
        self.assertEqual(report["metrics"]["state_gated_tool_call_f1"]["value"], 0.25)  # s3 hash mismatch -> 0.


class TeacherForcedTests(unittest.TestCase):
    def test_four_classes_finish_by_current_prefix_and_invalid_is_fn(self):
        items = [
            {"target_type": "initial_finish", "decision_index": 0, "target": {"action": "finish"}, "predicted": {"action": "finish"}},
            {"target_type": "finish_after_calls", "decision_index": 2, "target": {"action": "finish"}, "predicted": {"action": "finish"}},
            {"target_type": "normal_call", "decision_index": 0, "target": {"action": "call", "name": "a.b", "arguments": {"x": 1}},
             "predicted": {"action": "call", "name": "a.b", "arguments": {"x": 2}}},
            {"target_type": "normal_call", "decision_index": 1, "target": {"action": "call", "name": "a.b", "arguments": {}},
             "predicted": {"action": "finish"}},
            {"target_type": "ask_missing_info", "decision_index": 1, "code": "NATIVE_JSON_INVALID",
             "target": {"action": "call", "name": "sys.ask_missing_info", "arguments": {}}, "predicted": None},
        ]
        result = m.teacher_forced_metrics(items)
        self.assertEqual(result["next_action_accuracy"]["numerator"], 2)
        self.assertEqual(result["argument_accuracy_given_name"]["value"], 0.0)
        self.assertEqual(result["teacher_forced_premature_finish"]["numerator"], 1)
        per_class = result["action_type_macro_f1"]["per_class"]
        self.assertEqual(per_class["ask_missing_info"]["fn"], 1)
        self.assertEqual(per_class["finish_after_calls"]["fp"], 1)  # decision 1 finish predicted on a call row.
        self.assertEqual(result["invalid_outputs"], {"NATIVE_JSON_INVALID": 1})
        self.assertIsNotNone(result["action_type_macro_f1"]["value"])
        missing = m.teacher_forced_metrics(items[:2])
        self.assertIsNone(missing["action_type_macro_f1"]["value"])
        self.assertEqual(missing["action_type_macro_f1"]["missing_reason"], "missing_class_support")

    def test_nearest_rank_and_null_metrics(self):
        self.assertEqual(m.nearest_rank_p95([float(i) for i in range(1, 21)]), 19.0)
        self.assertIsNone(m.nearest_rank_p95([]))
        self.assertEqual(m.ratio(0, 0)["missing_reason"], "undefined_denominator")
        with self.assertRaises(ValueError):
            m.metric(float("nan"))

    def test_fixed_cases_are_the_ten_validation_ids(self):
        cases = m.fixed_cases([])
        self.assertEqual(len(cases), 10)
        self.assertEqual(cases[0], {"id": "train_0072", "status": "absent"})


if __name__ == "__main__":
    unittest.main()
