"""Offline manifest readers, distributions, and report/comparison building.

Reads only durable run artifacts (manifest.json, predictions, optional evaluation
files) per `contracts/measurement.md` and `contracts/experiments.md`. Never loads
a model, creates a `ToolEnv`, or reads gold/environment files; never recomputes a
sample_score, only validates and reports the evaluator-supplied value.
"""
from __future__ import annotations

import math
from pathlib import Path

from . import artifacts
from .contracts import JSON, PipelineError
from .jsonio import digest, dumps, loads, read_json
from .metrics import MODEL_ROLES, SPAN_STAGES

REPORT_SCHEMA_VERSION = 1
EVALUATION_SCHEMA_VERSION = 1
SLOWEST_LIMIT = 10


# ---------------------------------------------------------------------------
# Nearest-rank distributions
# ---------------------------------------------------------------------------

def nearest_rank(sorted_values: list[float], p: float) -> float | None:
    n = len(sorted_values)
    if n == 0:
        return None
    index = max(0, min(math.ceil(p * n) - 1, n - 1))
    return sorted_values[index]


def distribution(values) -> JSON:
    finite = sorted(v for v in values if v is not None)
    n = len(finite)
    return {
        "count": n,
        "p50": nearest_rank(finite, 0.50),
        "p95": nearest_rank(finite, 0.95),
        "p99": nearest_rank(finite, 0.99),
        "max": finite[-1] if finite else None,
        # Descriptive-tail thresholds from contracts/measurement.md.
        "p95_descriptive_tail": n < 20,
        "p99_descriptive_tail": n < 100,
    }


# ---------------------------------------------------------------------------
# Manifest reading and validation
# ---------------------------------------------------------------------------

REQUIRED_MANIFEST_KEYS = {
    "schema_version", "run_id", "status", "selected_ids", "completed_ids",
    "failed_ids", "not_started_ids", "samples", "failures", "limits",
    "data_root", "runtime_dir", "split", "input_mode",
}


def validate_manifest(manifest: JSON) -> None:
    if not isinstance(manifest, dict):
        raise PipelineError("INPUT_INVALID", "Run manifest is not a JSON object", "report")
    missing = REQUIRED_MANIFEST_KEYS - manifest.keys()
    if missing:
        raise PipelineError("INPUT_INVALID", f"Run manifest is missing fields: {sorted(missing)}", "report")
    if manifest["schema_version"] != artifacts.SCHEMA_VERSION:
        raise PipelineError("INPUT_INVALID", "Unsupported run manifest schema version", "report")
    selected = manifest["selected_ids"]
    samples, failures, not_started = manifest["samples"], manifest["failures"], manifest["not_started_ids"]
    if (not isinstance(selected, list) or len(set(selected)) != len(selected)
            or not isinstance(samples, list) or not isinstance(failures, list)
            or not isinstance(not_started, list)):
        raise PipelineError("INPUT_INVALID", "Run manifest has invalid selection/sample fields", "report")
    try:
        sample_ids = [s["id"] for s in samples]
        failure_ids = [f["id"] for f in failures]
    except (KeyError, TypeError) as exc:
        raise PipelineError("INPUT_INVALID", "Run manifest sample/failure entries are malformed", "report") from exc
    if len(set(sample_ids)) != len(sample_ids) or len(set(failure_ids)) != len(failure_ids):
        raise PipelineError("INPUT_INVALID", "Run manifest has duplicate sample/failure IDs", "report")
    if set(sample_ids) & set(failure_ids):
        raise PipelineError("INPUT_INVALID", "Run manifest marks an ID both completed and failed", "report")
    accounted = len(sample_ids) + len(failure_ids) + len(not_started)
    if (set(sample_ids) | set(failure_ids) | set(not_started) != set(selected)
            or accounted != len(set(selected))):
        raise PipelineError("INPUT_INVALID", "Run manifest coverage does not match its selected IDs", "report")


def _journal_ids(run_dir: Path) -> set[str] | None:
    for name in ("predictions.jsonl", "predictions.partial.jsonl"):
        path = Path(run_dir) / name
        if path.is_file():
            try:
                with path.open(encoding="utf-8") as stream:
                    return {loads(line)["id"] for line in stream if line.strip()}
            except (OSError, ValueError, TypeError, UnicodeError, RecursionError, KeyError) as exc:
                raise PipelineError("INPUT_INVALID", "Prediction journal is unreadable or invalid", "report") from exc
    return None


def load_manifest(run_dir: Path) -> JSON:
    run_dir = Path(run_dir)
    manifest = read_json(run_dir / "manifest.json")
    validate_manifest(manifest)
    sample_ids = {sample["id"] for sample in manifest["samples"]}
    if sample_ids and not sample_ids <= (_journal_ids(run_dir) or set()):
        raise PipelineError("INPUT_INVALID", "Manifest lists samples missing from the prediction journal", "report")
    return manifest


def _prediction_sha256(run_dir: Path) -> str | None:
    for name in ("predictions.jsonl", "predictions.partial.jsonl"):
        path = Path(run_dir) / name
        if path.is_file():
            return digest(path)
    return None


# ---------------------------------------------------------------------------
# Per-ID entries derived from a validated manifest
# ---------------------------------------------------------------------------

def _entries(manifest: JSON) -> list[JSON]:
    entries = []
    for sample in manifest["samples"]:
        entries.append({
            "id": sample["id"], "outcome": sample.get("status"),
            "source": sample.get("source", "executed"),
            "agent_loop_seconds": sample.get("elapsed"),
            "full_attempt_seconds": sample.get("full_attempt_seconds"),
            "measurements": sample.get("measurements"),
            "error_code": None,
        })
    for failure in manifest["failures"]:
        agent_loop = failure.get("agent_loop") or {}
        entries.append({
            "id": failure["id"], "outcome": "failed", "source": "executed",
            "agent_loop_seconds": agent_loop.get("elapsed"),
            "full_attempt_seconds": failure.get("full_attempt_seconds"),
            "measurements": failure.get("measurements"),
            "error_code": (failure.get("error") or {}).get("code"),
        })
    for sample_id in manifest["not_started_ids"]:
        entries.append({
            "id": sample_id, "outcome": "not_started", "source": None,
            "agent_loop_seconds": None, "full_attempt_seconds": None,
            "measurements": None, "error_code": None,
        })
    return entries


def _current_run(entries: list[JSON]) -> list[JSON]:
    # Imported rows and not-started IDs stay outside current-run timing populations.
    return [e for e in entries if e["source"] == "executed"]


def _counts(manifest: JSON, entries: list[JSON]) -> JSON:
    current_run = _current_run(entries)
    successes = [e for e in current_run if e["outcome"] != "failed"]
    failed = [e for e in current_run if e["outcome"] == "failed"]
    imported = [e for e in entries if e["source"] == "imported"]
    not_started = [e for e in entries if e["outcome"] == "not_started"]
    known_total = [e for e in current_run if e["full_attempt_seconds"] is not None]
    timeout = manifest["limits"]["timeout"]
    return {
        "selected": len(manifest["selected_ids"]),
        "executed_completed": len(successes),
        "imported": len(imported),
        "failed": len(failed),
        "not_started": len(not_started),
        "time_limit_failures": sum(1 for e in failed if e["error_code"] == "TIME_LIMIT"),
        "known_total_over_or_at_30s": sum(1 for e in known_total if e["full_attempt_seconds"] >= 30.0),
        "unknown_total": len(current_run) - len(known_total),
        "configured_timeout_seconds": timeout,
        "configured_timeout_exceeds_30s": timeout > 30.0,
    }


def _timing(entries: list[JSON]) -> JSON:
    current_run = _current_run(entries)
    successes = [e for e in current_run if e["outcome"] != "failed"]
    return {
        "sample_total_seconds": distribution([e["full_attempt_seconds"] for e in current_run]),
        "sample_total_seconds_success_only": distribution([e["full_attempt_seconds"] for e in successes]),
        "agent_loop_seconds": distribution([e["agent_loop_seconds"] for e in current_run]),
    }


def _stage_durations(entries: list[JSON]) -> JSON:
    per_sample_totals = {stage: [] for stage in SPAN_STAGES}
    per_invocation = {stage: [] for stage in SPAN_STAGES}
    for entry in _current_run(entries):
        measurements = entry.get("measurements")
        if not measurements:
            continue
        sample_totals = {stage: 0.0 for stage in SPAN_STAGES}
        present = {stage: False for stage in SPAN_STAGES}
        for span in measurements.get("spans", []):
            if span.get("status") != "completed" or span.get("duration") is None:
                continue
            stage = span["stage"]
            sample_totals[stage] += span["duration"]
            present[stage] = True
            per_invocation[stage].append(span["duration"])
        for stage, was_present in present.items():
            if was_present:
                per_sample_totals[stage].append(sample_totals[stage])
    return {stage: {"per_sample_total": distribution(per_sample_totals[stage]),
                    "per_invocation": distribution(per_invocation[stage])}
            for stage in sorted(SPAN_STAGES)}


def _token_rates(entries: list[JSON]) -> JSON:
    by_role = {role: [] for role in MODEL_ROLES}
    for entry in _current_run(entries):
        measurements = entry.get("measurements")
        if not measurements:
            continue
        for generation in measurements.get("generations", []):
            role = generation.get("role")
            if role in by_role:
                by_role[role].append(generation)
    result = {}
    for role, generations in by_role.items():
        eligible = [g for g in generations if g.get("output_tokens") is not None
                    and g.get("seconds") is not None and g["seconds"] > 0]
        total_tokens = sum(g["output_tokens"] for g in eligible)
        total_seconds = sum(g["seconds"] for g in eligible)
        result[role] = {
            "generation_count": len(generations), "eligible_count": len(eligible),
            "total_output_tokens": total_tokens, "total_seconds": total_seconds,
            # Aggregate rate over complete records, never a mean of individual rates.
            "tokens_per_second": (total_tokens / total_seconds) if total_seconds > 0 else None,
        }
    return result


def _slowest(entries: list[JSON], limit: int = SLOWEST_LIMIT) -> list[JSON]:
    known = [e for e in _current_run(entries) if e["full_attempt_seconds"] is not None]
    ranked = sorted(known, key=lambda e: e["full_attempt_seconds"], reverse=True)[:limit]
    return [{"id": e["id"], "full_attempt_seconds": e["full_attempt_seconds"], "outcome": e["outcome"]}
            for e in ranked]


# ---------------------------------------------------------------------------
# Optional evaluation evidence (v1)
# ---------------------------------------------------------------------------

EVALUATION_REQUIRED_KEYS = {"evaluation_schema_version", "run_id", "prediction_sha256", "selected_ids", "rows"}


def _finite_unit(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and 0.0 <= value <= 1.0


def validate_evaluation(payload: JSON, manifest: JSON, prediction_sha256: str | None) -> None:
    if not isinstance(payload, dict) or EVALUATION_REQUIRED_KEYS - payload.keys():
        raise PipelineError("INPUT_INVALID", "Evaluation file is missing required fields", "evaluation")
    if payload["evaluation_schema_version"] != EVALUATION_SCHEMA_VERSION:
        raise PipelineError("INPUT_INVALID", "Unsupported evaluation schema version", "evaluation")
    if payload["run_id"] != manifest["run_id"]:
        raise PipelineError("INPUT_INVALID", "Evaluation file belongs to a different run", "evaluation")
    if prediction_sha256 is None or payload["prediction_sha256"] != prediction_sha256:
        raise PipelineError("INPUT_INVALID", "Evaluation file prediction hash does not match this run", "evaluation")
    selected = set(manifest["selected_ids"])
    eval_selected = payload["selected_ids"]
    if not isinstance(eval_selected, list) or not set(eval_selected) <= selected:
        raise PipelineError("INPUT_INVALID", "Evaluation selected_ids exceeds this run's selection", "evaluation")
    eval_selected_set = set(eval_selected)
    rows = payload["rows"]
    if not isinstance(rows, list):
        raise PipelineError("INPUT_INVALID", "Evaluation rows must be a list", "evaluation")
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise PipelineError("INPUT_INVALID", "Evaluation row must be an object", "evaluation")
        sample_id = row.get("id")
        if not isinstance(sample_id, str) or sample_id not in eval_selected_set or sample_id in seen:
            raise PipelineError("INPUT_INVALID", "Evaluation row has an unknown or duplicate sample ID", "evaluation")
        seen.add(sample_id)
        if type(row.get("gold_empty")) is not bool:
            raise PipelineError("INPUT_INVALID", "Evaluation row gold_empty must be boolean", "evaluation")
        if not _finite_unit(row.get("sample_score")):
            raise PipelineError("INPUT_INVALID", "Evaluation row sample_score must be in [0, 1]", "evaluation")
        if row.get("state_hash_match") is not None and type(row["state_hash_match"]) is not bool:
            raise PipelineError("INPUT_INVALID", "Evaluation row state_hash_match must be boolean or null", "evaluation")
        for key in ("call_precision", "call_recall", "call_f1"):
            value = row.get(key)
            if value is not None and not _finite_unit(value):
                raise PipelineError("INPUT_INVALID", f"Evaluation row {key} must be in [0, 1] or null", "evaluation")
        if row.get("empty_gold_result") is not None and type(row["empty_gold_result"]) is not bool:
            raise PipelineError("INPUT_INVALID", "Evaluation row empty_gold_result must be boolean or null", "evaluation")
        errors = row.get("errors")
        if errors is not None and (not isinstance(errors, dict)
                or any(type(v) is not int or v < 0 for v in errors.values())):
            raise PipelineError("INPUT_INVALID", "Evaluation row errors must be nonnegative integers", "evaluation")


def load_evaluation(path: Path, manifest: JSON, prediction_sha256: str | None) -> JSON:
    payload = read_json(Path(path))
    validate_evaluation(payload, manifest, prediction_sha256)
    return payload


def _correctness(manifest: JSON, evaluation: JSON | None) -> JSON:
    selected = manifest["selected_ids"]
    if evaluation is None:
        return {"status": "not_evaluated", "selected": len(selected), "scored": 0,
                "full_coverage": False, "rows": {}}
    rows = {row["id"]: row for row in evaluation["rows"]}
    scores = [row["sample_score"] for row in rows.values()]
    return {
        "status": "evaluated", "selected": len(selected), "scored": len(rows),
        "full_coverage": set(rows) == set(selected),
        "missing_ids": sorted(set(selected) - set(rows)),
        # A development diagnostic only, never the official competition aggregate.
        "mean_sample_score_diagnostic": (sum(scores) / len(scores)) if scores else None,
        "state_hash_matches": sum(1 for row in rows.values() if row.get("state_hash_match") is True),
        "evaluator": evaluation.get("evaluator"),
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# Single-run report (T009 + T010)
# ---------------------------------------------------------------------------

def build_report(run_dir: Path, evaluation_file: Path | None = None) -> JSON:
    run_dir = Path(run_dir)
    manifest = load_manifest(run_dir)
    prediction_sha256 = _prediction_sha256(run_dir)
    evaluation = (load_evaluation(Path(evaluation_file), manifest, prediction_sha256)
                  if evaluation_file is not None else None)
    entries = _entries(manifest)
    resume = manifest.get("resume") or {}
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "run_id": manifest["run_id"],
        "run_status": manifest["status"],
        "prediction_sha256": prediction_sha256,
        "coverage": {
            "selected_ids": len(manifest["selected_ids"]),
            "transcript_mode": manifest["input_mode"] == "transcript",
            "mixed_resume": bool(resume.get("development_composite")),
        },
        "counts": _counts(manifest, entries),
        "timing": _timing(entries),
        "stages": _stage_durations(entries),
        "tokens": _token_rates(entries),
        "slowest": _slowest(entries),
        "correctness": _correctness(manifest, evaluation),
    }


def render_markdown(report: JSON) -> str:
    lines = ["# LifeMate run report", "", f"- run_id: `{report['run_id']}`",
              f"- status: {report['run_status']}",
              f"- transcript_mode: {report['coverage']['transcript_mode']}",
              f"- mixed_resume: {report['coverage']['mixed_resume']}", "", "## Counts", ""]
    for key, value in report["counts"].items():
        lines.append(f"- {key}: {value}")
    lines += ["", "## Timing (seconds)", ""]
    for key, dist in report["timing"].items():
        lines.append(f"- {key}: p50={dist['p50']} p95={dist['p95']} p99={dist['p99']} "
                     f"max={dist['max']} n={dist['count']}")
    lines += ["", "## Correctness", ""]
    correctness = report["correctness"]
    lines.append(f"- status: {correctness['status']}")
    if correctness["status"] == "evaluated":
        lines.append(f"- mean_sample_score_diagnostic: {correctness['mean_sample_score_diagnostic']}")
        lines.append(f"- full_coverage: {correctness['full_coverage']}")
        lines.append(f"- state_hash_matches: {correctness['state_hash_matches']}")
    lines += ["", "## Slowest attempts", ""]
    for row in report["slowest"]:
        lines.append(f"- {row['id']}: {row['full_attempt_seconds']:.3f}s ({row['outcome']})")
    return "\n".join(lines) + "\n"


def _atomic_text(path: Path, content: str) -> None:
    import os
    import uuid

    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            artifacts.sync_write(stream, content)
        os.replace(temporary, path)
    except (OSError, ValueError, TypeError) as exc:
        raise PipelineError("OUTPUT_IO", "Cannot persist report markdown", "report") from exc
    finally:
        temporary.unlink(missing_ok=True)


def write_report(run_dir: Path, report: JSON) -> None:
    run_dir = Path(run_dir)
    artifacts.atomic_json(run_dir / "report.json", report)
    _atomic_text(run_dir / "report.md", render_markdown(report))


# ---------------------------------------------------------------------------
# Controlled comparisons (T010)
# ---------------------------------------------------------------------------

FACTORS = ("harness", "instructions", "few-shot")
FIXED_IDENTITY_KEYS = ("device", "seed", "selection_filter", "model_offload")


def _model_identity(manifest: JSON) -> JSON:
    identity = manifest.get("execution_identity") or {}
    return {"planner": identity.get("planner"), "asr": identity.get("asr"), "packages": identity.get("packages")}


def _comparable_prompt(manifest: JSON) -> JSON:
    # `example_overhead_tokens` is only known after the planner loads a bundle; it is
    # informational, not an experiment-defining input, so it never gates identity.
    value = manifest.get("effective_prompt") or {}
    return {k: v for k, v in value.items() if k != "example_overhead_tokens"}


def validate_factor_identity(factor: str, baseline: JSON, candidate: JSON) -> None:
    if factor not in FACTORS:
        raise PipelineError("INPUT_INVALID", "Unsupported comparison factor", "compare")
    for key in ("split", "input_mode", "dataset_sha256", "catalog_sha256", "runtime"):
        if baseline.get(key) != candidate.get(key):
            raise PipelineError("INPUT_INVALID", f"Baseline/candidate {key} differ", "compare")
    if set(baseline["selected_ids"]) != set(candidate["selected_ids"]):
        raise PipelineError("INPUT_INVALID", "Baseline/candidate selected IDs differ", "compare")
    for manifest in (baseline, candidate):
        if bool((manifest.get("resume") or {}).get("development_composite")):
            raise PipelineError("INPUT_INVALID", "A mixed-resume run cannot support acceptance comparison", "compare")
    if _model_identity(baseline) != _model_identity(candidate):
        raise PipelineError("INPUT_INVALID", "Baseline/candidate model identity differs", "compare")
    for key in FIXED_IDENTITY_KEYS:
        if baseline.get(key) != candidate.get(key):
            raise PipelineError("INPUT_INVALID", f"Baseline/candidate {key} differ", "compare")
    if baseline["limits"] != candidate["limits"]:
        raise PipelineError("INPUT_INVALID", "Baseline/candidate limits differ", "compare")
    baseline_prompt, candidate_prompt = _comparable_prompt(baseline), _comparable_prompt(candidate)
    if factor == "harness":
        if (baseline["prompt_version"], baseline["prompt_sha256"]) != (candidate["prompt_version"], candidate["prompt_sha256"]):
            raise PipelineError("INPUT_INVALID", "A harness factor must not change the prompt", "compare")
        if baseline_prompt != candidate_prompt:
            raise PipelineError(
                "INPUT_INVALID", "A harness factor must not change the effective prompt configuration", "compare")
        return
    # Instructions/few-shot trials declare an unchanged harness: require identical code.
    if baseline["execution_identity"]["code"] != candidate["execution_identity"]["code"]:
        raise PipelineError("INPUT_INVALID", f"Factor {factor!r} requires identical execution code", "compare")
    # Each trial isolates exactly one prompt factor; the other must stay fixed.
    if factor == "instructions":
        other = lambda prompt: {k: v for k, v in prompt.items() if k != "profile"}
        if other(baseline_prompt) != other(candidate_prompt):
            raise PipelineError(
                "INPUT_INVALID", "An instructions factor must hold the few-shot configuration fixed", "compare")
    else:  # few-shot
        if baseline_prompt.get("profile") != candidate_prompt.get("profile"):
            raise PipelineError(
                "INPUT_INVALID", "A few-shot factor must hold the instruction profile fixed", "compare")


def _paired_rows(baseline_entries: list[JSON], candidate_entries: list[JSON]) -> list[JSON]:
    baseline_by_id = {e["id"]: e for e in baseline_entries}
    candidate_by_id = {e["id"]: e for e in candidate_entries}
    rows = []
    for sample_id in sorted(set(baseline_by_id) | set(candidate_by_id)):
        b, c = baseline_by_id.get(sample_id), candidate_by_id.get(sample_id)
        b_total = b["full_attempt_seconds"] if b else None
        c_total = c["full_attempt_seconds"] if c else None
        rows.append({
            "id": sample_id,
            "baseline_outcome": b["outcome"] if b else "missing",
            "candidate_outcome": c["outcome"] if c else "missing",
            "baseline_total_seconds": b_total, "candidate_total_seconds": c_total,
            "delta_total_seconds": (c_total - b_total) if (b_total is not None and c_total is not None) else None,
            # A missing, not-started or failed candidate is a regression/incomplete
            # comparison, never a dropped pair.
            "regression_or_incomplete": bool(b is None or c is None or c["outcome"] == "not_started"
                                             or (c["outcome"] == "failed" and b["outcome"] != "failed")),
        })
    return rows


def _paired_scores(baseline_correctness: JSON, candidate_correctness: JSON) -> list[JSON] | None:
    if baseline_correctness["status"] != "evaluated" or candidate_correctness["status"] != "evaluated":
        return None
    baseline_rows, candidate_rows = baseline_correctness["rows"], candidate_correctness["rows"]
    paired = []
    for sample_id in sorted(set(baseline_rows) | set(candidate_rows)):
        b, c = baseline_rows.get(sample_id), candidate_rows.get(sample_id)
        b_score, c_score = (b["sample_score"] if b else None), (c["sample_score"] if c else None)
        b_hash, c_hash = (b.get("state_hash_match") if b else None), (c.get("state_hash_match") if c else None)
        paired.append({
            "id": sample_id, "baseline_score": b_score, "candidate_score": c_score,
            "delta_score": (c_score - b_score) if (b_score is not None and c_score is not None) else None,
            "score_regression": (c_score < b_score) if (b_score is not None and c_score is not None) else None,
            "baseline_state_hash_match": b_hash, "candidate_state_hash_match": c_hash,
            "hash_match_regression": bool(b_hash is True and c_hash is not True),
        })
    return paired


def _classify_harness(baseline: JSON, candidate: JSON, paired_scores: list[JSON] | None) -> JSON:
    full_coverage = (baseline["correctness"]["full_coverage"] and candidate["correctness"]["full_coverage"]
                     if paired_scores is not None else None)
    failure_ok = candidate["counts"]["failed"] <= baseline["counts"]["failed"]
    deadline_ok = (candidate["counts"]["time_limit_failures"] <= baseline["counts"]["time_limit_failures"]
                   and candidate["counts"]["known_total_over_or_at_30s"] <= baseline["counts"]["known_total_over_or_at_30s"])
    b_p95, c_p95 = baseline["timing"]["sample_total_seconds"]["p95"], candidate["timing"]["sample_total_seconds"]["p95"]
    latency_improved = b_p95 is not None and c_p95 is not None and c_p95 < b_p95
    # Partial evaluator coverage must never read as preserved correctness; require
    # every selected ID scored on both sides before trusting the paired comparison.
    correctness_preserved = (None if paired_scores is None else
                              bool(full_coverage) and not any(
                                  row["score_regression"] or row["hash_match_regression"] for row in paired_scores))
    return {
        "no_failure_regression": failure_ok, "no_deadline_regression": deadline_ok,
        "p95_latency_improved": latency_improved, "full_evaluator_coverage": full_coverage,
        "correctness_preserved": correctness_preserved,
        "single_pair_eligible": bool(failure_ok and deadline_ok and latency_improved
                                     and correctness_preserved in (True, None)),
        "latency_direction_confirmed_on_three_replicates": False,
        "limitation": "Harness acceptance also requires confirming the latency direction on three fresh "
                      "paired runs; this command compares exactly one baseline/candidate pair.",
    }


def _classify_prompt(baseline: JSON, candidate: JSON, paired_scores: list[JSON] | None) -> JSON:
    if paired_scores is None:
        return {"status": "exploratory", "reason": "Missing evaluation evidence for baseline and/or candidate."}
    full_coverage = baseline["correctness"]["full_coverage"] and candidate["correctness"]["full_coverage"]
    b_mean, c_mean = baseline["correctness"]["mean_sample_score_diagnostic"], candidate["correctness"]["mean_sample_score_diagnostic"]
    score_improved = b_mean is not None and c_mean is not None and c_mean > b_mean
    hash_regression = any(row["hash_match_regression"] for row in paired_scores)
    failure_ok = candidate["counts"]["failed"] <= baseline["counts"]["failed"]
    deadline_ok = (candidate["counts"]["time_limit_failures"] <= baseline["counts"]["time_limit_failures"]
                   and candidate["counts"]["known_total_over_or_at_30s"] <= baseline["counts"]["known_total_over_or_at_30s"])
    b_p95, c_p95 = baseline["timing"]["sample_total_seconds"]["p95"], candidate["timing"]["sample_total_seconds"]["p95"]
    latency_known = b_p95 is not None and c_p95 is not None
    latency_not_worse = not latency_known or c_p95 <= b_p95
    return {
        "status": "evaluated",
        "full_fixed_selection_scored": full_coverage,
        "mean_score_improved_diagnostic": score_improved,
        "no_state_hash_regression": not hash_regression,
        "no_failure_or_deadline_regression": failure_ok and deadline_ok,
        "p95_latency_known": latency_known,
        "p95_latency_not_increased": latency_not_worse,
        # An unknown p95 is never comparative latency evidence; never auto-recommend on it.
        "default_automatic_recommendation": bool(full_coverage and score_improved and not hash_regression
                                                  and failure_ok and deadline_ok and latency_not_worse
                                                  and latency_known),
        "accuracy_latency_tradeoff": bool(score_improved and not latency_not_worse),
        "per_sample_regressions": [row["id"] for row in paired_scores if row["score_regression"]],
    }


def _classify_final_budget(baseline: JSON, candidate: JSON) -> JSON:
    def ready(report):
        counts = report["counts"]
        return (counts["failed"] == 0 and counts["unknown_total"] == 0 and counts["not_started"] == 0
                and counts["known_total_over_or_at_30s"] == 0 and counts["imported"] == 0)

    return {
        "baseline_ready": ready(baseline), "candidate_ready": ready(candidate),
        "hardware_confirmed_a30": None,
        "limitation": "A30 hardware identity is not recorded in the run manifest; non-A30 or "
                      "transcript-mode evidence is exploratory, not compliance evidence.",
    }


def build_comparison(baseline_dir: Path, candidate_dir: Path, factor: str,
                      baseline_evaluation: Path | None = None,
                      candidate_evaluation: Path | None = None) -> JSON:
    baseline_dir, candidate_dir = Path(baseline_dir), Path(candidate_dir)
    baseline_manifest, candidate_manifest = load_manifest(baseline_dir), load_manifest(candidate_dir)
    validate_factor_identity(factor, baseline_manifest, candidate_manifest)
    baseline_report = build_report(baseline_dir, baseline_evaluation)
    candidate_report = build_report(candidate_dir, candidate_evaluation)
    paired_rows = _paired_rows(_entries(baseline_manifest), _entries(candidate_manifest))
    paired_scores = _paired_scores(baseline_report["correctness"], candidate_report["correctness"])
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION, "factor": factor,
        "baseline_run_id": baseline_report["run_id"], "candidate_run_id": candidate_report["run_id"],
        "baseline": baseline_report, "candidate": candidate_report,
        "paired": {"rows": paired_rows,
                   "delta_total_seconds": distribution([row["delta_total_seconds"] for row in paired_rows]),
                   "scores": paired_scores},
        "acceptance": {
            "harness": _classify_harness(baseline_report, candidate_report, paired_scores),
            "prompt": _classify_prompt(baseline_report, candidate_report, paired_scores),
            "final_budget": _classify_final_budget(baseline_report, candidate_report),
        },
    }


def render_comparison_markdown(comparison: JSON) -> str:
    lines = [f"# LifeMate run comparison ({comparison['factor']})", "",
              f"- baseline_run_id: `{comparison['baseline_run_id']}`",
              f"- candidate_run_id: `{comparison['candidate_run_id']}`", "",
              "## Paired total-time delta (seconds, candidate - baseline)", ""]
    dist = comparison["paired"]["delta_total_seconds"]
    lines.append(f"- p50={dist['p50']} p95={dist['p95']} p99={dist['p99']} max={dist['max']} n={dist['count']}")
    lines += ["", "## Acceptance", ""]
    for name, verdict in comparison["acceptance"].items():
        lines.append(f"### {name}")
        for key, value in verdict.items():
            lines.append(f"- {key}: {value}")
        lines.append("")
    return "\n".join(lines) + "\n"


def write_comparison(output_dir: Path, comparison: JSON) -> None:
    output_dir = Path(output_dir)
    artifacts.atomic_json(output_dir / "comparison.json", comparison)
    _atomic_text(output_dir / "comparison.md", render_comparison_markdown(comparison))


def _nested(a: Path, b: Path) -> bool:
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def validate_comparison_output(output_dir: Path, baseline_manifest: JSON, candidate_manifest: JSON,
                                baseline_dir: Path, candidate_dir: Path) -> None:
    for manifest in (baseline_manifest, candidate_manifest):
        for key in ("data_root", "runtime_dir"):
            if output_dir.is_relative_to(Path(manifest[key])):
                raise PipelineError("INPUT_INVALID", "Comparison output must be outside organizer inputs", "compare")
    if _nested(output_dir, Path(baseline_dir)) or _nested(output_dir, Path(candidate_dir)):
        raise PipelineError("INPUT_INVALID", "Comparison output must not overlap a source run", "compare")


__all__ = [
    "EVALUATION_SCHEMA_VERSION", "REPORT_SCHEMA_VERSION",
    "build_comparison", "build_report", "distribution", "load_evaluation", "load_manifest",
    "nearest_rank", "render_comparison_markdown", "render_markdown", "validate_comparison_output",
    "validate_evaluation", "validate_factor_identity", "validate_manifest", "write_comparison", "write_report",
]
