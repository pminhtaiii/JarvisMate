"""Offline pinned-snapshot verification, including actual weight bytes (F6)."""
from pathlib import Path
import hashlib
import re
import math

from ..jsonio import contained
from .config import BASE_MODEL
from .storage import file_hash, ordered_hash, read_json
from .tokenization import tokenizer_identity


def weight_files(directory: Path) -> list[str]:
    index = directory / "model.safetensors.index.json"
    if index.is_file():
        mapping = read_json(index).get("weight_map")
        if not isinstance(mapping, dict) or not mapping:
            raise ValueError("Empty/malformed safetensors weight index")
        names = sorted(set(mapping.values()))
    else:
        names = ["model.safetensors"]
    for name in names:
        if not isinstance(name, str) or not name.endswith(".safetensors"):
            raise ValueError("Unsupported weight shard")
        contained(directory, name)
    return names


def logical_parameters(directory: Path) -> int:
    """Count actual unquantized safetensors header shapes, never packed NF4 storage."""
    total = 0
    seen = set()
    for name in weight_files(directory):
        path = contained(directory, name)
        with path.open("rb") as stream:
            length = int.from_bytes(stream.read(8), "little")
            if not 0 < length <= 16 * 1024 * 1024:
                raise ValueError("Safetensors header length invalid")
            from ..jsonio import loads
            header = loads(stream.read(length).decode("utf-8"))
        for key, tensor in header.items():
            if key == "__metadata__":
                continue
            shape = tensor.get("shape")
            if key in seen or not isinstance(shape, list) or any(type(n) is not int or n < 0 for n in shape):
                raise ValueError("Invalid/duplicate safetensors logical tensor")
            seen.add(key)
            total += math.prod(shape)
    if total <= 0:
        raise ValueError("No logical base tensors")
    return total


def snapshot_identity(directory: Path, *, weights: bool = True) -> dict:
    """Verify an acquisition manifest or HF download metadata against the pinned revision.

    snapshot-manifest.json is an operator-provided transfer manifest with base_model,
    files (relative name -> SHA256), license and release provenance. It is never
    synthesized from an arbitrary model directory and called pretrained evidence.
    """
    config = read_json(directory / "config.json")
    if config.get("model_type") != "qwen3" or config.get("architectures") != ["Qwen3ForCausalLM"]:
        raise ValueError("Pinned Qwen3ForCausalLM architecture required")
    tok = tokenizer_identity(directory)
    if not tok or not {"tokenizer.json", "tokenizer_config.json", "config.json", "LICENSE"} <= tok["files"].keys():
        raise ValueError("Incomplete tokenizer/config/license")
    names = list(tok["files"])
    if weights:
        names += weight_files(directory)
        if (directory / "model.safetensors.index.json").exists():
            names.append("model.safetensors.index.json")
    actual = {name: file_hash(contained(directory, name)) for name in names}
    manifest_path = directory / "snapshot-manifest.json"
    if manifest_path.is_file():
        manifest = read_json(manifest_path)
        if (manifest.get("schema") != "lifemate-pinned-snapshot-v1" or manifest.get("base_model") != BASE_MODEL
                or not manifest.get("license") or not manifest.get("release_provenance")
                or any(manifest.get("files", {}).get(n) != h for n, h in actual.items())):
            raise ValueError("Snapshot provenance/revision/file hashes mismatch")
        provenance = {"manifest_sha256": file_hash(manifest_path)}
    else:
        metadata_hashes = {}
        for name, sha in actual.items():
            path = directory / ".cache" / "huggingface" / "download" / (name + ".metadata")
            lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
            if len(lines) < 2 or lines[0] != BASE_MODEL["revision"]:
                raise ValueError("Pinned acquisition/transfer metadata required")
            etag = lines[1].strip('"')
            if len(etag) == 64:
                verified = etag == sha
            elif re.fullmatch("[0-9a-f]{40}", etag):
                data = contained(directory, name).read_bytes()
                verified = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == etag
            else:
                verified = False
            if not verified:
                raise ValueError(f"Acquisition hash mismatch: {name}")
            metadata_hashes[name] = file_hash(path)
        provenance = {"hf_download_metadata": metadata_hashes, "repository": BASE_MODEL["id"]}
    body = {"base_model": BASE_MODEL, "files": actual, "tokenizer": tok, "provenance": provenance,
            "logical_parameters": logical_parameters(directory) if weights else None}
    return body | {"identity": ordered_hash(body), "verified_weights": weights,
                   "training_status": "pretrained" if weights else "not_loaded"}
