"""Frozen checkpoint selection and group-paired uncertainty; no model imports."""
from __future__ import annotations

from collections import defaultdict
import random


def checkpoint_key(metrics: dict, step: int) -> tuple:
    if metrics["coverage"] != 1:
        return (2, float("inf"), float("inf"), float("inf"), float("inf"), step)
    csa = metrics.get("slots", {}).get("critical_slot_accuracy")
    return (0 if csa is not None else 1, -csa if csa is not None else 0,
            metrics["normalized_wer"], metrics["normalized_cer"],
            metrics["mean_latency_seconds"] if csa is not None else 0, step)


def promotion(baseline: dict, candidate: dict) -> dict:
    base_slots, slots = baseline.get("slots", {}), candidate.get("slots", {})
    if candidate["coverage"] != 1:
        return {"status": "rejected", "reason": "incomplete_coverage"}
    if base_slots.get("critical_slot_accuracy") is None or slots.get("critical_slot_accuracy") is None:
        return {"status": "provisional", "reason": "slot_metric_unavailable"}
    if any(candidate[k] > baseline[k] for k in ("normalized_wer", "normalized_cer")):
        return {"status": "rejected", "reason": "word_or_character_regression"}
    if slots["critical_slot_accuracy"] < base_slots["critical_slot_accuracy"]:
        return {"status": "rejected", "reason": "critical_slot_regression"}
    for kind, base in base_slots.get("per_type", {}).items():
        new = slots["per_type"][kind]
        if base["accuracy"] is not None and (new["accuracy"] is None or new["accuracy"] < base["accuracy"]):
            return {"status": "rejected", "reason": f"slot_regression:{kind}"}
    improved = (candidate["normalized_wer"] < baseline["normalized_wer"]
                or slots["critical_slot_accuracy"] > base_slots["critical_slot_accuracy"])
    return {"status": "candidate" if improved else "retain_E0", "reason": "paired_uncertainty_required" if improved else "no_strict_improvement"}


def bootstrap(baseline_rows: list[dict], candidate_rows: list[dict], slots, repetitions: int = 1000) -> dict:
    def fingerprint(row):
        return row["utterance_id"], row["reference"], row["wav_sha256"], row["group"]
    if [fingerprint(r) for r in baseline_rows] != [fingerprint(r) for r in candidate_rows]:
        raise ValueError("Cannot compare different evaluation selections/references/audio")
    groups = defaultdict(list)
    for i, row in enumerate(baseline_rows):
        groups[row["group"]].append(i)
    names, rng, wer, csa = sorted(groups), random.Random(42), [], []
    for _ in range(repetitions):
        indices = [i for key in rng.choices(names, k=len(names)) for i in groups[key]]
        pairs = [[rows[i] for i in indices] for rows in (baseline_rows, candidate_rows)]
        ratios = []
        for selected in pairs:
            counts = [r["scores"]["normalized"]["wer"] for r in selected]
            units = sum(r["reference_units"] for r in counts)
            ratios.append(sum(r["errors"] for r in counts)/units if units else None)
        if None not in ratios:
            wer.append(ratios[0] - ratios[1])
        if slots.status == "available":
            values = [slots.summarize(selected)["critical_slot_accuracy"] for selected in pairs]
            if None not in values:
                csa.append(values[1] - values[0])
    def interval(values):
        values.sort()
        return [values[int(.025*(len(values)-1))], values[int(.975*(len(values)-1))]] if values else None
    return {"seed": 42, "repetitions": repetitions, "unit": "source_group",
            "wer_improvement_95ci": interval(wer), "csa_improvement_95ci": interval(csa)}
