"""Validate saved primary evaluations without opening audio, weights, or a worker."""
from __future__ import annotations

import math
from pathlib import Path

from asr.pretrained.metrics import NORMALIZATION, score, summarize
from asr.pretrained.runner import TIMING
from .slots import SlotEvaluator
from .storage import digest, identity, read, rows, verify

METHODS = {"E0": "Pretrained", "E1": "Decoder LoRA", "E2": "Encoder + Decoder LoRA",
           "E3": "QLoRA", "E4": "LoRA + Augmentation"}
RATES = ("raw_wer", "raw_cer", "normalized_wer", "normalized_cer")


def suite_inputs(suite: Path):
    metadata = read(suite / "suite.json")
    if metadata.get("identity") != identity({k: v for k, v in metadata.items() if k != "identity"}):
        raise ValueError("Suite identity mismatch")
    verify(suite / "data")
    validation = rows(suite / "data/validation-current.jsonl")
    if (len(validation) != metadata["audit"]["validation_current"] or not validation
            or len({r["utterance_id"] for r in validation}) != len(validation)
            or any(r["turn_id"] != "current" or r["partition"] != "validation" for r in validation)
            or identity(validation) != metadata["validation_identity"]):
        raise ValueError("Prepared primary Validation identity/count/scope mismatch")
    selection = {"split": metadata["split_identity"], "scope": "current",
                 "utterance_ids": [r["utterance_id"] for r in validation]}
    if identity(selection) != metadata["selection_identity"]:
        raise ValueError("Prepared selection identity mismatch")
    annotations = rows(suite / "data/slots.jsonl") if (suite / "data/slots.jsonl").exists() else None
    rules = read(suite / "data/slot-rules.json") if (suite / "data/slot-rules.json").exists() else None
    if identity(annotations) != metadata["annotation_identity"] or identity(rules) != metadata["rules_identity"]:
        raise ValueError("Frozen slot annotations/rules identity mismatch")
    return metadata, validation, SlotEvaluator(validation, annotations, rules)


def owned_evaluation(suite: Path, run: Path, value: str) -> Path:
    path = Path(value)
    path = path.resolve() if path.is_absolute() else (run / path).resolve()
    if not path.is_relative_to(run.resolve()) or not path.is_relative_to(suite.resolve()):
        raise ValueError("Evaluation must belong to the selected run in this suite")
    return path


def fingerprint(record):
    return tuple(record.get(k) for k in (
        "utterance_id", "sample_id", "turn_id", "group", "reference", "audio",
        "wav_sha256", "pcm_sha256", "duration_seconds", "partition"))


def validate_evaluation(suite, run, evaluation, validation, representation, slots):
    evaluation = owned_evaluation(suite, run, str(evaluation))
    saved = rows(evaluation / "transcripts.jsonl")
    metrics = read(evaluation / "metrics.json")
    if [fingerprint(r) for r in saved] != [fingerprint(r) for r in validation]:
        raise ValueError("Evaluation IDs/reference/audio/order differ from frozen primary Validation")
    if metrics.get("representation") != representation or any(r.get("representation") != representation for r in saved):
        raise ValueError("Incompatible inference representation")
    if metrics.get("normalization") != NORMALIZATION or metrics.get("timing") != TIMING:
        raise ValueError("Incompatible normalization/timing protocol")
    if any(r.get("status") != "ok" or not isinstance(r.get("prediction"), str) for r in saved):
        raise ValueError("Completed comparison requires all primary predictions to succeed")
    # Recompute text edits only: no inference, audio reads, or dataset access.
    for record in saved:
        if record.get("scores") != score(record["reference"], record["prediction"]):
            raise ValueError("Saved prediction/edit counts disagree")
        latency = record.get("latency_seconds")
        if type(latency) not in (int, float) or not math.isfinite(latency) or latency < 0:
            raise ValueError("Invalid measured inference latency")
    calculated = summarize(saved)
    for key, value in calculated.items():
        stored = metrics.get(key)
        equal = (math.isclose(stored, value, rel_tol=1e-9, abs_tol=1e-9)
                 if type(value) is float and type(stored) in (int, float) else stored == value)
        if not equal:
            raise ValueError(f"Saved corpus metric disagrees with predictions: {key}")
    if metrics.get("coverage") != 1:
        raise ValueError("Primary Validation coverage is incomplete")
    if metrics.get("slots") != slots.summarize(saved):
        raise ValueError("Saved slot metrics differ from frozen annotations/extractor")
    return saved, metrics, {str(p): digest(p) for p in
                            (evaluation / "transcripts.jsonl", evaluation / "metrics.json")}


def validate_primary(suite, metadata, validation, slots, run, manifest):
    for key in ("split_identity", "selection_identity", "fit_identity"):
        if manifest.get(key) != metadata[key]:
            raise ValueError(f"Run {key} differs from suite")
    expected = {"suite_identity": metadata["identity"], "source": metadata["source"],
                "model_revision": metadata["model"]["provenance"]["revision"],
                "model_identity": identity(metadata["model"]), "evaluation_policy": metadata["policy"]}
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("Run suite/source/model/evaluation policy differs")
    config = read(run / "resolved-config.json")
    if (config.get("experiment") != manifest["experiment"] or config.get("seed") != 42
            or config.get("inference_dtype") != "float16"):
        raise ValueError("Incompatible primary inference config")
    if not manifest.get("hardware") or not manifest.get("environment") or not manifest.get("code", {}).get("hash"):
        raise ValueError("Missing hardware/environment/code provenance")
    representation = "base_fp16" if manifest["experiment"] == "E0" else "merged_fp16"
    evaluation = owned_evaluation(suite, run, manifest["best_evaluation"])
    saved, metrics, hashes = validate_evaluation(suite, run, evaluation, validation, representation, slots)
    if manifest.get("metrics") != metrics:
        raise ValueError("Selected manifest metrics differ from saved evaluation")
    signature = {key: manifest[key] for key in ("source", "hardware", "environment")}
    signature.update(code=manifest["code"]["hash"], inference_dtype=config["inference_dtype"],
                     seed=config["seed"], threads=config.get("threads"), timing=metrics["timing"])
    hashes.update({str(p): digest(p) for p in (run / "manifest.json", run / "resolved-config.json")})
    return saved, metrics, signature, hashes


def enrich(entry, manifest, metrics, slots):
    entry.update(metrics)
    entry.update(comparison_eligible=True, reason=None, checkpoint_id=manifest.get("best_checkpoint"),
                 best_step=manifest.get("best_step"), best_evaluation=manifest.get("best_evaluation"))
    entry["slot_status"] = metrics.get("slots", {}).get("status", "unavailable")
    entry["annotation_coverage"] = metrics.get("slots", {}).get("annotation_coverage", 0)
    total = metrics.get("slots", {}).get("total", {}) if slots.status == "available" else {}
    entry["critical_slot_accuracy"] = metrics.get("slots", {}).get("critical_slot_accuracy") if slots.status == "available" else None
    for key in ("precision", "f1", "support", "tp", "fp", "fn"):
        entry["slot_" + key] = total.get(key)
    entry["slot_recall"] = total.get("accuracy")
    entry["trainable_parameters"] = manifest.get("trainable_parameters")
    entry["logical_parameters"] = metrics.get("initialization", {}).get("logical_parameters")
    entry["load_seconds"] = metrics.get("initialization", {}).get("load_seconds")
    for source, destination in ((manifest.get("train_memory"), "train"), (metrics.get("memory"), "infer")):
        if source is not None and not isinstance(source, dict):
            raise ValueError("Invalid saved VRAM measurement")
        for key in ("peak_allocated_gib", "peak_reserved_gib"):
            value = source.get(key) if source else None
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise ValueError("Invalid saved VRAM value")
            entry[f"{destination}_{key}"] = value
    notes = {}
    if slots.status != "available":
        notes["slots"] = "N/A: no complete reviewed gold + validated frozen extractor; semantic promotion remains provisional"
    elif any(entry.get(key) is None for key in ("critical_slot_accuracy", "slot_precision", "slot_recall", "slot_f1")):
        notes["slots"] = "N/A slot values have an empty gold/prediction denominator; see support and TP/FP/FN"
    if manifest["experiment"] == "E0":
        notes["training_vram_checkpoint"] = "N/A: pretrained E0 has no optimizer or adapter checkpoint"
    for key in ("train_peak_allocated_gib", "train_peak_reserved_gib", "infer_peak_allocated_gib", "infer_peak_reserved_gib"):
        if entry[key] is None and not (manifest["experiment"] == "E0" and key.startswith("train_")):
            notes[key] = "N/A: measurement not saved"
    entry["unavailable_reasons"] = notes
    entry["metric_notes"] = "; ".join(notes.values())


def add_percentages(entries):
    base = next((r for r in entries if r["experiment"] == "E0" and r["comparison_eligible"]), None)
    for entry in entries:
        for key in RATES + ("critical_slot_accuracy", "slot_precision", "slot_recall", "slot_f1"):
            value = entry.get(key)
            entry[key + "_pct"] = value * 100 if value is not None else None
        for key in RATES:
            entry["delta_" + key + "_pp"] = ((entry[key] - base[key]) * 100
                if base and entry["comparison_eligible"] else None)
