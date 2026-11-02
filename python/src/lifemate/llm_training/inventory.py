"""Model-free phase-specific resource inventory and training preflight (LL005).

Hashes visible source/model/cache files only; never imports model libraries,
allocates GPU memory, enumerates environment directories or reads audio content.
Optional ASR resources never block clean preparation.
"""
from __future__ import annotations

from pathlib import Path

from ..jsonio import digest, loads, visible_path
from ..contracts import PipelineError
from .config import CATALOG_SHA256, DATASET_SHA256, EXPERIMENTS, SPLIT_IDENTITY, SuiteConfig, content_hash
from .corpus import PreparationError, load_suite, sealed_policy
from .storage import read_json, source_provenance
from .tokenization import tokenizer_identity, verify_proof

PHASES = {
    "transfer": ("source", "dataset", "catalog", "split_manifest", "weights", "tokenizer", "environment_lock"),
    "prepare": ("source", "dataset", "catalog", "split_manifest", "runtime_validator", "decoder_proof"),
    "decoder-poc": ("source", "catalog", "tokenizer"),
    "token-audit": ("source", "suite", "tokenizer"),
    "evaluate-G": ("source", "suite", "selection_policy", "dataset", "runtime", "weights", "tokenizer"),
    "evaluate-A": ("source", "suite", "selection_policy", "dataset", "runtime", "weights", "tokenizer",
                   "asr_export", "validation_asr_cache"),
    "pilot": ("source", "suite", "dataset", "audio", "weights", "tokenizer", "asr_export"),
    "train": ("source", "suite", "weights", "tokenizer", "token_audit", "environment_lock"),
    "compare": ("source", "suite", "selection_policy"),
}
ALL_RESOURCES = ("source", "dataset", "catalog", "audio", "split_manifest", "runtime", "runtime_validator",
                 "weights", "tokenizer", "asr_export", "fit_asr_cache", "validation_asr_cache",
                 "decoder_proof", "selection_policy", "suite", "token_audit", "environment_lock")


def _entry(status: str, **detail) -> dict:
    return {"status": status, **detail}


def _file(path: Path | None, expected: str | None = None) -> dict:
    if path is None:
        return _entry("not_configured")
    if not path.is_file():
        return _entry("missing")
    actual = digest(path)
    return _entry("present" if expected in (None, actual) else "mismatch", sha256=actual, expected_sha256=expected)


def _weights(model_dir: Path | None, hash_weights: bool) -> dict:
    if model_dir is None or not (model_dir / "config.json").is_file():
        return _entry("missing")
    index = model_dir / "model.safetensors.index.json"
    if index.is_file():
        visible_path(index)
        shards = sorted(set(loads(index.read_text(encoding="utf-8")).get("weight_map", {}).values()))
    else:
        shards = ["model.safetensors"]
    files = {}
    for name in shards:
        path = model_dir / name
        if not path.is_file():
            return _entry("missing", missing_shard=name)
        files[name] = {"bytes": path.stat().st_size, "sha256": digest(path) if hash_weights else None}
    config = loads((model_dir / "config.json").read_text(encoding="utf-8"))
    ok = config.get("model_type") == "qwen3" and "Qwen3ForCausalLM" in config.get("architectures", [])
    return _entry("present" if ok else "mismatch", shards=files, hashes="sha256" if hash_weights else "deferred",
                  model_type=config.get("model_type"), architectures=config.get("architectures"))


def resource_report(config: SuiteConfig, phase: str, *, suite_dir: Path | None = None,
                    hash_weights: bool = True) -> dict:
    if phase not in PHASES:
        raise ValueError("Unknown inventory phase")
    paths = config.paths
    data = paths["data_root"] / "train" if paths["data_root"] else None
    required = set(PHASES[phase])
    report: dict[str, dict] = {}
    for name in ALL_RESOURCES:
        if name not in required and name in {"weights", "suite", "token_audit"}:
            report[name] = _entry("not_required")  # Avoid hashing large/derived resources needlessly.
            continue
        if name == "source":
            report[name] = _entry("present", **source_provenance(config.project_root))
        elif name == "dataset":
            report[name] = _file(data / "train.jsonl" if data else None, DATASET_SHA256)
        elif name == "catalog":
            report[name] = _file(data / "train_tools_catalog.json" if data else None, CATALOG_SHA256)
        elif name == "audio":
            # Existence only: text-only phases never read audio content.
            report[name] = _entry("present" if data and (data / "audio").is_dir() else "missing", enumerated=False)
        elif name == "split_manifest":
            entry = _file(paths["split_manifest"])
            if entry["status"] == "present":
                manifest = loads(paths["split_manifest"].read_text(encoding="utf-8"))
                body = {k: v for k, v in manifest.items() if k != "identity"}
                if manifest.get("identity") != SPLIT_IDENTITY or content_hash(body) != SPLIT_IDENTITY:
                    entry["status"] = "mismatch"
            report[name] = entry
        elif name in {"runtime", "runtime_validator"}:
            target = paths["runtime_dir"] / ("__init__.py" if name == "runtime" else "validate.py")
            report[name] = _file(target)
        elif name == "weights":
            if hash_weights:
                from .model_identity import snapshot_identity
                try:
                    identity = snapshot_identity(paths["model_dir"])
                    report[name] = _entry("present", identity=identity)
                except (ValueError, OSError, PipelineError) as exc:
                    report[name] = _entry("missing", reason=str(exc)[:200])
            else:
                report[name] = _entry("unverified", reason="weight hashes explicitly skipped; not readiness evidence")
        elif name == "tokenizer":
            identity = tokenizer_identity(paths["model_dir"])
            report[name] = (_entry("present", **identity) if identity and "tokenizer_config.json" in identity["files"]
                            else _entry("missing"))
        elif name == "asr_export":
            directory = paths["asr_model_dir"]
            report[name] = (_entry("not_configured") if directory is None else
                            _entry("present", config_sha256=digest(directory / "config.json"))
                            if (directory / "config.json").is_file() else _entry("missing"))
        elif name in {"fit_asr_cache", "validation_asr_cache"}:
            report[name] = _file(paths[name])
        elif name == "decoder_proof":
            proof = verify_proof(paths["native_decoder_proof"], paths["model_dir"])
            report[name] = _entry("present" if proof["status"] == "passed" else "missing", proof=proof)
        elif name == "selection_policy":
            report[name] = _policy(suite_dir)
        elif name == "suite":
            report[name] = _suite(suite_dir)
        elif name == "token_audit":
            try:
                from .acceptance import accepted_corpus
                corpus = accepted_corpus(config, suite_dir)
                report[name] = _entry("present", identity=corpus["identity"], support=corpus["report"]["accepted_support"])
            except (ValueError, OSError, TypeError) as exc:
                report[name] = _entry("missing", reason=str(exc)[:200])
        elif name == "environment_lock":
            lock = paths.get("environment_lock")
            report[name] = _file(lock)
            if report[name]["status"] == "present":
                manifest_path = lock.with_suffix(".manifest.json")
                if not manifest_path.is_file():
                    report[name] = _entry("missing", reason="platform lock manifest is required")
                else:
                    manifest = read_json(manifest_path)
                    if manifest.get("profile") != config.source["environment_profile"] or manifest.get("lock_sha256") != digest(lock):
                        report[name] = _entry("mismatch", reason="platform lock profile/hash mismatch")
    for name, entry in report.items():
        entry["required"] = name in required
    blocking = sorted(n for n, e in report.items() if e["required"] and e["status"] not in {"present"})
    return {"schema": "lifemate-llm-resource-inventory-v1", "phase": phase,
            "status": "ready" if not blocking else "blocked", "blocking": blocking,
            "portable_paths": config.portable, "resources": report,
            "model_libraries_imported": False}


def _suite(suite_dir: Path | None) -> dict:
    if suite_dir is None:
        return _entry("not_configured")
    try:
        loaded = load_suite(suite_dir)
        return _entry("present", suite_id=loaded["suite"]["suite_id"], seal=loaded["seal"]["identity"])
    except PreparationError as exc:
        return _entry("missing", reason=exc.reason)


def _policy(suite_dir: Path | None) -> dict:
    if suite_dir is None:
        return _entry("not_configured")
    try:
        record = sealed_policy(suite_dir)
        return _entry("present", policy_sha256=record["policy_sha256"], sealed_at=record["sealed_at"])
    except (PreparationError, OSError) as exc:
        return _entry("missing", reason=str(exc))


def _token_audit(suite_dir: Path | None) -> dict:
    if suite_dir is None:
        return _entry("not_configured")
    audits = sorted((suite_dir / "token-audits").glob("*/token-audit.json"))
    for path in reversed(audits):
        record = read_json(path)
        if record.get("status") == "passed" and record.get("scope") == "clean":
            return _entry("present", audit=path.parent.name)
    return _entry("missing", reason="no passed clean token audit")


def preflight(config: SuiteConfig, suite_dir: Path, experiment: str, *, settings_path=None, policy_report=None) -> dict:
    """Training readiness for one experiment; L0 has no training phase."""
    if experiment not in EXPERIMENTS:
        raise ValueError("Unknown experiment")
    if not EXPERIMENTS[experiment]["trainable"]:
        return {"status": "failed_preflight", "experiment": experiment,
                "reason": "L0 is the pretrained baseline and cannot be trained"}
    report = resource_report(config, "train", suite_dir=suite_dir, hash_weights=True)
    missing = list(report["blocking"])
    try:
        from .acceptance import evaluation_readiness, accepted_corpus
        from .qualification import verify_qualification
        from .trainer import training_settings
        evaluation_readiness(config, suite_dir, teacher_forced=True)
        settings = training_settings(settings_path or config.project_root / "fine-tune-llm/configs/training.json")
        verify_qualification(config.require("resource_qualification"), accepted_corpus(config, suite_dir), settings, config)
        decision = read_json(config.require("latency_decision"))
        if not decision.get("operator") or decision.get("decision") not in {"pilot_reviewed", "proceed_with_unresolved_audio_latency"}:
            missing.append("explicit_operator_latency_decision")
    except (ValueError, OSError) as exc:
        missing.append(str(exc))
    if experiment == "L3":
        try:
            from .trainer import l3_dependencies
            l3_dependencies(suite_dir, policy_report, accepted_corpus(config, suite_dir), config=config)
        except (ValueError, OSError) as exc:
            missing.append(str(exc))
    return {"status": "blocked_dependency" if missing else "ready", "experiment": experiment, "missing": missing,
            "inventory": report, "model_libraries_imported": False}
