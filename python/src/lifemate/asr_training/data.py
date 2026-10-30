"""Freeze Train-only audio pairs against the existing ASR split; never re-split."""
from __future__ import annotations

from pathlib import Path

from asr.pretrained.data import SCHEMA, identity, project_train, audio_asset, inspect_audio
from asr.pretrained.metrics import normalize
from asr.pretrained.models import local_spec
from lifemate.jsonio import digest, visible_path
from .storage import read, write, write_rows, rows, ignored, now, seal, verify

SPLIT_ID = "da6b2725c4a7136e66e6ee93d2cda9a30561edd0905b4a78b258de35996dfcfa"


def project(data_root: Path, manifest_path: Path, *, expected_identity: str = SPLIT_ID,
            expected_validation: int = 309) -> tuple[dict, list, list, list, dict]:
    split = read(manifest_path)
    body = {k: v for k, v in split.items() if k != "identity"}
    if (split.get("schema") != SCHEMA or split.get("seed") != 42
            or split.get("identity") != expected_identity or identity(body) != expected_identity):
        raise ValueError("Frozen seed-42 split identity mismatch; do not re-split")
    actual, source = project_train(data_root)
    if source != split["source"] or len(actual) != len(split["samples"]):
        raise ValueError("Source dataset changed")
    fit, validation, history, seen, owners, groups = [], [], [], {}, {}, {}
    removed = []
    for original, sample in zip(actual, split["samples"], strict=True):
        if original["id"] != sample["id"] or original["utterances"] != sample["utterances"]:
            raise ValueError("Manifest current/history alignment differs from source JSONL")
        partition, group = sample["partition"], sample["group"]
        if partition not in {"train", "validation"} or (group in groups and groups[group] != partition):
            raise ValueError("Invalid partition or cross-partition group")
        groups[group] = partition
        for item in sample["utterances"]:
            row = dict(item, group=group, partition=partition)
            if not row["reference"].strip():
                raise ValueError(f"Empty transcript: {row['utterance_id']}")
            pcm = row["pcm_sha256"]
            if pcm in owners and owners[pcm] != partition:
                raise ValueError("Duplicate audio crosses partitions; review the frozen experiment")
            owners[pcm] = partition
            key = (pcm, normalize(row["reference"]))
            if pcm in seen and seen[pcm][0] != key:
                raise ValueError("Same PCM has conflicting transcripts")
            if partition == "train":
                if pcm in seen:
                    removed.append({"id": row["utterance_id"], "representative": seen[pcm][1]})
                    continue
                fit.append(row)
            else:
                history.append(row)
                if row["turn_id"] == "current":
                    validation.append(row)
            seen[pcm] = key, row["utterance_id"]
    if len(validation) != expected_validation or not fit:
        raise ValueError("Frozen validation count differs from expected primary selection")
    if len({r["utterance_id"] for r in fit + history}) != len(fit + history):
        raise ValueError("Duplicate utterance IDs")
    audit = {"source": source, "train_rows": len(fit), "validation_current": len(validation),
             "validation_with_history": len(history), "deduplicated_fit": removed,
             "dedup_policy": "PCM+normalized-reference; keep first manifest occurrence"}
    return split, fit, validation, history, audit


def prepare_suite(path: Path, data_root: Path, split_path: Path, model: Path,
                  annotations: Path | None = None, rules: Path | None = None) -> dict:
    path = ignored(path)
    if path.exists():
        raise ValueError("Suite already exists; reuse it or choose a fresh suite directory")
    split, fit, val, history, audit = project(data_root, split_path)
    spec = local_spec("phowhisper-large", model.resolve().parent)
    if Path(spec["path"]) != model.resolve():
        raise ValueError("Use the prepared directory named phowhisper-large")
    if bool(annotations) != bool(rules):
        raise ValueError("Provide both slot annotations and extractor rules, or neither")
    from .slots import SlotEvaluator
    annotation_rows, rule_data = (rows(annotations), read(rules)) if annotations else (None, None)
    SlotEvaluator(val, annotation_rows, rule_data)  # Validate before writing anything.
    metadata = {"schema": "asr-ft-suite-v1", "created": now(), "data_root": str(data_root.resolve()),
                "split_manifest": str(split_path.resolve()), "split_identity": split["identity"],
                "split_manifest_sha256": digest(split_path),
                "source": split["source"], "model": spec,
                "fit_identity": identity(fit), "validation_identity": identity(val),
                "selection_identity": identity({"split": split["identity"], "scope": "current",
                                                 "utterance_ids": [r["utterance_id"] for r in val]}),
                "annotation_identity": identity(annotation_rows), "rules_identity": identity(rule_data),
                "policy": "lifemate-asr-ft-eval-v1", "audit": audit}
    metadata["identity"] = identity(metadata)
    path.mkdir(parents=True)
    data = path / "data"
    data.mkdir()
    write_rows(data / "fit.jsonl", fit)
    write_rows(data / "validation-current.jsonl", val)
    write_rows(data / "validation-history.jsonl", history)
    write(data / "audit.json", audit)
    if annotation_rows is not None:
        write_rows(data / "slots.jsonl", annotation_rows)
        write(data / "slot-rules.json", rule_data)
    seal(data)
    write(path / "suite.json", metadata)
    return metadata


def load_suite(path: Path, *, assets: bool = True) -> tuple[dict, list, list]:
    metadata = read(path / "suite.json")
    if metadata["identity"] != identity({k: v for k, v in metadata.items() if k != "identity"}):
        raise ValueError("Suite identity mismatch")
    verify(path / "data")
    fit, val = rows(path / "data/fit.jsonl"), rows(path / "data/validation-current.jsonl")
    if identity(fit) != metadata["fit_identity"] or identity(val) != metadata["validation_identity"]:
        raise ValueError("Prepared rows changed")
    if assets:
        root = Path(metadata["data_root"])
        if digest(Path(metadata["split_manifest"])) != metadata["split_manifest_sha256"]:
            raise ValueError("Original frozen split manifest changed")
        if digest(root / "train/train.jsonl") != metadata["source"]["train_jsonl_sha256"]:
            raise ValueError("Source JSONL changed")
        spec = local_spec("phowhisper-large", Path(metadata["model"]["path"]).parent)
        if spec != metadata["model"]:
            raise ValueError("Model snapshot/provenance changed")
        for row in fit + rows(path / "data/validation-history.jsonl"):
            actual = inspect_audio(audio_asset(root / "train", row["audio"]))
            if any(actual[k] != row[k] for k in actual):
                raise ValueError(f"Audio changed: {row['utterance_id']}")
    return metadata, fit, val
