"""Standalone merged FP16 planner export and its offline reload verification.

The selection file is a claim, not evidence: its update is recomputed from committed
checkpoints and a replay of their coverage before anything merges. The merged snapshot
must reload where the training libraries are absent, as in the inference environment.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable
from pathlib import Path

from ..adapters.qwen_native import FINISH_TEXT, PROTOCOL, completion_text, parse_completion, render_prompt, validate_template
from ..artifacts import atomic_json
from ..configuration import ModelSettings, inspect_snapshot
from ..contracts import JSON, PipelineError
from ..jsonio import dumps, read_json
from . import SELECTION_MODES, SftConfig
from .data import ReadyExport, base_identity, encode_row, load_ready_export
from .training import TrainPlan, checkpoint_path, read_candidates, select_for

# Copied verbatim so the export serves the exact tokenizer, template and generation settings.
COPIED_FILES = ("tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt", "added_tokens.json",
                "special_tokens_map.json", "chat_template.jinja", "generation_config.json")
TRAINING_MODULES = ("peft", "bitsandbytes", "accelerate")
RELOAD_TIMEOUT_SECONDS = 1800


def failure(message: str, code: str = "SFT_EXPORT") -> PipelineError:
    return PipelineError(code, message, "sft_export")


def verify_selection(config: SftConfig, ready: ReadyExport, selection_path: Path, *,
                     plan: TrainPlan | None = None) -> tuple[JSON, Path]:
    """Recompute the selection from committed checkpoints; reject anything it does not reproduce."""
    plan = plan or TrainPlan()
    selection = read_json(selection_path, "SFT_IDENTITY")
    if not isinstance(selection, dict) or selection.get("status") != "selected":
        raise failure("Selection did not choose a checkpoint", "SFT_SELECTION")
    identity = selection.get("identity")
    if not isinstance(identity, dict):
        raise failure("Selection has no run identity", "SFT_IDENTITY")
    # Selections from before selection modes existed were all lowest-validation-NLL.
    if selection.get("mode", SELECTION_MODES["separate"]) != config.selection_mode:
        raise failure(f"Selection mode differs from this configuration's {config.selection_mode}", "SFT_SELECTION")
    # Packages and GPU may legitimately differ on the merging host; run-defining inputs may not.
    if (identity.get("config_identity") != config.identity()
            or identity.get("export_manifest_sha256") != ready.manifest_sha256
            or identity.get("plan") != plan.identity()):
        raise failure("Selection belongs to a different configuration, export or plan", "SFT_IDENTITY")
    base = base_identity(config, hash_files=True)
    if identity.get("base_files_sha256") != base["files_sha256"]:
        raise failure("Base snapshot differs from the trained base", "SFT_IDENTITY")
    row_sources = [row["provenance"]["source_id"] for row in ready.train]
    states = read_candidates(config.experiment_dir, plan, row_sources, identity, config.validation_mode)
    recomputed = select_for(config.validation_mode, states, plan)
    if recomputed["status"] != "selected":
        raise failure("No fully covered finite-NLL checkpoint exists" if config.validated
                      else f"The update-{plan.updates} checkpoint lacks full row/source coverage", "SFT_SELECTION")
    if (recomputed["selected_update"] != selection.get("selected_update")
            or recomputed["adapter_sha256"] != selection.get("adapter_sha256")):
        raise failure("Selection does not match the eligible checkpoint its evidence produces", "SFT_SELECTION")
    state = next(s for s in states if s["update"] == recomputed["selected_update"])
    return state | {"base": base}, checkpoint_path(config.experiment_dir, state["update"]) / "adapter"


def merge_snapshot(base_path: Path, adapter: Path, target: Path) -> JSON:
    """Merge into a fresh unquantized base at full precision, then store finite FP16 weights."""
    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM
    except ImportError as exc:
        raise PipelineError("MODEL_UNAVAILABLE", "Merging needs the training extra", "sft_export") from exc
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    base = AutoModelForCausalLM.from_pretrained(base_path, dtype=torch.float32, local_files_only=True,
                                                trust_remote_code=False, weights_only=True)
    merged = PeftModel.from_pretrained(base, adapter, is_trainable=False).merge_and_unload(safe_merge=True)
    names = [name for name, _ in merged.named_parameters()]
    if any("lora_" in name for name in names):
        raise failure("Adapter weights remain after merging")
    merged = merged.half()
    if not all(bool(torch.isfinite(parameter).all()) for parameter in merged.parameters()):
        raise failure("FP16 conversion produced a nonfinite weight")
    merged.config.use_cache = True
    merged.save_pretrained(target, safe_serialization=True)
    return {"parameter_count": sum(p.numel() for p in merged.parameters()), "dtype": "float16"}


def run_export(config: SftConfig, selection_path: Path, *, plan: TrainPlan | None = None,
               merge: Callable[[Path, Path, Path], JSON] = merge_snapshot,
               verifier: Callable[[Path], JSON] | None = None) -> JSON:
    ready = load_ready_export(config)
    state, adapter = verify_selection(config, ready, selection_path, plan=plan)
    target = config.experiment_dir / "merged_fp16"
    if target.exists():
        raise failure("merged_fp16 already exists; move it aside to export again")
    stage = config.experiment_dir / f".merged-{uuid.uuid4().hex}"
    stage.mkdir(parents=True)
    try:
        merged = merge(config.base_path, adapter, stage)
        for name in COPIED_FILES:
            if (config.base_path / name).is_file():
                shutil.copyfile(config.base_path / name, stage / name)
        settings = ModelSettings("qwen3", stage, config.device, "float16", protocol=PROTOCOL,
                                 context_tokens=config.context_tokens, max_new_tokens=config.max_new_tokens)
        snapshot = inspect_snapshot(settings, planner=True)
        if snapshot["template_sha256"] != state["base"]["template_sha256"]:
            raise failure("Merged template differs from the base template")
        if merged["parameter_count"] >= 5_000_000_000:
            raise failure("Merged planner must have fewer than 5B parameters")
        os.replace(stage, target)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    manifest = {"state": "merged", "protocol": PROTOCOL, "validation_mode": config.validation_mode,
                "selection_mode": config.selection_mode, "selected_update": state["update"],
                "adapter_sha256": state["adapter_sha256"], "base_files_sha256": state["base"]["files_sha256"],
                "base_revision": config.revision, "export_manifest_sha256": ready.manifest_sha256,
                "dtype": merged["dtype"], "parameter_count": merged["parameter_count"],
                "template_sha256": snapshot["template_sha256"]}
    if config.validated:
        manifest |= {"validation_nll": state["validation_nll"],
                     "note": "Validation NLL is a teacher-forced diagnostic, not a competition score"}
    else:
        manifest["note"] = ("Final update chosen without a validation set; no held-out metric exists, "
                            "and this is not a quality or competition score")
    manifest_path = config.experiment_dir / "export_manifest.json"
    atomic_json(manifest_path, manifest)
    report = (verifier or verify_reload_subprocess)(target)
    manifest |= {"state": "reload_verified", "reload": report}
    atomic_json(manifest_path, manifest)
    return {"stage": "export", "state": manifest["state"], "selected_update": state["update"],
            "merged": target.as_posix(), "parameter_count": merged["parameter_count"]}


# --- Reload verification: runs in a process without the training libraries --------

def protocol_cases() -> list[tuple[JSON, list[JSON], JSON]]:
    """Lookup, dependent call, clarification and finish through the real template."""
    tool = {"name": "contacts.search", "description": "Tìm", "parameters": {
        "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}
    send = {"name": "sms.send", "description": "Gửi", "parameters": {
        "type": "object", "properties": {"contact_id": {"type": "string"}}, "required": ["contact_id"]}}
    ask = {"name": "sys.ask_missing_info", "description": "Hỏi", "parameters": {
        "type": "object", "properties": {"tool_name": {"type": "string"}, "params": {"type": "array", "items": {"type": "string"}}},
        "required": ["tool_name", "params"]}}
    prepared = {"request": "Nhắn Lân", "context": {}, "history": [], "available_tools": [tool, send, ask]}
    lookup = {"name": "contacts.search", "arguments": {"query": "Lân"}}
    found = {**lookup, "result": {"ok": True, "contacts": [{"id": "c_07"}]}}
    return [(prepared, [], {"action": "call", **lookup}),
            (prepared, [found], {"action": "call", "name": "sms.send", "arguments": {"contact_id": "c_07"}}),
            (prepared, [found], {"action": "call", "name": "sys.ask_missing_info",
                                 "arguments": {"tool_name": "sms.send", "params": ["content"]}}),
            (prepared, [found], {"action": "finish"})]


def verify_reload(path: Path) -> JSON:
    """Offline reload and native protocol checks on the merged snapshot itself."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True, trust_remote_code=False)
    template = validate_template(tokenizer)
    if tokenizer.decode(tokenizer(FINISH_TEXT, add_special_tokens=False)["input_ids"]) != FINISH_TEXT:
        raise failure("Finish text does not round trip")
    for prepared, observations, action in protocol_cases():
        eligible = {tool["name"] for tool in prepared["available_tools"]}
        render_prompt(tokenizer, prepared, observations)
        body = tokenizer(completion_text(action), add_special_tokens=False)["input_ids"]
        if parse_completion(tokenizer.decode(body), eligible) != action:
            raise failure("Native action does not survive the merged tokenizer")
    model = AutoModelForCausalLM.from_pretrained(path, dtype=torch.float16, local_files_only=True, trust_remote_code=False,
                                                 weights_only=True)
    model.eval()
    dtypes = {str(p.dtype) for p in model.parameters()}
    if dtypes != {"torch.float16"}:
        raise failure(f"Merged weights are not FP16: {sorted(dtypes)}"[:200])
    prompt = tokenizer(render_prompt(tokenizer, *protocol_cases()[0][:2]), return_tensors="pt", add_special_tokens=False)
    with torch.no_grad():
        logits = model(**prompt, use_cache=False, logits_to_keep=1).logits
    if not bool(torch.isfinite(logits).all()):
        raise failure("Merged model produces nonfinite logits")
    return {"template": template, "parameter_count": sum(p.numel() for p in model.parameters()),
            "protocol_cases": len(protocol_cases()), "training_modules_blocked": list(TRAINING_MODULES)}


def verify_reload_subprocess(path: Path) -> JSON:
    root = str(Path(__file__).resolve().parents[2])
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [root, os.environ.get("PYTHONPATH")])),
                   "PYTHONUTF8": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    try:
        done = subprocess.run([sys.executable, "-m", "lifemate.sft.export", "--verify", str(path)], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=RELOAD_TIMEOUT_SECONDS, env=environment)
    except (OSError, subprocess.SubprocessError) as exc:
        raise failure("Reload verification could not run") from exc
    if done.returncode != 0:
        raise failure(f"Reload verification failed: {done.stderr[-300:]}")
    return json.loads(done.stdout.strip().splitlines()[-1])


# --- Fixed-prompt drift diagnostics (T020) --------------------------------------

def _generate(torch, model, tokenizer, example: JSON, device, max_new_tokens: int) -> list[int]:
    prompt = torch.tensor([example["input_ids"][:example["prompt_tokens"]]], device=device)
    with torch.no_grad():
        output = model.generate(input_ids=prompt, attention_mask=torch.ones_like(prompt), do_sample=False, num_beams=1,
                                max_new_tokens=max_new_tokens, eos_token_id=tokenizer.eos_token_id,
                                pad_token_id=tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id)
    return [int(token) for token in output[0][example["prompt_tokens"]:]]


def _classify(tokenizer, generated: list[int], eligible: set[str]) -> str:
    body = generated[:-1] if generated and generated[-1] == tokenizer.eos_token_id else generated
    try:
        parse_completion(tokenizer.decode(body), eligible)
        return "valid" if len(body) < len(generated) else "no_eos"
    except ValueError:
        return "invalid"


def load_adapter_for_diagnostics(config: SftConfig, adapter: Path):
    """The selected adapter on its frozen NF4 base, as during training."""
    import torch
    import transformers
    from peft import PeftModel

    quantization = transformers.BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                   bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16)
    base = transformers.AutoModelForCausalLM.from_pretrained(
        config.base_path, quantization_config=quantization, dtype=torch.bfloat16, device_map={"": config.device},
        local_files_only=True, trust_remote_code=False)
    return PeftModel.from_pretrained(base, adapter, is_trainable=False).eval()


def load_merged_for_diagnostics(config: SftConfig, merged: Path):
    import torch
    import transformers

    return transformers.AutoModelForCausalLM.from_pretrained(
        merged, dtype=torch.float16, local_files_only=True, trust_remote_code=False).to(config.device).eval()


def run_diagnostics(config: SftConfig, selection_path: Path, *, count: int = 8, plan: TrainPlan | None = None,
                    adapter_loader=load_adapter_for_diagnostics, merged_loader=load_merged_for_diagnostics,
                    device: str | None = None) -> JSON:
    """Record drift between the selected adapter and its export; equivalence is never assumed."""
    if not config.validated:
        # Train prompts are not substituted: fitted rows would make the comparison look independent.
        raise failure("diagnose uses fixed validation prompts; validation_mode none has none, and Train prompts "
                      "are not substituted", "SFT_DIAGNOSTICS")
    import torch

    from .data import load_tokenizer

    ready = load_ready_export(config)
    state, adapter = verify_selection(config, ready, selection_path, plan=plan)
    merged_path = config.experiment_dir / "merged_fp16"
    if not merged_path.is_dir():
        raise failure("No merged export exists")
    device = device or config.device
    tokenizer = load_tokenizer(merged_path)
    rows = list(ready.validation[:count])
    examples = [encode_row(tokenizer, row, config.context_tokens, config.max_new_tokens) for row in rows]

    def outputs(model) -> list[list[int]]:
        result = [_generate(torch, model, tokenizer, example, device, config.max_new_tokens) for example in examples]
        del model
        if device.startswith("cuda"):
            torch.cuda.empty_cache()
        return result

    adapter_outputs = outputs(adapter_loader(config, adapter))
    merged_outputs = outputs(merged_loader(config, merged_path))
    records = []
    for row, one, two in zip(rows, adapter_outputs, merged_outputs):
        eligible = {tool["name"] for tool in row["input"]["available_tools"]}
        records.append({"source_id": row["provenance"]["source_id"], "decision_index": row["provenance"]["decision_index"],
                        "identical": one == two, "adapter": _classify(tokenizer, one, eligible),
                        "merged": _classify(tokenizer, two, eligible)})
    report = {"stage": "diagnose", "prompts": len(records), "identical": sum(r["identical"] for r in records),
              "merged_valid": sum(r["merged"] == "valid" for r in records), "records": records,
              "selected_update": state["update"], "note": "Unconstrained teacher-forced prompts; not a competition score"}
    atomic_json(config.experiment_dir / "export_diagnostics.json", report)
    return {key: report[key] for key in ("stage", "prompts", "identical", "merged_valid", "selected_update")}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a merged planner without training libraries")
    parser.add_argument("--verify", type=Path, required=True)
    arguments = parser.parse_args()
    for name in TRAINING_MODULES:
        sys.modules[name] = None  # Import fails, and Transformers reports the package as absent.
    try:
        print(dumps(verify_reload(arguments.verify)))
        return 0
    except PipelineError as exc:
        print(dumps(exc.record()), file=sys.stderr)
        return 1
    except Exception as exc:  # The parent records this bounded text as the reload failure.
        print(f"{type(exc).__name__}: {exc}"[:300], file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
