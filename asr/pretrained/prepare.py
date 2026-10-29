"""Explicit online preparation. Benchmark code never calls these functions."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import re

from lifemate.jsonio import digest, dumps, loads, visible_path
from lifemate.model_budget import check_budget

from .models import REGISTRY, local_spec, offline, packages

CUTOFF = datetime(2026, 10, 26, tzinfo=timezone.utc)


def asset_hashes(path: Path) -> dict:
    result = {}
    for file in sorted(path.rglob("*")):
        visible_path(file)
        if (file.is_file() and ".cache" not in file.relative_to(path).parts
                and file.name not in {"provenance.json", ".provenance.json.tmp"}):
            result[file.relative_to(path).as_posix()] = digest(file)
    return result


def write_provenance(target: Path, provenance: dict) -> None:
    pending = target / ".provenance.json.tmp"
    pending.write_text(dumps(provenance) + "\n", encoding="utf-8")
    pending.replace(target / "provenance.json")


def model_details(target: Path) -> tuple[int, dict]:
    """Inspect the source architecture without loading checkpoint weights."""
    import torch
    from transformers import WhisperConfig, WhisperForConditionalGeneration

    config = WhisperConfig.from_pretrained(target, local_files_only=True)
    with torch.device("meta"):
        model = WhisperForConditionalGeneration(config)
    count = sum(p.numel() for p in model.parameters())
    check_budget(count)
    generation_path = target / "generation_config.json"
    generation = loads(generation_path.read_text(encoding="utf-8")) if generation_path.is_file() else config.to_dict()
    return count, generation


def source_snapshot(name: str, models_dir: Path, revision: str) -> Path:
    from huggingface_hub import HfApi, snapshot_download

    source, engine = REGISTRY[name]
    target = models_dir / name
    visible_path(target)
    if (target / "provenance.json").is_file():
        existing = local_spec(name, models_dir)
        if revision != "main" and existing["provenance"]["revision"] != revision:
            raise ValueError(f"Existing {name} has a different revision; use another --models-dir")
        return target
    # A failure after download leaves valid Hub-managed files but no provenance.
    # Pin the completed config's commit and let snapshot_download reuse its cache.
    cached_revision = None
    cache_metadata = target / ".cache/huggingface/download/config.json.metadata"
    if cache_metadata.is_file():
        visible_path(cache_metadata)
        lines = cache_metadata.read_text(encoding="utf-8").splitlines()
        if lines and re.fullmatch(r"[0-9a-f]{40}", lines[0]):
            cached_revision = lines[0]
    api = HfApi()
    resolved_revision = cached_revision if revision == "main" and cached_revision else revision
    info = api.model_info(source, revision=resolved_revision)
    if cached_revision and info.sha != cached_revision:
        raise ValueError(f"Partial {name} belongs to another revision; use another --models-dir")
    if target.exists():
        print(f"Resuming {name}@{info.sha}; reusing cached downloads", flush=True)
    commit = next(c for c in api.list_repo_commits(source, revision=info.sha) if c.commit_id == info.sha)
    if commit.created_at >= CUTOFF:
        raise ValueError(f"{source}@{info.sha} is dated after the release cutoff; supply an older --revision")
    files = {f.rfilename for f in info.siblings}
    weights = "*.safetensors" if any(f.endswith(".safetensors") for f in files) else "pytorch_model*.bin"
    snapshot_download(source, revision=info.sha, local_dir=target,
                      allow_patterns=[weights, "*.json", "*.txt", "*.model", "*.tiktoken", "README.md", "LICENSE*"])
    count, generation = model_details(target)
    provenance = {"source": source, "revision": info.sha, "engine": engine,
                  "commit_date": commit.created_at.isoformat(), "release_cutoff_utc": CUTOFF.isoformat(),
                  "license_from_model_card": (info.card_data or {}).get("license"),
                  "eligibility_note": "Commit date/license metadata recorded; verify final organizer requirements",
                  "parameter_count": count, "parameter_count_method": "source architecture on meta device",
                  "generation_defaults": {k: generation.get(k) for k in ("suppress_tokens", "begin_suppress_tokens")},
                  "assets": asset_hashes(target), "packages": packages()}
    write_provenance(target, provenance)
    return target


def convert_small(models_dir: Path) -> Path:
    source = local_spec("whisper-small", models_dir)
    target = models_dir / "whisper-small-ct2"
    if target.exists():
        existing = local_spec("whisper-small-ct2", models_dir)
        if existing["provenance"].get("source_assets") != source["provenance"]["assets"]:
            raise ValueError("Existing CT2 conversion is from a different source snapshot")
        return target
    offline()
    from ctranslate2.converters import TransformersConverter

    converter = TransformersConverter(source["path"],
                                      copy_files=["tokenizer.json", "preprocessor_config.json"],
                                      trust_remote_code=False)
    converter.convert(str(target), quantization="float32")
    provenance = {**source["provenance"], "engine": "faster-whisper",
                  "source_assets": source["provenance"]["assets"],
                  "conversion": {"api": "ctranslate2.converters.TransformersConverter",
                                 "source": source["path"], "quantization": "float32",
                                 "copy_files": ["tokenizer.json", "preprocessor_config.json"]},
                  "assets": asset_hashes(target), "packages": packages()}
    write_provenance(target, provenance)
    return target


def prepare_models(names: list[str], models_dir: Path, revision: str = "main") -> None:
    # Online access is confined to this explicitly requested command.
    os.environ.pop("HF_HUB_OFFLINE", None)
    os.environ.pop("TRANSFORMERS_OFFLINE", None)
    os.environ["HF_HOME"] = str(models_dir / ".hf-cache")
    models_dir.mkdir(parents=True, exist_ok=True)
    sources = list(dict.fromkeys("whisper-small" if n == "whisper-small-ct2" else n for n in names))
    for name in sources:
        print(f"Preparing {name} (explicit download)", flush=True)
        source_snapshot(name, models_dir, revision)
    if "whisper-small-ct2" in names:
        print("Converting the same Whisper-small snapshot to CTranslate2", flush=True)
        convert_small(models_dir)
