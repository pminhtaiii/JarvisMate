"""Versioned Vietnamese text normalization and corpus edit-distance metrics."""
from __future__ import annotations

import math
import unicodedata

NORMALIZATION = "vi-nfc-lower-punctuation-space-v1"


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower()
    text = "".join(" " if unicodedata.category(c).startswith("P") else c for c in text)
    return " ".join(text.split())


def edits(reference, prediction) -> dict:
    """Levenshtein counts; ties prefer substitution, deletion, then insertion."""
    previous = [(i, 0, 0, i) for i in range(len(prediction) + 1)]
    for i, ref in enumerate(reference, 1):
        current = [(i, 0, i, 0)]
        for j, pred in enumerate(prediction, 1):
            if ref == pred:
                current.append(previous[j - 1])
                continue
            cost, sub, delete, insert = previous[j - 1]
            substitution = (cost + 1, sub + 1, delete, insert)
            cost, sub, delete, insert = previous[j]
            deletion = (cost + 1, sub, delete + 1, insert)
            cost, sub, delete, insert = current[j - 1]
            insertion = (cost + 1, sub, delete, insert + 1)
            current.append(min((substitution, deletion, insertion), key=lambda v: v[0]))
        previous = current
    total, sub, delete, insert = previous[-1]
    return {"errors": total, "substitutions": sub, "deletions": delete,
            "insertions": insert, "reference_units": len(reference)}


def score(reference: str, prediction: str) -> dict:
    result = {}
    for mode, ref, pred in (("raw", reference, prediction),
                            ("normalized", normalize(reference), normalize(prediction))):
        result[mode] = {"wer": edits(ref.split(), pred.split()),
                        "cer": edits(ref, pred)}
    return result


def percentile95(values: list[float]) -> float | None:
    return sorted(values)[math.ceil(.95 * len(values)) - 1] if values else None


def summarize(rows: list[dict]) -> dict:
    successful = [r for r in rows if r["status"] == "ok"]
    measured = [r for r in rows if r.get("latency_seconds") is not None]
    result = {"selected": len(rows), "succeeded": len(successful),
              "failed": sum(r["status"] == "error" for r in rows),
              "timeouts": sum(r["status"] == "timeout" for r in rows),
              "not_run": sum(r["status"] == "not_run" for r in rows),
              "coverage": len(successful) / len(rows) if rows else 0,
              "empty_references": sum(not r["reference"].split() for r in rows)}
    for mode in ("raw", "normalized"):
        for metric in ("wer", "cer"):
            counts = {key: sum(r["scores"][mode][metric][key] for r in rows)
                      for key in ("errors", "reference_units", "substitutions", "deletions", "insertions")}
            result[f"{mode}_{metric}"] = (counts["errors"] / counts["reference_units"]
                                           if counts["reference_units"] else None)
            result[f"{mode}_{metric}_counts"] = counts
    latencies = [r["latency_seconds"] for r in measured]
    audio_seconds = sum(r["duration_seconds"] for r in measured)
    result.update(mean_latency_seconds=sum(latencies) / len(latencies) if latencies else None,
                  p95_latency_seconds=percentile95(latencies),
                  rtf=sum(latencies) / audio_seconds if audio_seconds else None,
                  measured_utterances=len(measured), measured_audio_seconds=audio_seconds,
                  inference_seconds=sum(latencies))
    return result
