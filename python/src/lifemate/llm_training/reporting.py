"""Read-only native L0/L1/L2 comparison and RV018 weighting selection (LL024).

Reads saved manifests/metrics/outcomes only: no Torch, CUDA, planner, ASR, ToolEnv or
replay. Hard validity (protocol/data/identity/export/evaluator/coverage) is checked
separately from the preregistered performance policy. A fully evaluated run with
scored failures/timeouts stays comparable; partial/leaked/incompatible runs do not.
"""
from __future__ import annotations

from pathlib import Path
import math

from .config import BASE_MODEL, EXPERIMENTS, content_hash, native_identities
from .corpus import load_suite, sealed_policy
from .storage import file_hash, new_directory, read_json, read_jsonl, write_json, write_jsonl, write_text
from .metrics import coverage, nearest_rank_p95
from ..artifacts import validate_prediction
from ..jsonio import contained

COMPARISON_SCHEMA = "lifemate-native-comparison-v1"
SHARED_MANIFEST_KEYS = ("identities", "limits", "seed", "decode", "runtime", "evaluator", "evaluator_code", "execution_profile")
ARTIFACTS = {"outcomes": "outcomes.jsonl", "per_sample_metrics": "per-sample-metrics.jsonl",
             "errors": "errors.jsonl", "fixed_cases": "fixed-10-cases.json", "metrics": "metrics.json"}


def load_run(suite_dir: Path, selection: dict) -> dict:
    """One explicitly named closed-loop evaluation, with integrity-checked artifacts."""
    if set(selection) != {"experiment", "mode", "evaluation"} or selection["experiment"] not in EXPERIMENTS \
            or selection["mode"] not in {"G", "A"}:
        raise ValueError("Run selection entries need experiment, mode and evaluation")
    directory = contained(suite_dir / "evaluations", selection["evaluation"], must_exist=False)
    issues, manifest, metrics, outcomes = [], {}, {}, []
    try:
        manifest = read_json(directory / "manifest.json")
        for key, name in ARTIFACTS.items() | {("predictions", manifest.get("predictions_file", ""))}:
            if not name or file_hash(directory / name) != manifest["artifact_hashes"].get(key):
                issues.append(f"artifact_hash:{key}")
        metrics = read_json(directory / "metrics.json")
        outcomes = read_jsonl(directory / "outcomes.jsonl")
        per_source = read_jsonl(directory / "per-sample-metrics.jsonl")
        predictions = read_jsonl(contained(directory, manifest["predictions_file"]))
    except (OSError, KeyError, TypeError, ValueError) as exc:
        issues.append(f"unreadable:{type(exc).__name__}")
    if manifest and (manifest.get("experiment"), manifest.get("mode"), manifest.get("protocol")) != (
            selection["experiment"], selection["mode"], "closed_loop"):
        issues.append("selection_mismatch")
    return {"selection": selection, "manifest": manifest, "metrics": metrics, "outcomes": outcomes,
            "issues": issues, "per_source": locals().get("per_source", []),
            "predictions": locals().get("predictions", [])}


def reconcile(run: dict, expected: list[str]) -> list[str]:
    issues = []
    try:
        manifest, report = run["manifest"], run["metrics"]
        from .evaluation import EVALUATION_SCHEMA
        if (manifest.get("schema") != EVALUATION_SCHEMA or report.get("schema") != EVALUATION_SCHEMA
                or any(report.get(k) != manifest.get(k) for k in ("experiment", "mode", "protocol", "status"))):
            issues.append("evaluation_schema")
        actual = coverage(run["outcomes"], expected)
        if not actual["full_coverage"]:
            issues.append("partial_coverage")
        if report.get("counts") != actual or manifest.get("counts") != actual:
            issues.append("coverage_counts_inconsistent")
        by_id = {r["id"]: r for r in run["outcomes"]}
        durations = []
        for o in run["outcomes"]:
            calls = o.get("attempted_calls")
            if not isinstance(calls, list) or any(not isinstance(c, dict) or set(c) != {"name", "arguments"}
                  or not isinstance(c["name"], str) or not isinstance(c["arguments"], dict) for c in calls):
                raise ValueError("invalid authoritative calls")
            elapsed = o.get("elapsed")
            if o["status"] == "not_attempted":
                if elapsed is not None or calls:
                    raise ValueError("invented unattempted support")
            elif type(elapsed) not in (float, int) or not math.isfinite(elapsed) or elapsed < 0:
                raise ValueError("attempted timing missing/invalid")
            else:
                durations.append(elapsed)
        per = run["per_source"]
        if sorted(r["id"] for r in per) != sorted(expected):
            raise ValueError("per-source coverage")
        for r in per:
            o = by_id[r["id"]]
            if r["status"] != o["status"] or r.get("predicted_calls") != len(o["attempted_calls"]):
                raise ValueError("per-source counts")
            score = r["tool_call_f1"]
            if o["status"] == "not_attempted":
                if score is not None:
                    raise ValueError("unattempted score")
            elif type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
                raise ValueError("invalid score")
            elif o["status"] == "failed" and score != 0:
                raise ValueError("failure scored nonzero")
        values = report["metrics"]
        score = values["tool_call_f1"]
        total = sum(r["tool_call_f1"] for r in per if r["tool_call_f1"] is not None)
        if (score.get("denominator") != len(expected) or (actual["full_coverage"] and (
                score.get("numerator") != total or score.get("value") != total / len(expected)))):
            raise ValueError("macro score/support")
        for name, value in (("latency_mean", sum(durations) / len(durations) if durations else None),
                            ("latency_p95", nearest_rank_p95(durations))):
            if values[name].get("denominator") != len(durations) or values[name].get("value") != value:
                raise ValueError("timing support mismatch")
        expected_predictions = {o["id"]: {"id": o["id"], "tool_calls": o["attempted_calls"], "state_hash": o["state_hash"]}
                                for o in run["outcomes"] if o["status"] in {"completed", "needs_info"}}
        predictions = run["predictions"]
        for row in predictions:
            validate_prediction(row)
        if len(predictions) != len(expected_predictions) or {p["id"]: p for p in predictions} != expected_predictions:
            raise ValueError("prediction/outcome mismatch")
    except (ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
        issues.append(f"outcome_inconsistent:{exc}")
    return issues


def hard_validity(run: dict, suite: dict, policy: dict, *, config=None) -> list[str]:
    """Protocol/data/identity/export/evaluator/coverage gates; never per-source failures."""
    issues = list(run["issues"])
    manifest, metrics = run["manifest"], run["metrics"]
    if not manifest:
        return issues or ["missing_manifest"]
    if manifest.get("identities") != native_identities():
        issues.append("native_identity_mismatch")
    from .evaluation import EVALUATOR_VERSION, evaluator_binding
    if manifest.get("evaluator") != EVALUATOR_VERSION or manifest.get("evaluator_code") != evaluator_binding():
        issues.append("evaluator_binding_mismatch")
    from .evaluation import limits
    from .config import SEEDS
    if (manifest.get("limits") != vars(limits()) or manifest.get("seed") != SEEDS["inference"]
            or manifest.get("decode") != {"do_sample": False, "num_beams": 1, "selection_filter": False}
            or not manifest.get("execution_profile")):
        issues.append("decode_or_profile_contract")
    if manifest.get("suite_seal") != suite["seal"]["identity"]:
        issues.append("suite_mismatch")
    if manifest.get("selection_policy_sha256") != policy["policy_sha256"] or \
            not manifest.get("started_at", "") > policy["sealed_at"]:
        issues.append("selection_policy_not_preregistered")
    counts = metrics.get("counts", {})
    expected = suite["partition"]["validation_ids"]
    issues += reconcile(run, expected)
    if counts.get("expected") != len(expected) or not counts.get("full_coverage"):
        issues.append("partial_coverage")
    if sorted(o["id"] for o in run["outcomes"]) != sorted(expected):
        issues.append("outcome_membership")
    if set(expected) & set(suite["partition"]["fit_ids"]):
        issues.append("validation_leakage")
    from .config import config_from_suite
    from .acceptance import evaluation_readiness, input_identity
    try:
        config = config or config_from_suite(suite["suite"])
        actual_inputs = input_identity(config, suite, mode=run["selection"]["mode"])
        if manifest.get("input_identity") != actual_inputs:
            issues.append("input_identity_mismatch")
        readiness = evaluation_readiness(config, suite["directory"], mode=run["selection"]["mode"])
        if manifest.get("readiness") != readiness:
            issues.append("native_readiness_mismatch")
    except (ValueError, OSError):
        issues.append("input_identity_unverified")
    experiment = run["selection"]["experiment"]
    model = manifest.get("model", {})
    if EXPERIMENTS[experiment]["trainable"] and model.get("training_status") != "completed_full_budget":
        issues.append("incomplete_training_budget")
    if EXPERIMENTS[experiment]["trainable"] and model.get("export_status") != "verified":
        issues.append("unverified_export")
    if EXPERIMENTS[experiment]["trainable"]:
        binding = model.get("training_binding", {})
        if (not model.get("checkpoint_identity") or not model.get("identity")
                or model.get("logical_parameters") != 4_022_468_096
                or binding.get("settings", {}).get("max_updates") != 500
                or not binding.get("corpus") or binding.get("corpus") != binding.get("readiness", {}).get("token_corpus")
                or not binding.get("code") or model.get("base", {}).get("base_model") != BASE_MODEL):
            issues.append("trained_export_binding_incomplete")
    if not EXPERIMENTS[experiment]["trainable"] and model.get("training_status") != "pretrained":
        issues.append("l0_not_pretrained")
    if not EXPERIMENTS[experiment]["trainable"] and (model.get("base_model") != BASE_MODEL or
            model.get("verified_weights") is not True or not model.get("identity") or
            not any(n.endswith(".safetensors") and isinstance(h, str) and len(h) == 64 for n, h in model.get("files", {}).items())):
        issues.append("l0_snapshot_unverified")
    if metrics.get("metrics", {}).get("state_gated_tool_call_f1", {}).get("value") is not None:
        reference = manifest.get("state_reference", {})
        if reference.get("trusted") is not True or not reference.get("identity") or not reference.get("evaluator_identity"):
            issues.append("state_reference_unverified")
    return issues


def shared_controls(run):
    controls = {k: run["manifest"].get(k) for k in SHARED_MANIFEST_KEYS}
    controls["runtime"] = {k: v for k, v in (controls.get("runtime") or {}).items() if k != "directory"}
    model = run["manifest"].get("model", {})
    base = model if run["selection"]["experiment"] == "L0" else model.get("base", {})
    controls["base_files"] = base.get("files")
    return controls


def training_controls(run):
    binding = run["manifest"].get("model", {}).get("training_binding", {})
    return {k: binding.get(k) for k in ("settings", "corpus", "code")}


def verify_weighting_report(suite_dir: Path, report: dict, *, config=None):
    """Reconcile the explicitly selected saved RV018 decision, without writing/selecting runs."""
    loaded, policy = load_suite(suite_dir), sealed_policy(suite_dir)
    if (report.get("schema") != COMPARISON_SCHEMA or report.get("suite_id") != loaded["suite"]["suite_id"]
            or report.get("selection_policy_sha256") != policy["policy_sha256"]
            or report.get("selection_sha256") != content_hash(report.get("selection"))):
        raise ValueError("RV018 report/suite/selection/policy identity mismatch")
    valid, controls, trained = {}, None, None
    for entry in report["selection"]["runs"]:
        if entry["experiment"] not in {"L1", "L2"}:
            continue
        run = load_run(suite_dir, entry)
        if hard_validity(run, loaded, policy, config=config):
            raise ValueError("RV018 run artifacts are no longer valid")
        shared = shared_controls(run)
        if controls is not None and controls != shared:
            raise ValueError("RV018 shared controls differ")
        controls = shared
        current_training = training_controls(run)
        if trained is not None and trained != current_training:
            raise ValueError("RV018 common corpus/method/budget/trainer controls differ")
        trained = current_training
        key = (entry["experiment"], entry["mode"])
        if key in valid:
            raise ValueError("Duplicate RV018 experiment/mode")
        valid[key] = run
    decision = performance_decision(valid.get(("L1", "A")), valid.get(("L2", "A")),
        valid.get(("L1", "G")), valid.get(("L2", "G")), policy["policy"])
    if decision["status"] != "decided":
        raise ValueError("Comparable L1/L2 G/A supports are missing")
    decision["selected_policy"] = "L2" if decision["candidate_qualifies"] and not decision["tie"] else "L1"
    if report.get("weighting_selection") != decision:
        raise ValueError("RV018 saved weighting decision does not match the sealed policy/artifacts")
    return decision["selected_policy"]


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
        gold_support = lambda x: x.get("gold", x.get("tp", 0) + x.get("fn", 0)) if x else None
        if not require(support, a is not None and b is not None and gold_support(a) == gold_support(b)):
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
    reviewed_a = control["metrics"].get("metrics", {}).get("critical_argument_errors", {})
    reviewed_b = candidate["metrics"].get("metrics", {}).get("critical_argument_errors", {})
    critical_available = (reviewed_a.get("value") is not None and reviewed_b.get("value") is not None
        and reviewed_a.get("reviewed_ids_sha256") is not None
        and reviewed_a.get("reviewed_ids_sha256") == reviewed_b.get("reviewed_ids_sha256")
        and reviewed_a.get("denominator") == reviewed_b.get("denominator") and reviewed_a.get("denominator", 0) > 0)
    if require("critical_argument_errors", critical_available):
        increase = reviewed_b["value"] - reviewed_a["value"]
        rules.append({"rule": "critical_argument_errors", "increase": increase,
                      "passed": increase <= tolerance["critical_argument_error_increase"]})
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


def compare(suite_dir: Path, selection: dict, *, config=None) -> dict:
    loaded = load_suite(suite_dir)
    policy = sealed_policy(suite_dir)
    if not isinstance(selection, dict) or not isinstance(selection.get("runs"), list) or not selection["runs"]:
        raise ValueError("RUN_SELECTION must explicitly name runs")
    runs = [load_run(suite_dir, entry) for entry in selection["runs"]]
    keys = [(r["selection"]["experiment"], r["selection"]["mode"]) for r in runs]
    if len(set(keys)) != len(keys):
        raise ValueError("Each experiment/mode may be selected once; no implicit latest/favorable runs")
    valid, rows = {}, []
    shared, trained_shared = None, None
    for run in runs:
        issues = hard_validity(run, loaded, policy, config=config)
        controls = shared_controls(run)
        if not issues:
            shared = shared or controls
            if controls != shared:
                issues.append("shared_controls_differ")
        if not issues and run["selection"]["experiment"] != "L0":
            training = training_controls(run)
            trained_shared = trained_shared or training
            if training != trained_shared:
                issues.append("shared_training_controls_differ")
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
    # Full final output always shows all eight cells, including unrun experiments.
    for experiment in EXPERIMENTS:
        for mode in ("G", "A"):
            if not any(r["experiment"] == experiment and r["mode"] == mode for r in rows):
                rows.append({"experiment": experiment, "mode": mode, "evaluation": None, "valid": False,
                    "issues": ["not_selected_or_not_run"], "counts": None, "tool_call_f1": None,
                    "state_gated_tool_call_f1": None, "ask_strict_recall": None, "no_action_recall": None,
                    "latency_p95": None, "delta_vs_L0": None, "delta_missing_reason": "not_run"})
    rows.sort(key=lambda r: (r["experiment"], r["mode"] != "G"))
    weighting = performance_decision(valid.get(("L1", "A")), valid.get(("L2", "A")), valid.get(("L1", "G")),
                                     valid.get(("L2", "G")), policy["policy"])
    if weighting["status"] == "decided":
        chosen = "L2" if weighting["candidate_qualifies"] and not weighting["tie"] else "L1"
        weighting["selected_policy"] = chosen  # Ties and non-qualifying L2 retain comparable valid L1.
    promotion = final_promotion(valid, policy["policy"])
    uncertainty, examples = {}, []
    for (experiment, mode), current in valid.items():
        baseline = valid.get(("L0", mode))
        if experiment != "L0" and baseline is not None:
            uncertainty[f"{experiment}-{mode}-vs-L0"] = paired_bootstrap(
                baseline["per_source"], current["per_source"], loaded["partition"])
    from .config import FIXED_VALIDATION_CASES
    for source_id in FIXED_VALIDATION_CASES:
        examples.append({"source_id": source_id, "runs": [
            {"experiment": e, "mode": m, "evaluation": r["selection"]["evaluation"],
             "outcome": next((o for o in r["outcomes"] if o["id"] == source_id), None)} for (e, m), r in valid.items()]})
    l2_minus_l1 = {mode: (None if _value(valid.get(("L2", mode)), "tool_call_f1") is None
                          or _value(valid.get(("L1", mode)), "tool_call_f1") is None
                          else _value(valid[("L2", mode)], "tool_call_f1") - _value(valid[("L1", mode)], "tool_call_f1"))
                   for mode in ("G", "A")}
    selected_policy = weighting.get("selected_policy")
    l3_minus_policy = {mode: (None if selected_policy is None or _value(valid.get(("L3", mode)), "tool_call_f1") is None
        or _value(valid.get((selected_policy, mode)), "tool_call_f1") is None else
        _value(valid[("L3", mode)], "tool_call_f1") - _value(valid[(selected_policy, mode)], "tool_call_f1")) for mode in ("G", "A")}
    for label, candidate, control in (("L2-minus-L1", "L2", "L1"), ("L3-minus-policy", "L3", selected_policy)):
        if control is not None:
            for mode in ("G", "A"):
                if (candidate, mode) in valid and (control, mode) in valid:
                    uncertainty[f"{label}-{mode}"] = paired_bootstrap(valid[(control, mode)]["per_source"],
                        valid[(candidate, mode)]["per_source"], loaded["partition"])
    report = {"schema": COMPARISON_SCHEMA, "suite_id": loaded["suite"]["suite_id"],
              "selection_policy_sha256": policy["policy_sha256"], "selection": selection,
              "selection_sha256": content_hash(selection), "rows": rows, "l2_minus_l1": l2_minus_l1,
              "l3_minus_selected_policy": l3_minus_policy,
              "weighting_selection": weighting, "promotion": promotion,
              "winner_status": promotion["winner_status"], "paired_uncertainty": uncertainty,
              "deployment_acceptance_status": "unverified",
              "notes": ["ungated F1 uses a local unverified matcher", "no model, ToolEnv or replay was used"]}
    directory = new_directory(loaded["directory"] / "comparisons", "comparison")
    write_json(directory / "comparison.json", report)
    write_json(directory / "fixed-10-cases.json", examples)
    write_text(directory / "fixed-10-cases.md", "# Fixed ten Validation cases\n\n" + "\n".join(
        f"- {x['source_id']}: {len(x['runs'])} selected comparable runs; see fixed-10-cases.json for actual attempts/status/timing."
        for x in examples) + "\n")
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


def paired_bootstrap(baseline, candidate, partition, repetitions=1000, seed=42):
    import random
    a, b = {r["id"]: r for r in baseline}, {r["id"]: r for r in candidate}
    if set(a) != set(b) or set(a) != set(partition["validation_ids"]):
        return {"interval_95": None, "missing_reason": "paired_membership_mismatch"}
    groups = {}
    for sid in partition["validation_ids"]:
        groups.setdefault(partition["sources"][sid]["group"], []).append(sid)
    names, rng, values = sorted(groups), random.Random(seed), []
    for _ in range(repetitions):
        selected = [sid for name in rng.choices(names, k=len(names)) for sid in groups[name]]
        deltas = [b[i]["tool_call_f1"] - a[i]["tool_call_f1"] for i in selected
                  if b[i]["tool_call_f1"] is not None and a[i]["tool_call_f1"] is not None]
        if len(deltas) == len(selected) and deltas:
            values.append(sum(deltas) / len(deltas))
    values.sort()
    return {"unit": "source_group", "seed": seed, "repetitions": repetitions, "available_resamples": len(values),
            "interval_95": [values[int(.025*(len(values)-1))], values[int(.975*(len(values)-1))]] if values else None,
            "missing_reason": None if values else "undefined_support", "training_seed_uncertainty": False}


def final_promotion(valid, policy):
    control, control_g = valid.get(("L0", "A")), valid.get(("L0", "G"))
    if control is None or control_g is None:
        return {"status": "blocked_dependency", "selected": None, "winner_status": "none", "reason": "native_L0_G_A_required"}
    decisions, passing = {}, []
    for experiment in policy["tie_order"]:
        decision = performance_decision(control, valid.get((experiment, "A")), control_g, valid.get((experiment, "G")), policy)
        decisions[experiment] = decision
        if decision.get("candidate_qualifies"):
            passing.append(experiment)
    if not passing:
        return {"status": "retain_control", "selected": "L0", "winner_status": "none", "decisions": decisions}
    winner = passing[0]
    metric = decisions[winner]["metric"]
    # All candidates must use the same primary/reference availability.
    if any(decisions[e]["metric"] != metric for e in passing):
        return {"status": "pending", "selected": None, "winner_status": "none", "reason": "mixed_reference_availability", "decisions": decisions}
    for experiment in passing[1:]:
        if _value(valid[(experiment, "A")], metric) - _value(valid[(winner, "A")], metric) > policy["tie_epsilon"]:
            winner = experiment
    return {"status": "decided", "selected": winner,
            "winner_status": "state_verified" if decisions[winner]["metric_status"] == "trusted_state" else "provisional",
            "decisions": decisions, "deployment_acceptance": "unverified"}

