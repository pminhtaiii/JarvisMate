"""Merge a saved adapter onto its original base into a self-contained deployment checkpoint.

The merged directory loads through the existing `--planner-model` path, so inference
needs no PEFT or bitsandbytes. Tokenizer and template files are copied byte for byte,
which keeps the `planner-model` comparison factor's tokenizer identity unchanged.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import os
import shutil
import uuid
from pathlib import Path

from ..adapters import qwen_protocol
from ..adapters.common import model_directory
from ..artifacts import sync_write, utc_now
from ..contracts import JSON, PipelineError
from ..jsonio import digest, dumps, read_json
from ..prompting import NATIVE_FINISH_TEXT
from ..provenance import code_identity, model_identity
from ..reporting import TOKENIZER_FILE
from . import fit

MERGER_VERSION = "lifemate-native-sft-merge-v1"
EXPORT_MARKER = "lifemate_export.json"
ADAPTER_FILES = (fit.ADAPTER_CONFIG, fit.ADAPTER_WEIGHTS, fit.ADAPTER_PROVENANCE)


def _invalid(message: str) -> PipelineError:
    return PipelineError("INPUT_INVALID", message, "merge")


def adapter_provenance(adapter: Path) -> JSON:
    """The provenance of a complete checkpoint written by this trainer, with its weights verified."""
    if not adapter.is_dir() or not all((adapter / name).is_file() for name in ADAPTER_FILES):
        raise _invalid("The adapter must be a complete checkpoint directory written by the fit command")
    value = read_json(adapter / fit.ADAPTER_PROVENANCE)
    try:
        valid = (value["trainer"] == fit.TRAINER_VERSION
                 and value["protocol"]["protocol"] == qwen_protocol.PROTOCOL
                 and isinstance(value["base_model"]["files"], dict) and bool(value["base_model"]["files"])
                 and isinstance(value["adapter_sha256"], str) and isinstance(value["adapter_config_sha256"], str))
        same_prompt = (value["protocol"]["prompt"] == fit.native_prompt_identity()
                       and value["protocol"]["final_text"] == NATIVE_FINISH_TEXT)
    except (KeyError, TypeError) as exc:
        raise _invalid("The adapter provenance is incomplete") from exc
    if not valid:
        raise _invalid("The adapter was not trained by this trainer for the native protocol")
    if not same_prompt:
        raise _invalid("The adapter was trained with a different native prompt or final text than this revision")
    if digest(adapter / fit.ADAPTER_WEIGHTS) != value["adapter_sha256"]:
        raise _invalid("The adapter weights differ from their recorded provenance")
    if digest(adapter / fit.ADAPTER_CONFIG) != value["adapter_config_sha256"]:
        raise _invalid("The adapter configuration differs from its recorded provenance")
    return value


def tokenizer_files(path: Path) -> list[str]:
    """Relative names of the files that define tokenization and the chat template."""
    return sorted(name for name in (str(p.relative_to(path)).replace("\\", "/") for p in path.rglob("*")
                                    if p.is_file()) if TOKENIZER_FILE.search(name))


def merge(base_model: Path, adapter: Path, output: Path) -> JSON:
    """Verify the adapter's base, merge it in BF16 and write a reloaded, self-contained export.

    Refuses a different base, an existing output and an output inside the base or the
    adapter. Everything is written to a hidden staging directory beside `output`, which is
    renamed to `output` only after the completion marker is written. A failed merge removes
    the staging directory; a killed one leaves it, but never a partial checkpoint at `output`.
    """
    base = model_directory(Path(base_model))
    adapter, output = Path(adapter).resolve(), Path(output).resolve()
    if output.exists():
        raise _invalid("The merge output already exists; deployment exports are immutable")
    if output.is_relative_to(base) or output.is_relative_to(adapter):
        raise _invalid("The merge output must be outside the base model and the adapter")
    provenance = adapter_provenance(adapter)
    base_identity = model_identity(base)
    if base_identity["files"] != provenance["base_model"]["files"]:
        raise _invalid("The adapter was trained on a different base: weights, config or tokenizer files differ")
    torch, hf, peft = fit.libraries("lora")
    staging = output.with_name(f".{output.name}.partial-{uuid.uuid4().hex}")
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        os.mkdir(staging)
    except OSError as exc:
        raise PipelineError("OUTPUT_IO", "Cannot create the merge staging directory", "merge") from exc
    try:
        marker = _merge(torch, hf, peft, base, adapter, staging, provenance, base_identity)
        published = _invalid("The merge output already exists; deployment exports are immutable")
        if output.exists():
            raise published
        try:
            # Windows refuses an existing target; POSIX replaces at most an empty directory.
            os.rename(staging, output)
        except OSError as exc:
            if output.exists():
                raise published from exc
            raise PipelineError("OUTPUT_IO", "Cannot publish the merged export", "merge") from exc
        return marker
    except BaseException as exc:
        # The staging directory was created by this call; nothing else writes there.
        shutil.rmtree(staging, ignore_errors=True)
        if isinstance(exc, (PipelineError, KeyboardInterrupt)):
            raise
        raise PipelineError("MODEL_UNAVAILABLE", f"Merging failed with {type(exc).__name__}", "merge") from exc


def _merge(torch, hf, peft, base: Path, adapter: Path, output: Path, provenance: JSON, base_identity: JSON) -> JSON:
    options = {"local_files_only": True, "trust_remote_code": False, "dtype": torch.bfloat16, "weights_only": True}
    model = hf.AutoModelForCausalLM.from_pretrained(base, **options)
    if model.config.model_type != "qwen3":
        raise PipelineError("MODEL_UNAVAILABLE", "Merging requires the original Qwen3 checkpoint", "merge")
    base_parameters = model.num_parameters()
    merged = peft.PeftModel.from_pretrained(model, adapter, is_trainable=False).merge_and_unload()
    merged.eval()
    deployed_parameters = merged.num_parameters()
    if deployed_parameters >= fit.PARAMETER_LIMIT:
        raise PipelineError("MODEL_UNAVAILABLE", "The merged model exceeds the parameter budget", "merge")
    merged.save_pretrained(output, safe_serialization=True)
    copied = {}
    for name in tokenizer_files(base) + sorted(p.name for p in base.glob("LICENSE*") if p.is_file()):
        (output / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(base / name, output / name)
        copied[name] = digest(output / name)
        if copied[name] != digest(base / name):
            raise PipelineError("OUTPUT_IO", f"Copied {name} differs from the base", "merge")
    if tokenizer_files(output) != tokenizer_files(base):
        raise PipelineError("OUTPUT_IO", "The export's tokenizer files differ from the base's", "merge")

    reloaded = hf.AutoModelForCausalLM.from_pretrained(output, **options)
    expected, actual = merged.state_dict(), reloaded.state_dict()
    if set(expected) != set(actual) or not all(torch.equal(expected[k], actual[k]) for k in expected):
        raise PipelineError("OUTPUT_IO", "The reloaded export differs from the merged weights", "merge")
    tokenizer = hf.AutoTokenizer.from_pretrained(output, local_files_only=True, trust_remote_code=False)
    template = hashlib.sha256(str(getattr(tokenizer, "chat_template", "")).encode()).hexdigest()
    if template != provenance["base_model"]["chat_template_sha256"]:
        raise PipelineError("OUTPUT_IO", "The export's chat template differs from the training base", "merge")

    identity = model_identity(output)
    marker = {"schema_version": 1, "merger": MERGER_VERSION, "status": "completed", "finished_at": utc_now(),
              "state": "merged-export",
              "base_model": {"path": str(base), "files": base_identity["files"]},
              "adapter": {"path": str(adapter), "files": {name: digest(adapter / name) for name in ADAPTER_FILES},
                          "provenance": provenance},
              "protocol": provenance["protocol"], "chat_template_sha256": template,
              "tokenizer_class": type(tokenizer).__name__, "tokenizer_files_copied": copied,
              "dtype": "bfloat16", "reload_verified": True, "inference_verified": False,
              "parameters": {"base": base_parameters, "adapter_trainable": provenance.get("trainable_parameters"),
                             "deployed": deployed_parameters, "limit": fit.PARAMETER_LIMIT},
              "files": identity["files"],
              "packages": {name: importlib.metadata.version(name)
                           for name in ("torch", "transformers", "peft", "safetensors")},
              "code_sha256": hashlib.sha256(dumps(code_identity()).encode()).hexdigest(),
              "limitations": ["Merged from the original non-quantized base; a QLoRA adapter's merged weights are "
                              "not numerically identical to the quantized model it was trained with.",
                              "Reload is verified here; native inference and benchmark evaluation are separate "
                              "steps through `lifemate run --planner-model`."]}
    # Written last: a directory without it is not a completed export.
    with (output / EXPORT_MARKER).open("x", encoding="utf-8", newline="\n") as stream:
        sync_write(stream, dumps(marker) + "\n")
    return marker
