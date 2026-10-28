import copy
import json
import unittest
from unittest.mock import Mock

from lifemate.adapters.planner import LocalPlanner
from lifemate.contracts import Limits, PipelineError
from lifemate.selection import referenced_records
from support import call


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.action = call("tasks.complete", task_id="older")
        self.value = {"request": "Complete matching tasks", "context": {}, "history": [],
                      "observations": [], "available_tools": [
            {"name": "tasks.list", "kind": "read", "parameters": {"properties": {}}},
            {"name": "tasks.complete", "kind": "write", "parameters": {"properties": {
                "task_id": {"type": "string", "x-ref": "tasks.tasks"}}}}]}

    def read(self, records, **changes):
        return {"kind": "tool_result", "name": "tasks.list",
                "result": {"ok": True, "tasks": records}, **changes}

    def test_all_successful_reads_contribute_newest_record_per_id(self):
        self.value["observations"] = [
            self.read([{"id": "older", "title": "keep"}, {"id": "shared", "title": "old"}]),
            self.read([{"id": "newer", "title": "keep"}, {"id": "shared", "title": "new"}]),
            self.read([]),
            self.read([{"id": "wrong_app", "title": "ignore"}], name="other.list"),
            self.read([{"id": "write", "title": "ignore"}], name="tasks.complete"),
            self.read([{"id": "wrong_kind", "title": "ignore"}], kind="validation_rejection"),
            self.read([], result={"ok": False, "tasks": [{"id": "failed", "title": "ignore"}]}),
            self.read([], result={"ok": True, "other": []})]
        original = copy.deepcopy(self.value)
        selection = referenced_records(self.value, self.action)
        self.assertEqual({r["id"]: r["title"] for r in selection["records"]},
                         {"older": "keep", "newer": "keep", "shared": "new"})
        self.assertEqual(selection["fields"], ["title"])
        selection["records"][0]["title"] = "changed"
        self.assertEqual(self.value, original)

    def test_invalid_collection_records_disable_selection(self):
        for records in ([{"title": "missing ID"}], [{"id": "a"}, {"id": "a"}]):
            with self.subTest(records=records):
                self.value["observations"] = [self.read(records)]
                self.assertIsNone(referenced_records(self.value, self.action))

    def planner(self, actions):
        planner = LocalPlanner.__new__(LocalPlanner)
        planner.selection_filter, planner.limits = True, Limits()
        planner._selection_filters = {}
        planner._action = Mock(side_effect=[json.dumps(action) for action in actions])
        planner._select = Mock(return_value={"supported": True, "filters": [
            {"field": "title", "operator": "equals", "value": "eligible"}]})
        self.value["observations"] = [self.read([
            {"id": "older", "title": "ineligible"}, {"id": "allowed", "title": "eligible"}])]
        return planner

    def test_exhausted_validation_does_not_generate_an_unvalidated_action(self):
        planner = self.planner([self.action, self.action])
        with self.assertRaises(PipelineError) as caught:
            planner.next_action(self.value, 30)
        self.assertEqual(caught.exception.code, "NO_PROGRESS")
        self.assertEqual(planner._action.call_count, 2)
        self.assertEqual(len(planner.last_decision_details), 2)

    def test_valid_correction_is_returned_after_validation(self):
        corrected = call("tasks.complete", task_id="allowed")
        planner = self.planner([self.action, corrected])
        self.assertEqual(json.loads(planner.next_action(self.value, 30)), corrected)
        self.assertEqual(planner._action.call_count, 2)

    def test_proposal_from_an_earlier_read_remains_eligible(self):
        planner = self.planner([call("tasks.complete", task_id="allowed")])
        self.value["observations"].append(self.read([{"id": "new", "title": "ineligible"}]))
        self.assertEqual(json.loads(planner.next_action(self.value, 30))["arguments"]["task_id"], "allowed")
        planner._action.assert_called_once()
