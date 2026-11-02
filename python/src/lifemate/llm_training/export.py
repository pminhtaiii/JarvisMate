"""Selected adapter -> merged FP16 offline export; fresh-process verification is separate."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from ..jsonio import contained
from .storage import (file_hash, new_directory, read_json, seal, verify_seal, write_json)
from .tokenization import proof_binding


def export_model(config, suite_dir: Path, run_dir: Path, checkpoint: Path):
    from .resources import validate_lock
    validate_lock(config)
    from .checkpoints import load
    from .model_identity import snapshot_identity
    from .corpus import load_suite
    from .acceptance import evaluation_readiness
    loaded = load_suite(suite_dir)
    evaluation_readiness(config, suite_dir, teacher_forced=True)
    if not run_dir.resolve().is_relative_to(suite_dir.resolve()) or not checkpoint.resolve().is_relative_to(suite_dir.resolve()):
        raise ValueError("Run/checkpoint must belong to the selected suite")
    verify_seal(run_dir)
    training = read_json(run_dir / "manifest.json")
    if training.get("status") != "completed_full_budget" or training.get("completed_updates") != 500:
        raise ValueError("Export candidate requires the full declared training budget")
    state = load(checkpoint, training["binding"], allow_exhausted=True)
    best = training["best"]
    if (state["training"]["step"] != best["step"]
            or state["training"]["history"][-1].get("clean_G_nll") != best["nll"]):
        raise ValueError("Export must use the common NLL-selected checkpoint")
    base = snapshot_identity(config.require("model_dir"))
    directory = new_directory(suite_dir / "exports", training["experiment"])
    model_path = directory / "model"
    try:
        from .resources import checked_packages
        checked_packages()
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import PeftModel
        model = AutoModelForCausalLM.from_pretrained(config.require("model_dir"), local_files_only=True,
                    trust_remote_code=False, dtype=torch.float16, device_map={"": "cpu"}, weights_only=True)
        logical = sum(p.numel() for p in model.parameters())
        if logical != 4_022_468_096:
            raise ValueError("Base logical size differs")
        model = PeftModel.from_pretrained(model, checkpoint / "adapter", local_files_only=True, is_trainable=False)
        merged = model.merge_and_unload(safe_merge=True)
        merged.save_pretrained(model_path, safe_serialization=True)
        tokenizer = AutoTokenizer.from_pretrained(config.require("model_dir"), local_files_only=True, trust_remote_code=False)
        tokenizer.save_pretrained(model_path)
        # Keep licensing and tokenizer/template identity together with the model.
        import shutil
        shutil.copyfile(config.require("model_dir") / "LICENSE", model_path / "LICENSE")
        write_json(model_path / "native-format-contract.json", {"binding": proof_binding(config.paths["model_dir"]),
                   "suite_seal": loaded["seal"]["identity"]})
        files = {p.relative_to(model_path).as_posix(): file_hash(p) for p in model_path.iterdir() if p.is_file()}
        manifest = {"schema": "lifemate-native-export-v1", "status": "exported_pending_verification",
                    "experiment": training["experiment"], "training_status": training["status"], "base": base,
                    "checkpoint_identity": verify_seal(checkpoint)["identity"], "checkpoint_step": best["step"],
                    "suite_seal": loaded["seal"]["identity"], "logical_parameters": logical,
                    "representation": "merged_fp16", "training_method": training["model"]["method"],
                    "dtype": "float16", "model_files": files, "native_binding": proof_binding(config.paths["model_dir"]),
                    "training_binding": training["binding"], "checkpoint_selection": "common_clean_G_NLL_earliest_tie"}
        write_json(directory / "export-manifest.json", manifest)
        seal(directory, ["export-manifest.json", *["model/" + n for n in files]])
        return {"status": "exported_pending_verification", "directory": str(directory)}
    except Exception as exc:
        write_json(directory / "failure.json", {"status": "export_failed", "error": type(exc).__name__})
        raise


def export_identity(directory: Path, config, suite_dir: Path, *, require_verified=True):
    from .corpus import load_suite
    verify_seal(directory)
    manifest = read_json(directory / "export-manifest.json")
    if (manifest.get("schema") != "lifemate-native-export-v1" or manifest.get("representation") != "merged_fp16"
            or manifest.get("training_status") != "completed_full_budget"
            or manifest.get("logical_parameters") != 4_022_468_096
            or manifest.get("native_binding") != proof_binding(config.paths["model_dir"])
            or manifest.get("suite_seal") != load_suite(suite_dir)["seal"]["identity"]):
        raise ValueError("Export native/checkpoint/size identity mismatch")
    required = {"config.json", "tokenizer_config.json", "tokenizer.json", "LICENSE", "native-format-contract.json"}
    if not required <= manifest.get("model_files", {}).keys() or not any(
            name.endswith(".safetensors") for name in manifest["model_files"]):
        raise ValueError("Export is missing complete local model/tokenizer/native assets")
    for name, expected in manifest["model_files"].items():
        if file_hash(contained(directory / "model", name)) != expected:
            raise ValueError("Export asset changed")
    result = {"identity": verify_seal(directory)["identity"], "export_status": "unverified",
              "training_status": manifest["training_status"], "experiment": manifest["experiment"],
              "checkpoint_identity": manifest["checkpoint_identity"], "logical_parameters": manifest["logical_parameters"],
              "base": manifest["base"], "training_binding": manifest["training_binding"]}
    if require_verified:
        checks = sorted((suite_dir / "export-verifications").glob("*/reload-check.json"))
        matching = []
        for path in checks:
            verify_seal(path.parent)
            record = read_json(path)
            workers = [read_json(path.parent / f"worker-{i}.json") for i in (1, 2)] if all(
                (path.parent / f"worker-{i}.json").is_file() for i in (1, 2)) else []
            if record.get("export_identity") == result["identity"] and record.get("status") == "passed" \
                    and record.get("binding") == proof_binding(config.paths["model_dir"]) \
                    and record.get("verification_code_sha256") == file_hash(Path(__file__)) \
                    and record.get("independent_reloads") == 2 and record.get("child_exits") == [0, 0] \
                    and len(workers) == 2 and all(w.get("status") == "passed" and w.get("network_blocked") is True
                        and w.get("logical_parameters") == 4_022_468_096 for w in workers) \
                    and workers[0].get("semantic_output_sha256") == workers[1].get("semantic_output_sha256"):
                matching.append(record)
        if not matching:
            raise ValueError("Fresh offline native export verification required")
        result["export_status"] = "verified"
    return result


def verify_export(config, suite_dir: Path, directory: Path, *, device="cuda"):
    identity = export_identity(directory, config, suite_dir, require_verified=False)
    result_dir = new_directory(suite_dir / "export-verifications", directory.name)
    # The child has no networking capability through adapters: offline flags and local_files_only.
    env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1")
    results, exit_codes = [], []
    for index in (1, 2):
        worker_path = result_dir / f"worker-{index}.json"
        completed = subprocess.run([sys.executable, "-m", "lifemate.llm_training.export", "--model", str(directory / "model"),
                       "--output", str(worker_path), "--device", device], env=env, capture_output=True, timeout=900)
        exit_codes.append(completed.returncode)
        results.append(read_json(worker_path) if worker_path.exists() else {"status": "failed", "reason": "worker_failed"})
    result = dict(results[0])
    result.update(export_identity=identity["identity"], binding=proof_binding(config.paths["model_dir"]),
                  child_exits=exit_codes, independent_reloads=2, verification_code_sha256=file_hash(Path(__file__)),
                  network="socket outbound blocked + HF offline/local_files_only; Docker acceptance separate")
    if (any(exit_codes) or any(r.get("status") != "passed" for r in results)
            or results[0].get("semantic_output_sha256") != results[1].get("semantic_output_sha256")):
        result["status"] = "failed"
    write_json(result_dir / "reload-check.json", result)
    seal(result_dir, [p.name for p in result_dir.iterdir() if p.is_file()])
    return result | {"directory": str(result_dir)}


def worker():
    import socket
    class OfflineSocket(socket.socket):
        def connect(self, *_):
            raise OSError("Export verification is offline")
        def connect_ex(self, *_):
            raise OSError("Export verification is offline")
        def sendto(self, *_):
            raise OSError("Export verification is offline")
    socket.socket = OfflineSocket
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), required=True)
    args = parser.parse_args()
    from ..adapters.planner import LocalPlanner
    from .evaluation import limits
    from ..native_tools import adapt_tools
    from ..prompting import SYSTEM
    from .data import load_catalog
    from .config import content_hash
    try:
        planner = LocalPlanner(args.model, args.device, limits())
        if planner.metadata["parameter_count"] != 4_022_468_096:
            raise ValueError("Merged logical count mismatch")
        _, specs = load_catalog(Path(__file__).resolve().parents[4] / "tools/train_tools_catalog.json")
        tools, _ = adapt_tools([specs["sys.ask_missing_info"]])
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Không cần làm gì."}]
        first = planner.generate_native(messages, tools, 300.)
        second = planner.generate_native(messages, tools, 300.)
        if first.kind == "rejected" or second.kind == "rejected" or first.internal() != second.internal():
            raise ValueError("Offline repeatability/native parser/EOS failure")
        write_json(args.output, {"status": "passed", "logical_parameters": planner.metadata["parameter_count"],
                                "semantic_output_sha256": content_hash(first.internal()), "metadata": planner.metadata,
                                "network_blocked": True})
        return 0
    except Exception as exc:
        write_json(args.output, {"status": "failed", "reason": type(exc).__name__})
        return 1


if __name__ == "__main__":
    raise SystemExit(worker())
