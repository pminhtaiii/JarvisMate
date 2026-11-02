"""Explicit early smoke versus accepted worst-corpus qualification; no automatic fallback."""
from pathlib import Path
import threading
import time

from .storage import file_hash, new_directory, read_json, read_jsonl, seal, verify_seal, write_json
from .config import content_hash
from .resources import GIB, cuda_memory, host_inventory


class MemoryMonitor:
    """NVML sampled device/process peaks, explicitly reported as observed samples."""
    def __init__(self):
        self.samples, self.error, self.stop_event = [], None, threading.Event()
        self.driver_model, self.own_pid_seen, self.device_uuid = None, False, None

    def start(self):
        try:
            import pynvml
            import os
            import torch
            pynvml.nvmlInit()
            self.nvml = pynvml
            uuid = str(torch.cuda.get_device_properties(0).uuid)
            self.device_uuid = uuid if uuid.startswith('GPU-') else 'GPU-'+uuid
            handle = pynvml.nvmlDeviceGetHandleByUUID(self.device_uuid)
            if os.name == 'nt':
                current,_ = pynvml.nvmlDeviceGetDriverModel(handle)
                self.driver_model = 'WDDM' if current == pynvml.NVML_DRIVER_WDDM else 'TCC'
            def sample():
                while not self.stop_event.is_set():
                    try:
                        m = pynvml.nvmlDeviceGetMemoryInfo(handle)
                        processes = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
                        self.own_pid_seen |= any(p.pid == os.getpid() for p in processes)
                        own = [p.usedGpuMemory for p in processes if p.pid == os.getpid() and p.usedGpuMemory is not None
                               and 0 <= p.usedGpuMemory <= m.total]
                        self.samples.append({"used": m.used, "free": m.free, "process": own[0] if own else None,
                                             "reserved":torch.cuda.memory_reserved()})
                    except Exception as exc:
                        self.error = type(exc).__name__
                        break
                    self.stop_event.wait(.05)
            self.thread = threading.Thread(target=sample, daemon=True)
            self.thread.start()
        except Exception as exc:
            self.error = type(exc).__name__

    def finish(self):
        self.stop_event.set()
        if hasattr(self, "thread"):
            self.thread.join(timeout=2)
            self.nvml.nvmlShutdown()
        return {"sampling_seconds": .05, "samples": len(self.samples), "error": self.error,
                "device_peak_observed_bytes": max((s["used"] for s in self.samples), default=None),
                "device_min_free_observed_bytes": min((s["free"] for s in self.samples), default=None),
                "process_peak_observed_bytes": max((s["process"] for s in self.samples if s["process"] is not None), default=None),
                "driver_model":self.driver_model,"own_pid_seen":self.own_pid_seen,"device_uuid":self.device_uuid,
                "process_peak_unavailable_reason": 'NVML_VALUE_NOT_AVAILABLE under Windows WDDM' if self.driver_model=='WDDM' else None,
                "device_non_torch_reserved_peak_observed_bytes":max(
                    (max(0,s['used']-s['reserved']) for s in self.samples),default=None),
                "non_torch_scope":"all other device usage/context/driver; not attributed per process",
                "scope": "sampled_nvml_peaks; unsampled transients are not exact peaks"}


def memory_acceptance(memory, nvml):
    """Keep device/cap headroom strict; WDDM unavailable residency stays null.

    The all-device observed peak conservatively bounds this process's physical
    residency, including every competing allocation. It is not a process metric.
    """
    def count(value):
        return type(value) is int and value >= 0
    issues=[]
    cap=memory.get('operating_cap_bytes')
    physical=memory.get('physical_bytes')
    reserved=memory.get('reserved_peak')
    peak=nvml.get('device_peak_observed_bytes')
    free=nvml.get('device_min_free_observed_bytes')
    if not all(count(x) for x in (cap,physical,reserved,peak,free)) or min(cap or 0,physical or 0)<=GIB:
        return {'passed':False,'issues':['missing_or_invalid_memory_values'],'evidence_mode':None}
    if cap!=min(12*GIB,physical) or reserved>cap-GIB:
        issues.append('allocator_cap_or_headroom')
    if peak>cap-GIB or free<GIB or peak>physical or free>physical:
        issues.append('whole_device_cap_or_headroom')
    if not count(nvml.get('samples')) or nvml['samples']<2 or nvml.get('error') is not None:
        issues.append('insufficient_device_samples')
    process=nvml.get('process_peak_observed_bytes')
    mode='native_process_and_device'
    if process is None:
        if nvml.get('driver_model')=='WDDM' and nvml.get('own_pid_seen') is True:
            mode='WDDM_conservative_whole_device_upper_bound'
        else:
            issues.append('process_evidence_unavailable_without_verified_WDDM_bound')
    elif not count(process) or process<=0 or process>physical:
        issues.append('invalid_process_measurement')
    return {'passed':not issues,'issues':issues,'evidence_mode':mode,
            'exact_process_peak_available':process is not None,
            'device_upper_bound_observed_bytes':peak,'headroom_required_bytes':GIB}


def qualification_binding(config, corpus, settings, *, include_asr=False):
    from ..provenance import code_identity
    from .model_identity import snapshot_identity
    env = host_inventory(config.project_root)
    from .acceptance import accepted_corpus
    from .resources import validate_lock
    noisy = accepted_corpus(config, corpus["directory"].parents[1], scope="asr")["identity"] if include_asr else None
    return {"settings": settings, "corpus": corpus["identity"], "noisy_corpus": noisy, "code": code_identity(),
            "environment_lock": validate_lock(config),
            "base": snapshot_identity(config.require("model_dir"))["identity"], "packages": env["packages"],
            "gpu": [{k: v for k, v in g.items() if k not in {"free", "allocation"}} for g in env["gpus"]]}


def verify_qualification(path: Path, corpus, settings, config):
    verify_seal(path.parent)
    report = read_json(path)
    if (report.get("schema") != "lifemate-native-resource-probe-v1" or report.get("scope") != "full"
            or report.get("status") != "passed" or report.get("updates", 0) < 5
            or report.get("binding") != qualification_binding(config, corpus, settings,
                    include_asr=report.get("binding", {}).get("noisy_corpus") is not None)
            or report.get("generation_verified") is not True or report.get("reload_verified") is not True):
        raise ValueError("Matching full worst-corpus qualification required; early smoke is insufficient")
    if not memory_acceptance(report.get('memory',{}),report.get('nvml',{}))['passed']:
        raise ValueError('Qualification memory evidence/cap/headroom is insufficient')
    return file_hash(path)


def probe(config, suite_dir: Path | None, settings, *, scope: str, smoke_fixtures: Path | None = None, include_asr=False):
    from .progress import Progress
    from .resources import validate_lock
    validate_lock(config)
    from .acceptance import accepted_corpus, evaluation_readiness
    from .tokenization import supervised
    if scope not in {"early", "full"}:
        raise ValueError("Probe scope must be early or full")
    corpus = None
    if scope == "full":
        if suite_dir is None:
            raise ValueError("Full probe requires a sealed accepted corpus")
        evaluation_readiness(config, suite_dir, teacher_forced=True)
        corpus = accepted_corpus(config, suite_dir)
        fit = [r for r in corpus["rows"] if r["provenance"]["partition"] == "fit"]
        by_id = {c["row_id"]: c for c in corpus["cache"]}
        if include_asr:
            noisy = accepted_corpus(config, suite_dir, scope="asr")
            fit += noisy["rows"]
            by_id.update({c["row_id"]: c for c in noisy["cache"]})
        selected = list({r["row_id"]: r for r in (
            max(fit, key=lambda r: by_id[r["row_id"]]["prompt_tokens"]),
            max(fit, key=lambda r: by_id[r["row_id"]]["completion_tokens"]),
            max(fit, key=lambda r: by_id[r["row_id"]]["total_tokens"]))}.values())
        binding = qualification_binding(config, corpus, settings, include_asr=include_asr)
    else:
        if include_asr:
            raise ValueError("--include-asr is a full accepted-corpus probe scope")
        if smoke_fixtures is None:
            raise ValueError("Early smoke requires explicitly declared short/long native fixtures")
        selected = read_jsonl(smoke_fixtures)
        if len(selected) < 2 or any(set(r) != {"input", "target", "target_type"} for r in selected):
            raise ValueError("Short and long fixtures need native input/target/type")
        binding = {"settings": settings, "smoke_fixtures_sha256": file_hash(smoke_fixtures), "corpus": None}
    from .tokenization import verify_proof
    if verify_proof(config.paths["native_decoder_proof"], config.paths["model_dir"])["status"] != "passed":
        raise ValueError("Matching actual-tokenizer decoder proof required before model probe")
    root = suite_dir or config.require("output_root")
    directory = new_directory(root / "probes", scope)
    monitor = MemoryMonitor()
    result = {"schema": "lifemate-native-resource-probe-v1", "scope": scope, "binding": binding,
              "status": "resource_failed", "updates": 0, "generation_verified": False, "reload_verified": False,
              "asr_loaded": False, "source_scope": "accepted_fit_worst_lengths" if corpus else "declared_structural_fixtures"}
    torch = None
    try:
        import torch
        from .models import load_training_model, planner_for_loaded
        from .losses import optimizer_update
        torch.cuda.reset_peak_memory_stats()
        monitor.start()
        model, tokenizer, metadata = load_training_model(config.require("model_dir"), settings)
        result["model"] = metadata
        import sys
        print(f"[LLM] probe {scope} | {settings['method']} loaded | checkpointing={metadata['gradient_checkpointing']['decoder_layers']} layers",file=sys.stderr,flush=True)
        write_json(directory/'progress.json',{'stage':'model_loaded','checkpointing':metadata['gradient_checkpointing']})
        cache = [supervised(tokenizer, r["input"]["messages"], r["input"]["tools"], r["target"]) for r in selected]
        result["lengths"] = [{k: t[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens")} for t in cache]
        optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=settings["lr"])
        scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda _: 1.)
        scaler = torch.amp.GradScaler("cuda", enabled=settings["precision"] == "fp16")
        total_updates = 5 if scope == 'full' else 1
        progress = Progress(f'probe {scope}',total_updates)
        for step in range(total_updates):
            write_json(directory/'progress.json',{'stage':'optimizer_update','update':step+1,
                       'updates_completed':result['updates']},exclusive=False)
            progress.note(f"update {step+1}/{total_updates}",force=True)
            window = [(cache[i % len(cache)], selected[i % len(selected)]["target_type"])
                      for i in range(settings["accumulation"] if scope == "full" else len(cache))]
            optimizer_update(model, optimizer, scheduler, scaler, window,
                             dict.fromkeys([r["target_type"] for r in selected], 1), 1., torch,
                             on_row=lambda done,total:progress.note(f'update {step+1}/{total_updates}, row {done}/{total}'))
            result["updates"] = step + 1
            progress.advance(step+1,force=True)
        model.eval()
        progress.note('checking generation',force=True)
        write_json(directory/'progress.json',{'stage':'native_generation','updates_completed':result['updates']},exclusive=False)
        planner = planner_for_loaded(model, tokenizer)
        predictions = [planner.generate_native(r["input"]["messages"], r["input"]["tools"], 300.) for r in selected]
        if any(p.kind == "rejected" or not p.metadata["eos_observed"] for p in predictions):
            raise ValueError("Constrained native generation failed")
        result["generation_verified"] = True
        progress.note('checking adapter save/reload',force=True)
        model.save_pretrained(directory / "adapter", safe_serialization=True, save_embedding_layers=False)
        from peft import set_peft_model_state_dict
        from safetensors.torch import load_file
        saved = load_file(str(directory / "adapter/adapter_model.safetensors"))
        set_peft_model_state_dict(model, saved)
        reloaded = [planner.generate_native(r["input"]["messages"], r["input"]["tools"], 300.) for r in selected]
        result["reload_verified"] = all(a.internal() == b.internal() for a, b in zip(predictions, reloaded))
        result["model"], result["memory"] = metadata, cuda_memory(torch)
        if not result["reload_verified"]:
            raise ValueError("Adapter save/reload generation differs")
        result["status"] = "passed_early_smoke" if scope == "early" else "resource_unverified"
    except Exception as exc:
        result["reason"] = f"{type(exc).__name__}: {exc}"[:500]
    finally:
        if torch is not None and torch.cuda.is_initialized():
            try:
                result['memory']=cuda_memory(torch)
            except Exception as exc:
                result['memory_measurement_error']=type(exc).__name__
        result["nvml"] = monitor.finish()
    if result["status"] == "resource_unverified":
        m, nv = result["memory"], result["nvml"]
        result['memory_acceptance']=memory_acceptance(m,nv)
        if result['memory_acceptance']['passed']:
            result["status"] = "passed"
        else:
            result["reason"] = "Memory evidence/cap/headroom: "+','.join(result['memory_acceptance']['issues'])
    write_json(directory / "outcome.json", result)
    files = [p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()]
    seal(directory, files)
    return result | {"directory": str(directory)}
