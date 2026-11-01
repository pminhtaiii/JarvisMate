"""Synthetic arguments and organizer-schema integration; no models or hidden state."""
import copy
from dataclasses import replace
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from lifemate.agent import run_sample
from lifemate.adapters.constrained import argument_schemas
from lifemate.arguments import ArgumentRejection, check_references, normalize_arguments
from lifemate.contracts import Limits
from lifemate.dataset import preflight
from lifemate.numbers import number, quantity
from lifemate.temporal import temporal
from support import FINISH, ControlledEnvironment, ControlledPlanner, Fixture, MemoryTrace, call

ROOT = Path(__file__).resolve().parents[2]
CONTEXT = {"current_time": "2026-12-31T23:45:00+07:00", "timezone": "Asia/Ho_Chi_Minh"}


def tool(properties):
    return {"parameters": {"type": "object", "properties": properties}}


class NumberTests(unittest.TestCase):
    def test_numbers_scales_decimals_and_regional_variants(self):
        for text, expected in (("năm trăm nghìn", 500000), ("năm trăm ngàn", 500000),
                               ("một triệu hai trăm nghìn", 1200000), ("hai mươi mốt", 21),
                               ("hai mươi tư", 24), ("hai mươi lăm", 25), ("một trăm lẻ năm", 105),
                               ("một triệu rưỡi", 1500000), ("1,5 triệu", 1500000),
                               ("1.234.567,5", Decimal("1234567.5")),
                               ("hai phẩy không năm", Decimal("2.05")), ("âm năm", -5),
                               ("một tỷ hai triệu ba nghìn", 1002003000), ("500000", 500000)):
            with self.subTest(text=text):
                self.assertEqual(number(text), expected)

    def test_bad_or_ambiguous_number_grammar_is_not_silently_repaired(self):
        for value in ("", "một hai", "một trăm năm", "hai mươi mười", "năm xị",
                      "triệu", "một nghìn triệu", "NaN", "Inf", "1e6", "1.23.4", "năm trăm abc"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                number(value)

    def test_explicit_units(self):
        for text, field, expected in (("năm trăm nghìn đồng", "amount", 500000),
                                      ("500.000 VND", "amount", 500000),
                                      ("một tiếng rưỡi", "minutes", 90),
                                      ("hai phút", "delay_seconds", 120),
                                      ("ba mươi phút", "delay_minutes", 30),
                                      ("hai mươi sáu độ C", "temperature", 26)):
            with self.subTest(text=text):
                self.assertEqual(quantity(text, field), expected)


class TemporalTests(unittest.TestCase):
    def test_explicit_dates_and_relative_day_rollover(self):
        for value, expected in (("31/12/2026", "2026-12-31"), ("ngày mai", "2027-01-01"),
                                ("ngày kia", "2027-01-02"), ("hôm qua", "2026-12-30"),
                                ("thứ sáu tới", "2027-01-01"), ("thứ hai tuần sau", "2027-01-04")):
            with self.subTest(value=value):
                self.assertEqual(temporal(value, "date", CONTEXT), expected)

    def test_relative_datetimes_use_sample_clock(self):
        for value, expected in (("ba giờ chiều mai", "2027-01-01T15:00:00+07:00"),
                                ("mai lúc 15:00", "2027-01-01T15:00:00+07:00"),
                                ("01/01/2027 15:30:45", "2027-01-01T15:30:45+07:00"),
                                ("sau ba mươi phút", "2027-01-01T00:15:00+07:00"),
                                ("một giờ rưỡi chiều mai", "2027-01-01T13:30:00+07:00"),
                                ("mười hai giờ sáng mai", "2027-01-01T00:00:00+07:00"),
                                ("mười hai giờ trưa mai", "2027-01-01T12:00:00+07:00")):
            with self.subTest(value=value):
                self.assertEqual(temporal(value, "date-time", CONTEXT), expected)

    def test_valid_literals_preserve_precision_and_timezone(self):
        for value, fmt in (("2026-11-11T05:30:00+07:00", "date-time"),
                           ("2026-11-11T05:30Z", "date-time"),
                           ("2026-11-11T05:30:00.125+07:00", "date-time"),
                           ("19:00", "time"), ("19:00:03", "time"), ("2026-11-11", "date")):
            with self.subTest(value=value):
                self.assertEqual(temporal(value, fmt, CONTEXT), value)
        self.assertEqual(temporal("2026-11-11T05:30:00", "date-time", CONTEXT), "2026-11-11T05:30:00+07:00")
        self.assertEqual(temporal("không giờ", "time", CONTEXT), "00:00")

    def test_missing_information_and_impossible_dates_are_rejected(self):
        for value, fmt in (("31/02/2026", "date"), ("29/02/2026", "date"),
                           ("01/11", "date"), ("ba giờ mai", "date-time"),
                           ("ba giờ chiều", "date-time"), ("mai", "date-time"),
                           ("25:00", "time"), ("12:60", "time"),
                           ("sau âm hai phút", "date-time"), ("2026-12-31T23:00:61+07:00", "date-time")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                temporal(value, fmt, CONTEXT)
        self.assertEqual(temporal("29/02/2028", "date", CONTEXT), "2028-02-29")

    def test_timezone_conversion_and_missing_windows_database(self):
        context = {**CONTEXT, "current_time": "2026-12-31T18:00:00+00:00"}
        self.assertEqual(temporal("hôm nay", "date", context), "2027-01-01")
        with patch("lifemate.temporal.ZoneInfo", side_effect=ZoneInfoNotFoundError):
            self.assertEqual(temporal("sau một giờ", "date-time", CONTEXT), "2027-01-01T00:45:00+07:00")
            with self.assertRaises(ValueError):
                temporal("sau một giờ", "date-time", {**CONTEXT, "timezone": "Europe/Paris"})

    def test_dst_fold_and_gap_rejected_when_database_available(self):
        try:
            ZoneInfo("America/New_York")
        except ZoneInfoNotFoundError:
            self.skipTest("IANA database unavailable")
        context = {"current_time": "2026-01-01T00:00:00-05:00", "timezone": "America/New_York"}
        for value in ("08/03/2026 02:30", "01/11/2026 01:30"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                temporal(value, "date-time", context)


class ArgumentTests(unittest.TestCase):
    def test_only_typed_fields_change_and_input_is_immutable(self):
        schema = tool({"amount": {"type": "integer"}, "time": {"type": "string", "format": "date-time"},
                       "phone_number": {"type": "string"}, "content": {"type": "string"},
                       "mode": {"type": "string", "enum": ["năm"]},
                       "account_id": {"type": "string", "x-ref": "banking.accounts"}})
        original = {"amount": "năm trăm nghìn", "time": "ba giờ chiều mai", "phone_number": "0900123456",
                    "content": "Gửi năm trăm nghìn ngày mai", "mode": "năm", "account_id": "000123"}
        args = copy.deepcopy(original)
        result = normalize_arguments(args, schema, CONTEXT)
        self.assertEqual(result, {**original, "amount": 500000, "time": "2027-01-01T15:00:00+07:00"})
        self.assertEqual(args, original)

    def test_numeric_phones_are_not_guessed_or_leading_zeros_invented(self):
        args = {"phone_number": 900123456}
        self.assertEqual(normalize_arguments(args, tool({"phone_number": {"type": "string"}}), CONTEXT), args)

    def test_fraction_in_integer_field_rejects_instead_of_rounding(self):
        with self.assertRaises(ArgumentRejection):
            normalize_arguments({"minutes": "một giây"}, tool({"minutes": {"type": "integer"}}), CONTEXT)

    def test_catalog_description_supports_dates_without_format_and_arrays(self):
        schema = tool({"start": {"type": "string", "description": "ISO-8601 đầy đủ giây và offset"},
                       "dates": {"type": "array", "items": {"type": "string", "format": "date"}}})
        self.assertEqual(normalize_arguments({"start": "mai lúc 15:00", "dates": ["mai", "31/12/2026"]}, schema, CONTEXT),
                         {"start": "2027-01-01T15:00:00+07:00", "dates": ["2027-01-01", "2026-12-31"]})

    def test_actual_train_catalog_rules_pass_organizer_validator(self):
        catalog = json.loads((ROOT / "tools/train_tools_catalog.json").read_text(encoding="utf-8"))
        tools = {t["name"]: t for app in catalog["apps"] for t in app["tools"]}
        spec = importlib.util.spec_from_file_location("_argument_schema_test", ROOT / "tools/train/validate.py")
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        cases = [("banking.transfer", {"from_account_id": "a", "beneficiary_id": "b", "amount": "năm trăm nghìn"}),
                 ("calendar.create_event", {"title": "Họp", "start": "ba giờ chiều mai"}),
                 ("home_automation.create_rule", {"device_id": "d", "action": "on", "time": "bảy giờ tối"}),
                 ("fitness.log_workout", {"type": "walking", "minutes": "một tiếng rưỡi"})]
        for name, args in cases:
            with self.subTest(name=name):
                normalized = normalize_arguments(args, tools[name], CONTEXT)
                self.assertIsNone(validator.schema_error(name, normalized, catalog))

    def test_proposal_grammar_accepts_numeric_strings_without_mutating_catalog(self):
        original = tool({"amount": {"type": "integer", "exclusiveMinimum": 0},
                         "time": {"type": "string", "format": "date-time"}})
        snapshot = copy.deepcopy(original)
        props = argument_schemas(original)[0]["properties"]
        self.assertEqual(props["amount"]["anyOf"][0]["exclusiveMinimum"], 0)
        self.assertEqual(props["amount"]["anyOf"][1]["type"], "string")
        self.assertNotIn("format", props["time"])
        self.assertEqual(original, snapshot)

    def test_real_constraint_parser_accepts_numeric_expressions_and_datetimes(self):
        try:
            from lmformatenforcer import CharacterLevelParserConfig
        except ImportError:
            self.skipTest("lm-format-enforcer is an optional inference dependency")
        from lifemate.adapters.constrained import action_parser
        schema = {"name": "demo.create", **tool({
            "amount": {"type": "integer", "exclusiveMinimum": 0},
            "start": {"type": "string", "format": "date-time"}})}
        schema["parameters"]["required"] = ["amount", "start"]
        for amount, start in (("năm trăm nghìn", "ba giờ chiều mai"),
                              (500000, "2026-11-11T05:30:00+07:00")):
            value = call("demo.create", amount=amount, start=start)
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            config = CharacterLevelParserConfig(force_json_field_order=True)
            # Production uses the tokenizer's alphabet; the default is ASCII-only.
            config = replace(config, alphabet=config.alphabet + encoded)
            parser = action_parser([schema], config)
            for char in encoded:
                self.assertIn(char, parser.get_allowed_characters())
                parser = parser.add_character(char)
            self.assertTrue(parser.can_end())

    def test_reference_ids_require_successful_visible_evidence(self):
        schema = tool({"contact_id": {"type": "string", "x-ref": "contacts.contacts"}})
        prepared = {"context": {}, "history": []}
        read = {"kind": "tool_result", "name": "contacts.search",
                "result": {"ok": True, "contacts": [{"id": "c1"}]}}
        check_references({"contact_id": "c1"}, schema, prepared, [read])
        for observations in ([], [{**read, "result": {"ok": False, "contacts": [{"id": "c1"}]}}],
                             [{**read, "name": "other.search"}]):
            with self.subTest(observations=observations), self.assertRaises(ArgumentRejection):
                check_references({"contact_id": "c1"}, schema, prepared, observations)
        check_references({"contact_id": "c1"}, schema,
                         {"context": {"contact_id": "c1"}, "history": []}, [])
        array_schema = tool({"contacts": {"type": "array", "x-ref": "contacts.contacts", "items": {"type": "string"}}})
        with self.assertRaises(ArgumentRejection):
            check_references({"contacts": ["invented"]}, array_schema, prepared, [read])


class ArgumentLoopTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.close)
        sample = preflight(self.fx.config()).samples[0]
        self.amount_tool = {"name": "banking.transfer", "parameters": {
            "type": "object", "properties": {"amount": {"type": "integer", "exclusiveMinimum": 0}}}}
        self.sample = replace(sample, context={**sample.context, **CONTEXT},
                              tools=(*sample.tools, self.amount_tool))

    def execute(self, actions, env=None, sample=None):
        self.env = env or ControlledEnvironment()
        self.planner, self.trace = ControlledPlanner(actions), MemoryTrace()
        return run_sample(sample or self.sample, self.planner, None, lambda *_: self.env,
                          self.trace, Limits(), split="train", data_root=self.fx.data)

    def test_normalized_call_is_used_for_dispatch_observation_and_submission(self):
        outcome = self.execute([call("banking.transfer", amount="năm trăm nghìn"), FINISH])
        self.assertEqual(outcome.status, "completed", outcome.error)
        self.assertEqual(outcome.result["tool_calls"][0]["arguments"], {"amount": 500000})
        self.assertEqual(self.planner.inputs[1]["observations"][0]["arguments"], {"amount": 500000})
        self.assertEqual(self.planner.inputs[0]["request"], self.sample.text)

    def test_bad_normalization_can_correct_without_invalid_call_in_log(self):
        outcome = self.execute([call("banking.transfer", amount="năm xị"),
                                call("banking.transfer", amount="năm trăm nghìn"), FINISH])
        self.assertEqual(outcome.status, "completed", outcome.error)
        self.assertEqual(len(outcome.result["tool_calls"]), 1)
        self.assertEqual(self.planner.inputs[1]["observations"][0]["code"], "ARGUMENT_NORMALIZATION")

    def test_schema_preview_and_call_order_and_runtime_rejection_retention(self):
        events = []
        class Env(ControlledEnvironment):
            def validate(self, name, arguments):
                events.append(("validate", copy.deepcopy(arguments)))
                return {"ok": arguments["amount"] > 0}
            def call(self, name, arguments):
                events.append(("call", copy.deepcopy(arguments)))
                return super().call(name, arguments)
        env = Env(lambda *_: {"ok": False, "error": "execution-time rejection"})
        outcome = self.execute([call("banking.transfer", amount=-1),
                                call("banking.transfer", amount="năm trăm nghìn"), FINISH], env)
        self.assertEqual([item[0] for item in events], ["validate", "validate", "call"])
        self.assertEqual(outcome.status, "completed", outcome.error)
        self.assertEqual(len(outcome.result["tool_calls"]), 1)
        self.assertFalse(self.planner.inputs[2]["observations"][1]["result"]["ok"])

    def test_repeated_bad_arguments_stop_without_dispatch(self):
        outcome = self.execute([call("banking.transfer", amount="năm xị")] * 3)
        self.assertEqual(outcome.error["code"], "PLANNER_FORMAT")
        self.assertEqual(self.env.calls, [])

    def test_ungrounded_id_rejected_then_read_result_supplies_it(self):
        tools = copy.deepcopy(self.sample.tools)
        next(t for t in tools if t["name"] == "sms.send")["parameters"]["properties"]["contact_id"]["x-ref"] = "contacts.contacts"
        outcome = self.execute([call("sms.send", contact_id="invented", content="x"),
                                call("contacts.search", query="Lan"),
                                call("sms.send", contact_id="observed_77", content="x"), FINISH],
                               sample=replace(self.sample, tools=tools))
        self.assertEqual(outcome.status, "completed", outcome.error)
        self.assertEqual([c["name"] for c in outcome.result["tool_calls"]], ["contacts.search", "sms.send"])

    def test_ambiguous_time_can_ask_for_missing_information(self):
        date_tool = {"name": "calendar.create_event", "parameters": {
            "type": "object", "properties": {"start": {"type": "string", "format": "date-time"}}}}
        sample = replace(self.sample, tools=(*self.sample.tools, date_tool))
        outcome = self.execute([call("calendar.create_event", start="ba giờ mai"),
                                call("sys.ask_missing_info", tool_name="calendar.create_event", params=["start"])],
                               sample=sample)
        self.assertEqual(outcome.status, "needs_info", outcome.error)
        self.assertEqual([c["name"] for c in outcome.result["tool_calls"]], ["sys.ask_missing_info"])

    def test_validation_failure_never_dispatches(self):
        class Env(ControlledEnvironment):
            def validate(self, *_):
                raise RuntimeError("Validator unavailable")
        outcome = self.execute([call("banking.transfer", amount=500000)], Env())
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(self.env.calls, [])
