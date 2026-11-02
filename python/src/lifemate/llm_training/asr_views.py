"""Selected-ASR handoff, separated caches, full-prefix approval and one-view visits."""
from __future__ import annotations

import copy
import math
import random
import re
import unicodedata
from collections import Counter
from pathlib import Path

from ..contracts import PipelineError
from ..jsonio import contained
from .config import content_hash
from .data import base_messages, load_catalog, read_train, visible_source
from .storage import (file_hash, new_directory, ordered_hash, read_json, read_jsonl,
                      seal, verify_seal, write_json, write_jsonl)

ASR_HANDOFF = "lifemate-selected-asr-handoff-v1"
CACHE_SCHEMA = "lifemate-asr-turn-cache-v1"
VIEW_POLICY = "lifemate-asr-full-prefix-v1"
ASR_DECODING = {"language": "vi", "task": "transcribe", "do_sample": False, "num_beams": 1, "max_new_tokens": 440}


def validate_export(directory: Path, partition: dict) -> dict:
    """Explicit bridge from ASR selection/export evidence; a config alone is insufficient."""
    manifest = read_json(directory / "llm-handoff.json")
    required = {"schema", "base_model", "base_revision", "selected_experiment", "checkpoint_sha256", "processor_sha256",
                "selection", "training_source_ids", "split_identity", "files", "logical_parameters", "decoding"}
    if set(manifest) != required or manifest["schema"] != ASR_HANDOFF:
        raise ValueError("ASR handoff schema mismatch; supply the selected export handoff")
    trained = manifest["training_source_ids"]
    if (manifest["base_model"] != "vinai/PhoWhisper-large" or not isinstance(manifest["base_revision"], str)
            or not re.fullmatch("[0-9a-f]{40}", manifest["base_revision"])
            or manifest["selected_experiment"] not in {"E1", "E2", "E3", "E4"}
            or manifest["split_identity"] != partition["split_identity"] or not isinstance(trained, list) or not trained
            or len(trained) != len(set(trained)) or not set(trained) <= set(partition["fit_ids"])
            or set(trained) & set(partition["validation_ids"])):
        raise ValueError("Selected ASR must be fine-tuned on this Fit partition only")
    if (type(manifest["logical_parameters"]) is not int or manifest["logical_parameters"] <= 0
            or manifest["decoding"] != ASR_DECODING):
        raise ValueError("ASR logical size/decoding missing")
    for key in ("checkpoint_sha256", "processor_sha256"):
        if not isinstance(manifest[key], str) or not re.fullmatch("[0-9a-f]{64}", manifest[key]):
            raise ValueError("ASR checkpoint/processor identity missing")
    selection = manifest["selection"]
    if (not isinstance(selection, dict) or selection.get("experiment") != manifest["selected_experiment"]
            or selection.get("checkpoint_sha256") != manifest["checkpoint_sha256"]
            or not selection.get("policy_sha256") or not selection.get("evidence_sha256")):
        raise ValueError("ASR frozen selection evidence missing")
    files = manifest["files"]
    processor_names = {"preprocessor_config.json", "tokenizer_config.json", "vocab.json", "merges.txt"}
    if (not isinstance(files, dict) or not {"config.json", *processor_names} <= files.keys()
            or not any(n.endswith(".safetensors") for n in files)):
        raise ValueError("ASR export assets missing")
    for name, expected in files.items():
        if file_hash(contained(directory, name)) != expected:
            raise ValueError("ASR export file changed")
    processor_files = {name: expected for name, expected in files.items() if name in processor_names or
                       name in {"tokenizer.json", "special_tokens_map.json", "added_tokens.json", "normalizer.json"}}
    if manifest["processor_sha256"] != content_hash(processor_files):
        raise ValueError("ASR processor identity does not match actual assets")
    model_config = read_json(directory / "config.json")
    if (model_config.get("model_type") != "whisper" or model_config.get("d_model") != 1280
            or model_config.get("encoder_layers") != 32 or model_config.get("decoder_layers") != 32
            or "WhisperForConditionalGeneration" not in model_config.get("architectures", [])):
        raise ValueError("Selected ASR export must retain the PhoWhisper-large architecture")
    for field, hash_key in (("evidence_file", "evidence_sha256"), ("policy_file", "policy_sha256")):
        path = contained(directory, selection.get(field))
        if file_hash(path) != selection[hash_key]:
            raise ValueError("ASR selection/policy evidence file mismatch")
    evidence = read_json(contained(directory, selection["evidence_file"]))
    if (evidence.get("schema") != "lifemate-asr-selection-evidence-v1" or evidence.get("status") != "selected"
            or evidence.get("experiment") != manifest["selected_experiment"]
            or evidence.get("checkpoint_sha256") != manifest["checkpoint_sha256"]
            or evidence.get("policy_sha256") != selection["policy_sha256"]
            or evidence.get("fit_membership_sha256") != content_hash(sorted(trained))
            or evidence.get("export_files_sha256") != content_hash(files)):
        raise ValueError("ASR selection evidence does not bind this checkpoint/export/Fit membership")
    return manifest | {"identity": ordered_hash(manifest), "handoff_sha256": file_hash(directory / "llm-handoff.json")}


def expected_turns(source: dict) -> dict[str, str]:
    turns = {f"history:{i}": t["audio"] for i, t in enumerate(source.get("history", [])) if t["role"] == "user"}
    return turns | {"current": source["audio"]}


class CacheASR:
    """ASR protocol with exact source/turn/audio/hash binding and no gold fallback."""

    def __init__(self, cache: Path, config, partition: dict, *, kind="validation"):
        if kind not in {"fit", "validation"}:
            raise ValueError("Cache partition invalid")
        export = validate_export(config.require("asr_model_dir"), partition)
        manifest = read_json(cache.with_suffix(".manifest.json"))
        if (manifest.get("schema") != CACHE_SCHEMA or manifest.get("partition") != kind
                or manifest.get("split_identity") != partition["split_identity"]
                or manifest.get("export_identity") != export["identity"]
                or manifest.get("cache_sha256") != file_hash(cache) or not manifest.get("packages")):
            raise ValueError("Cache manifest/export/partition mismatch")
        data = config.require("data_root") / "train"
        sources = {s.id: s.record for s in read_train(data / "train.jsonl")}
        allowed = set(partition["fit_ids" if kind == "fit" else "validation_ids"])
        self.by_audio, self.turns = {}, {}
        for row in read_jsonl(cache):
            required = {"source_id", "group_id", "partition", "turn", "audio", "wav_sha256", "pcm_sha256",
                        "export_identity", "processor_sha256", "decoding_sha256", "status", "transcript", "elapsed"}
            if not isinstance(row, dict) or set(row) != required:
                raise ValueError("Cache turn schema mismatch")
            sid, turn = row["source_id"], row["turn"]
            if (sid not in allowed or row["partition"] != kind
                    or row["group_id"] != partition["sources"][sid]["group"]
                    or expected_turns(sources[sid]).get(turn) != row["audio"]
                    or row["export_identity"] != export["identity"]
                    or row["processor_sha256"] != export["processor_sha256"]
                    or row["decoding_sha256"] != content_hash(export["decoding"])):
                raise ValueError("Cache source/group/turn alignment mismatch")
            path = contained(data, row["audio"])
            if file_hash(path) != row["wav_sha256"]:
                raise ValueError("Cached audio changed")
            import wave
            import hashlib
            with wave.open(str(path), "rb") as wav:
                pcm = wav.readframes(wav.getnframes())
            if hashlib.sha256(pcm).hexdigest() != row["pcm_sha256"]:
                raise ValueError("PCM identity mismatch")
            if ((sid, turn) in self.turns or path in self.by_audio
                    or row["status"] not in {"ok", "failed"}
                    or (row["status"] == "ok" and (not isinstance(row["transcript"], str) or not row["transcript"].strip()))
                    or type(row["elapsed"]) not in (int, float) or not math.isfinite(row["elapsed"]) or row["elapsed"] < 0):
                raise ValueError("Duplicate/invalid cache turn")
            self.turns[sid, turn] = row
            self.by_audio[path] = row
        expected = {(sid, turn) for sid in allowed for turn in expected_turns(sources[sid])}
        if kind == "validation" and set(self.turns) != expected:
            raise ValueError("A evaluation needs complete current/history cache coverage")
        self.metadata = {"adapter": "fixed-cache-asr", "cache_sha256": file_hash(cache),
                         "manifest_sha256": file_hash(cache.with_suffix(".manifest.json")),
                         "export_identity": export["identity"], "partition": kind,
                         "parameter_count": export["logical_parameters"], "timing_scope": "cached_transcripts"}

    def transcribe(self, audio_path: Path, remaining_seconds: float) -> str:
        row = self.by_audio.get(audio_path.resolve())
        if remaining_seconds <= 0 or row is None or row["status"] != "ok" or file_hash(audio_path) != row["wav_sha256"]:
            raise PipelineError("ASSET_MISSING", "Missing/failed/mismatched ASR cache turn; no gold fallback", "asr")
        return row["transcript"]

    def project(self, source: dict) -> dict:
        result = {k: copy.deepcopy(source[k]) for k in ("id", "audio", "audio_text", "context", "history")}
        for turn, audio in expected_turns(source).items():
            row = self.turns.get((source["id"], turn))
            if row is None or row["status"] != "ok":
                raise PipelineError("ASSET_MISSING", "Incomplete ASR current/history projection", "asr")
            if turn == "current":
                result["audio_text"] = row["transcript"]
            else:
                result["history"][int(turn.split(":")[1])]["audio_text"] = row["transcript"]
        return result

    def project_row(self, row: dict, source: dict, specs: dict) -> dict:
        """Rebuild current/history before messages; retain the full original gold prefix."""
        clean_base = base_messages(visible_source(source, specs))
        noisy_base = base_messages(visible_source(self.project(source), specs))
        messages = row["input"]["messages"]
        if messages[:len(clean_base)] != clean_base:
            raise ValueError("Stored gold prefix does not match the source")
        result = copy.deepcopy(row)
        result["input"]["messages"] = noisy_base + copy.deepcopy(messages[len(clean_base):])
        return result


def surface(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def approve_view(clean: dict, noisy: dict, clean_texts: list[str], noisy_texts: list[str], review=None) -> dict:
    if clean["provenance"]["partition"] != "fit" or noisy["target"] != clean["target"] or noisy["input"]["tools"] != clean["input"]["tools"]:
        raise ValueError("Noisy views must retain Fit targets and tools")
    same = clean_texts == noisy_texts
    equivalent = len(clean_texts) == len(noisy_texts) and all(surface(a) == surface(b) for a, b in zip(clean_texts, noisy_texts))
    decision = "ACCEPT_EQUIVALENT" if equivalent else "NEEDS_REVIEW"
    category = "identical" if same else "unicode_whitespace" if equivalent else "unknown"
    if review is not None:
        if (review.get("schema") != "lifemate-asr-prefix-review-v1"
                or review.get("base_row_id") != clean["provenance"]["base_row_id"]
                or review.get("clean_sha256") != ordered_hash(clean) or review.get("noisy_sha256") != ordered_hash(noisy)
                or not review.get("reviewer") or not review.get("policy") or not review.get("evidence_paths")
                or not isinstance(review.get("affected_slots"), list)):
            raise ValueError("Noisy review certificate identity/evidence invalid")
        decision = review.get("decision")
        if decision not in {"ACCEPT_EQUIVALENT", "ACCEPT_UNAFFECTED_ROW", "REJECT_CHANGED_SEMANTICS", "NEEDS_REVIEW"}:
            raise ValueError("Unknown noisy decision")
        if decision.startswith("ACCEPT") and review.get("full_original_prefix_valid") is not True:
            raise ValueError("Acceptance requires the complete original prefix")
        category = review.get("difference_category", "unknown")
        if category not in {"identical", "unicode_whitespace", "non_surface_preserving", "semantic_change", "unknown"}:
            raise ValueError("Unknown noise category")
    return {"base_row_id": clean["provenance"]["base_row_id"], "source_id": clean["provenance"]["source_id"],
            "target_type": clean["target_type"], "tool": clean["target"].get("tool_calls", [{}])[0].get("function", {}).get("name"),
            "decision": decision, "status": "accepted" if decision.startswith("ACCEPT") else "needs_review" if decision == "NEEDS_REVIEW" else "quarantined",
            "category": category, "review": review, "policy": VIEW_POLICY}


def coverage_report(clean: list[dict], audits: list[dict], visits: list[dict] = ()) -> dict:
    by_type, by_tool = {}, {}
    approved = [a for a in audits if a["status"] == "accepted"]
    meaningful = {a["base_row_id"] for a in approved if a["category"] in {"non_surface_preserving", "semantic_change"}}
    for key, out in (("target_type", by_type), ("tool", by_tool)):
        names = {r["target_type"] if key == "target_type" else
                 r["target"].get("tool_calls", [{}])[0].get("function", {}).get("name") for r in clean}
        for name in names:
            bases = {r["provenance"]["base_row_id"] for r in clean if (r["target_type"] if key == "target_type" else
                     r["target"].get("tool_calls", [{}])[0].get("function", {}).get("name")) == name}
            selected = [a for a in audits if a[key] == name]
            passed = {a["base_row_id"] for a in selected if a["status"] == "accepted"}
            out[str(name)] = {"eligible": len(bases), "assessed": len(selected), "approved_bases": len(passed),
                              "approval_rate": len(passed) / len(selected) if selected else None,
                              "base_coverage": len(passed) / len(bases) if bases else None,
                              "meaningful": len(bases & meaningful)}
    threshold = max(32, math.ceil(.05 * len(clean)))
    realized = {}
    for key in ("target_type", "tool", "source_id"):
        groups = {}
        for visit in visits:
            group = str(visit.get(key))
            counts = groups.setdefault(group, {"clean": 0, "asr": 0})
            counts[visit["view"]] += 1
        for counts in groups.values():
            counts["noisy_ratio"] = counts["asr"] / (counts["clean"] + counts["asr"])
        realized[key] = groups
    noisy_visits = sum(v["view"] == "asr" for v in visits)
    return {"clean_bases": len(clean), "generated_assessed": len(audits), "approved_views": len(approved),
            "approved_bases": len({a["base_row_id"] for a in approved}),
            "approved_sources": len({a["source_id"] for a in approved}), "meaningful_bases": len(meaningful),
            "threshold": threshold, "limited_noisy_coverage": len(meaningful) < threshold or any(x["meaningful"] == 0 for x in by_type.values()),
            "by_type": by_type, "by_tool": by_tool, "status_counts": dict(Counter(a["status"] for a in audits)),
            "categories": dict(Counter(a["category"] for a in audits)),
            "visits": dict(Counter(v["view"] for v in visits)), "realized_noisy_ratio": noisy_visits / len(visits) if visits else None,
            "realized_by": realized, "fallback_reasons": dict(Counter(v.get("fallback_reason") for v in visits if v["view"] == "clean")),
            "cache_failures": sum(a.get("decision") == "REJECT_CACHE_OR_BUDGET" for a in audits),
            "decision_counts": dict(Counter(a["decision"] for a in audits)),
            "unassessed": len(clean) - len({a["base_row_id"] for a in audits})}


class ViewSampler:
    """Independent RNG; base permutation is owned by the trainer."""
    def __init__(self, approved: dict[str, list[dict]], seed=42, probability=.5):
        self.approved, self.rng, self.probability = approved, random.Random(seed), probability
        self.counts = Counter()

    def choose(self, clean):
        candidates = self.approved.get(clean["provenance"]["base_row_id"], [])
        noisy = self.rng.random() < self.probability
        selected = self.rng.choice(candidates) if candidates and noisy else clean
        view = "asr" if selected is not clean else "clean"
        reason = None if view == "asr" else "not_selected" if candidates else "no_approved_view"
        self.counts[view] += 1
        return selected, {"base_row_id": clean["provenance"]["base_row_id"], "view": view, "fallback_reason": reason}

    def state_dict(self):
        return {"rng": self.rng.getstate(), "counts": dict(self.counts), "probability": self.probability}

    def load_state_dict(self, state):
        def tuples(x):
            return tuple(map(tuples, x)) if isinstance(x, (list, tuple)) else x
        if state["probability"] != self.probability:
            raise ValueError("View probability changed")
        self.rng.setstate(tuples(state["rng"]))
        self.counts = Counter(state["counts"])


def build_views(config, suite_dir: Path, cache_path: Path, *, reviews_path=None) -> dict:
    from .acceptance import accepted_corpus
    from .corpus import load_suite
    loaded = load_suite(suite_dir)
    corpus = accepted_corpus(config, suite_dir)
    clean = [r for r in corpus["rows"] if r["provenance"]["partition"] == "fit"]
    asr = CacheASR(cache_path, config, loaded["partition"], kind="fit")
    sources = {s.id: s.record for s in read_train(config.require("data_root") / "train" / "train.jsonl")}
    _, specs = load_catalog(config.require("data_root") / "train" / "train_tools_catalog.json")
    reviews = {r["base_row_id"]: r for r in read_jsonl(reviews_path)} if reviews_path else {}
    views, audits = [], []
    for row in clean:
        source = sources[row["provenance"]["source_id"]]
        try:
            projected = asr.project(source)
            noisy = asr.project_row(row, source, specs)
            texts = lambda r: [t["audio_text"] for t in r["history"] if t["role"] == "user"] + [r["audio_text"]]
            audit = approve_view(row, noisy, texts(source), texts(projected), reviews.get(row["provenance"]["base_row_id"]))
        except PipelineError:
            audit = {"base_row_id": row["provenance"]["base_row_id"], "source_id": source["id"],
                     "target_type": row["target_type"], "tool": None, "status": "quarantined", "category": "unknown",
                     "decision": "REJECT_CACHE_OR_BUDGET"}
        audits.append(audit)
        if audit["status"] == "accepted":
            noisy["provenance"]["view"] = "asr"
            noisy["provenance"]["identities"]["asr_cache"] = asr.metadata["cache_sha256"]
            noisy["row_id"] = ordered_hash({k: v for k, v in noisy.items() if k != "row_id"})
            audit["row_id"], audit["row_sha256"] = noisy["row_id"], ordered_hash(noisy)
            views.append(noisy)
    directory = new_directory(suite_dir / "asr-views", "fit")
    write_jsonl(directory / "fit.asr-approved.jsonl", views)
    write_jsonl(directory / "asr-view-audit.jsonl", audits)
    write_json(directory / "coverage.json", coverage_report(clean, audits))
    write_json(directory / "manifest.json", {"schema": VIEW_POLICY, "cache": asr.metadata, "clean_corpus": corpus["identity"],
                                           "suite_seal": loaded["seal"]["identity"], "policy": VIEW_POLICY})
    seal(directory, ["fit.asr-approved.jsonl", "asr-view-audit.jsonl", "coverage.json", "manifest.json"])
    return {"status": "authored_views", "directory": str(directory), "approved": len(views), "assessed": len(audits),
            "next": "explicit token-audit --scope asr --view-dir required"}
