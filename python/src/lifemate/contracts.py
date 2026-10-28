"""Validated configuration and replaceable capability interfaces."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Protocol

JSON = dict[str, Any]
ERROR_CODES = frozenset({
    "INPUT_INVALID", "ASSET_MISSING", "CATALOG_INVALID", "MODEL_UNAVAILABLE",
    "CONTEXT_LIMIT", "STEP_LIMIT", "TIME_LIMIT", "PLANNER_ERROR",
    "EXECUTION_UNCERTAIN", "TRACE_IO", "OUTPUT_IO",
})


class PipelineError(Exception):
    def __init__(self, code: str, message: str, stage: str = "preflight"):
        if code not in ERROR_CODES:
            raise ValueError("Unknown failure code")
        super().__init__(message)
        self.code, self.stage = code, stage

    def record(self) -> JSON:
        return {"code": self.code, "stage": self.stage, "message": str(self)[:500]}


@dataclass(frozen=True)
class Limits:
    max_steps: int = 16
    timeout: float = 30.0
    context_tokens: int = 16_384
    output_tokens: int = 512
    response_bytes: int = 65_536

    def __post_init__(self):
        for name in ("max_steps", "context_tokens", "output_tokens", "response_bytes"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise PipelineError("INPUT_INVALID", f"{name} must be a positive integer")
        if (isinstance(self.timeout, bool) or not isinstance(self.timeout, (int, float))
                or not math.isfinite(self.timeout) or self.timeout <= 0):
            raise PipelineError("INPUT_INVALID", "Timeout must be positive and finite")
        if not self.output_tokens < self.context_tokens <= 16_384:
            raise PipelineError("INPUT_INVALID", "Invalid context/generation budget")


@dataclass(frozen=True)
class RunConfig:
    data_root: Path
    runtime_dir: Path
    split: str
    input_mode: str
    selected_ids: tuple[str, ...] = ()
    select_all: bool = False
    planner_model: Path | None = None
    asr_model: Path | None = None
    device: str = "cpu"
    run_dir: Path | None = None
    trace_payloads: bool = False
    limits: Limits = field(default_factory=Limits)
    seed: int = 20261027

    def __post_init__(self):
        if not isinstance(self.data_root, Path) or not isinstance(self.runtime_dir, Path):
            raise PipelineError("INPUT_INVALID", "Data/runtime directories must be paths")
        if any(p is not None and not isinstance(p, Path)
               for p in (self.run_dir, self.planner_model, self.asr_model)):
            raise PipelineError("INPUT_INVALID", "Model/output paths must be paths")
        if not isinstance(self.limits, Limits) or type(self.seed) is not int or not 0 <= self.seed < 2**32:
            raise PipelineError("INPUT_INVALID", "Invalid limits or seed")
        if (not isinstance(self.selected_ids, tuple)
                or any(not isinstance(value, str) or not value for value in self.selected_ids)
                or type(self.select_all) is not bool or type(self.trace_payloads) is not bool):
            raise PipelineError("INPUT_INVALID", "Invalid selection/trace configuration")
        if not isinstance(self.split, str) or self.split not in {"train", "public_test"}:
            raise PipelineError("INPUT_INVALID", "Unsupported dataset split")
        if not isinstance(self.input_mode, str) or self.input_mode not in {"transcript", "audio"}:
            raise PipelineError("INPUT_INVALID", "Unsupported input mode")
        if self.input_mode == "transcript" and self.split != "train":
            raise PipelineError("INPUT_INVALID", "Transcript mode is Train-only")
        if not isinstance(self.device, str) or self.device not in {"cpu", "cuda"}:
            raise PipelineError("INPUT_INVALID", "Device must be cpu or cuda")
        if bool(self.selected_ids) == self.select_all:
            raise PipelineError("INPUT_INVALID", "Select explicit IDs or --all, exclusively")
        if len(set(self.selected_ids)) != len(self.selected_ids):
            raise PipelineError("INPUT_INVALID", "Duplicate selected IDs")


@dataclass(frozen=True)
class SampleInput:
    id: str
    context: JSON
    history: tuple[JSON, ...]
    tools: tuple[JSON, ...]
    mode: str
    audio: Path
    text: str | None


@dataclass(frozen=True)
class PreparedDataset:
    samples: tuple[SampleInput, ...]
    catalog: JSON
    metadata: JSON


@dataclass
class SampleOutcome:
    id: str
    status: Literal["completed", "needs_info", "failed"]
    elapsed: float
    steps: int
    stop_reason: str
    result: JSON | None = None
    error: JSON | None = None
    diagnostic: JSON | None = None
    timings: dict[str, float] = field(default_factory=dict)


class Planner(Protocol):
    metadata: JSON

    def next_action(self, planner_input: JSON, remaining_seconds: float) -> str: ...


class ASR(Protocol):
    metadata: JSON

    def transcribe(self, audio_path: Path, remaining_seconds: float) -> str: ...


class Environment(Protocol):
    def call(self, name: str, arguments: JSON) -> JSON: ...
    def get_tool_calls(self) -> list[JSON]: ...
    def get_state_hash(self) -> str: ...


class TraceSink(Protocol):
    def emit(self, kind: str, *, step: int | None = None,
             payload: Any = None, **metadata: Any) -> None: ...


EnvironmentFactory = Callable[[str, str, Path], Environment]


class Deadline:
    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic):
        self.clock, self.started = clock, clock()
        self.ends = self.started + seconds

    def remaining(self) -> float:
        remaining = self.ends - self.clock()
        if remaining <= 0:
            raise PipelineError("TIME_LIMIT", "Sample deadline exhausted", "sample")
        return remaining

    def elapsed(self) -> float:
        return self.clock() - self.started
