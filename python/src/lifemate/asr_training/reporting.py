"""Read-only model-free status/compare; keeps failed/skipped/unsupported outcomes."""
from __future__ import annotations

from pathlib import Path

from .storage import EXPERIMENTS, digest, outcome, latest, read, rows, write
from .selection import promotion, bootstrap, checkpoint_key
from .comparison_artifacts import (METHODS, RATES, suite_inputs, validate_primary, enrich,
                                   add_percentages, owned_evaluation)
from .comparison_examples import save_csv, write_examples
from .comparison_report import render, rankings
from .relocation import operational_view


def status(suite: Path) -> list[dict]:
    result = []
    for experiment in EXPERIMENTS:
        last = outcome(suite, experiment)
        probe = latest(suite, experiment, "probe")
        result.append({"experiment": experiment, "status": last[1]["status"] if last else "not_run",
                       "phase": last[1].get("phase") if last else None,
                       "preflight": probe[1]["status"] if probe else "not_run",
                       "run": str(last[0]) if last else None, "reason": last[1].get("error") if last else None,
                       "latest_checkpoint": read(last[0]/"latest-checkpoint.json") if last and (last[0]/"latest-checkpoint.json").exists() else None})
    return operational_view(result, suite)


def compare(suite: Path) -> dict:
    from datetime import datetime, timezone
    from uuid import uuid4
    suite_data, validation, slots = suite_inputs(suite)
    primary, selected, predictions, signatures = [], {}, {}, {}
    inputs = [suite / "suite.json", *(suite / "data").glob("*")]
    hashes = {str(path): digest(path) for path in inputs if path.is_file()}
    for experiment in EXPERIMENTS:
        last = outcome(suite, experiment)
        entry = {"experiment": experiment, "method": METHODS[experiment], "status": "not_run",
                 "reason": "No recorded outcome", "comparison_eligible": False, "comparison_role": "primary_best"}
        if last:
            path, manifest = last
            entry.update(status=manifest["status"], run_id=path.name,
                         reason=manifest.get("error") or f"Run status: {manifest['status']}")
            if manifest["status"] == "completed":
                try:
                    saved, metrics, signature, source_hashes = validate_primary(
                        suite, suite_data, validation, slots, path, manifest)
                    if experiment != "E0" and signature != signatures.get("E0"):
                        raise ValueError("Missing valid E0 or incompatible hardware/environment/code/inference protocol")
                    config = read(path / "resolved-config.json")
                    accepted = dict(entry)
                    enrich(accepted, operational_view(manifest, suite), metrics, slots)
                    accepted.update(scope=config.get("scope"), control_run=config.get("control_run"),
                        seed=config["seed"], inference_dtype=config["inference_dtype"],
                        training_precision=manifest.get("precision") if experiment != "E0" else None)
                    for key in ("split_identity", "selection_identity", "fit_identity", "model_revision", "evaluation_policy"):
                        accepted[key] = manifest[key]
                    entry = accepted
                    selected[experiment] = last
                    predictions[experiment] = {row["utterance_id"]: row for row in saved}
                    signatures[experiment] = signature
                    hashes.update(source_hashes)
                except (ValueError, OSError, KeyError, TypeError) as exc:
                    entry["reason"] = f"Excluded from comparison: {str(exc)[:1000]}"
        if not entry["comparison_eligible"]:
            entry["metric_notes"] = "N/A: " + entry["reason"]
            entry["unavailable_reasons"] = {"all_primary_metrics": entry["reason"]}
        primary.append(entry)
    add_percentages(primary)
    variants = operational_view(saved_variants(suite, selected, hashes), suite)
    decisions, control_comparison = {}, None
    if "E0" in selected:
        base_rows = list(predictions["E0"].values())
        for experiment, (_, manifest) in selected.items():
            if experiment == "E0":
                continue
            decision = promotion(selected["E0"][1]["metrics"], manifest["metrics"])
            decision["uncertainty"] = bootstrap(base_rows, list(predictions[experiment].values()), slots)
            if decision["status"] == "candidate":
                intervals = decision["uncertainty"]
                positive = any(intervals.get(key) and intervals[key][0] > 0 for key in
                               ("wer_improvement_95ci", "csa_improvement_95ci"))
                decision["status"] = "candidate_supported" if positive else "promising_unconfirmed"
            decisions[experiment] = decision
    if "E4" in selected:
        config = read(selected["E4"][0] / "resolved-config.json")
        control = next((e for e, (p, _) in selected.items() if p.resolve() == (suite / config["control_run"]).resolve()), None)
        if control:
            new, old = selected["E4"][1]["metrics"], selected[control][1]["metrics"]
            control_comparison = {"control": control, "delta_wer_pp": (new["normalized_wer"] - old["normalized_wer"]) * 100,
                "delta_cer_pp": (new["normalized_cer"] - old["normalized_cer"]) * 100,
                "uncertainty": bootstrap(list(predictions[control].values()), list(predictions["E4"].values()), slots)}
    # Refuse publishing from a snapshot that changed while it was being read.
    if any(digest(Path(path)) != sha for path, sha in hashes.items()):
        raise ValueError("Input artifacts changed during comparison; rerun after the writer finishes")
    summary = rankings(primary)
    recommendation = {"experiment": "E0", "status": "retain_E0", "reason": "No eligible improved candidate"}
    base_metrics = selected.get("E0", (None, {"metrics": {}}))[1]["metrics"]
    candidates = [(e, m) for e, (_, m) in selected.items() if e != "E0"
        and decisions[e]["status"] != "rejected"
        and all(m["metrics"][key] <= base_metrics[key] for key in ("normalized_wer", "normalized_cer"))
        and (m["metrics"]["normalized_wer"] < base_metrics["normalized_wer"]
             or (slots.status == "available" and m["metrics"]["slots"]["critical_slot_accuracy"] > base_metrics["slots"]["critical_slot_accuracy"]))]
    if candidates:
        name, _ = min(candidates, key=lambda pair: checkpoint_key(pair[1]["metrics"], pair[1]["best_step"]))
        recommendation = {"experiment": name, **decisions[name], "fallback": "E0"}
    report = suite / "comparisons" / (datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f") + "-" + uuid4().hex[:6])
    report.mkdir(parents=True, exist_ok=False)
    fields = comparison_fields()
    save_csv(report / "comparison.csv", fields, primary)
    save_csv(report / "comparison-variants.csv", fields, variants)
    examples = write_examples(report, validation, predictions, primary)
    text = render(primary, predictions, decisions, validation, summary, control_comparison, recommendation)
    (report / "comparison.md").write_text(text, encoding="utf-8")
    (report / "report.md").write_text(text, encoding="utf-8")  # Existing operator commands keep working.
    write(report / "details.json", {"rows": primary, "variants": variants, "decisions": decisions,
        "valid_runs": len(selected), "primary_utterances": len(validation), "rankings": summary,
        "recommendation": recommendation, "control_comparison": control_comparison,
        "examples": examples, "input_sha256": hashes,
        "generator_sha256": {p.name: digest(p) for p in (Path(__file__), *Path(__file__).parent.glob("comparison_*.py"))},
        "units": {"legacy_rate_columns": "ratio", "*_pct": "percent", "delta_*_pp": "candidate minus E0, percentage points"}})
    return {"report_dir": str(report), "experiments": len(primary), "valid_runs": len(selected), "decisions": decisions}


def saved_variants(suite, selected, hashes):
    variants = []
    for experiment, (path, _) in selected.items():
        for variant in sorted(path.glob("native-4bit/*/metrics.json")):
            native = read(variant)
            hashes[str(variant)] = digest(variant)
            native.update(experiment=experiment, method=METHODS[experiment], run_id=path.name,
                checkpoint_id=variant.parent.name, status="completed" if native["coverage"] == 1 else "incomplete",
                comparison_eligible=False, representation="native_nf4", inference_dtype="NF4",
                comparison_role="native_nf4_epoch",
                metric_notes="Diagnostic NF4 representation; excluded from primary FP16 ranking")
            for key in ("peak_allocated_gib", "peak_reserved_gib"):
                native["infer_" + key] = (native.get("memory") or {}).get(key)
            variants.append(native)
    if "E4" in selected and selected["E4"][1]["status"] == "completed":
        path, manifest = selected["E4"]
        config = read(path / "resolved-config.json")
        control = suite / config["control_run"]
        for directory, role in ((control, "matched_budget_control"), (path, "matched_budget_augmented")):
            if directory.resolve() not in {p.resolve() for p, _ in selected.values()}:
                continue
            history = rows(directory / "evaluation-history.jsonl")
            hashes[str(directory / "evaluation-history.jsonl")] = digest(directory / "evaluation-history.jsonl")
            match = next((r for r in history if r["step"] == config["update_budget"]), None)
            if match:
                owned_evaluation(suite, directory, match["evaluation"])
                experiment = read(directory/"manifest.json")["experiment"]
                variants.append({**match["metrics"], "experiment": experiment, "method": METHODS[experiment],
                    "run_id": directory.name, "status": "completed", "comparison_role": role,
                    "comparison_eligible": False,
                    "checkpoint_id": match["checkpoint"],
                    "critical_slot_accuracy": match["metrics"].get("slots", {}).get("critical_slot_accuracy"),
                    "slot_status": match["metrics"].get("slots", {}).get("status", "unavailable")})
    for variant in variants:
        for key in RATES:
            variant[key + "_pct"] = variant[key] * 100 if variant.get(key) is not None else None
    return variants


def comparison_fields():
    fields = ["experiment", "status", "reason", "run_id", "checkpoint_id", "scope", "control_run",
              "seed", "training_precision", "inference_dtype", "representation", "split_identity", "selection_identity", "fit_identity", "model_revision",
              "selected", "succeeded", "failed", "timeouts", "not_run", "coverage",
              "raw_wer", "raw_cer", "normalized_wer", "normalized_cer", "critical_slot_accuracy", "slot_status", "annotation_coverage",
              "slot_precision", "slot_f1", "slot_support", "slot_tp", "slot_fp", "slot_fn", "tool_call_f1", "final_state_match",
              "mean_latency_seconds", "p95_latency_seconds", "rtf", "train_peak_allocated_gib",
              "train_peak_reserved_gib", "infer_peak_allocated_gib", "infer_peak_reserved_gib", "trainable_parameters", "logical_parameters", "load_seconds"]
    fields += ["method", "comparison_eligible", "comparison_role", "best_step", "best_evaluation", "evaluation_policy", "metric_notes", "slot_recall"]
    fields += [key + "_pct" for key in RATES + ("critical_slot_accuracy", "slot_precision", "slot_recall", "slot_f1")]
    fields += ["delta_" + key + "_pp" for key in RATES]
    return fields
