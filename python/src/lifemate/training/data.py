"""Frozen grouped Train partition and native next-action SFT export.

Both read Train JSONL/catalog only; environment files are never opened. Grouping uses
visible inputs (requests, history, installed tools); gold labels are read only for its
coverage audit. The exporter turns fit gold into strict-prefix rows through the
inference input whitelist and native rendering. Module imports are standard library
only; the export loads its tokenizer and grammar lazily.
"""
from __future__ import annotations

import hashlib
import os
import random
import re
import shutil
import unicodedata
import uuid
from collections import Counter, defaultdict
from pathlib import Path

from ..adapters import qwen_protocol
from ..adapters.common import model_directory
from ..adapters.constrained import grammar_ordered_arguments
from ..artifacts import sync_write
from ..contracts import JSON, Deadline, Limits, PipelineError, RunConfig
from ..dataset import normalize_record, prepare_request, validate_catalog
from ..example_audit import CONVERSION_VERSION
from ..jsonio import contained, digest, dumps, loads, read_json, safe_id
from ..prompt_profiles import (PARTITION_SCHEMA_VERSION, profile_identity, protocol_profile, resolve_profile,
                               validate_partition_manifest)
from ..prompting import ALLOWED_INPUT_FIELDS, NATIVE_FINISH_TEXT, planner_input
from ..provenance import code_identity

GROUPING_VERSION = "lifemate-train-grouping-v1"
JACCARD_THRESHOLD = 0.8
MIN_SKELETON_TOKENS = 3
SMOKE_FIT_IDS = ("train_1748", "train_1749", "train_1750", "train_1751")
DEFAULT_SEED = 20261027
DEFAULT_VALIDATION_FRACTION = 0.2
# The brief describes about 1,600 Train rows; this bounds memory for a corrupt or wrong file.
MAX_TRAIN_BYTES = 256 * 1024 * 1024
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


def read_train(data_root: Path) -> tuple[list[JSON], str, JSON, str]:
    """Train rows, dataset digest, validated catalog and its digest; environments untouched."""
    split = Path(data_root) / "train"
    if not split.is_dir():
        raise PipelineError("ASSET_MISSING", "Train split directory is missing", "partition")
    jsonl = contained(split, "train.jsonl")
    catalog = contained(split, "train_tools_catalog.json")
    # Hash exactly the bytes that are parsed, so a concurrent replacement cannot
    # pair one file's rows with another file's identity.
    try:
        catalog_bytes = catalog.read_bytes()
        catalog_value = loads(catalog_bytes.decode("utf-8"))
        validate_catalog(catalog_value)
    except PipelineError:
        raise
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        raise PipelineError("CATALOG_INVALID", "Train catalog is unreadable or invalid", "partition") from exc
    rows = []
    try:
        with jsonl.open("rb") as stream:
            jsonl_bytes = stream.read(MAX_TRAIN_BYTES + 1)
        if len(jsonl_bytes) > MAX_TRAIN_BYTES:
            raise _invalid("Train JSONL exceeds the supported size")
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
    return (rows, hashlib.sha256(jsonl_bytes).hexdigest(), catalog_value,
            hashlib.sha256(catalog_bytes).hexdigest())


def _publish_new_file(source: Path, destination: Path) -> None:
    """Move a fully written file to `destination`; raises FileExistsError instead of replacing.

    Windows rename refuses an existing destination and a POSIX link cannot replace one.
    On POSIX the caller removes `source` afterwards.
    """
    (os.rename if os.name == "nt" else os.link)(source, destination)


def write_partition(output: Path, manifest: JSON) -> None:
    """Publish the complete manifest at once; an existing partition is never overwritten.

    Writing a staging file first means an interrupted write never leaves a partial
    manifest at the frozen path, where it would block every retry.
    """
    output = Path(output)
    staging = output.with_name(f".{output.name}.partial-{uuid.uuid4().hex}")
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with staging.open("x", encoding="utf-8", newline="\n") as stream:
            sync_write(stream, dumps(manifest) + "\n")
        _publish_new_file(staging, output)
    except FileExistsError as exc:
        raise _invalid("Partition already exists; a new split needs a new experiment path") from exc
    except OSError as exc:
        raise PipelineError("OUTPUT_IO", "Cannot write the partition manifest", "partition") from exc
    finally:
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            pass


def partition(data_root: Path, output: Path, *, seed: int = DEFAULT_SEED,
              validation_fraction: float = DEFAULT_VALIDATION_FRACTION,
              decisions_path: Path | None = None) -> JSON:
    data_root, output = Path(data_root).resolve(), Path(output).resolve()
    if output.is_relative_to(data_root):
        raise _invalid("Partition output must be outside the organizer data root")
    if output.exists():
        raise _invalid("Partition already exists; a new split needs a new experiment path")
    rows, dataset_sha256, _, catalog_sha256 = read_train(data_root)
    decisions = read_json(decisions_path) if decisions_path is not None else None
    if decisions_path is not None and decisions is None:
        raise _invalid("Decisions file needs a 'decisions' list")
    manifest = build_partition(rows, dataset_sha256=dataset_sha256, catalog_sha256=catalog_sha256,
                               seed=seed, validation_fraction=validation_fraction, decisions=decisions)
    write_partition(output, manifest)
    return manifest


# ---------------------------------------------------------------------------
# Native next-action SFT export (spec 003 US3; docs/design/train-to-sft.md)
# ---------------------------------------------------------------------------

EXPORT_SCHEMA_VERSION = 1
EXPORTER_VERSION = "lifemate-native-sft-export-v1"
IGNORE_INDEX = -100
WAITING_TOOL = "sys.ask_missing_info"
EXPORT_FILES = {"fit": "fit.jsonl", "validation": "validation.next_action.jsonl"}
EXPORT_LIMITATIONS = (
    "Rows use supplied Train transcripts and gold observations; teacher-forced rows are not closed-loop evidence.",
    "ID grounding is lexical: a reference value must occur in the request, context, history or an earlier "
    "result. It cannot prove the value came from the right record.",
    "Grammar parity is checked character by character against the inference grammar; token-level EOS "
    "admission is covered by the opt-in real-tokenizer smoke tests.",
)


class Quarantine(Exception):
    """A sample or row excluded from training with an explicit, reviewable reason."""

    def __init__(self, reason: str, detail: str, step: int | None = None, target_name: str | None = None):
        super().__init__(detail)
        self.reason, self.detail, self.step, self.target_name = reason, detail, step, target_name


def _export_invalid(message: str) -> PipelineError:
    return PipelineError("INPUT_INVALID", message, "export")


def _exclusion(member: JSON, error: Quarantine) -> JSON:
    return {"source_id": member["id"], "group_id": member["group_id"], "partition": member["partition"],
            "step": error.step, "target_name": error.target_name, "reason": error.reason, "detail": error.detail}


def _gold(row: JSON) -> tuple[list[JSON], list[JSON]]:
    label = row.get("label")
    calls = label.get("tool_calls") if isinstance(label, dict) else None
    results = label.get("tool_results") if isinstance(label, dict) else None
    if not isinstance(calls, list) or not isinstance(results, list):
        raise Quarantine("label_missing", "label.tool_calls/tool_results are absent")
    if len(calls) != len(results):
        raise Quarantine("pairing_mismatch", f"{len(calls)} gold calls but {len(results)} gold results")
    for index, (call, result) in enumerate(zip(calls, results)):
        if not (isinstance(call, dict) and isinstance(call.get("name"), str) and call["name"]
                and isinstance(call.get("arguments"), dict) and isinstance(result, dict)):
            raise Quarantine("invalid_gold_shape", "A gold call needs a name and object arguments, "
                             "paired with an object result", index)
    return calls, results


def _terminal_wait(call: JSON, result: JSON) -> bool:
    # The runner stops only on this exact result; any other missing-info result is observed.
    return call["name"] == WAITING_TOOL and result.get("ok") is True and result.get("waiting_for_user") is True


def _reference_values(value, schema):
    """Argument values whose catalog schema marks them as references (`x-ref`)."""
    if not isinstance(schema, dict):
        return
    if "x-ref" in schema:
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, (str, int, float)) and not isinstance(item, bool):
                yield item
        return
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _reference_values(item, schema.get("properties", {}).get(key))
    elif isinstance(value, list):
        for item in value:
            yield from _reference_values(item, schema.get("items"))


def _evidence(value: JSON) -> tuple[str, set[str]]:
    """Text and numbers a reference may be grounded in: request, context, history, earlier results."""
    texts, numbers = [value["request"]], set()

    def walk(item):
        if isinstance(item, dict):
            texts.extend(str(key) for key in item)
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
        elif isinstance(item, str):
            texts.append(item)
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            numbers.add(dumps(item))

    walk(value["context"])
    walk(value["history"])
    for observation in value["observations"]:
        walk(observation["result"])
    return "\n".join(texts), numbers


def _grounded(reference, evidence: tuple[str, set[str]]) -> bool:
    text, numbers = evidence
    if isinstance(reference, str):
        return reference in text
    return dumps(reference) in numbers or dumps(reference) in text


def gold_rows(row: JSON, member: JSON, specs: dict[str, JSON], data_root: Path) -> tuple[list[JSON], list[JSON]]:
    """Strict-prefix next-action rows from one Train sample's gold, plus explicit exclusions.

    Inputs come from the inference whitelist (`normalize_record`, `prepare_request`,
    `planner_input`); labels supply only the target and earlier paired observations.
    No environment is opened, no ID or target is invented.
    """
    try:
        config = RunConfig(data_root=data_root, runtime_dir=data_root, split="train", input_mode="transcript",
                           selected_ids=(member["id"],))
        prepared = prepare_request(normalize_record(row, config, specs), None, Deadline(10 ** 6))
    except PipelineError as exc:
        return [], [_exclusion(member, Quarantine("visible_input_invalid", f"{exc.code}: {exc}"))]
    tools = {tool["name"]: tool for tool in prepared["available_tools"]}
    try:
        calls, results = _gold(row)
        for index, call in enumerate(calls):
            if call["name"] not in tools:
                raise Quarantine("unavailable_tool", "The gold call's tool is not installed for this sample",
                                 index, call["name"])
            if _terminal_wait(call, results[index]) and index < len(calls) - 1:
                raise Quarantine("continues_after_terminal_wait",
                                 "Gold continues after a waiting missing-info result", index, call["name"])
    except Quarantine as error:
        return [], [_exclusion(member, error)]

    def converted(step: int, target: JSON, origin: str) -> JSON:
        observations = [{"step": i + 1, "kind": "tool_result", "name": calls[i]["name"],
                         # The runner re-reads executed arguments from canonical (sorted-key) JSON.
                         "arguments": loads(dumps(calls[i]["arguments"])), "result": results[i]}
                        for i in range(step)]
        return {"row_id": f"{member['id']}:{step}",
                "provenance": {"source_id": member["id"], "group_id": member["group_id"],
                               "partition": member["partition"], "source_sha256": member["source_sha256"],
                               "step": step, "gold_calls": len(calls), "target_kind": target["action"],
                               "target_origin": origin},
                "input": planner_input(prepared, observations), "target": target}

    rows, exclusions = [], []
    for step, call in enumerate(calls):
        row_value = converted(step, {"action": "call", "name": call["name"], "arguments": call["arguments"]},
                              "gold_call")
        evidence = _evidence(row_value["input"])
        if not all(_grounded(reference, evidence)
                   for reference in _reference_values(call["arguments"], tools[call["name"]]["parameters"])):
            exclusions.append(_exclusion(member, Quarantine(
                "ungrounded_reference", "A reference argument is absent from the visible prefix; review the "
                "sample", step, call["name"])))
            continue
        rows.append(row_value)
    if not (calls and _terminal_wait(calls[-1], results[-1])):
        # Gold has no final prose; the declared neutral final response ends the trajectory.
        rows.append(converted(len(calls), {"action": "finish"}, "policy_finish"))
    return rows, exclusions


def leakage_audit(rows: list[JSON], source: JSON) -> int:
    """Independently re-check that each input is whitelisted and holds exactly the strict gold prefix."""
    if not rows:
        return 0
    calls, results = source["label"]["tool_calls"], source["label"]["tool_results"]
    for row in rows:
        step, value, target = row["provenance"]["step"], row["input"], row["target"]
        expected = [(c["name"], dumps(c["arguments"]), dumps(r)) for c, r in zip(calls[:step], results[:step])]
        actual = [(o["name"], dumps(o["arguments"]), dumps(o["result"])) for o in value["observations"]
                  if o["kind"] == "tool_result"]
        exact_target = (target == {"action": "finish"} and step == len(calls) if target["action"] == "finish"
                        else step < len(calls) and dumps(target) == dumps(
                            {"action": "call", "name": calls[step]["name"], "arguments": calls[step]["arguments"]}))
        if (set(value) != set(ALLOWED_INPUT_FIELDS) | {"observations"} or len(value["observations"]) != step
                or actual != expected or not exact_target):
            raise _export_invalid(f"Leakage audit failed for {row['row_id']}; the exporter is defective")
    return len(rows)


def token_labels(tokenizer, prompt: str, completion: str) -> tuple[list[int], list[int]]:
    """Input ids and labels that train only the final completion and its EOS.

    Raises ValueError when separate prompt/completion tokenization differs from the
    joined text, or when the completion does not end in exactly one EOS.
    """
    def ids(text):
        return list(tokenizer(text, add_special_tokens=False)["input_ids"])

    prompt_ids, completion_ids = ids(prompt), ids(completion)
    if ids(prompt + completion) != prompt_ids + completion_ids:
        raise ValueError("token_boundary_mismatch")
    eos = tokenizer.eos_token_id
    if not completion_ids or completion_ids[-1] != eos or eos in completion_ids[:-1]:
        raise ValueError("completion_eos_invalid")
    return prompt_ids + completion_ids, [IGNORE_INDEX] * len(prompt_ids) + completion_ids


def render_row(row: JSON, tokenizer, admits, *, system: str, limits: Limits) -> JSON:
    """The trainer-facing prompt/completion pair, rendered through the runtime path.

    Raises Quarantine for a target the inference grammar cannot generate, a template that
    does not extend the generation prompt with exactly that target, an inseparable
    token boundary, or a prompt/target over the runtime budgets.
    """
    value, target, step = row["input"], row["target"], row["provenance"]["step"]
    name = target.get("name")
    if target["action"] == "call":
        tool = next(tool for tool in value["available_tools"] if tool["name"] == name)
        target = target | {"arguments": grammar_ordered_arguments(tool, target["arguments"])}
    text = qwen_protocol.encode_decision(target)
    if not admits(value["available_tools"], text):
        raise Quarantine("grammar_rejected_target", "The native inference grammar cannot generate this gold "
                         "target; review it as schema-invalid gold", step, name)
    try:
        prompt = qwen_protocol.render_prompt(tokenizer, value, system=system)
        full = qwen_protocol.render_prompt(tokenizer, value, system=system, target=target)
    except Exception as exc:
        # A checkpoint template may reject unusual row content; exclude the row, not the export.
        raise Quarantine("template_render_failed", "The chat template cannot render this row", step,
                         name) from exc
    completion = text + tokenizer.eos_token
    if not full.startswith(prompt):
        raise Quarantine("template_prefix_mismatch", "The conversation ending in the target does not extend "
                         "the generation prompt", step, name)
    if not full[len(prompt):].startswith(completion):
        raise Quarantine("template_target_mismatch", "The chat template renders the target differently from "
                         "the grammar", step, name)
    try:
        input_ids, labels = token_labels(tokenizer, prompt, completion)
    except ValueError as exc:
        raise Quarantine(str(exc), "Prompt and completion tokens are not separable at the boundary", step,
                         name) from exc
    prompt_tokens = labels.count(IGNORE_INDEX)
    completion_tokens = len(input_ids) - prompt_tokens
    if prompt_tokens + limits.output_tokens > limits.context_tokens:
        raise Quarantine("context_overflow", f"{prompt_tokens} prompt tokens plus {limits.output_tokens} reserved "
                         f"output exceed {limits.context_tokens}", step, name)
    if completion_tokens > limits.output_tokens:
        raise Quarantine("target_overflow", f"{completion_tokens} target tokens exceed the "
                         f"{limits.output_tokens}-token output budget", step, name)
    try:
        decoded = qwen_protocol.decode_decision(
            tokenizer.decode(input_ids[prompt_tokens:], skip_special_tokens=True), limits.response_bytes)
        if dumps(decoded) != dumps(row["target"]):
            raise ValueError("Decoded decision differs from gold")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise Quarantine("target_decode_mismatch", "Decoding the completion tokens does not return the gold "
                         "decision", step, name) from exc
    return {"row_id": row["row_id"], "provenance": row["provenance"], "prompt": prompt, "completion": completion,
            "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
            "canonical_target": row["target"]}


def partition_audit(accepted: dict[str, list[JSON]], members: dict[str, JSON]) -> JSON:
    """Rows keep their source member's partition and group; no group feeds both sides."""
    groups = {}
    for side, rows in accepted.items():
        for row in rows:
            member = members.get(row["provenance"]["source_id"])
            if (member is None or member["partition"] != side or row["provenance"]["partition"] != side
                    or row["provenance"]["group_id"] != member["group_id"]):
                raise _export_invalid(f"Partition audit failed for {row['row_id']}")
        groups[side] = {row["provenance"]["group_id"] for row in rows}
    if groups.get("validation", set()) & groups["fit"]:
        raise _export_invalid("Partition audit failed: a group has rows on both sides")
    return {"groups": {side: len(ids) for side, ids in groups.items()}, "shared_groups": 0,
            "non_fit_rows_in_fit": 0}


def load_tokenizer(base_model: Path):
    """The base checkpoint's own tokenizer and chat template, offline."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise PipelineError("MODEL_UNAVAILABLE", "Export needs the inference extra (transformers, "
                            "lm-format-enforcer)", "export") from exc
    try:
        tokenizer = AutoTokenizer.from_pretrained(base_model, local_files_only=True, trust_remote_code=False)
    except Exception as exc:
        raise PipelineError("MODEL_UNAVAILABLE", "Cannot load the base model tokenizer", "export") from exc
    if not isinstance(getattr(tokenizer, "chat_template", None), str) or not tokenizer.eos_token:
        raise PipelineError("MODEL_UNAVAILABLE", "Native export requires the checkpoint chat template and EOS",
                            "export")
    return tokenizer


def native_grammar(tokenizer):
    from ..adapters.constrained import ActionConstraint

    return ActionConstraint(tokenizer).native_admits


def base_identity(path: Path, tokenizer) -> JSON:
    """Tokenizer/template/config identity of the base checkpoint; weights are verified by fit/merge."""
    files = sorted(p for p in path.iterdir()
                   if p.is_file() and p.suffix in {".json", ".jinja", ".txt", ".model", ".tiktoken"})
    return {"path": str(path), "snapshot": path.name, "files": {p.name: digest(p) for p in files},
            "weights_hashed": False, "tokenizer_class": type(tokenizer).__name__,
            "chat_template_sha256": hashlib.sha256(tokenizer.chat_template.encode()).hexdigest(),
            "eos_token": tokenizer.eos_token, "eos_token_id": tokenizer.eos_token_id}


def _length_stats(values: list[int]) -> JSON:
    if not values:
        return {"count": 0}
    ordered = sorted(values)

    def rank(fraction):
        # Nearest-rank percentile.
        return ordered[max(0, -int(-len(ordered) * fraction // 1) - 1)]

    return {"count": len(ordered), "min": ordered[0], "max": ordered[-1],
            "mean": round(sum(ordered) / len(ordered), 2), "p50": rank(0.5), "p95": rank(0.95)}


def _side_summary(rows: list[JSON]) -> JSON:
    per_sample = Counter(row["provenance"]["source_id"] for row in rows)
    targets = Counter(row["canonical_target"].get("name", "finish") for row in rows)
    return {"rows": len(rows), "samples": len(per_sample),
            "targets": {"calls": sum(n for name, n in targets.items() if name != "finish"),
                        "policy_finish": targets.get("finish", 0), "missing_info": targets.get(WAITING_TOOL, 0),
                        "by_tool": dict(sorted((k, v) for k, v in targets.items() if k != "finish"))},
            "rows_per_sample": {str(k): v for k, v in sorted(Counter(per_sample.values()).items())},
            "lengths": {"prompt_tokens": _length_stats([r["prompt_tokens"] for r in rows]),
                        "completion_tokens": _length_stats([r["completion_tokens"] for r in rows]),
                        "total_tokens": _length_stats([r["prompt_tokens"] + r["completion_tokens"] for r in rows])}}


def write_export(output: Path, files: dict[str, str]) -> None:
    """Stage every artifact, then publish into a freshly claimed output directory.

    `os.mkdir` claims the output path atomically and never replaces anything, including
    an empty directory created by another process. Files move in `files` order and the
    last one is the completion marker, so a directory without it is incomplete. On a
    failure the files this call published, and the directory itself, are removed.
    """
    staging = output.with_name(f".{output.name}.partial-{uuid.uuid4().hex}")
    published = []
    try:
        staging.mkdir(parents=True)
        for name, content in files.items():
            with (staging / name).open("x", encoding="utf-8", newline="\n") as stream:
                sync_write(stream, content)
        os.mkdir(output)
        try:
            for name in files:
                _publish_new_file(staging / name, output / name)
                published.append(output / name)
        except OSError:
            for path in published:
                path.unlink(missing_ok=True)
            try:
                # rmdir removes the directory only while it is empty, so others' files are never deleted.
                output.rmdir()
            except OSError:
                pass
            raise
    except FileExistsError as exc:
        raise _export_invalid("Export output already exists; exports are immutable") from exc
    except OSError as exc:
        raise PipelineError("OUTPUT_IO", "Cannot write the export", "export") from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def export(data_root: Path, partition_path: Path, base_model: Path, output: Path, *,
           validation_diagnostics: bool = False, limits: Limits | None = None,
           tokenizer=None, admits=None) -> JSON:
    """Audited fit-only native prompt/completion rows plus exclusions and a manifest.

    Validation rows are written only on request, to a separate teacher-forced diagnostic
    file. `tokenizer`/`admits` default to the base checkpoint's tokenizer and the
    inference grammar; tests may inject doubles.
    """
    data_root, partition_path, output = (Path(p).resolve() for p in (data_root, partition_path, output))
    base_model = model_directory(Path(base_model))
    limits = limits or Limits()
    if output.exists():
        raise _export_invalid("Export output already exists; exports are immutable")
    if output.is_relative_to(data_root) or output.is_relative_to(base_model):
        raise _export_invalid("Export output must be outside the organizer data root and the base model")
    rows, dataset_sha256, catalog, catalog_sha256 = read_train(data_root)
    specs = validate_catalog(catalog)
    try:
        partition_bytes = partition_path.read_bytes()
        partition = loads(partition_bytes.decode("utf-8"))
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        raise _export_invalid("Partition manifest is unreadable or invalid") from exc
    members = validate_partition_manifest(partition)
    if partition["dataset_sha256"] != dataset_sha256 or partition.get("catalog_sha256") != catalog_sha256:
        raise _export_invalid("Partition manifest belongs to a different Train dataset or catalog revision")
    by_id = {}
    for row in rows:
        sample_id = safe_id(row.get("id"))
        if sample_id in by_id:
            raise _export_invalid("Train records have duplicate IDs")
        by_id[sample_id] = row
    if set(by_id) != set(members):
        raise _export_invalid("Partition members and Train IDs differ")
    for sample_id, member in members.items():
        if hashlib.sha256(dumps(by_id[sample_id]).encode("utf-8")).hexdigest() != member["source_sha256"]:
            raise _export_invalid(f"{sample_id} changed since partitioning")
    if tokenizer is None:
        tokenizer = load_tokenizer(base_model)
    if admits is None:
        admits = native_grammar(tokenizer)
    profile = protocol_profile(resolve_profile("baseline"), qwen_protocol.PROTOCOL)

    sides = ("fit", "validation") if validation_diagnostics else ("fit",)
    accepted = {side: [] for side in sides}
    exclusions, leakage_checked, rendered_checked = [], 0, 0
    for sample_id in sorted(members):
        member = members[sample_id]
        if member["partition"] not in sides:
            continue
        converted, excluded = gold_rows(by_id[sample_id], member, specs, data_root)
        exclusions += excluded
        leakage_checked += leakage_audit(converted, by_id[sample_id])
        for row in converted:
            rendered_checked += 1
            try:
                accepted[member["partition"]].append(
                    render_row(row, tokenizer, admits, system=profile["system"], limits=limits))
            except Quarantine as error:
                exclusions.append(_exclusion(member, error) | {"row_id": row["row_id"]})
    partition_check = partition_audit(accepted, members)
    reasons = dict(sorted(Counter(item["reason"] for item in exclusions).items()))
    if not accepted["fit"]:
        raise _export_invalid(f"No fit row passed the export audits; exclusions by reason: {reasons}")

    uses = {"fit": "fit", "validation": "teacher_forced_diagnostic"}
    contents = {EXPORT_FILES[side]: "".join(dumps(row | {"use": uses[side]}) + "\n" for row in accepted[side])
                for side in sides}
    contents["exclusions.jsonl"] = "".join(dumps(item) + "\n" for item in exclusions)
    fit_ids = {sample_id for sample_id, m in members.items() if m["partition"] == "fit"}
    accepted_rows = sum(len(side_rows) for side_rows in accepted.values())
    manifest = {
        "export_schema_version": EXPORT_SCHEMA_VERSION,
        "exporter": {"version": EXPORTER_VERSION, "conversion": CONVERSION_VERSION,
                     "code_sha256": hashlib.sha256(dumps(code_identity()).encode()).hexdigest()},
        "protocol": {"protocol": qwen_protocol.PROTOCOL, "prompt": profile_identity(profile),
                     "final_text": NATIVE_FINISH_TEXT, "constraint_schema": "lifemate-native-tool-call-v1",
                     "target_key_order": "grammar order: a branch's required keys first, then schema order",
                     "observation_arguments": "canonical sorted-key JSON, as the runner re-reads executed calls"},
        "source": {"dataset_sha256": dataset_sha256, "catalog_sha256": catalog_sha256,
                   "catalog_version": catalog["schema_version"], "input_mode": "transcript"},
        "partition": {"path": str(partition_path), "sha256": hashlib.sha256(partition_bytes).hexdigest(),
                      "grouping_method": partition["grouping_method"], "seed": partition.get("seed"),
                      "fit_samples": len(fit_ids), "validation_samples": len(members) - len(fit_ids),
                      "validation_diagnostics_exported": validation_diagnostics},
        "base_model": base_identity(base_model, tokenizer),
        "budgets": {"context_tokens": limits.context_tokens, "output_tokens": limits.output_tokens,
                    "response_bytes": limits.response_bytes,
                    "rule": "prompt tokens + reserved output <= context; target tokens <= output"},
        "supervision": {"loss": "completion only: the final target text and its EOS; every prompt token is "
                                "labelled ignore_index", "ignore_index": IGNORE_INDEX, "packing": False,
                        "weighting": "ordinary row-level completion NLL; a sample yields one row per accepted "
                                     "gold call plus its finish, so long trajectories weigh more",
                        "finish_target": "policy_finish: the declared neutral final text, not gold prose",
                        "augmentation": None},
        "rows": {side: _side_summary(accepted[side]) for side in sides},
        "exclusions": {"total": len(exclusions), "by_reason": reasons,
                       "by_tool": dict(sorted(Counter(item["target_name"] for item in exclusions
                                                      if item["target_name"]).items())),
                       "fit_samples_with_exclusions": len({item["source_id"] for item in exclusions
                                                           if item["partition"] == "fit"}),
                       "fit_samples_without_rows": len(fit_ids - {r["provenance"]["source_id"]
                                                                  for r in accepted["fit"]})},
        "audits": {"leakage": {"rows_checked": leakage_checked, "failures": 0},
                   "rendering_and_masks": {"rows_checked": rendered_checked, "accepted": accepted_rows,
                                           "quarantined": rendered_checked - accepted_rows},
                   "partition": partition_check},
        "files": {name: {"sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                         "rows": content.count("\n")} for name, content in contents.items()},
        "limitations": list(EXPORT_LIMITATIONS),
    }
    # Published last: a directory without the manifest is an incomplete export.
    contents["export_manifest.json"] = dumps(manifest) + "\n"
    write_export(output, contents)
    return manifest
