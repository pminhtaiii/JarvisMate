"""Bounded single-sample execution. No model decisions are executed as code."""
from __future__ import annotations

from contextlib import ExitStack
import time

from .adapters.common import inference_session
from .adapters.qwen_native import MAX_REPAIRS, NativeProposalRejected, fingerprint, rejection_record
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
            precheck = getattr(environment_factory, "schema_precheck", None)
            observations: list[JSON] = []
            rejections = 0
            last_failure, repeated_failures = None, 0
            status, reason = "completed", "finish"
            for steps in range(1, limits.max_steps + 1):
                stage = "planner"
                started = clock()
                rejected = None
                try:
                    raw = planner.next_action(planner_input(prepared, observations), deadline.remaining())
                except NativeProposalRejected as exc:
                    rejected, raw = exc, None
                finally:
                    for detail in getattr(planner, "last_decision_details", ()):
                        trace.emit("planner_selection", step=steps, payload=detail)
                    generation = getattr(planner, "last_generation", None)
                    if generation:
                        trace.emit("native_generation", step=steps, payload={"text": generation.get("text")},
                                   **{k: v for k, v in generation.items() if k != "text"})
                timings["planner"] += clock() - started
                deadline.remaining()
                if rejected is None:
                    # Bound raw output before even debug tracing it.
                    if not isinstance(raw, str) or len(raw.encode("utf-8")) > limits.response_bytes:
                        raise PipelineError("PLANNER_ERROR", "Planner output is not bounded text", stage)
                    trace.emit("planner_action", step=steps, payload={"response": raw})
                    try:
                        action = parse_action(raw, limits.response_bytes)
                        if action["action"] == "call" and action["name"] not in allowed:
                            rejected = ("NATIVE_UNAVAILABLE_TOOL", raw)
                    except (ValueError, TypeError, UnicodeError, RecursionError):
                        rejected = ("NATIVE_JSON_INVALID", raw)
                if rejected is not None:
                    if isinstance(rejected, NativeProposalRejected):
                        record, identity = dict(rejected.record, step=steps), rejected.full_output_sha256
                    else:
                        # A compatibility planner returned a complete internal string; no
                        # native stop evidence exists, so stop metadata is unknown (null).
                        code, text = rejected
                        record = rejection_record(steps, code, text, stop_reason=None,
                                                  eos_observed=None, repairable=True)
                        identity = fingerprint(code, text)
                    trace.emit("validation_result", step=steps, accepted=False,
                               scope="native_shape_and_eligibility", code=record["code"],
                               output_fingerprint=identity, payload=record)
                    if not record["repairable"]:
                        code = "OUTPUT_LIMIT" if record["code"] == "NATIVE_TRUNCATED" else "PLANNER_FORMAT"
                        raise PipelineError(code, f"Unrepairable native proposal: {record['code']}", "planner")
                    # A third invalid proposal (identical or not) exceeds the total cap.
                    rejections += 1
                    if rejections > MAX_REPAIRS:
                        raise PipelineError("PLANNER_FORMAT", "Native repair budget exhausted", "planner")
                    # Prior actual calls/results stay intact; nothing was dispatched.
                    observations.append({"step": steps, "kind": "native_rejection", "record": record})
                    continue
                trace.emit("validation_result", step=steps, accepted=True, action=action["action"],
                           scope="native_shape_and_eligibility",
                           arguments_schema="delegated_to_env.call" if action["action"] == "call" else "not_applicable")
                if action["action"] == "finish":
                    break
                if precheck is not None:
                    # Pure organizer schema check; records a violation but never replaces env.call.
                    checked = precheck(sample, action["name"], action["arguments"])
                    trace.emit("validation_result", step=steps, accepted=checked["status"] != "invalid",
                               scope="pure_schema_precheck", status=checked["status"], dispatch="env.call",
                               error=None if checked["error"] is None else str(checked["error"])[:500])
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
                # Schema errors with the same cause are not progress, even if the model
                # changes an irrelevant optional parameter. Every dispatched call stays logged.
                failure = ((action["name"], dumps(result)) if result.get("ok") is False else
                           (action["name"], dumps(action["arguments"]), dumps(result))
                           if result.get("done") is False else None)
                repeated_failures = repeated_failures + 1 if failure is not None and failure == last_failure else 1
                last_failure = failure
                if failure is not None and repeated_failures >= 3:
                    raise PipelineError("NO_PROGRESS", "Three consecutive tool failures without progress", "planner")
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
