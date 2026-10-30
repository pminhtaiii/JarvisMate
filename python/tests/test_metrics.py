"""metrics.py: validated spans/generations and the injectable clock (T002)."""
from __future__ import annotations

import unittest

from lifemate.contracts import PipelineError
from lifemate.metrics import (
    METRICS_SCHEMA_VERSION, Clock, Generation, Span, SpanRecorder,
)


class FakeClock:
    def __init__(self, ticks):
        self._ticks = iter(ticks)

    def __call__(self):
        return next(self._ticks)


class ClockTests(unittest.TestCase):
    def test_offset_is_relative_to_construction(self):
        clock = Clock(FakeClock([10.0, 10.0, 12.5, 15.0]))
        self.assertEqual(clock.offset(), 0.0)
        self.assertEqual(clock.offset(), 2.5)
        self.assertEqual(clock.offset(), 5.0)

    def test_default_clock_uses_monotonic(self):
        clock = Clock()
        self.assertGreaterEqual(clock.offset(), 0.0)


class SpanTests(unittest.TestCase):
    def test_terminal_span_requires_end_offset(self):
        with self.assertRaises(PipelineError) as ctx:
            Span("request", 0.0, status="completed")
        self.assertEqual(ctx.exception.code, "INPUT_INVALID")

    def test_unfinished_span_rejects_end_offset(self):
        with self.assertRaises(PipelineError):
            Span("request", 0.0, end_offset=1.0, status="unfinished")

    def test_terminal_span_rejects_lower_bound_duration(self):
        with self.assertRaises(PipelineError):
            Span("request", 0.0, end_offset=1.0, lower_bound_duration=0.5)

    def test_end_before_start_rejected(self):
        with self.assertRaises(PipelineError):
            Span("request", 5.0, end_offset=1.0)

    def test_invalid_stage_rejected(self):
        with self.assertRaises(PipelineError):
            Span("not_a_stage", 0.0, end_offset=1.0)

    def test_duration_and_json_for_a_completed_span(self):
        span = Span("tool_call", 1.0, end_offset=3.5, index=2, parent_stage="planner_decision")
        self.assertEqual(span.duration, 2.5)
        payload = span.to_json()
        self.assertEqual(payload["stage"], "tool_call")
        self.assertEqual(payload["duration"], 2.5)
        self.assertEqual(payload["parent_stage"], "planner_decision")

    def test_unfinished_span_has_null_duration_and_optional_lower_bound(self):
        span = Span("generation", 0.0, status="unfinished", lower_bound_duration=4.0,
                    unavailable_reason="process_lost")
        self.assertIsNone(span.duration)
        self.assertEqual(span.to_json()["lower_bound_duration"], 4.0)
        self.assertEqual(span.to_json()["unavailable_reason"], "process_lost")


class GenerationTests(unittest.TestCase):
    def test_invalid_role_rejected(self):
        with self.assertRaises(PipelineError):
            Generation("not_a_role", 0)

    def test_negative_index_rejected(self):
        with self.assertRaises(PipelineError):
            Generation("planner_action", -1)

    def test_negative_token_counts_rejected(self):
        with self.assertRaises(PipelineError):
            Generation("planner_action", 0, output_tokens=-1)

    def test_invalid_stop_reason_rejected(self):
        with self.assertRaises(PipelineError):
            Generation("planner_action", 0, stop_reason="not_a_reason")

    def test_rate_requires_both_tokens_and_positive_duration(self):
        self.assertIsNone(Generation("planner_action", 0).rate)
        self.assertIsNone(Generation("planner_action", 0, output_tokens=10).rate)
        self.assertIsNone(Generation("planner_action", 0, output_tokens=10, seconds=0.0).rate)
        self.assertEqual(Generation("planner_action", 0, output_tokens=10, seconds=2.0).rate, 5.0)

    def test_rate_stays_finite_or_null_never_infinite(self):
        # A vanishingly small positive duration can make the quotient overflow to
        # inf; jsonio rejects non-finite values, so persisting the sample would fail.
        generation = Generation("planner_action", 0, output_tokens=10**18, seconds=1e-300)
        self.assertIsNone(generation.rate)

    def test_partial_availability_keeps_other_fields_null(self):
        generation = Generation("asr", 1, input_tokens=120)
        payload = generation.to_json()
        self.assertEqual(payload["input_tokens"], 120)
        self.assertIsNone(payload["output_tokens"])
        self.assertIsNone(payload["seconds"])
        self.assertIsNone(payload["rate"])


class SpanRecorderTests(unittest.TestCase):
    def test_mark_appends_a_completed_span_against_the_shared_clock(self):
        recorder = SpanRecorder(clock=Clock(FakeClock([0.0, 0.0, 1.0, 2.0])))
        start = recorder.clock.offset()
        recorder.mark("request", start)
        self.assertEqual(len(recorder.spans), 1)
        self.assertEqual(recorder.spans[0].duration, 1.0)

    def test_unfinished_records_a_lower_bound_without_an_end_offset(self):
        recorder = SpanRecorder()
        start = recorder.clock.offset()
        span = recorder.unfinished("tool_call", start, lower_bound_duration=0.0,
                                   unavailable_reason="crashed")
        self.assertEqual(span.status, "unfinished")
        self.assertIsNone(span.end_offset)

    def test_record_generation_and_serialize(self):
        recorder = SpanRecorder()
        recorder.record_generation(Generation("planner_action", 0, seconds=1.0, output_tokens=5))
        payload = recorder.to_json()
        self.assertEqual(payload["metrics_schema_version"], METRICS_SCHEMA_VERSION)
        self.assertEqual(len(payload["generations"]), 1)
        self.assertEqual(payload["generations"][0]["role"], "planner_action")

    def test_nested_spans_are_independent_entries_not_summed(self):
        recorder = SpanRecorder(clock=Clock(FakeClock([0.0, 0.0, 0.5, 1.0, 1.0])))
        outer_start = recorder.clock.offset()
        inner_start = recorder.clock.offset()
        recorder.mark("generation", inner_start, parent_stage="planner_decision")
        recorder.mark("planner_decision", outer_start)
        self.assertEqual(len(recorder.spans), 2)
        self.assertEqual(recorder.spans[0].duration, 0.5)
        self.assertEqual(recorder.spans[1].duration, 1.0)


if __name__ == "__main__":
    unittest.main()
