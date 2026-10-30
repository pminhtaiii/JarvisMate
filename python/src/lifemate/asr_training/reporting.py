"""Read-only model-free status/compare; keeps failed/skipped/unsupported outcomes."""
from __future__ import annotations

import csv
from pathlib import Path

from .storage import EXPERIMENTS, outcome, latest, read, rows, write
from .selection import promotion, bootstrap
from .evaluation import slot_evaluator


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
    return result


def compare(suite: Path) -> dict:
    from datetime import datetime, timezone
    from uuid import uuid4
    report = suite / "comparisons" / (datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f") + "-" + uuid4().hex[:6])
    report.mkdir(parents=True, exist_ok=False)
    suite_data = read(suite / "suite.json")
    primary, variants, selected = [], [], {}
    for experiment in EXPERIMENTS:
        last = outcome(suite, experiment)
        entry = {"experiment": experiment, "status": "not_run", "reason": None}
        if last:
            path, manifest = last
            selected[experiment] = last
            entry.update(status=manifest["status"], reason=manifest.get("error"), run_id=path.name,
                         checkpoint_id=manifest.get("best_checkpoint"), **manifest.get("metrics", {}))
            config_path = path / "resolved-config.json"
            if config_path.exists():
                config = read(config_path)
                entry.update(scope=config.get("scope"), training_precision=manifest.get("precision"),
                             inference_dtype=config["inference_dtype"], control_run=config.get("control_run"),
                             seed=config["seed"])
                if experiment == "E0":
                    entry["training_precision"] = None
            entry["critical_slot_accuracy"] = entry.get("slots", {}).get("critical_slot_accuracy")
            entry["slot_status"] = entry.get("slots", {}).get("status", "unavailable")
            entry["annotation_coverage"] = entry.get("slots", {}).get("annotation_coverage", 0)
            totals = entry.get("slots", {}).get("total", {})
            for key in ("precision", "f1", "support", "tp", "fp", "fn"):
                entry["slot_" + key] = totals.get(key)
            entry["load_seconds"] = entry.get("initialization", {}).get("load_seconds")
            entry["logical_parameters"] = entry.get("initialization", {}).get("logical_parameters")
            entry["trainable_parameters"] = manifest.get("trainable_parameters")
            for source, destination in (("train_memory", "train"), ("memory", "infer")):
                memory = manifest.get(source) if source == "train_memory" else entry.get("memory")
                for key in ("peak_allocated_gib", "peak_reserved_gib"):
                    entry[destination + "_" + key] = memory.get(key) if memory else None
            for variant in sorted(path.glob("native-4bit/*/metrics.json")):
                native = read(variant)
                native.update(experiment=experiment, run_id=path.name, checkpoint_id=variant.parent.name,
                              status="completed" if native["coverage"] == 1 else "incomplete",
                              representation="native_nf4", inference_dtype="NF4",
                              critical_slot_accuracy=native.get("slots", {}).get("critical_slot_accuracy"),
                              slot_status=native.get("slots", {}).get("status", "unavailable"))
                for key in ("peak_allocated_gib", "peak_reserved_gib"):
                    native["infer_"+key] = (native.get("memory") or {}).get(key)
                variants.append(native)
        entry.update(split_identity=suite_data["split_identity"], selection_identity=suite_data["selection_identity"])
        entry.update(fit_identity=suite_data["fit_identity"], model_revision=suite_data["model"]["provenance"]["revision"])
        primary.append(entry)
    # Matched-update E4/control comparison uses saved evaluations only.
    if "E4" in selected and selected["E4"][1]["status"] == "completed":
        path, manifest = selected["E4"]
        config = read(path / "resolved-config.json")
        control = suite / config["control_run"]
        for directory, role in ((control, "matched_budget_control"), (path, "matched_budget_augmented")):
            history = rows(directory / "evaluation-history.jsonl")
            match = next((r for r in history if r["step"] == config["update_budget"]), None)
            if match:
                variants.append({"experiment": read(directory/"manifest.json")["experiment"],
                    "run_id": directory.name, "status": "completed", "representation": role,
                    "checkpoint_id": match["checkpoint"], **match["metrics"],
                    "critical_slot_accuracy": match["metrics"].get("slots", {}).get("critical_slot_accuracy"),
                    "slot_status": match["metrics"].get("slots", {}).get("status", "unavailable")})
    fields = ["experiment", "status", "reason", "run_id", "checkpoint_id", "scope", "control_run",
              "seed", "training_precision", "inference_dtype", "representation", "split_identity", "selection_identity", "fit_identity", "model_revision",
              "selected", "succeeded", "failed", "timeouts", "not_run", "coverage",
              "raw_wer", "raw_cer", "normalized_wer", "normalized_cer", "critical_slot_accuracy", "slot_status", "annotation_coverage",
              "slot_precision", "slot_f1", "slot_support", "slot_tp", "slot_fp", "slot_fn", "tool_call_f1", "final_state_match",
              "mean_latency_seconds", "p95_latency_seconds", "rtf", "train_peak_allocated_gib",
              "train_peak_reserved_gib", "infer_peak_allocated_gib", "infer_peak_reserved_gib", "trainable_parameters", "logical_parameters", "load_seconds"]
    def save_csv(path, values):
        with path.open("x", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(values)
    save_csv(report / "comparison.csv", primary)
    save_csv(report / "comparison-variants.csv", variants)
    decisions = {}
    if "E0" in selected and selected["E0"][1]["status"] == "completed":
        base_path, base = selected["E0"]
        base_rows = rows(base_path / base["best_evaluation"] / "transcripts.jsonl")
        slots = slot_evaluator(suite, rows(suite / "data/validation-current.jsonl"))
        for experiment, (path, manifest) in selected.items():
            if experiment == "E0" or manifest["status"] != "completed":
                continue
            decision = promotion(base["metrics"], manifest["metrics"])
            candidate_rows = rows(path / manifest["best_evaluation"] / "transcripts.jsonl")
            decision["uncertainty"] = bootstrap(base_rows, candidate_rows, slots)
            if decision["status"] == "candidate":
                intervals = decision["uncertainty"]
                positive = any(intervals.get(key) and intervals[key][0] > 0 for key in
                               ("wer_improvement_95ci", "csa_improvement_95ci"))
                decision["status"] = "candidate_supported" if positive else "promising_unconfirmed"
            decisions[experiment] = decision
    write(report / "details.json", {"rows": primary, "variants": variants, "decisions": decisions})
    lines = ["# PhoWhisper-large E0–E4", "", "Nguồn: artifacts đã lưu; compare không train hoặc load model.", "",
             "| Experiment | Status | WER norm (%) | CER norm (%) | Mean (s) | CSA |", "|---|---|---:|---:|---:|---:|"]
    def number(value, scale=1):
        return f"{value*scale:.2f}" if isinstance(value, (float, int)) else "N/A"
    for item in primary:
        lines.append(f"| {item['experiment']} | {item['status']} | {number(item.get('normalized_wer'),100)} | "
                     f"{number(item.get('normalized_cer'),100)} | {number(item.get('mean_latency_seconds'))} | "
                     f"{number(item.get('critical_slot_accuracy'),100)} |")
    lines += ["", "CSA thiếu annotation/extractor đáng tin được ghi N/A. Xem details.json cho lỗi, slot breakdown và bootstrap.",
              "Chưa có bằng chứng GPU/A30 hoặc pipeline scoring thì không suy ra deployment đạt yêu cầu.", ""]
    (report / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return {"report_dir": str(report), "experiments": len(primary), "decisions": decisions}
