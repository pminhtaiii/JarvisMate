"""Bounded single-sample execution. No model decisions are executed as code."""
from __future__ import annotations

import time

from .contracts import (ASR, Deadline, EnvironmentFactory, JSON, Limits,
                        PipelineError, Planner, SampleInput, SampleOutcome, TraceSink)
from .dataset import prepare_request
from .jsonio import dumps, loads
from .prompting import planner_input


def parse_action(raw: str, max_bytes: int = 65_536) -> JSON:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > max_bytes:
        raise ValueError("Response is not bounded text")
    value = loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Action must be an object")
    if value == {"action": "finish"}:
        return value
    if (set(value) != {"action", "name", "arguments"} or value["action"] != "call"
            or not isinstance(value["name"], str) or not value["name"]
            or not isinstance(value["arguments"], dict)):
        raise ValueError("Expected a call with name/arguments, or finish")
    return value


def authoritative(env, sample_id: str) -> JSON:
    from .artifacts import validate_prediction

    result = {"id": sample_id, "tool_calls": env.get_tool_calls(), "state_hash": env.get_state_hash()}
    validate_prediction(result)
    return result


def run_sample(sample: SampleInput, planner: Planner, asr: ASR | None,
               environment_factory: EnvironmentFactory, trace: TraceSink,
               limits: Limits, *, split: str, data_root,
               clock=time.monotonic) -> SampleOutcome:
    deadline = Deadline(limits.timeout, clock)
    env, steps, stage = None, 0, "request"
    timings = {"request": 0.0, "planner": 0.0, "tools": 0.0}
    try:
        trace.emit("sample_started", input_mode=sample.mode)
        started = clock()
        prepared = prepare_request(sample, asr, deadline)
        timings["request"] = clock() - started
        trace.emit("request_prepared", payload={"request": prepared["request"], "history": prepared["history"]},
                   available_tools=[t["name"] for t in sample.tools])
        deadline.remaining()
        stage = "environment"
        env = environment_factory(split, sample.id, data_root)
        deadline.remaining()
        allowed = {t["name"] for t in sample.tools}
        observations: list[JSON] = []
        status, reason = "completed", "finish"
        for steps in range(1, limits.max_steps + 1):
            stage = "planner"
            started = clock()
            raw = planner.next_action(planner_input(prepared, observations), deadline.remaining())
            timings["planner"] += clock() - started
            deadline.remaining()
            # Bound raw output before even debug tracing it.
            if not isinstance(raw, str) or len(raw.encode("utf-8")) > limits.response_bytes:
                raise PipelineError("PLANNER_ERROR", "Planner output is not bounded text", stage)
            trace.emit("planner_action", step=steps, payload={"response": raw})
            try:
                action = parse_action(raw, limits.response_bytes)
                if action["action"] == "call" and action["name"] not in allowed:
                    raise ValueError("Tool unavailable in this sample")
            except (ValueError, TypeError, UnicodeError, RecursionError):
                feedback = {"step": steps, "kind": "validation_rejection",
                            "message": "Return one strict call/finish JSON using only available tool names."}
                trace.emit("validation_result", step=steps, accepted=False,
                           scope="action_shape_and_eligibility", payload=feedback)
                observations.append(feedback)
                continue
            trace.emit("validation_result", step=steps, accepted=True, action=action["action"],
                       scope="action_shape_and_eligibility",
                       arguments_schema="delegated_to_env.call" if action["action"] == "call" else "not_applicable")
            if action["action"] == "finish":
                break
            stage = "dispatch"
            trace.emit("tool_call_started", step=steps, name=action["name"], payload=action["arguments"])
            deadline.remaining()
            started = clock()
            # Arguments, including schema-invalid ones, reach the authoritative logger.
            try:
                result = env.call(action["name"], action["arguments"])
            except Exception as exc:
                raise PipelineError("EXECUTION_UNCERTAIN", "Tool execution raised; do not retry", stage) from exc
            timings["tools"] += clock() - started
            if not isinstance(result, dict):
                raise PipelineError("EXECUTION_UNCERTAIN", "Invalid tool response; do not retry", stage)
            dumps(result)
            trace.emit("tool_call_result", step=steps, name=action["name"], payload=result)
            deadline.remaining()
            observations.append({"step": steps, "kind": "tool_result", "name": action["name"],
                                 "arguments": action["arguments"], "result": result})
            if (action["name"] == "sys.ask_missing_info" and result.get("ok") is True
                    and result.get("waiting_for_user") is True):
                status, reason = "needs_info", "waiting_for_user"
                break
        else:
            raise PipelineError("STEP_LIMIT", "Planner decision budget exhausted", "planner")
        stage = "collection"
        deadline.remaining()
        result = authoritative(env, sample.id)
        deadline.remaining()
        trace.emit("sample_finished", step=steps, status=status, stop_reason=reason,
                   payload=result, timings=timings)
        deadline.remaining()
        return SampleOutcome(sample.id, status, deadline.elapsed(), steps, reason,
                             result=result, timings=timings)
    except Exception as exc:
        error = exc if isinstance(exc, PipelineError) else PipelineError(
            "EXECUTION_UNCERTAIN" if stage in {"environment", "dispatch", "collection"} else "PLANNER_ERROR",
            "Sample failed; inspect stage and local trace", stage)
        diagnostic = None
        if env is not None:
            try:
                diagnostic = authoritative(env, sample.id)
            except Exception:
                pass  # Best-effort diagnostics cannot justify a second environment or call.
        try:
            trace.emit("sample_failed", step=steps, error=error.record(), payload=diagnostic)
        except Exception:
            error = PipelineError("TRACE_IO", "Failure trace could not be persisted", "trace")
        return SampleOutcome(sample.id, "failed", deadline.elapsed(), steps, error.code,
                             error=error.record(), diagnostic=diagnostic, timings=timings)
