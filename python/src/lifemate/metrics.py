"""Validated timing/generation records and an injectable monotonic span clock.

Additive to the existing coarse `SampleOutcome.timings` bucket (contracts.py);
this module defines the shapes orchestration code (dataset.py/agent.py/cli.py,
a later task) will populate per `contracts/measurement.md`. It never reads a
sample's data itself and never runs a model.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Callable, Literal

from .contracts import PipelineError

METRICS_SCHEMA_VERSION = 1

Stage = Literal[
    "request", "asr_clip", "environment_open", "planner_decision",
    "generation", "tool_call", "final_collection", "prediction_output", "trace_close",
]
SPAN_STAGES = frozenset(Stage.__args__)
SpanStatus = Literal["completed", "failed", "unfinished"]
SPAN_STATUSES = frozenset(SpanStatus.__args__)
ModelRole = Literal["planner_action", "selection_filter", "asr"]
MODEL_ROLES = frozenset(ModelRole.__args__)
StopReason = Literal["eos", "max_tokens", "deadline", "error", "unknown"]
STOP_REASONS = frozenset(StopReason.__args__)


def _finite(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise PipelineError("INPUT_INVALID", f"{name} must be a finite number")
    return float(value)


def _nonnegative(value, name: str) -> float:
    value = _finite(value, name)
    if value < 0:
        raise PipelineError("INPUT_INVALID", f"{name} must be nonnegative")
    return value


def _nonnegative_int(value, name: str) -> int:
    if type(value) is not int or value < 0:
        raise PipelineError("INPUT_INVALID", f"{name} must be a nonnegative integer")
    return value


class Clock:
    """One instance anchors every span offset for a single sample attempt."""

    def __init__(self, fn: Callable[[], float] = time.monotonic):
        self._fn = fn
        self.origin = fn()

    def offset(self) -> float:
        return self._fn() - self.origin


@dataclass(frozen=True)
class Span:
    """One timing span. Nested spans (e.g. `generation` inside `planner_decision`)
    overlap by design; do not sum a child back into its parent's total."""

    stage: Stage
    start_offset: float
    end_offset: float | None = None
    status: SpanStatus = "completed"
    index: int | None = None
    parent_stage: Stage | None = None
    lower_bound_duration: float | None = None
    unavailable_reason: str | None = None

    def __post_init__(self):
        if self.stage not in SPAN_STAGES:
            raise PipelineError("INPUT_INVALID", "Invalid span stage")
        if self.status not in SPAN_STATUSES:
            raise PipelineError("INPUT_INVALID", "Invalid span status")
        if self.parent_stage is not None and self.parent_stage not in SPAN_STAGES:
            raise PipelineError("INPUT_INVALID", "Invalid parent span stage")
        if self.index is not None:
            _nonnegative_int(self.index, "span index")
        _nonnegative(self.start_offset, "start_offset")
        if self.status == "unfinished":
            if self.end_offset is not None:
                raise PipelineError("INPUT_INVALID", "An unfinished span cannot have an end offset")
            if self.lower_bound_duration is not None:
                _nonnegative(self.lower_bound_duration, "lower_bound_duration")
        else:
            if self.end_offset is None:
                raise PipelineError("INPUT_INVALID", "A terminal span requires an end offset")
            if self.lower_bound_duration is not None:
                raise PipelineError("INPUT_INVALID", "A terminal span cannot carry a lower-bound duration")
            end = _nonnegative(self.end_offset, "end_offset")
            if end < self.start_offset:
                raise PipelineError("INPUT_INVALID", "Span end precedes its start")

    @property
    def duration(self) -> float | None:
        return None if self.end_offset is None else self.end_offset - self.start_offset

    def to_json(self) -> dict:
        return {"stage": self.stage, "index": self.index, "parent_stage": self.parent_stage,
                "start_offset": self.start_offset, "end_offset": self.end_offset,
                "duration": self.duration, "status": self.status,
                "lower_bound_duration": self.lower_bound_duration,
                "unavailable_reason": self.unavailable_reason}


@dataclass(frozen=True)
class Generation:
    """Optional per-generation detail. Each count/timing field is independently
    nullable: a telemetry-capable adapter may know some fields and not others.
    Absence of a whole record (not emitted at all) is how a legacy/custom
    adapter without this capability is represented — never a fabricated one."""

    role: ModelRole
    index: int
    seconds: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    stop_reason: StopReason | None = None

    def __post_init__(self):
        if self.role not in MODEL_ROLES:
            raise PipelineError("INPUT_INVALID", "Invalid generation role")
        _nonnegative_int(self.index, "generation index")
        if self.seconds is not None:
            _nonnegative(self.seconds, "generation seconds")
        if self.input_tokens is not None:
            _nonnegative_int(self.input_tokens, "input_tokens")
        if self.output_tokens is not None:
            _nonnegative_int(self.output_tokens, "output_tokens")
        if self.stop_reason is not None and self.stop_reason not in STOP_REASONS:
            raise PipelineError("INPUT_INVALID", "Invalid generation stop reason")

    @property
    def rate(self) -> float | None:
        if self.output_tokens is None or self.seconds is None or self.seconds <= 0:
            return None
        rate = self.output_tokens / self.seconds
        # A very small positive duration can make this quotient infinite; jsonio
        # rejects non-finite values, so persisting the sample would otherwise fail.
        return rate if math.isfinite(rate) else None

    def to_json(self) -> dict:
        return {"role": self.role, "index": self.index, "seconds": self.seconds,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "rate": self.rate, "stop_reason": self.stop_reason}


@dataclass
class SpanRecorder:
    """The optional sink for one sample attempt: a shared `Clock` plus the spans
    and generations observed against it, in recording order."""

    clock: Clock = field(default_factory=Clock)
    spans: list[Span] = field(default_factory=list)
    generations: list[Generation] = field(default_factory=list)

    def mark(self, stage: Stage, start_offset: float, status: SpanStatus = "completed", *,
             index: int | None = None, parent_stage: Stage | None = None,
             unavailable_reason: str | None = None) -> Span:
        span = Span(stage, start_offset, self.clock.offset(), status, index, parent_stage,
                   None, unavailable_reason)
        self.spans.append(span)
        return span

    def unfinished(self, stage: Stage, start_offset: float, *, index: int | None = None,
                   parent_stage: Stage | None = None, lower_bound_duration: float | None = None,
                   unavailable_reason: str | None = None) -> Span:
        span = Span(stage, start_offset, None, "unfinished", index, parent_stage,
                   lower_bound_duration, unavailable_reason)
        self.spans.append(span)
        return span

    def record_generation(self, generation: Generation) -> None:
        self.generations.append(generation)

    def to_json(self) -> dict:
        return {"metrics_schema_version": METRICS_SCHEMA_VERSION,
                "spans": [s.to_json() for s in self.spans],
                "generations": [g.to_json() for g in self.generations]}


__all__ = [
    "Clock", "Generation", "METRICS_SCHEMA_VERSION", "ModelRole", "Span",
    "SpanRecorder", "SpanStatus", "Stage", "StopReason",
]
