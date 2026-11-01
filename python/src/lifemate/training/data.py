"""Frozen grouped Train partition. Standard library only; reads Train JSONL/catalog only.

Grouping uses visible inputs (requests, history, installed tools). Gold labels are
read only for the coverage audit, never to decide groups. Environment files are
never opened.
"""
from __future__ import annotations

import hashlib
import random
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from ..contracts import JSON, PipelineError
from ..dataset import validate_catalog
from ..jsonio import contained, dumps, loads, read_json, safe_id
from ..prompt_profiles import PARTITION_SCHEMA_VERSION, validate_partition_manifest

GROUPING_VERSION = "lifemate-train-grouping-v1"
JACCARD_THRESHOLD = 0.8
MIN_SKELETON_TOKENS = 3
SMOKE_FIT_IDS = ("train_1748", "train_1749", "train_1750", "train_1751")
DEFAULT_SEED = 20261027
DEFAULT_VALIDATION_FRACTION = 0.2
LIMITATIONS = (
    "Visible Train inputs carry no explicit conversation or scenario-template IDs; conversation "
    "links are inferred from shared history turns.",
    "Near-duplicate and skeleton candidates are lexical; reworded paraphrases are not detected, "
    "so semantic deduplication is not claimed.",
    "Skeleton masking covers numbers/dates/times and capitalized non-initial words only.",
)


def _invalid(message: str) -> PipelineError:
    return PipelineError("INPUT_INVALID", message, "partition")


def normalize_text(text: str) -> str:
    """NFC, case-folded, whitespace-collapsed; Vietnamese diacritics and numbers kept."""
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def token_set(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"\w+", normalize_text(text)))


def skeleton(text: str) -> str:
    """The request with variable numbers/times and likely names replaced by placeholders."""
    words = unicodedata.normalize("NFC", text).split()
    masked = []
    for index, word in enumerate(words):
        # Times/dates such as 7h30, 9h, 12/11 or 1.5 collapse to one placeholder.
        word = re.sub(r"\d+(?:[.,:/hg-]\d*)*", "<num>", word)
        if index > 0 and word[:1].isupper():
            word = "<name>"
        masked.append(word)
    return normalize_text(" ".join(masked))


class _Groups:
    def __init__(self, ids):
        self.parent = {i: i for i in ids}

    def find(self, item: str) -> str:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a: str, b: str) -> bool:
        root_a, root_b = self.find(a), self.find(b)
        if root_a == root_b:
            return False
        self.parent[max(root_a, root_b)] = min(root_a, root_b)
        return True


def _text(value, name: str, sample_id: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{sample_id}: missing/invalid {name}")
    return value


def visible_record(row: JSON) -> JSON:
    """The grouping view of one Train row: request, user history turns, installed tools."""
    sample_id = safe_id(row.get("id"))
    request = _text(row.get("audio_text"), "audio_text", sample_id)
    history = row.get("history")
    context = row.get("context")
    if (not isinstance(history, list) or not isinstance(context, dict)
            or any(not isinstance(turn, dict) for turn in history)):
        raise _invalid(f"{sample_id}: history/context have an invalid shape")
    turns = [_text(turn.get("audio_text"), "historical audio_text", sample_id)
             for turn in history if turn.get("role") == "user"]
    installed = context.get("installed_apps")
    if not isinstance(installed, dict) or any(
            not isinstance(info, dict) or not isinstance(info.get("tools"), list)
            or not all(isinstance(name, str) and name.strip() for name in info["tools"])
            for info in installed.values()):
        raise _invalid(f"{sample_id}: invalid installed_apps")
    tools = frozenset(name for info in installed.values() for name in info["tools"])
    return {"id": sample_id, "request": request, "history": [normalize_text(t) for t in turns],
            "tools": tools}


def _coverage_flags(row: JSON, visible: JSON) -> JSON:
    # long_history comes from visible inputs, so it is known even without a label.
    flags = {"long_history": len(visible["history"]) >= 2}
    label = row.get("label")
    calls = label.get("tool_calls") if isinstance(label, dict) else None
    if not isinstance(calls, list) or not all(isinstance(c, dict) and isinstance(c.get("name"), str)
                                               for c in calls):
        return flags | {"label_missing": True}
    apps = {call["name"].split(".", 1)[0] for call in calls}
    return flags | {"empty_gold": not calls,
                    "missing_info": any(call["name"] == "sys.ask_missing_info" for call in calls),
                    "multi_app": len(apps - {"sys"}) > 1,
                    "apps": sorted(apps)}


def _coverage(flags: dict[str, JSON], members: list[JSON]) -> JSON:
    result = {}
    for side in ("fit", "validation"):
        ids = [m["id"] for m in members if m["partition"] == side]
        known = [flags[i] for i in ids if not flags[i].get("label_missing")]
        apps = defaultdict(int)
        for item in known:
            for app in item["apps"]:
                apps[app] += 1
        result[side] = {"samples": len(ids), "label_missing": len(ids) - len(known),
                        **{key: sum(1 for item in known if item[key])
                           for key in ("empty_gold", "missing_info", "multi_app")},
                        "long_history": sum(1 for i in ids if flags[i]["long_history"]),
                        "samples_calling_app": dict(sorted(apps.items()))}
    fit_apps, validation_apps = (set(result[s]["samples_calling_app"]) for s in ("fit", "validation"))
    result["apps_missing_from_validation"] = sorted(fit_apps - validation_apps)
    result["apps_missing_from_fit"] = sorted(validation_apps - fit_apps)
    result["categories_missing_from_validation"] = [
        key for key in ("empty_gold", "missing_info", "multi_app", "long_history")
        if result["fit"][key] and not result["validation"][key]]
    return result


def _validated_decisions(decisions: JSON | None, ids: set[str]) -> list[JSON]:
    if decisions is None:
        return []
    items = decisions.get("decisions") if isinstance(decisions, dict) else None
    if not isinstance(items, list):
        raise _invalid("Decisions file needs a 'decisions' list")
    result = []
    for item in items:
        pair = item.get("ids") if isinstance(item, dict) else None
        if (not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(i, str) for i in pair)
                or len(set(pair)) != 2 or not set(pair) <= ids
                or item.get("decision") not in ("group", "separate")
                or not isinstance(item.get("reason"), str) or not item["reason"].strip()):
            raise _invalid("Each decision needs two known distinct ids, group|separate and a reason")
        result.append({"ids": sorted(pair), "decision": item["decision"], "reason": item["reason"]})
    return result


def build_partition(rows: list[JSON], *, dataset_sha256: str, catalog_sha256: str,
                    seed: int = DEFAULT_SEED, validation_fraction: float = DEFAULT_VALIDATION_FRACTION,
                    decisions: JSON | None = None) -> JSON:
    """Deterministic grouped fit/validation manifest, validated as partition v1."""
    if (isinstance(validation_fraction, bool) or not isinstance(validation_fraction, (int, float))
            or not 0 < validation_fraction < 1):
        raise _invalid("validation_fraction must be between 0 and 1")
    if type(seed) is not int:
        raise _invalid("seed must be an integer")
    visible = [visible_record(row) for row in rows]
    ids = [v["id"] for v in visible]
    if not ids or len(set(ids)) != len(ids):
        raise _invalid("Train records are empty or have duplicate IDs")
    by_id = {v["id"]: v for v in visible}
    groups = _Groups(sorted(ids))
    links = defaultdict(int)

    # Conversation links: a sample whose history replays another's turns, or shares its opening turn.
    conversations, openers = {}, defaultdict(list)
    for v in visible:
        conversations.setdefault(tuple(v["history"] + [normalize_text(v["request"])]), []).append(v["id"])
        if v["history"]:
            openers[v["history"][0]].append(v["id"])
    for v in visible:
        for length in range(1, len(v["history"]) + 1):
            for other in conversations.get(tuple(v["history"][:length]), ()):
                links["conversation"] += groups.union(v["id"], other)
    for members in openers.values():
        for other in members[1:]:
            links["conversation"] += groups.union(members[0], other)
    # Exact normalized request/history duplicates.
    for members in conversations.values():
        for other in members[1:]:
            links["exact_duplicate"] += groups.union(members[0], other)

    # Review candidates, compared only within the same installed-tool signature.
    buckets = defaultdict(list)
    for sample_id in sorted(ids):
        buckets[by_id[sample_id]["tools"]].append(sample_id)
    candidates = []
    for bucket in buckets.values():
        text_tokens = {i: token_set(" ".join(by_id[i]["history"] + [by_id[i]["request"]])) for i in bucket}
        for position, a in enumerate(bucket):
            for b in bucket[position + 1:]:
                if groups.find(a) == groups.find(b):
                    continue
                union = text_tokens[a] | text_tokens[b]
                similarity = len(text_tokens[a] & text_tokens[b]) / len(union) if union else 0.0
                if similarity >= JACCARD_THRESHOLD:
                    candidates.append({"ids": [a, b], "kind": "near_duplicate", "similarity": round(similarity, 4)})
        shapes = defaultdict(list)
        for sample_id in bucket:
            shape = skeleton(by_id[sample_id]["request"])
            if len(shape.split()) >= MIN_SKELETON_TOKENS:
                shapes[shape].append(sample_id)
        listed = {tuple(c["ids"]) for c in candidates}
        for members in shapes.values():
            for a, b in zip(members, members[1:]):
                if groups.find(a) != groups.find(b) and (a, b) not in listed:
                    candidates.append({"ids": [a, b], "kind": "request_skeleton", "similarity": None})

    reviewed = _validated_decisions(decisions, set(ids))
    separated = {tuple(d["ids"]) for d in reviewed if d["decision"] == "separate"}
    candidate_pairs = {tuple(c["ids"]) for c in candidates}
    if not separated <= candidate_pairs:
        raise _invalid("A 'separate' decision must name a reported candidate pair, not a deterministic link")
    for candidate in candidates:
        pair = tuple(candidate["ids"])
        if pair in separated:
            candidate["decision"] = "separate"
            continue
        candidate["decision"] = "co-grouped (conservative default)"
        groups.union(*pair)
    for item in reviewed:
        if item["decision"] == "group":
            groups.union(*item["ids"])
    ineffective = [list(pair) for pair in sorted(separated) if groups.find(pair[0]) == groups.find(pair[1])]

    members_of = defaultdict(list)
    for sample_id in sorted(ids):
        members_of[groups.find(sample_id)].append(sample_id)
    group_ids = {root: "g" + hashlib.sha256(dumps(members).encode()).hexdigest()[:16]
                 for root, members in members_of.items()}
    smoke_present = [i for i in SMOKE_FIT_IDS if i in by_id]
    forced_fit = {groups.find(i) for i in smoke_present}
    order = sorted(members_of, key=lambda root: group_ids[root])
    random.Random(seed).shuffle(order)
    target = round(validation_fraction * len(ids))
    partition_of, validation_count = {}, 0
    for root in order:
        size = len(members_of[root])
        if root not in forced_fit and validation_count + size <= target:
            partition_of[root] = "validation"
            validation_count += size
        else:
            partition_of[root] = "fit"
    if validation_count == 0:
        # A frozen split without validation members cannot support any evaluation.
        raise _invalid("No group fits the validation target; use more data or a larger validation_fraction")

    source_hashes = {safe_id(row["id"]): hashlib.sha256(dumps(row).encode("utf-8")).hexdigest() for row in rows}
    members = [{"id": i, "group_id": group_ids[groups.find(i)], "partition": partition_of[groups.find(i)],
                "source_sha256": source_hashes[i]} for i in sorted(ids)]
    flags = {safe_id(row["id"]): _coverage_flags(row, by_id[safe_id(row["id"])]) for row in rows}
    sizes = sorted((len(m) for m in members_of.values()), reverse=True)
    manifest = {
        "partition_schema_version": PARTITION_SCHEMA_VERSION,
        "dataset_sha256": dataset_sha256,
        "grouping_method": GROUPING_VERSION,
        "members": members,
        "catalog_sha256": catalog_sha256,
        "source_sha256_definition": "sha256 of the row's canonical JSON (sorted keys, compact, UTF-8)",
        "seed": seed,
        "validation_fraction": validation_fraction,
        "grouping": {
            "version": GROUPING_VERSION,
            "normalization": "NFC, casefold, collapsed whitespace; diacritics and numbers kept",
            "rules": ["conversation: history replays another sample's turns, or shares its opening user turn",
                      "exact_duplicate: identical normalized history and request",
                      "near_duplicate candidate: token-set Jaccard >= threshold within one installed-tool signature",
                      "request_skeleton candidate: identical masked request within one installed-tool signature",
                      "candidates are co-grouped unless a recorded review decision separates them"],
            "parameters": {"jaccard_threshold": JACCARD_THRESHOLD, "min_skeleton_tokens": MIN_SKELETON_TOKENS},
            "deterministic_links": dict(links),
            "limitations": list(LIMITATIONS),
        },
        "candidates": candidates,
        "decisions": reviewed,
        "separate_decisions_overridden_by_other_links": ineffective,
        "smoke_ids": {"fit_required": list(SMOKE_FIT_IDS), "present": smoke_present,
                      "absent": [i for i in SMOKE_FIT_IDS if i not in by_id]},
        "counts": {"samples": len(ids), "groups": len(members_of),
                   "fit": len(ids) - validation_count, "validation": validation_count,
                   "validation_target": target,
                   "fit_groups": sum(1 for p in partition_of.values() if p == "fit"),
                   "validation_groups": sum(1 for p in partition_of.values() if p == "validation"),
                   "largest_group": sizes[0], "singleton_groups": sizes.count(1),
                   "candidates": len(candidates)},
        "coverage": _coverage(flags, members),
    }
    validate_partition_manifest(manifest)
    return manifest


def read_train(data_root: Path) -> tuple[list[JSON], str, str]:
    """Train rows plus dataset/catalog digests; the catalog is validated, environments untouched."""
    split = Path(data_root) / "train"
    if not split.is_dir():
        raise PipelineError("ASSET_MISSING", "Train split directory is missing", "partition")
    jsonl = contained(split, "train.jsonl")
    catalog = contained(split, "train_tools_catalog.json")
    # Hash exactly the bytes that are parsed, so a concurrent replacement cannot
    # pair one file's rows with another file's identity.
    try:
        catalog_bytes = catalog.read_bytes()
        validate_catalog(loads(catalog_bytes.decode("utf-8")))
    except PipelineError:
        raise
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        raise PipelineError("CATALOG_INVALID", "Train catalog is unreadable or invalid", "partition") from exc
    rows = []
    try:
        jsonl_bytes = jsonl.read_bytes()
        for line in jsonl_bytes.decode("utf-8").splitlines():
            if line.strip():
                if len(line.encode("utf-8")) > 4 * 1024 * 1024:
                    raise _invalid("Train row is too large")
                row = loads(line)
                if not isinstance(row, dict):
                    raise _invalid("Train row must be an object")
                rows.append(row)
    except PipelineError:
        raise
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        raise _invalid("Train JSONL is unreadable or invalid") from exc
    return rows, hashlib.sha256(jsonl_bytes).hexdigest(), hashlib.sha256(catalog_bytes).hexdigest()


def write_partition(output: Path, manifest: JSON) -> None:
    """Create the manifest; an existing partition is never overwritten."""
    output, content, created = Path(output), dumps(manifest) + "\n", False
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            created = True
            stream.write(content)
    except FileExistsError as exc:
        raise _invalid("Partition already exists; a new split needs a new experiment path") from exc
    except OSError as exc:
        # A partial file would block every retry at this frozen path; the write error still wins.
        if created:
            try:
                output.unlink(missing_ok=True)
            except OSError:
                pass
        raise PipelineError("OUTPUT_IO", "Cannot write the partition manifest", "partition") from exc


def partition(data_root: Path, output: Path, *, seed: int = DEFAULT_SEED,
              validation_fraction: float = DEFAULT_VALIDATION_FRACTION,
              decisions_path: Path | None = None) -> JSON:
    data_root, output = Path(data_root).resolve(), Path(output).resolve()
    if output.is_relative_to(data_root):
        raise _invalid("Partition output must be outside the organizer data root")
    if output.exists():
        raise _invalid("Partition already exists; a new split needs a new experiment path")
    rows, dataset_sha256, catalog_sha256 = read_train(data_root)
    decisions = read_json(decisions_path) if decisions_path is not None else None
    if decisions_path is not None and decisions is None:
        raise _invalid("Decisions file needs a 'decisions' list")
    manifest = build_partition(rows, dataset_sha256=dataset_sha256, catalog_sha256=catalog_sha256,
                               seed=seed, validation_fraction=validation_fraction, decisions=decisions)
    write_partition(output, manifest)
    return manifest
