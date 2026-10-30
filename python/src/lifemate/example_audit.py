"""Offline audit of a proposed few-shot bundle against supplied Train labels.

Verifies each example's prefix/target against the stepwise conversion rules in
`docs/design/train-to-sft.md`, reusing the same `normalize_record`/`prepare_request`
helpers inference uses so an audited input is provably reproducible. Never creates
a `ToolEnv`, never reads an environment file's content, and never feeds this raw
labeled row to inference; only this separate command parses Train labels.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .artifacts import sync_write
from .contracts import Deadline, JSON, PipelineError, RunConfig
from .dataset import normalize_record, prepare_request, validate_catalog
from .jsonio import digest, dumps, loads, read_json, safe_id
from .prompt_profiles import load_partition_manifest, validate_bundle

AUDIT_SCHEMA_VERSION = 2
CONVERSION_VERSION = "lifemate-sft-conversion-v1"


def verified_content_sha256(examples: list[JSON]) -> str:
    """Bind an audit to the exact input/target content it checked against Train
    gold. Editing an example's content after auditing changes this digest, so a
    run comparing it against the bundle's current content catches the edit —
    a copied/forged marker on hand-written content will not reproduce it."""
    content = dumps([{"id": e["id"], "input": e["input"], "target": e["target"]} for e in examples])
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _load_train_rows(path: Path) -> dict[str, JSON]:
    rows: dict[str, JSON] = {}
    try:
        with Path(path).open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                row = loads(line)
                if not isinstance(row, dict):
                    raise PipelineError("INPUT_INVALID", "Train row must be an object", "audit")
                sample_id = safe_id(row.get("id"))
                if sample_id in rows:
                    raise PipelineError("INPUT_INVALID", "Duplicate Train row ID", "audit")
                rows[sample_id] = row
    except PipelineError:
        raise
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        raise PipelineError("INPUT_INVALID", "Train JSONL is unreadable or invalid", "audit") from exc
    return rows


def _gold_prefix(row: JSON, specs: dict[str, JSON], base: Path, split: str):
    config = RunConfig(data_root=base, runtime_dir=base, split=split, input_mode="transcript",
                       selected_ids=(row["id"],))
    sample = normalize_record(row, config, specs)
    prepared = prepare_request(sample, None, Deadline(10 ** 6), None)
    label = row.get("label")
    if not isinstance(label, dict):
        raise PipelineError("INPUT_INVALID", "Train row is missing its label", "audit")
    calls, results = label.get("tool_calls"), label.get("tool_results")
    if (not isinstance(calls, list) or not isinstance(results, list) or len(calls) != len(results)
            or any(not isinstance(c, dict) or not isinstance(c.get("name"), str)
                   or not isinstance(c.get("arguments"), dict) or not isinstance(r, dict)
                   for c, r in zip(calls, results))):
        raise PipelineError("INPUT_INVALID", "Invalid gold tool_calls/tool_results", "audit")
    return prepared, calls, results


def _expected_input(prepared: JSON, calls: list, results: list, prefix_index: int) -> JSON:
    observations = [{"step": i + 1, "kind": "tool_result", "name": calls[i]["name"],
                     "arguments": calls[i]["arguments"], "result": results[i]}
                    for i in range(prefix_index)]
    return {"request": prepared["request"], "context": prepared["context"], "history": prepared["history"],
            "available_tools": prepared["available_tools"], "observations": observations}


def _expected_target(calls: list, results: list, prefix_index: int) -> JSON:
    n = len(calls)
    if prefix_index > n:
        raise PipelineError("INPUT_INVALID", "prefix_index is beyond the gold trajectory", "audit")
    terminal_missing_info = (n > 0 and calls[n - 1]["name"] == "sys.ask_missing_info"
                             and results[n - 1].get("ok") is True and results[n - 1].get("waiting_for_user") is True)
    if prefix_index < n:
        return {"action": "call", "name": calls[prefix_index]["name"], "arguments": calls[prefix_index]["arguments"]}
    if terminal_missing_info:
        raise PipelineError("INPUT_INVALID", "A finish row cannot follow a terminal missing-information call", "audit")
    return {"action": "finish"}


def audit_bundle(bundle_path: Path, partition_manifest_path: Path, train_jsonl_path: Path,
                 catalog_path: Path) -> JSON:
    bundle_path, partition_manifest_path = Path(bundle_path), Path(partition_manifest_path)
    train_jsonl_path, catalog_path = Path(train_jsonl_path), Path(catalog_path)
    catalog = read_json(catalog_path, "CATALOG_INVALID")
    specs = validate_catalog(catalog)
    catalog_fingerprint = digest(catalog_path)
    partition_sha256 = digest(partition_manifest_path)
    partition, members = load_partition_manifest(partition_manifest_path)
    source_dataset_sha256 = digest(train_jsonl_path)
    if partition["dataset_sha256"] != source_dataset_sha256:
        raise PipelineError("INPUT_INVALID", "Partition manifest belongs to a different Train revision", "audit")
    bundle = read_json(bundle_path)
    validate_bundle(bundle, members, partition_sha256, catalog_fingerprint)
    rows = _load_train_rows(train_jsonl_path)
    base, split = train_jsonl_path.resolve().parent.parent, train_jsonl_path.resolve().parent.name
    for example in bundle["examples"]:
        row = rows.get(example["id"])
        if row is None:
            raise PipelineError("INPUT_INVALID",
                                f"Bundle example {example['id']} is absent from the supplied Train JSONL", "audit")
        prepared, calls, results = _gold_prefix(row, specs, base, split)
        # Bounds-checks prefix_index before any observation slice is built from it.
        expected_target = _expected_target(calls, results, example["prefix_index"])
        expected_input = _expected_input(prepared, calls, results, example["prefix_index"])
        if dumps(expected_input) != dumps(example["input"]):
            raise PipelineError("INPUT_INVALID",
                                f"Bundle example {example['id']} input does not match its verified source prefix", "audit")
        if dumps(expected_target) != dumps(example["target"]):
            raise PipelineError("INPUT_INVALID",
                                f"Bundle example {example['id']} target does not match its gold action", "audit")
    return bundle | {
        "audit_schema_version": AUDIT_SCHEMA_VERSION, "conversion_version": CONVERSION_VERSION,
        "source_dataset_sha256": source_dataset_sha256, "catalog_sha256": catalog_fingerprint,
        "partition_sha256": partition_sha256,
        "verified_content_sha256": verified_content_sha256(bundle["examples"]),
    }


def write_audited_bundle(output_path: Path, audited_bundle: JSON) -> None:
    output_path = Path(output_path)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PipelineError("OUTPUT_IO", "Cannot create audited bundle output directory", "audit") from exc
    payload = dumps(audited_bundle) + "\n"
    created = False
    try:
        # Exclusive create (O_CREAT|O_EXCL) is atomically exclusive on every
        # filesystem, unlike a hard link, which some (FAT/exFAT) do not support;
        # it closes the same exists()-check/later-write race without that limit.
        with output_path.open("x", encoding="utf-8", newline="\n") as stream:
            created = True
            sync_write(stream, payload)
    except FileExistsError as exc:
        raise PipelineError("OUTPUT_IO", "Audited bundle output must be new; audited bundles are immutable",
                            "audit") from exc
    except OSError as exc:
        if created:
            # Leave no partial/empty file behind; a rerun with the same --output
            # must not be blocked by a failed previous attempt.
            output_path.unlink(missing_ok=True)
        raise PipelineError("OUTPUT_IO", "Cannot persist audited bundle", "audit") from exc


__all__ = ["AUDIT_SCHEMA_VERSION", "CONVERSION_VERSION", "audit_bundle", "verified_content_sha256",
          "write_audited_bundle"]
