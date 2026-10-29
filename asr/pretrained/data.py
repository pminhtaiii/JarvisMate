"""Train-only ASR projection, grouped split and frozen asset provenance."""
from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher
import hashlib
from pathlib import Path
import random
import re
import wave

from lifemate.dataset import wav_info
from lifemate.jsonio import contained, digest, dumps, loads, safe_id, visible_path

from .metrics import normalize

SCHEMA = "asr-grouped-split-v1"
GROUPING = {"version": "audio-user-text-template-v1", "audio": "SHA256 of decoded PCM",
            "text": "all user turns, exact normalized text or digit-masked template",
            "near_text": "character-trigram Jaccard >=0.85 AND SequenceMatcher >=0.92",
            "conversation": "shared user turns/prefixes; transitive connected components",
            "limitations": "heuristic near-text detection; no semantic/audio perceptual matching"}


def identity(value: dict) -> str:
    return hashlib.sha256(dumps(value).encode("utf-8")).hexdigest()


def audio_asset(base: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative.startswith("audio/") or not relative.endswith(".wav"):
        raise ValueError("Expected a WAV path under train/audio/")
    path = contained(base, relative)
    if not path.is_relative_to((base / "audio").resolve()):
        raise ValueError("Audio must remain under train/audio/")
    return path


def inspect_audio(path: Path) -> dict:
    info = wav_info(path)
    pcm = hashlib.sha256()
    remaining = info["frames"] * 2
    with wave.open(str(path), "rb") as stream:
        while remaining:
            block = stream.readframes(min(remaining // 2, 65536))
            if not block:
                raise ValueError(f"Truncated WAV: {path}")
            pcm.update(block)
            remaining -= len(block)
    return {"duration_seconds": info["seconds"], "wav_sha256": digest(path),
            "pcm_sha256": pcm.hexdigest()}


def project_train(data_root: Path) -> tuple[list[dict], dict]:
    """Discard labels/context/assistant turns; never import or access ToolEnv."""
    base = (data_root / "train").resolve(strict=True)
    source = base / "train.jsonl"
    visible_path(source)
    samples, ids, assets = [], set(), {}
    with source.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            record = loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"Invalid record at line {line_number}")
            sample_id = safe_id(record.get("id"))
            if sample_id in ids:
                raise ValueError(f"Duplicate source sample: {sample_id}")
            ids.add(sample_id)
            history = record.get("history", [])
            if not isinstance(history, list) or any(not isinstance(t, dict) for t in history):
                raise ValueError(f"Invalid history: {sample_id}")
            turns = [(f"history_{i:03d}", turn) for i, turn in enumerate(history)
                     if turn.get("role") == "user"] + [("current", record)]
            utterances = []
            for turn_id, turn in turns:
                reference = turn.get("audio_text")
                if not isinstance(reference, str):
                    raise ValueError(f"Missing audio_text: {sample_id}/{turn_id}")
                relative = turn.get("audio")
                path = audio_asset(base, relative)
                if relative not in assets:
                    assets[relative] = inspect_audio(path)
                utterances.append({"utterance_id": f"{sample_id}/{turn_id}", "sample_id": sample_id,
                                   "turn_id": turn_id, "audio": relative, "reference": reference,
                                   **assets[relative]})
            samples.append({"id": sample_id, "utterances": utterances})
    if len(samples) < 2:
        raise ValueError("At least two source samples are required")
    return samples, {"train_jsonl_sha256": digest(source), "samples": len(samples),
                     "user_utterances": sum(len(s["utterances"]) for s in samples),
                     "unique_audio_paths": len(assets)}


def group_samples(samples: list[dict]) -> tuple[list[list[str]], dict]:
    parents = {s["id"]: s["id"] for s in samples}

    def find(key):
        while key != parents[key]:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parents[max(a, b)] = min(a, b)

    owners, texts, reasons = {}, {}, defaultdict(int)
    for sample in samples:
        for utterance in sample["utterances"]:
            text = normalize(utterance["reference"])
            template = re.sub(r"\d+", "#", text)
            keys = [("audio", utterance["pcm_sha256"])]
            if text:
                keys += [("text", text), ("numeric_template", template)]
                texts.setdefault(template, sample["id"])
            for kind, key in keys:
                if (kind, key) in owners:
                    other = owners[kind, key]
                    if other != sample["id"]:
                        union(sample["id"], other)
                        reasons[kind] += 1
                else:
                    owners[kind, key] = sample["id"]

    # Inverted trigram index avoids an expensive all-pairs edit comparison.
    postings, grams_by_index, indexed = defaultdict(list), [], []
    for text, owner in sorted(texts.items()):
        grams = {text[i:i + 3] for i in range(max(0, len(text) - 2))}
        overlap = defaultdict(int)
        for gram in grams:
            for index in postings[gram]:
                overlap[index] += 1
        for index, shared in overlap.items():
            other_text, other_owner = indexed[index]
            if find(owner) == find(other_owner):
                continue
            jaccard = shared / (len(grams) + len(grams_by_index[index]) - shared)
            if jaccard >= .85 and SequenceMatcher(None, text, other_text, autojunk=False).ratio() >= .92:
                union(owner, other_owner)
                reasons["near_text"] += 1
        index = len(indexed)
        indexed.append((text, owner))
        grams_by_index.append(grams)
        for gram in grams:
            postings[gram].append(index)
    groups = defaultdict(list)
    for sample_id in sorted(parents):
        groups[find(sample_id)].append(sample_id)
    return sorted(groups.values()), dict(reasons)


def make_split(data_root: Path, *, seed: int = 42, validation_ratio: float = .2) -> dict:
    samples, source = project_train(data_root)
    groups, reasons = group_samples(samples)
    if len(groups) < 2:
        raise ValueError("Grouping leaves fewer than two groups; cannot create a leakage-safe split")
    shuffled = groups.copy()
    random.Random(seed).shuffle(shuffled)
    target, selected, count = len(samples) * validation_ratio, set(), 0
    # Whole groups only; keep at least one group on each side.
    for group in shuffled:
        if abs(count + len(group) - target) < abs(count - target):
            selected.update(group)
            count += len(group)
    if not selected:
        selected.update(min(shuffled, key=len))
    if len(selected) == len(samples):
        selected.difference_update(shuffled[-1])
    memberships = {sample_id: "g-" + hashlib.sha256(dumps(group).encode()).hexdigest()[:16]
                   for group in groups for sample_id in group}
    rows = [{"id": s["id"], "group": memberships[s["id"]],
             "partition": "validation" if s["id"] in selected else "train",
             "utterances": s["utterances"]} for s in samples]
    manifest = {"schema": SCHEMA, "seed": seed, "requested_validation_ratio": validation_ratio,
                "actual_validation_ratio": len(selected) / len(samples), "source": source,
                "grouping": GROUPING, "link_counts": reasons, "groups": len(groups),
                "largest_group": max(map(len, groups)), "samples": rows}
    manifest["identity"] = identity(manifest)
    return manifest


def load_selection(path: Path, data_root: Path, scope: str, limit: int | None = None) -> tuple[dict, list[dict]]:
    visible_path(path)
    manifest = loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise ValueError("Unsupported split manifest")
    body = {key: value for key, value in manifest.items() if key != "identity"}
    if manifest.get("identity") != identity(body):
        raise ValueError("Split manifest identity mismatch")
    source = data_root / "train" / "train.jsonl"
    if digest(source) != manifest["source"]["train_jsonl_sha256"]:
        raise ValueError("Source JSONL changed; use the original dataset or create a new experiment")
    partitions, ids, utterance_ids, selected = {}, set(), set(), []
    for sample in manifest["samples"]:
        sample_id = safe_id(sample["id"])
        if sample_id in ids or sample["partition"] not in {"train", "validation"}:
            raise ValueError("Invalid sample membership")
        ids.add(sample_id)
        group = sample["group"]
        if group in partitions and partitions[group] != sample["partition"]:
            raise ValueError("Group crosses partitions")
        partitions[group] = sample["partition"]
        for utterance in sample["utterances"]:
            if (utterance["sample_id"] != sample_id or utterance["utterance_id"] in utterance_ids
                    or not isinstance(utterance["reference"], str)):
                raise ValueError("Invalid utterance alignment")
            utterance_ids.add(utterance["utterance_id"])
            if sample["partition"] == "validation" and (scope == "with-history" or utterance["turn_id"] == "current"):
                selected.append({**utterance, "group": group})
    if limit is not None:
        selected = selected[:limit]
    if not selected:
        raise ValueError("No validation utterances selected")
    # Verify every selected asset before loading any model; never shrink the selection.
    for utterance in selected:
        actual = inspect_audio(audio_asset(data_root / "train", utterance["audio"]))
        if any(actual[k] != utterance[k] for k in actual):
            raise ValueError(f"Changed audio asset: {utterance['utterance_id']}")
    return manifest, selected
