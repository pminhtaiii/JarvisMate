"""Durable adapter/state checkpoints; explicit compatible remaining-budget resume."""
from __future__ import annotations

import os
import random
import uuid
from pathlib import Path

from ..jsonio import contained
from .storage import file_hash, read_json, seal, verify_seal, write_json


def rng_state(torch, np):
    n = np.random.get_state()
    return {"python": random.getstate(), "numpy": [n[0], n[1].tolist(), *n[2:]],
            "torch": torch.get_rng_state().tolist(),
            "cuda": [s.tolist() for s in torch.cuda.get_rng_state_all()] if torch.cuda.is_initialized() else []}


def restore_rng(state, torch, np):
    def tuples(x):
        return tuple(map(tuples, x)) if isinstance(x, list) else x
    random.setstate(tuples(state["python"]))
    n = state["numpy"]
    np.random.set_state((n[0], np.asarray(n[1], dtype="uint32"), *n[2:]))
    torch.set_rng_state(torch.tensor(state["torch"], dtype=torch.uint8))
    if state["cuda"]:
        if len(state["cuda"]) != torch.cuda.device_count():
            raise ValueError("CUDA RNG topology changed")
        torch.cuda.set_rng_state_all([torch.tensor(s, dtype=torch.uint8) for s in state["cuda"]])


def checkpoint_key(nll, step):
    import math
    if type(nll) not in (int, float) or not math.isfinite(nll):
        raise ValueError("Checkpoint selection requires finite common clean-G NLL")
    return nll, step


def save(parent: Path, model, optimizer, scheduler, scaler, state, binding, torch, np):
    parent.mkdir(parents=True, exist_ok=True)
    path = parent / f"step-{state['step']:06d}"
    if path.exists():
        raise ValueError("Checkpoint already exists")
    stage = parent / (".pending-" + uuid.uuid4().hex)
    stage.mkdir()
    model.save_pretrained(stage / "adapter", safe_serialization=True, save_embedding_layers=False)
    torch.save({"optimizer": optimizer.state_dict(), "scheduler": scheduler.state_dict(),
                "scaler": scaler.state_dict()}, stage / "optimizer.pt")
    write_json(stage / "state.json", {"schema": "lifemate-llm-checkpoint-v1", "kind": "training",
               "binding": binding, "training": state, "rng": rng_state(torch, np)})
    files = [p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file()]
    record = seal(stage, files)
    os.rename(stage, path)
    write_json(parent.parent / "latest.json", {"checkpoint": path.relative_to(parent.parent).as_posix(),
               "identity": record["identity"], "step": state["step"]}, exclusive=False)
    return path


def load(path: Path, binding: dict, *, allow_exhausted=False):
    verify_seal(path)
    state = read_json(path / "state.json")
    if state.get("schema") != "lifemate-llm-checkpoint-v1" or state.get("kind") != "training" or state.get("binding") != binding:
        raise ValueError("Corrupt/probe/cross-experiment/config/environment checkpoint rejected")
    training = state["training"]
    if (type(training.get("step")) is not int or not 0 < training["step"] <= binding["settings"]["max_updates"]
            or training.get("remaining_updates") != binding["settings"]["max_updates"] - training["step"]
            or (training["remaining_updates"] <= 0 and not allow_exhausted)):
        raise ValueError("Invalid/exhausted remaining budget")
    return state


def restore(path, binding, model, optimizer, scheduler, scaler, torch, np):
    state = load(path, binding)
    from peft import set_peft_model_state_dict
    from safetensors.torch import load_file
    adapter = contained(path, "adapter/adapter_model.safetensors")
    result = set_peft_model_state_dict(model, load_file(str(adapter)))
    if getattr(result, "unexpected_keys", []):
        raise ValueError("Unexpected adapter state")
    payload = torch.load(path / "optimizer.pt", map_location="cpu", weights_only=True)
    optimizer.load_state_dict(payload["optimizer"])
    scheduler.load_state_dict(payload["scheduler"])
    scaler.load_state_dict(payload["scaler"])
    restore_rng(state["rng"], torch, np)
    return state["training"]
