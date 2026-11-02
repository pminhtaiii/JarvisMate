"""Explicit fixed-ten L0 pilot and selected-export full-audio evaluation hooks."""
import time
from contextlib import contextmanager
from pathlib import Path

from ..adapters.common import inference_session
from .storage import file_hash, new_directory, read_json, write_json, write_jsonl
from .config import FIXED_VALIDATION_CASES


class TimedASR:
    def __init__(self, adapter, root):
        self.adapter, self.root, self.turns = adapter, root, []
        self.metadata = adapter.metadata

    @contextmanager
    def inference_session(self):
        with inference_session(self.adapter):
            yield

    def transcribe(self, audio_path, remaining_seconds):
        from ..dataset import wav_info
        started = time.monotonic()
        record = {"audio": audio_path.relative_to(self.root).as_posix(), "duration_seconds": wav_info(audio_path)["seconds"],
                  "wav_sha256": file_hash(audio_path), "elapsed": None, "status": "failed"}
        try:
            result = self.adapter.transcribe(audio_path, remaining_seconds)
            record["status"] = "completed"
            return result
        finally:
            record["elapsed"] = time.monotonic() - started
            self.turns.append(record)


class TimedPlanner:
    def __init__(self, adapter):
        self.adapter, self.decisions, self.current = adapter, [], None
        self.metadata = adapter.metadata

    @property
    def last_generation(self):
        return self.adapter.last_generation

    @property
    def last_decision_details(self):
        return self.adapter.last_decision_details

    @contextmanager
    def inference_session(self):
        with inference_session(self.adapter):
            yield

    def start_sample(self, sample_id):
        self.current = sample_id
        self.adapter.start_sample(sample_id)

    def next_action(self, value, remaining_seconds):
        started = time.monotonic()
        try:
            return self.adapter.next_action(value, remaining_seconds)
        finally:
            generation = self.adapter.last_generation or {}
            self.decisions.append({"source_id": self.current, "elapsed": time.monotonic() - started,
                 "reserved_output_tokens": self.adapter.limits.output_tokens,
                 **{k: generation.get(k) for k in ("prompt_tokens", "generated_tokens", "stop_reason", "eos_observed", "code")},
                 "prefill_seconds": None, "decode_seconds": None, "first_token_seconds": None,
                 "separation_missing_reason": "no calibrated per-token timing hook; total measured"})


class TimedFactory:
    def __init__(self, factory):
        self.factory, self.metadata, self.events = factory, factory.metadata, []

    def schema_precheck(self, *args):
        return self.factory.schema_precheck(*args)

    def __call__(self, split, sample_id, root):
        started = time.monotonic()
        env = self.factory(split, sample_id, root)
        self.events.append({"source_id": sample_id, "stage": "environment_setup", "elapsed": time.monotonic()-started})
        events = self.events
        class TimedEnvironment:
            def call(self, name, arguments):
                started = time.monotonic()
                try:
                    return env.call(name, arguments)
                finally:
                    events.append({"source_id": sample_id, "stage": "tool_call", "name": name,
                                   "elapsed": time.monotonic()-started})
            def get_tool_calls(self):
                return env.get_tool_calls()
            def get_state_hash(self):
                return env.get_state_hash()
        return TimedEnvironment()


def load_audio_adapters(config, device):
    """Own the shared full-audio residency policy for ASR and planner."""
    from ..adapters.asr import LocalASR
    from ..adapters.planner import LocalPlanner
    from .evaluation import limits
    offload = device == 'cuda'
    asr = LocalASR(config.require('asr_model_dir'),device,limits(),cpu_offload=offload)
    planner = LocalPlanner(config.require('model_dir'),device,limits(),cpu_offload=offload)
    policy = {'policy':'sequential_gpu_cpu_master_v1' if offload else 'joint_resident_v1',
              'offload':offload,'transfers_in_sample_elapsed':True}
    asr.metadata['residency_policy'] = planner.metadata['residency_policy'] = policy['policy']
    return asr,planner,policy


def run_audio(config, suite_dir: Path, *, experiment, export=None, pilot=False, device="cuda", continue_on_error=False, profile=None):
    from .resources import validate_lock
    validate_lock(config)
    from .acceptance import evaluation_readiness
    from .corpus import load_suite, sealed_policy
    from .asr_views import validate_export
    from .evaluation import evaluation_input_preflight, identity_of_model, limits, run_closed_loop
    from .export import export_identity
    from ..adapters.planner import LocalPlanner
    from ..adapters.asr import LocalASR
    from ..runtime import load_runtime
    from ..model_budget import check_budget
    from .qualification import MemoryMonitor, memory_acceptance
    from .resources import cuda_memory
    if pilot and experiment != "L0":
        raise ValueError("Latency pilot is an L0-only phase")
    loaded = load_suite(suite_dir)
    evaluation_readiness(config, suite_dir)
    sealed_policy(suite_dir)
    evaluation_input_preflight(config,partition=loaded['partition'])
    asr_identity = validate_export(config.require("asr_model_dir"), loaded["partition"])
    if experiment == "L0":
        if export is not None:
            raise ValueError("L0 uses only the pinned pretrained base")
        model_dir, identity = config.require("model_dir"), identity_of_model(config.require("model_dir"))
    else:
        if export is None:
            raise ValueError("Actual verified export required")
        identity = export_identity(export, config, suite_dir)
        model_dir = export / "model"
    check_budget(asr_identity["logical_parameters"], 4_022_468_096)
    initialized = time.monotonic()
    from dataclasses import replace
    # A trained export changes only the planner path, never the residency policy.
    adapter_config = replace(config,paths={**config.paths,'model_dir':model_dir})
    asr, planner, residency = load_audio_adapters(adapter_config,device)
    if asr.metadata["parameter_count"] != asr_identity["logical_parameters"]:
        raise ValueError("ASR manifest logical size differs from loaded model")
    check_budget(asr.metadata["parameter_count"], planner.metadata["parameter_count"])
    initialization = time.monotonic() - initialized
    asr.metadata["export_identity"] = asr_identity["identity"]
    wrapped_asr, wrapped_planner = TimedASR(asr, config.require("data_root")), TimedPlanner(planner)
    monitor = MemoryMonitor()
    if device == "cuda":
        planner.torch.cuda.reset_peak_memory_stats()
        monitor.start()
    result = None
    factory_holder = []
    def runtime_loader(run_config, dataset):
        factory = TimedFactory(load_runtime(run_config, dataset))
        factory_holder.append(factory)
        return factory
    try:
        result = run_closed_loop(config=config, suite_dir=suite_dir, experiment=experiment, mode="A", planner=wrapped_planner,
            asr=wrapped_asr, runtime_loader=runtime_loader, model_identity=identity, full_audio=True,
            selected_ids=FIXED_VALIDATION_CASES if pilot else None, output_group="pilots" if pilot else "evaluations",
            continue_on_error=continue_on_error)
    finally:
        memory = monitor.finish()
    directory = Path(result["evaluation_dir"])
    write_jsonl(directory / "asr-turn-timings.jsonl", wrapped_asr.turns)
    write_jsonl(directory / "decision-timings.jsonl", wrapped_planner.decisions)
    write_jsonl(directory / "environment-timings.jsonl", factory_holder[0].events)
    allocator = cuda_memory(planner.torch) if device == "cuda" else None
    write_json(directory / "memory.json", {"nvml": memory,
        "allocator": allocator, "joint_resident": device=='cuda' and not residency['offload'],
        "offload":residency['offload'],"residency_policy":residency['policy'],
        "scope":"full audio including in-budget model transfers after initialization"})
    outcomes = read_json(directory / "metrics.json")["counts"]
    # Feasibility also requires measured joint process/device support.
    status = "at_risk"
    if (pilot and outcomes["completed"] == 10 and outcomes["failed"] == 0
            and allocator is not None and memory_acceptance(allocator,memory)['passed']):
        status = "locally_feasible"
    write_json(directory / "audio-summary.json", {"status": status if pilot else result["status"],
               "initialization_seconds": initialization, "warmup_seconds": None, "warmup_reason": "none requested",
               "queue_seconds": None, "asr_turns": len(wrapped_asr.turns), "qwen_invocations": len(wrapped_planner.decisions),
               "profile": profile or config.source["environment_profile"],
               "residency":residency,"implementation_sha256":file_hash(Path(__file__)),
               "deployment_acceptance": "unverified", "power_thermal_conditions": "not_measured"})
    return result | {"pilot_status": status if pilot else None}
