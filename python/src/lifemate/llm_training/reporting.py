"""Read-only native L0/L1/L2 comparison and RV018 weighting selection (LL024).

Reads saved manifests/metrics/outcomes only: no Torch, CUDA, planner, ASR, ToolEnv or
replay. Hard validity (protocol/data/identity/export/evaluator/coverage) is checked
separately from the preregistered performance policy. A fully evaluated run with
scored failures/timeouts stays comparable; partial/leaked/incompatible runs do not.
"""
from __future__ import annotations

from pathlib import Path

from .config import EXPERIMENTS, content_hash, native_identities
from .corpus import load_suite, sealed_policy
from .storage import file_hash, new_directory, read_json, read_jsonl, write_json, write_jsonl, write_text

COMPARISON_SCHEMA = "lifemate-native-comparison-v1"
SHARED_MANIFEST_KEYS = ("identities", "limits", "seed", "decode", "runtime", "evaluator")
ARTIFACTS = {"outcomes": "outcomes.jsonl", "per_sample_metrics": "per-sample-metrics.jsonl",
             "errors": "errors.jsonl", "fixed_cases": "fixed-10-cases.json", "metrics": "metrics.json"}


def load_run(suite_dir: Path, selection: dict) -> dict:
    """One explicitly named closed-loop evaluation, with integrity-checked artifacts."""
    if set(selection) != {"experiment", "mode", "evaluation"} or selection["experiment"] not in EXPERIMENTS \
            or selection["mode"] not in {"G", "A"}:
        raise ValueError("Run selection entries need experiment, mode and evaluation")
    directory = suite_dir / "evaluations" / selection["evaluation"]
    issues, manifest, metrics, outcomes = [], {}, {}, []
    try:
        manifest = read_json(directory / "manifest.json")
        for key, name in ARTIFACTS.items() | {("predictions", manifest.get("predictions_file", ""))}:
            if not name or file_hash(directory / name) != manifest["artifact_hashes"].get(key):
                issues.append(f"artifact_hash:{key}")
        metrics = read_json(directory / "metrics.json")
        outcomes = read_jsonl(directory / "outcomes.jsonl")
    except (OSError, KeyError, TypeError) as exc:
        issues.append(f"unreadable:{type(exc).__name__}")
    if manifest and (manifest.get("experiment"), manifest.get("mode"), manifest.get("protocol")) != (
            selection["experiment"], selection["mode"], "closed_loop"):
        issues.append("selection_mismatch")
    return {"selection": selection, "manifest": manifest, "metrics": metrics, "outcomes": outcomes,
            "issues": issues}


def hard_validity(run: dict, suite: dict, policy: dict) -> list[str]:
    """Protocol/data/identity/export/evaluator/coverage gates; never per-source failures."""
    issues = list(run["issues"])
    manifest, metrics = run["manifest"], run["metrics"]
    if not manifest:
        return issues or ["missing_manifest"]
    if manifest.get("identities") != native_identities():
        issues.append("native_identity_mismatch")
    if manifest.get("suite_seal") != suite["seal"]["identity"]:
        issues.append("suite_mismatch")
    if manifest.get("selection_policy_sha256") != policy["policy_sha256"] or \
            not manifest.get("started_at", "") > policy["sealed_at"]:
        issues.append("selection_policy_not_preregistered")
    counts = metrics.get("counts", {})
    expected = suite["partition"]["validation_ids"]
    if counts.get("expected") != len(expected) or not counts.get("full_coverage"):
        issues.append("partial_coverage")
    if sorted(o["id"] for o in run["outcomes"]) != sorted(expected):
        issues.append("outcome_membership")
    if set(expected) & set(suite["partition"]["fit_ids"]):
        issues.append("validation_leakage")
    experiment = run["selection"]["experiment"]
    model = manifest.get("model", {})
    if EXPERIMENTS[experiment]["trainable"] and model.get("training_status") != "completed_full_budget":
        issues.append("incomplete_training_budget")
    if EXPERIMENTS[experiment]["trainable"] and model.get("export_status") != "verified":
        issues.append("unverified_export")
    if not EXPERIMENTS[experiment]["trainable"] and model.get("training_status") != "pretrained":
        issues.append("l0_not_pretrained")
    return issues


def _value(run: dict | None, name: str):
    return None if run is None else run["metrics"].get("metrics", {}).get(name, {}).get("value")


def _confusion(run: dict, name: str) -> dict | None:
    entry = run["metrics"].get("metrics", {}).get(name, {})
    return entry.get("confusion") or entry.get("counts")


def performance_decision(control: dict | None, candidate: dict | None, control_g: dict | None,
                         candidate_g: dict | None, policy: dict) -> dict:
    """Apply the sealed tolerances; mandatory missing evidence leaves selection pending."""
    rules, tolerance = [], policy["tolerances"]
    if control is None or candidate is None:
        return {"status": "blocked_dependency", "reason": "missing comparable A-mode runs", "rules": rules}
    trusted = all(_value(r, policy["primary"]["trusted_metric"]) is not None for r in (control, candidate))
    metric = policy["primary"]["trusted_metric"] if trusted else policy["primary"]["fallback_metric"]
    base, new = _value(control, metric), _value(candidate, metric)
    pending, unverified = [], []

    def require(support: str, available: bool):
        if not available:
            (pending if support in policy["mandatory_supports"] else unverified).append(support)
        return available

    if not require("primary_A", base is not None and new is not None):
        return {"status": "pending", "pending": pending, "metric": metric, "rules": rules}
    delta = new - base
    improved = delta > policy["improvement_epsilon"]
    rules.append({"rule": "primary_A", "control": base, "candidate": new, "delta": delta, "passed": improved})
    if require("g_tool_call_f1", _value(control_g, "tool_call_f1") is not None and _value(candidate_g, "tool_call_f1") is not None):
        drop = _value(control_g, "tool_call_f1") - _value(candidate_g, "tool_call_f1")
        rules.append({"rule": "g_tool_call_f1", "drop": drop, "passed": drop <= tolerance["g_macro_f1_drop"]})
    for support, recall, precision, tp_key in (("ask_confusion", "ask_strict_recall", "ask_strict_precision", "ask_strict_tp_drop"),
                                               ("no_action_confusion", "no_action_recall", "no_action_precision", "no_action_tp_drop")):
        a, b = _confusion(control, recall), _confusion(candidate, recall)
        if not require(support, a is not None and b is not None):
            continue
        tp_a, tp_b = a.get("tp", a.get("matched")), b.get("tp", b.get("matched"))
        rules.append({"rule": f"{support}_tp", "drop": tp_a - tp_b, "passed": tp_a - tp_b <= tolerance[tp_key]})
        pa, pb = _value(control, precision), _value(candidate, precision)
        if pa is not None and pb is not None:
            rules.append({"rule": f"{support}_precision", "drop": pa - pb,
                          "passed": pa - pb <= tolerance["minority_precision_drop"]})
        else:
            fp_a, fp_b = a.get("fp", a.get("predicted", 0) - tp_a), b.get("fp", b.get("predicted", 0) - tp_b)
            rules.append({"rule": f"{support}_fp_fallback", "increase": fp_b - fp_a,
                          "passed": fp_b - fp_a <= tolerance["minority_fp_increase_when_precision_undefined"]})
    for support, key, limit in (("failure_counts", "failed", "failed_sources_increase"),
                                ("timeout_counts", "timed_out", "timed_out_sources_increase")):
        a, b = control["metrics"].get("counts", {}).get(key), candidate["metrics"].get("counts", {}).get(key)
        if require(support, a is not None and b is not None):
            rules.append({"rule": support, "increase": b - a, "passed": b - a <= tolerance[limit]})
    require("critical_argument_errors", False)  # No trustworthy reviewed support is produced locally yet.
    pa, pb = _value(control, "latency_p95"), _value(candidate, "latency_p95")
    same_scope = (control["metrics"].get("metrics", {}).get("latency_p95", {}).get("scope")
                  == candidate["metrics"].get("metrics", {}).get("latency_p95", {}).get("scope"))
    if require("latency_p95", pa is not None and pb is not None and pa > 0 and same_scope):
        rules.append({"rule": "latency_p95", "relative_increase": (pb - pa) / pa,
                      "passed": (pb - pa) / pa <= tolerance["latency_p95_relative_increase"]})
    if pending:
        return {"status": "pending", "pending": pending, "unverified": unverified, "metric": metric, "rules": rules}
    guards = all(rule["passed"] for rule in rules if rule["rule"] != "primary_A")
    return {"status": "decided", "candidate_qualifies": improved and guards, "tie": abs(delta) <= policy["tie_epsilon"],
            "metric": metric, "metric_status": "trusted_state" if trusted else "provisional_ungated",
            "unverified": unverified, "rules": rules}


def compare(suite_dir: Path, selection: dict) -> dict:
    loaded = load_suite(suite_dir)
    policy = sealed_policy(suite_dir)
    if not isinstance(selection, dict) or not isinstance(selection.get("runs"), list) or not selection["runs"]:
        raise ValueError("RUN_SELECTION must explicitly name runs")
    runs = [load_run(suite_dir, entry) for entry in selection["runs"]]
    keys = [(r["selection"]["experiment"], r["selection"]["mode"]) for r in runs]
    if len(set(keys)) != len(keys):
        raise ValueError("Each experiment/mode may be selected once; no implicit latest/favorable runs")
    valid, rows = {}, []
    shared = None
    for run in runs:
        issues = hard_validity(run, loaded, policy)
        controls = {k: run["manifest"].get(k) for k in SHARED_MANIFEST_KEYS}
        if not issues:
            shared = shared or controls
            if controls != shared:
                issues.append("shared_controls_differ")
        key = (run["selection"]["experiment"], run["selection"]["mode"])
        if not issues:
            valid[key] = run
        metrics = run["metrics"].get("metrics", {})
        rows.append({"experiment": key[0], "mode": key[1], "evaluation": run["selection"]["evaluation"],
                     "valid": not issues, "issues": issues, "counts": run["metrics"].get("counts"),
                     "tool_call_f1": metrics.get("tool_call_f1"), "state_gated_tool_call_f1": metrics.get("state_gated_tool_call_f1"),
                     "ask_strict_recall": metrics.get("ask_strict_recall"), "no_action_recall": metrics.get("no_action_recall"),
                     "latency_p95": metrics.get("latency_p95")})
    for row in rows:
        control = valid.get(("L0", row["mode"]))
        current = valid.get((row["experiment"], row["mode"]))
        value, base = _value(current, "tool_call_f1"), _value(control, "tool_call_f1")
        row["delta_vs_L0"] = (None if value is None or base is None else value - base)
        row["delta_missing_reason"] = None if row["delta_vs_L0"] is not None else "missing_or_invalid_comparable_run"
    weighting = performance_decision(valid.get(("L1", "A")), valid.get(("L2", "A")), valid.get(("L1", "G")),
                                     valid.get(("L2", "G")), policy["policy"])
    if weighting["status"] == "decided":
        chosen = "L2" if weighting["candidate_qualifies"] and not weighting["tie"] else "L1"
        weighting["selected_policy"] = chosen  # Ties and non-qualifying L2 retain comparable valid L1.
    l2_minus_l1 = {mode: (None if _value(valid.get(("L2", mode)), "tool_call_f1") is None
                          or _value(valid.get(("L1", mode)), "tool_call_f1") is None
                          else _value(valid[("L2", mode)], "tool_call_f1") - _value(valid[("L1", mode)], "tool_call_f1"))
                   for mode in ("G", "A")}
    report = {"schema": COMPARISON_SCHEMA, "suite_id": loaded["suite"]["suite_id"],
              "selection_policy_sha256": policy["policy_sha256"], "selection": selection,
              "selection_sha256": content_hash(selection), "rows": rows, "l2_minus_l1": l2_minus_l1,
              "weighting_selection": weighting, "winner_status": "none",
              "deployment_acceptance_status": "unverified",
              "notes": ["ungated F1 uses a local unverified matcher", "no model, ToolEnv or replay was used"]}
    directory = new_directory(loaded["directory"] / "comparisons", "comparison")
    write_json(directory / "comparison.json", report)
    header = "experiment,mode,evaluation,valid,tool_call_f1,delta_vs_L0,issues"
    lines = [header] + [",".join(str(x) for x in (r["experiment"], r["mode"], r["evaluation"], r["valid"],
                                                  (r["tool_call_f1"] or {}).get("value"), r["delta_vs_L0"],
                                                  "|".join(r["issues"]))) for r in rows]
    write_text(directory / "comparison.csv", "\n".join(lines) + "\n")
    write_text(directory / "comparison.md", "\n".join(
        ["# Native comparison", "", f"Policy `{policy['policy_sha256']}`; winner status: none.", "",
         "| Experiment | Mode | Valid | Tool-call F1 | Δ vs L0 | Issues |", "|---|---|---|---|---|---|"]
        + [f"| {r['experiment']} | {r['mode']} | {r['valid']} | {(r['tool_call_f1'] or {}).get('value')} | "
           f"{r['delta_vs_L0']} | {', '.join(r['issues']) or '-'} |" for r in rows]
        + ["", f"RV018 weighting selection: `{weighting['status']}` {weighting.get('selected_policy', '')}"]) + "\n")
    write_jsonl(directory / "regressions.jsonl", [rule for rule in weighting.get("rules", []) if not rule["passed"]])
    return report | {"comparison_dir": str(directory)}

