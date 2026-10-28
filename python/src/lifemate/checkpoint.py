"""Read a stopped run's durable rows without modifying its evidence or simulator state."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .contracts import JSON, PipelineError
from .jsonio import loads, visible_path


def read_checkpoint(source: Path, current: JSON, *, allow_mixed: bool = False) -> tuple[list[JSON], JSON, JSON]:
    """Validate dataset/runtime compatibility; return rows, source manifest and provenance.

    A newline-terminated prediction is the commit record, even if the manifest update
    was interrupted. Only an unterminated final partial row may be discarded. Source
    files remain untouched; callers must write into a new run. Stop the source process
    first (a hard-killed run can still have status=running).
    """
    from .artifacts import SCHEMA_VERSION, validate_prediction

    def reject(message):
        raise PipelineError("INPUT_INVALID", message, "resume")

    def read(path, limit):
        visible_path(path)
        before = path.stat()
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            reject("Resume artifact exceeds supported size")
        return raw, before

    source = source.resolve()
    manifest_path = source / "manifest.json"
    partial, final = source / "predictions.partial.jsonl", source / "predictions.jsonl"
    try:
        manifest_raw, manifest_stat = read(manifest_path, 64 * 1024 * 1024)
        previous = loads(manifest_raw.decode("utf-8"))
        if (not isinstance(previous, dict) or previous.get("schema_version") != SCHEMA_VERSION
                or previous.get("status") not in {"running", "failed", "completed"}
                or not isinstance(previous.get("run_id"), str) or not previous["run_id"]):
            reject("Unsupported resume manifest")
        for key in ("split", "input_mode", "data_root", "runtime_dir", "selected_ids",
                    "dataset_sha256", "catalog_sha256", "runtime"):
            if key not in previous or previous[key] != current[key]:
                reject(f"Resume source differs from current {key}")
        differences = [key for key in ("execution_identity", "prompt_sha256", "prompt_version", "limits", "seed", "device", "selection_filter", "model_offload")
                       if key not in previous or previous[key] != current.get(key)]
        if previous.get("resume", {}).get("development_composite"):
            differences.append("source_is_development_composite")
        if differences and not allow_mixed:
            reject("Resume version/configuration differs or is unknown; use a matching run or explicit --allow-mixed-resume")
        if partial.exists() == final.exists():
            reject("Resume source must have exactly one prediction journal")
        prediction_path = final if final.exists() else partial
        raw, prediction_stat = read(prediction_path, 256 * 1024 * 1024)
        # Do not combine artifacts observed at different points of a live write.
        for path, before in ((manifest_path, manifest_stat), (prediction_path, prediction_stat)):
            after = path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (
                    after.st_size, after.st_mtime_ns, after.st_ino):
                reject("Resume source changed while reading; stop its process first")
        end = raw.rfind(b"\n") + 1
        discarded = len(raw) - end
        if prediction_path == final and discarded:
            reject("Published predictions have an incomplete final row")
        rows, seen = [], set()
        selected = set(current["selected_ids"])
        for line in raw[:end].splitlines():
            row = loads(line.decode("utf-8"))
            validate_prediction(row)
            if row["id"] not in selected or row["id"] in seen:
                reject("Resume predictions contain duplicate or unselected IDs")
            rows.append(row)
            seen.add(row["id"])
        completed = previous.get("completed_ids")
        if (not isinstance(completed, list) or any(not isinstance(i, str) for i in completed)
                or len(set(completed)) != len(completed) or not set(completed) <= seen):
            reject("Resume manifest claims completed rows missing from its predictions")
        if previous["status"] == "completed" and seen != selected:
            reject("Completed resume manifest has incomplete coverage")
        if prediction_path == final and [row["id"] for row in rows] != current["selected_ids"]:
            reject("Published resume predictions do not match selected order/coverage")
        samples = previous.get("samples")
        if (not isinstance(samples, list) or any(not isinstance(s, dict)
                or not isinstance(s.get("id"), str) for s in samples)
                or len({s["id"] for s in samples}) != len(samples)):
            reject("Invalid sample metadata in resume manifest")
        provenance = {
            "source_directory": str(source), "source_run_id": previous["run_id"],
            "source_manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
            "source_predictions_sha256": hashlib.sha256(raw).hexdigest(),
            "source_prediction_file": prediction_path.name,
            "reused_ids": [r["id"] for r in rows],
            "recovered_unmanifested_ids": [r["id"] for r in rows if r["id"] not in completed],
            "discarded_unterminated_bytes": discarded,
            "development_composite": bool(differences),
            "configuration_differences": differences,
            "mixed_resume_authorized": allow_mixed,
        }
        return rows, previous, provenance
    except PipelineError:
        raise
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise PipelineError("INPUT_INVALID", "Cannot read a valid resume checkpoint", "resume") from exc
