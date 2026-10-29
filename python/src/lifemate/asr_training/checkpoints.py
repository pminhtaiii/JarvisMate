"""Checksummed adapter/optimizer/RNG checkpoints; resume is always explicit."""
from __future__ import annotations

from pathlib import Path
import random
import uuid

from .storage import read, write, seal, verify


def rng_state(torch, np) -> dict:
    numpy = np.random.get_state()
    return {"python": random.getstate(), "numpy": [numpy[0], numpy[1].tolist(), *numpy[2:]],
            "torch": torch.get_rng_state().tolist(),
            "cuda": [s.tolist() for s in torch.cuda.get_rng_state_all()] if torch.cuda.is_available() else []}


def restore_rng(value: dict, torch, np) -> None:
    def tuples(item):
        return tuple(tuples(v) for v in item) if isinstance(item, list) else item
    random.setstate(tuples(value["python"]))
    numpy = value["numpy"]
    np.random.set_state((numpy[0], np.asarray(numpy[1], dtype="uint32"), *numpy[2:]))
    torch.set_rng_state(torch.tensor(value["torch"], dtype=torch.uint8))
    if value["cuda"]:
        if not torch.cuda.is_available() or len(value["cuda"]) != torch.cuda.device_count():
            raise ValueError("Checkpoint CUDA RNG topology differs")
        torch.cuda.set_rng_state_all([torch.tensor(s, dtype=torch.uint8) for s in value["cuda"]])


def save(directory: Path, model, optimizer, scheduler, scaler, state: dict, binding: dict,
         torch, np) -> Path:
    path = directory / f"step-{state['step']:08d}-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=False)
    model.save_pretrained(path / "adapter", safe_serialization=True, save_embedding_layers=False)
    torch.save({"optimizer": optimizer.state_dict(), "scheduler": scheduler.state_dict(),
                "scaler": scaler.state_dict()}, path / "optimizer.pt")
    write(path / "state.json", {"binding": binding, "training": state, "rng": rng_state(torch, np)})
    seal(path)
    write(directory.parent / "latest-checkpoint.json", {"path": str(path), "step": state["step"]})
    return path


def load(path: Path, expected: dict) -> dict:
    verify(path)
    state = read(path / "state.json")
    if state["binding"] != expected:
        raise ValueError("Resume rejected: model/split/config/code/environment/GPU binding changed")
    return state


def restore(path: Path, expected: dict, optimizer, scheduler, scaler, torch, np) -> dict:
    state = load(path, expected)
    payload = torch.load(path / "optimizer.pt", map_location="cpu", weights_only=True)
    optimizer.load_state_dict(payload["optimizer"])
    scheduler.load_state_dict(payload["scheduler"])
    scaler.load_state_dict(payload["scaler"])
    restore_rng(state["rng"], torch, np)
    return state["training"]
