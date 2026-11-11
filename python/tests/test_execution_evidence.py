"""Behavioral checks for bounded, provenance-preserving observation evidence."""
import unittest

from lifemate.execution_evidence import EvidenceLedger


TOOLS = [
    {"name": "contacts.search", "returns": "contacts[]",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "sms.send", "returns": "",
     "parameters": {"type": "object", "properties": {
         "contact_id": {"type": "string", "x-ref": "contacts.contacts"}}}},
    {"name": "calendar.list_events", "returns": "events[]",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "calendar.update_event", "returns": "",
     "parameters": {"type": "object", "properties": {
         "event_id": {"type": "string", "x-ref": "calendar.events"}}}},
    {"name": "flights.search_bookings", "returns": "bookings[]",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "flights.rebook", "returns": "",
     "parameters": {"type": "object", "properties": {
         "booking_id": {"type": "string", "x-ref": "flights.bookings"}}}},
    {"name": "trains.list_bookings", "returns": "bookings[]",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "trains.cancel", "returns": "",
     "parameters": {"type": "object", "properties": {
         "booking_id": {"type": "string", "x-ref": "trains.bookings"}}}},
]


def observation(name, result):
    return {"name": name, "arguments": {}, "result": result}


class EvidenceLedgerTests(unittest.TestCase):
    def test_supported_record_id_keeps_tool_step_and_reference_scope(self):
        ledger = EvidenceLedger(TOOLS)

        facts = ledger.sync([observation("contacts.search", {
            "ok": True, "contacts": [{"id": "contact-7", "name": "Lan"}],
        })])

        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["status"], "ok")
        self.assertEqual(facts[0]["step"], 1)
        self.assertEqual(facts[0]["tool"], "contacts.search")
        self.assertEqual(len(facts[0]["references"]), 1)
        reference = facts[0]["references"][0]
        self.assertEqual(reference["scope"], "contacts.contacts")
        self.assertEqual(reference["id"], "contact-7")
        self.assertTrue(reference["path"])

    def test_failed_or_unrecognized_shapes_never_add_candidate_ids(self):
        ledger = EvidenceLedger(TOOLS)
        payload = {"deeply_ignored": {"contacts": [{"id": "nested-fake"}]}}
        for _ in range(20):
            payload = {"nested": payload}

        facts = ledger.sync([
            observation("contacts.search", {
                "ok": False, "contacts": [{"id": "failed-result-id"}],
            }),
            observation("contacts.search", {
                "ok": True, "contacts": {"id": "malformed-result-id"},
                "message": "id=untrusted-text", "other": payload,
            }),
            observation("contacts.search", {
                "ok": True, "id": "unmatched-top-level-id",
            }),
        ])

        self.assertEqual([fact["status"] for fact in facts], ["error", "ok", "ok"])
        self.assertTrue(all(fact["references"] == [] for fact in facts))
        self.assertTrue(all("completed" not in fact for fact in facts))

    def test_success_is_observation_status_not_a_claim_that_the_request_is_done(self):
        ledger = EvidenceLedger(TOOLS)

        facts = ledger.sync([observation("sms.send", {"ok": True})])

        self.assertEqual(facts[0]["status"], "ok")
        self.assertEqual(facts[0]["references"], [])
        self.assertNotIn("completed", facts[0])

    def test_repeated_and_cross_app_ids_keep_separate_provenance(self):
        ledger = EvidenceLedger(TOOLS)
        shared_id = "record-9"

        facts = ledger.sync([
            observation("contacts.search", {"ok": True, "contacts": [{"id": shared_id}]}),
            observation("contacts.search", {"ok": True, "contacts": [{"id": shared_id}]}),
            observation("calendar.list_events", {"ok": True, "events": [{"id": shared_id}]}),
        ])

        references = [fact["references"][0] for fact in facts]
        self.assertEqual([fact["step"] for fact in facts], [1, 2, 3])
        self.assertEqual([reference["scope"] for reference in references], [
            "contacts.contacts", "contacts.contacts", "calendar.events",
        ])
        self.assertEqual([reference["id"] for reference in references], [shared_id] * 3)

    def test_same_collection_name_in_different_apps_keeps_its_own_scope(self):
        ledger = EvidenceLedger(TOOLS)
        same_key = "booking-3"

        facts = ledger.sync([
            observation("flights.search_bookings", {
                "ok": True, "bookings": [{"id": same_key, "flight": "VN1"}],
            }),
            observation("trains.list_bookings", {
                "ok": True, "bookings": [{"id": same_key, "route": "SE2"}],
            }),
        ])

        references = [fact["references"][0] for fact in facts]
        self.assertEqual([reference["scope"] for reference in references], [
            "flights.bookings", "trains.bookings",
        ])
        self.assertEqual([reference["id"] for reference in references], [same_key, same_key])

    def test_result_evidence_does_not_create_an_exhaustive_id_allowlist(self):
        ledger = EvidenceLedger(TOOLS)
        facts = ledger.sync([observation("contacts.search", {
            "ok": True, "contacts": [{"id": "observed-contact"}],
        })])

        # A request/history ID remains in the original prepared input; the ledger only
        # describes observations and provides no set that could reject other supplied IDs.
        self.assertEqual(facts[0]["references"][0]["id"], "observed-contact")
        self.assertNotIn("allowed_ids", facts[0])
        self.assertNotIn("enum", facts[0])

    def test_extraction_is_bounded_by_observation_reference_and_id_limits(self):
        ledger = EvidenceLedger(TOOLS, max_observations=2,
                                max_references_per_observation=2, max_id_chars=12)
        results = [observation("contacts.search", {
            "ok": True,
            "contacts": [{"id": f"contact-{index}"} for index in range(100)],
        }) for _ in range(3)]
        results[1]["result"]["contacts"].append({"id": "x" * 100})

        facts = ledger.sync(results)

        # The rendering shape remains positionally aligned to the caller's observations;
        # only the configured prefix is eligible for extraction.
        self.assertEqual(len(facts), len(results))
        self.assertLessEqual(sum(bool(fact and fact["references"]) for fact in facts), 2)
        for fact in facts:
            if fact is not None:
                self.assertLessEqual(len(fact["references"]), 2)
                self.assertTrue(all(len(reference["id"]) <= 12 for reference in fact["references"]))

    def test_one_result_with_many_scopes_stays_within_renderer_reference_bound(self):
        collections = [f"records_{index}" for index in range(9)]
        tools = [{"name": "catalog.search", "returns": "records[]",
                  "parameters": {"type": "object", "properties": {}}}]
        tools.extend({"name": f"catalog.use_{index}", "returns": "",
                      "parameters": {"type": "object", "properties": {
                          "record_id": {"type": "string", "x-ref": f"catalog.{collection}"}}}}
                     for index, collection in enumerate(collections))
        result = {"ok": True} | {collection: [{"id": f"id-{index}"}]
                                  for index, collection in enumerate(collections)}

        fact = EvidenceLedger(tools).sync([observation("catalog.search", result)])[0]

        self.assertLessEqual(len(fact["references"]), 8)
        self.assertLessEqual(len(fact.get("returned_counts", [])), 8)

    def test_serialized_fact_budget_drops_optional_facts_instead_of_expanding(self):
        ledger = EvidenceLedger(TOOLS, max_chars=1)

        facts = ledger.sync([observation("contacts.search", {
            "ok": True, "contacts": [{"id": "contact-7"}],
        })])

        self.assertEqual(facts, [None])

    def test_zero_reference_budget_also_blocks_item_shape_references(self):
        ledger = EvidenceLedger(TOOLS, max_references_per_observation=0)

        facts = ledger.sync([observation("contacts.search", {
            "ok": True, "item": {"id": "contact-7"}, "id": "contact-7",
        })])

        self.assertEqual(facts[0]["references"], [])


if __name__ == "__main__":
    unittest.main()
