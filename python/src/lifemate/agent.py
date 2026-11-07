"""Bounded single-sample execution. No model decisions are executed as code."""
from __future__ import annotations

from contextlib import ExitStack
import json
import time

from .adapters.common import inference_session
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


def execute_call(env, name: str, arguments: JSON) -> JSON:
    """Dispatch one validated call; arguments, even schema-invalid ones, reach ToolEnv's log."""
    try:
        result = env.call(name, arguments)
    except Exception as exc:
        raise PipelineError("EXECUTION_UNCERTAIN", "Tool execution raised; do not retry", "dispatch") from exc
    if not isinstance(result, dict):
        raise PipelineError("EXECUTION_UNCERTAIN", "Invalid tool response; do not retry", "dispatch")
    dumps(result)
    return result


def failure_key(name: str, arguments: JSON, result: JSON):
    """Schema errors with the same cause are not progress, even if irrelevant arguments change."""
    if result.get("ok") is False:
        return name, dumps(result)
    if result.get("done") is False:
        return name, dumps(arguments), dumps(result)
    return None


def waiting_for_user(name: str, result: JSON) -> bool:
    return name == "sys.ask_missing_info" and result.get("ok") is True and result.get("waiting_for_user") is True


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
        with ExitStack() as model_sessions:
            trace.emit("sample_started", input_mode=sample.mode)
            if hasattr(planner, "start_sample"):
                planner.start_sample(sample.id)
            started = clock()
            with inference_session(asr):
                prepared = prepare_request(sample, asr, deadline)
            timings["request"] = clock() - started
            trace.emit("request_prepared", payload={"request": prepared["request"], "history": prepared["history"]},
                       available_tools=[t["name"] for t in sample.tools])
            deadline.remaining()
            model_sessions.enter_context(inference_session(planner))
            deadline.remaining()
            stage = "environment"
            env = environment_factory(split, sample.id, data_root)
            deadline.remaining()
            allowed = {t["name"] for t in sample.tools}
            observations: list[JSON] = []
            last_rejected, repeated_rejections = None, 0
            last_failure, repeated_failures = None, 0
            status, reason = "completed", "finish"
            for steps in range(1, limits.max_steps + 1):
                stage = "planner"
                started = clock()
                try:
                    raw = planner.next_action(planner_input(prepared, observations), deadline.remaining())
                finally:
                    for detail in getattr(planner, "last_decision_details", ()):
                        trace.emit("planner_selection", step=steps, payload=detail)
                timings["planner"] += clock() - started
                deadline.remaining()
                # Bound raw output before even debug tracing it.
                if not isinstance(raw, str) or len(raw.encode("utf-8")) > limits.response_bytes:
                    raise PipelineError("PLANNER_ERROR", "Planner output is not bounded text", stage)
                trace.emit("planner_action", step=steps, payload={"response": raw})
                unavailable = False
                try:
                    action = parse_action(raw, limits.response_bytes)
                    if action["action"] == "call" and action["name"] not in allowed:
                        unavailable = True
                        raise ValueError("Tool unavailable in this sample")
                except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
                    reason = (f"Invalid JSON: {exc.msg}." if isinstance(exc, json.JSONDecodeError)
                              else "Invalid action shape or unavailable tool name.")
                    if unavailable:
                        reason = ("The top-level name is not in available_tools. Copy an exact name from "
                                  "available_tools into the top-level name field. Put that tool's parameters "
                                  "directly in arguments, without nesting another name/arguments call.")
                    feedback = {"step": steps, "kind": "validation_rejection",
                                "code": "UNAVAILABLE_TOOL" if unavailable else "INVALID_ACTION",
                                "message": reason + " No tool was executed. Correct the previous response; "
                                "return exactly one call/finish JSON object, with balanced braces and no extra text.",
                                "rejected_response": raw[:4096], "response_truncated": len(raw) > 4096}
                    trace.emit("validation_result", step=steps, accepted=False,
                               scope="action_shape_and_eligibility", payload=feedback)
                    observations.append(feedback)
                    repeated_rejections = repeated_rejections + 1 if raw == last_rejected else 1
                    last_rejected = raw
                    if repeated_rejections >= 3:
                        raise PipelineError("PLANNER_FORMAT", "Planner repeated the same invalid action three times", "planner")
                    continue
                last_rejected, repeated_rejections = None, 0
                trace.emit("validation_result", step=steps, accepted=True, action=action["action"],
                           scope="action_shape_and_eligibility",
                           arguments_schema="delegated_to_env.call" if action["action"] == "call" else "not_applicable")
                if action["action"] == "finish":
                    break
                stage = "dispatch"
                trace.emit("tool_call_started", step=steps, name=action["name"], payload=action["arguments"])
                deadline.remaining()
                started = clock()
                result = execute_call(env, action["name"], action["arguments"])
                timings["tools"] += clock() - started
                trace.emit("tool_call_result", step=steps, name=action["name"], payload=result)
                deadline.remaining()
                observations.append({"step": steps, "kind": "tool_result", "name": action["name"],
                                     "arguments": action["arguments"], "result": result})
                # Schema errors with the same cause are not progress, even if the model
                # changes an irrelevant optional parameter. Every dispatched call stays logged.
                failure = failure_key(action["name"], action["arguments"], result)
                repeated_failures = repeated_failures + 1 if failure is not None and failure == last_failure else 1
                last_failure = failure
                if failure is not None and repeated_failures >= 3:
                    raise PipelineError("NO_PROGRESS", "Three consecutive tool failures without progress", "planner")
                if waiting_for_user(action["name"], result):
                    status, reason = "needs_info", "waiting_for_user"
                    break
            else:
                raise PipelineError("STEP_LIMIT", "Planner decision budget exhausted", "planner")
            stage = "collection"
            deadline.remaining()
            result = authoritative(env, sample.id)
            deadline.remaining()
            model_sessions.close()
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


def run_integration_sample(sample: SampleInput, planner, asr: ASR | None,
                           environment_factory: EnvironmentFactory, trace: TraceSink,
                           limits: Limits, deadline: Deadline, *, split: str, data_root,
                           asr_identity: str = "", clock=time.monotonic) -> SampleOutcome:
    """Native integration path (ADR 011): one prepared request, one ToolEnv, real feedback.

    ``planner.decide(prepared, observations, remaining)`` returns one canonical action
    plus decision metrics. Invalid model output fails the sample; there is no repair,
    re-prompt or unconstrained fallback. Historical calls are never executed.
    """
    from .dataset import prepare_request_once

    env, steps, stage = None, 0, "request"
    timings = {"request": 0.0, "environment": 0.0, "planner": 0.0, "tools": 0.0, "collection": 0.0}
    metrics: JSON = {"asr": None, "decisions": [], "tools": []}

    def span(name, started):
        timings[name] += clock() - started

    try:
        trace.emit("sample_started", input_mode=sample.mode, protocol="qwen-native-v1")
        started = clock()
        with inference_session(asr):
            prepared, metrics["asr"] = prepare_request_once(sample, asr, deadline, asr_identity=asr_identity,
                                                            clock=clock)
        span("request", started)
        trace.emit("request_prepared", payload={"request": prepared["request"], "history": prepared["history"]},
                   available_tools=[t["name"] for t in sample.tools],
                   asr={k: v for k, v in metrics["asr"].items() if k != "clips"})
        stage = "environment"
        deadline.remaining()
        started = clock()
        env = environment_factory(split, sample.id, data_root)
        span("environment", started)
        deadline.remaining()
        allowed = {t["name"] for t in sample.tools}
        observations: list[JSON] = []
        last_failure, repeated_failures = None, 0
        status, reason = "completed", "finish"
        with inference_session(planner):
            for steps in range(1, limits.max_steps + 1):
                stage = "planner"
                started = clock()
                action, details = planner.decide(prepared, observations, deadline.remaining())
                span("planner", started)
                metrics["decisions"].append({"step": steps, "seconds": clock() - started,
                                             "action": action["action"], **details})
                deadline.remaining()
                trace.emit("planner_decision", step=steps, action=action["action"],
                           payload=action, **{k: v for k, v in details.items() if k != "seconds"})
                if action["action"] == "finish":
                    break
                if action["action"] != "call" or action["name"] not in allowed:
                    # Constrained decoding should make this unreachable; never dispatch it.
                    raise PipelineError("PLANNER_FORMAT", "Decision names an ineligible tool", "planner")
                stage = "dispatch"
                trace.emit("tool_call_started", step=steps, name=action["name"], payload=action["arguments"])
                deadline.remaining()  # Immediately before dispatch.
                started = clock()
                result = execute_call(env, action["name"], action["arguments"])
                span("tools", started)
                metrics["tools"].append({"step": steps, "name": action["name"], "seconds": clock() - started})
                trace.emit("tool_call_result", step=steps, name=action["name"], payload=result)
                deadline.remaining()  # And on return: a late mutation cannot become success.
                observations.append({"name": action["name"], "arguments": action["arguments"], "result": result})
                failure = failure_key(action["name"], action["arguments"], result)
                repeated_failures = repeated_failures + 1 if failure is not None and failure == last_failure else 1
                last_failure = failure
                if failure is not None and repeated_failures >= 3:
                    raise PipelineError("NO_PROGRESS", "Three consecutive tool failures without progress", "planner")
                if waiting_for_user(action["name"], result):
                    status, reason = "needs_info", "waiting_for_user"
                    break
            else:
                raise PipelineError("STEP_LIMIT", "Planner decision budget exhausted", "planner")
        stage = "collection"
        deadline.remaining()
        started = clock()
        result = authoritative(env, sample.id)
        span("collection", started)
        deadline.remaining()
        trace.emit("sample_finished", step=steps, status=status, stop_reason=reason, payload=result,
                   timings=timings)
        return SampleOutcome(sample.id, status, deadline.elapsed(), steps, reason, result=result,
                             timings=timings, metrics=metrics)
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
            pass  # The supervisor ledger still records this failure; never mask the original error.
        return SampleOutcome(sample.id, "failed", deadline.elapsed(), steps, error.code,
                             error=error.record(), diagnostic=diagnostic, timings=timings, metrics=metrics)
