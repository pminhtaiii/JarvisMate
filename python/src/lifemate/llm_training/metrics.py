"""Pure native evaluation metrics (specs §10.3; LL020/LL023).

Native format/EOS validity is reported separately from semantic decisions. Semantic
scores parse to normalized decisions; wrapper bytes are never compared. Every value
carries numerator/denominator/support and a missing_reason when undefined: no NaN,
no fabricated zeros. The call matcher is local and unverified against the organizer.
"""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

from ..native_tools import SYSTEM_TOOL
from .config import FIXED_VALIDATION_CASES, TARGET_TYPES

MATCHER = {"id": "lifemate-local-call-matcher-v1", "status": "local_unverified",
           "fuzzy": "NFC+lowercase, regex \\w+ tokens, multiset token-F1 > 0.6",
           "assignment": "maximum bipartite matching (augmenting paths)"}
SUCCESS = frozenset({"completed", "needs_info"})


def metric(value, numerator=None, denominator=None, unit="ratio", missing_reason=None, **extra) -> dict:
    if value is not None and (isinstance(value, bool) or not math.isfinite(value)):
        raise ValueError("Metric values must be finite or null")
    return {"value": value, "numerator": numerator, "denominator": denominator, "unit": unit,
            "missing_reason": None if value is not None else (missing_reason or "undefined_denominator"), **extra}


def ratio(numerator, denominator, missing="undefined_denominator", **extra) -> dict:
    if not denominator:
        return metric(None, numerator, denominator, missing_reason=missing, **extra)
    return metric(numerator / denominator, numerator, denominator, **extra)


def json_equal(a: Any, b: Any) -> bool:
    """Structural JSON equality: key order ignored, types exact (1 != 1.0 != true)."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(json_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b))
    return a == b


def fuzzy_tokens(text: str) -> list[str]:
    return re.findall(r"\w+", unicodedata.normalize("NFC", text).lower())


def token_f1(a: str, b: str) -> float:
    x, y = fuzzy_tokens(a), fuzzy_tokens(b)
    if not x and not y:
        return 1.0
    remaining, common = list(y), 0
    for token in x:
        if token in remaining:
            remaining.remove(token)
            common += 1
    if not common:
        return 0.0
    precision, recall = common / len(x), common / len(y)
    return 2 * precision * recall / (precision + recall)


def fuzzy_keys(catalog_tools: dict[str, dict]) -> dict[str, frozenset[str]]:
    return {name: frozenset(k for k, p in tool["parameters"].get("properties", {}).items()
                            if isinstance(p, dict) and p.get("x-match") == "fuzzy")
            for name, tool in catalog_tools.items()}


def call_matches(predicted: dict, gold: dict, fuzzy: dict[str, frozenset[str]]) -> bool:
    if not isinstance(predicted, dict) or predicted.get("name") != gold["name"]:
        return False
    a, b = predicted.get("arguments"), gold["arguments"]
    if not isinstance(a, dict) or a.keys() != b.keys():
        return False
    soft = fuzzy.get(gold["name"], frozenset())
    for key in b:
        if key in soft:
            if not (isinstance(a[key], str) and isinstance(b[key], str) and token_f1(a[key], b[key]) > 0.6):
                return False
        elif not json_equal(a[key], b[key]):
            return False
    return True


def max_matching(predicted: list[dict], gold: list[dict], fuzzy) -> int:
    """Maximum one-to-one matching; greedy order cannot lose a valid maximum."""
    edges = [[g for g, call in enumerate(gold) if call_matches(p, call, fuzzy)] for p in predicted]
    owner: dict[int, int] = {}

    def augment(p: int, seen: set[int]) -> bool:
        for g in edges[p]:
            if g not in seen:
                seen.add(g)
                if g not in owner or augment(owner[g], seen):
                    owner[g] = p
                    return True
        return False

    return sum(augment(p, set()) for p in range(len(predicted)))


def source_score(status: str, predicted: list[dict], gold: list[dict], fuzzy) -> dict:
    """Ungated tool-call F1 for one source; failures score 0, never successful empty."""
    matched = max_matching(predicted, gold, fuzzy) if gold else 0
    if status not in SUCCESS:
        score = 0.0
    elif not gold:
        score = 1.0 if not predicted else 0.0
    elif not predicted or not matched:
        score = 0.0
    else:
        precision, recall = matched / len(predicted), matched / len(gold)
        score = 2 * precision * recall / (precision + recall)
    return {"score": score, "matched": matched, "predicted": len(predicted), "gold": len(gold)}


def coverage(outcomes: list[dict], expected_ids: list[str]) -> dict:
    """Normalized coverage invariants (tasks 'Evaluation coverage contract')."""
    by_id = {}
    for outcome in outcomes:
        if outcome["id"] in by_id:
            raise ValueError("Duplicate outcome record")
        by_id[outcome["id"]] = outcome
    if set(by_id) != set(expected_ids):
        raise ValueError("Outcome records must cover exactly the expected IDs")
    statuses = [by_id[i]["status"] for i in expected_ids]
    attempted = sum(s != "not_attempted" for s in statuses)
    completed = sum(s in SUCCESS for s in statuses)
    failed = sum(s == "failed" for s in statuses)
    timed_out = sum(by_id[i]["status"] == "failed" and by_id[i].get("error_code") == "TIME_LIMIT" for i in expected_ids)
    counts = {"expected": len(expected_ids), "attempted": attempted, "not_attempted": len(expected_ids) - attempted,
              "completed": completed, "failed": failed, "timed_out": timed_out, "needs_info": statuses.count("needs_info")}
    if completed + failed != attempted or timed_out > failed:
        raise ValueError("Coverage invariants violated")
    counts["full_coverage"] = counts["not_attempted"] == 0
    counts["status_mapping"] = {"completed": "completed", "needs_info": "completed",
                                "failed": "failed (timed_out is a subset)", "not_attempted": "not_attempted"}
    return counts


def nearest_rank_p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def _asks(calls: list[dict]) -> list[dict]:
    return [c for c in calls if isinstance(c, dict) and c.get("name") == SYSTEM_TOOL]


def ask_strict(predicted: list[dict], gold: list[dict]) -> int:
    """One-to-one exact tool_name/params (array order kept) between ask calls."""
    used, matched = set(), 0
    for call in _asks(predicted):
        for index, reference in enumerate(_asks(gold)):
            if index not in used and json_equal(call.get("arguments"), reference["arguments"]):
                used.add(index)
                matched += 1
                break
    return matched


def closed_loop_metrics(outcomes: list[dict], references: dict[str, list[dict]], expected_ids: list[str],
                        fuzzy, *, trusted_state: dict[str, str] | None = None,
                        latency_scope: str = "planner_tools_gold_transcripts") -> tuple[dict, list[dict]]:
    """All §10.3 closed-loop metrics plus per-source rows; references are evaluation-only."""
    counts = coverage(outcomes, expected_ids)
    by_id = {o["id"]: o for o in outcomes}
    rows, ask, no_action = [], {"tp": 0, "fp": 0, "fn": 0, "tn": 0}, {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    strict = {"matched": 0, "predicted": 0, "gold": 0}
    micro = {"matched": 0, "predicted": 0, "gold": 0}
    state = {"matched": 0, "available": 0}
    for sample_id in expected_ids:
        outcome, gold = by_id[sample_id], references[sample_id]
        predicted = outcome.get("attempted_calls") or []
        status = outcome["status"]
        score = source_score(status, predicted, gold, fuzzy) if status != "not_attempted" else None
        row = {"id": sample_id, "status": status, "tool_call_f1": None if score is None else score["score"],
               "matched": None if score is None else score["matched"],
               "predicted_calls": len(predicted), "gold_calls": len(gold)}
        if score is not None:
            for key in micro:
                micro[key] += score[key]
            asked, gold_asked = bool(_asks(predicted)), bool(_asks(gold))
            ask["tp" if asked and gold_asked else "fp" if asked else "fn" if gold_asked else "tn"] += 1
            strict["matched"] += ask_strict(predicted, gold)
            strict["predicted"] += len(_asks(predicted))
            strict["gold"] += len(_asks(gold))
            positive = status == "completed" and outcome.get("stop_reason") == "finish" and not predicted
            no_action["tp" if positive and not gold else "fp" if positive else "fn" if not gold else "tn"] += 1
            if trusted_state is not None and sample_id in trusted_state:
                state["available"] += 1
                hit = status in SUCCESS and outcome.get("state_hash") == trusted_state[sample_id]
                state["matched"] += hit
                row["final_state_match"] = hit
        rows.append(row)
    full = counts["full_coverage"]
    scores = [r["tool_call_f1"] for r in rows if r["tool_call_f1"] is not None]
    trusted = trusted_state is not None and state["available"] == len(expected_ids)
    durations = [by_id[i]["elapsed"] for i in expected_ids if by_id[i].get("elapsed") is not None]
    successes = [by_id[i]["elapsed"] for i in expected_ids if by_id[i]["status"] in SUCCESS]
    gated = None
    if trusted and full:
        gated = sum((r["tool_call_f1"] if r.get("final_state_match") or r["gold_calls"] == 0 else 0.0)
                    for r in rows) / len(rows)
    values = {
        "tool_call_f1": metric(sum(scores) / len(expected_ids) if full else None, sum(scores) if full else None,
                               len(expected_ids), missing_reason="partial_coverage", aggregation="macro_local",
                               matcher=MATCHER),
        "tool_call_f1_attempted_only": ratio(sum(scores), len(scores), diagnostic=True),
        "micro_call_counts": {**micro, "diagnostic": True},
        "state_gated_tool_call_f1": metric(gated, None, len(expected_ids),
                                           missing_reason="trusted_reference_unavailable" if not trusted else "partial_coverage"),
        "final_state_match": (ratio(state["matched"], state["available"]) if trusted and full
                              else metric(None, None, None, missing_reason="trusted_reference_unavailable")),
        "ask_presence_precision": ratio(ask["tp"], ask["tp"] + ask["fp"], confusion=ask),
        "ask_presence_recall": ratio(ask["tp"], ask["tp"] + ask["fn"], confusion=ask),
        "ask_strict_precision": ratio(strict["matched"], strict["predicted"], counts=strict),
        "ask_strict_recall": ratio(strict["matched"], strict["gold"], counts=strict),
        "no_action_precision": ratio(no_action["tp"], no_action["tp"] + no_action["fp"], confusion=no_action),
        "no_action_recall": ratio(no_action["tp"], no_action["tp"] + no_action["fn"], confusion=no_action),
        "closed_loop_premature_finish": metric(None, missing_reason="trusted_completion_reference_unavailable"),
        "latency_mean": metric(sum(durations) / len(durations) if durations else None, None, len(durations),
                               unit="seconds", scope=latency_scope, missing_reason="no_observations"),
        "latency_p95": metric(nearest_rank_p95(durations), None, len(durations), unit="seconds",
                              scope=latency_scope, missing_reason="no_observations"),
        "latency_p95_success_only": metric(nearest_rank_p95(successes), None, len(successes), unit="seconds",
                                           scope=latency_scope, missing_reason="no_observations"),
        "peak_vram": metric(None, unit="bytes", missing_reason="not_measured_by_evaluator"),
        "failures": {"failed": counts["failed"], "timed_out": counts["timed_out"]},
    }
    return {"counts": counts, "metrics": values}, rows


def action_class(decision: dict | None, decision_index: int) -> str | None:
    """Fixed four classes; finish type by current-prefix length, not history."""
    if decision is None:
        return None
    if decision.get("action") == "finish":
        return "initial_finish" if decision_index == 0 else "finish_after_calls"
    return "ask_missing_info" if decision.get("name") == SYSTEM_TOOL else "normal_call"


def teacher_forced_metrics(items: list[dict]) -> dict:
    """items: {row_id, target_type, decision_index, target, predicted|None, code, eos_valid, nll}."""
    usable = len(items)
    correct = sum(1 for i in items if i["predicted"] is not None and json_equal(i["predicted"], i["target"]))
    calls = [i for i in items if i["target"]["action"] == "call"]
    joint = sum(1 for i in calls if i["predicted"] is not None and json_equal(i["predicted"], i["target"]))
    named = [i for i in calls if i["predicted"] is not None and i["predicted"].get("name") == i["target"]["name"]]
    premature = sum(1 for i in calls if i["predicted"] is not None and i["predicted"]["action"] == "finish")
    per_class, f1s = {}, []
    for kind in TARGET_TYPES:
        tp = sum(1 for i in items if i["target_type"] == kind and action_class(i["predicted"], i["decision_index"]) == kind)
        fp = sum(1 for i in items if i["target_type"] != kind and action_class(i["predicted"], i["decision_index"]) == kind)
        fn = sum(1 for i in items if i["target_type"] == kind) - tp  # Invalid outputs are FN of their true class.
        support = tp + fn
        f1 = None if not support else (0.0 if not tp else 2 * tp / (2 * tp + fp + fn))
        per_class[kind] = {"tp": tp, "fp": fp, "fn": fn, "support": support, "f1": f1}
        f1s.append(f1)
    nll = [i["nll"] for i in items if i.get("nll") is not None]
    invalid = {}
    for item in items:
        if item["predicted"] is None:
            invalid[item.get("code") or "UNKNOWN"] = invalid.get(item.get("code") or "UNKNOWN", 0) + 1
    return {
        "next_action_accuracy": ratio(correct, usable),
        "argument_accuracy": ratio(joint, len(calls)),
        "argument_accuracy_given_name": ratio(sum(1 for i in named if json_equal(i["predicted"], i["target"])), len(named)),
        "action_type_macro_f1": metric(sum(f1s) / 4 if all(f is not None for f in f1s) else None,
                                       missing_reason="missing_class_support", per_class=per_class),
        "teacher_forced_premature_finish": ratio(premature, len(calls)),
        "completion_mean_nll": metric(sum(nll) / len(nll) if nll else None, None, len(nll), unit="nats",
                                      missing_reason="not_scored", weighting="unweighted_clean"),
        "native_format_validity": ratio(sum(1 for i in items if i["predicted"] is not None), usable),
        "native_eos_validity": ratio(sum(1 for i in items if i.get("eos_valid")), usable),
        "invalid_outputs": invalid,
    }


def fixed_cases(outcomes: list[dict]) -> list[dict]:
    """The ten fixed Validation-only diagnostic IDs (never training/few-shot input)."""
    by_id = {o["id"]: o for o in outcomes}
    return [{"id": i, **({k: by_id[i].get(k) for k in ("status", "stop_reason", "error_code", "elapsed",
                                                        "attempted_calls", "native")} if i in by_id
                         else {"status": "absent"})} for i in FIXED_VALIDATION_CASES]
