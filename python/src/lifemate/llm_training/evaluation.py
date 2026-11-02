"""Native closed-loop and teacher-forced evaluation boundaries (LL021-LL023).

Closed loop reuses ``agent.run_sample``: one RuntimeFactory, one ToolEnv per source,
actual observations, authoritative log/hash, native rejection feedback and the total
repair cap. Gold references are read by a separate reader after execution and never
reach the planner. Teacher-forced diagnostics use exact gold strict prefixes from the
sealed suite. Model libraries load only through explicitly supplied backends.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from ..adapters.qwen_native import target_semantics
from ..agent import run_sample
from ..artifacts import Trace, validate_prediction
from ..contracts import Limits, PipelineError, RunConfig
from ..dataset import preflight as dataset_preflight
from ..jsonio import contained, loads, visible_path
from .config import LIMITS, SEEDS, content_hash, native_identities
from .corpus import load_suite, sealed_policy
from .data import load_catalog
from .metrics import closed_loop_metrics, fixed_cases, fuzzy_keys, teacher_forced_metrics
from .storage import file_hash, new_directory, now, read_jsonl, write_json, write_jsonl
from .acceptance import accepted_corpus, evaluation_readiness, input_identity

EVALUATION_SCHEMA = "lifemate-native-llm-evaluation-v2"
EVALUATOR_VERSION = "lifemate-native-evaluator-v1"


def evaluator_binding():
    return {name: file_hash(Path(__file__).with_name(name)) for name in ("evaluation.py", "metrics.py")}


def execution_profile(planner):
    from .resources import host_inventory
    import platform
    import hashlib
    inventory = host_inventory(Path.cwd())
    return {"host": hashlib.sha256(platform.node().encode()).hexdigest(), "platform": inventory["platform"],
            "packages": inventory["packages"], "gpu": [{k: v for k, v in gpu.items() if k not in {"free", "allocation"}}
                                                       for gpu in inventory["gpus"]],
            "planner": {k: planner.metadata.get(k) for k in ("device", "dtype", "attention_implementation", "cpu_offload",
                                                          "prefix_cache_policy","cuda_cache_policy","residency_policy",
                                                          "native_generation_policy")}}


def evaluation_dataset(config):
    """Keep unsupported selected inputs as failed outcomes, preserving the denominator."""
    from ..contracts import PreparedDataset
    from ..dataset import normalize_record
    from .data import read_train
    data = config.data_root / config.split
    sources = read_train(data / f"{config.split}.jsonl")
    catalog, specs = load_catalog(data / f"{config.split}_tools_catalog.json")
    selected = set(config.selected_ids)
    samples, errors = [], {}
    for source in sources:
        if source.id not in selected:
            continue
        started = time.monotonic()
        try:
            samples.append(normalize_record(source.record, config, specs))
        except PipelineError as exc:
            errors[source.id] = {"error": exc.record(), "elapsed": time.monotonic() - started}
    if {s.id for s in samples} | set(errors) != selected:
        raise ValueError("Evaluation membership differs from the frozen partition")
    metadata = {"split": config.split, "input_mode": config.input_mode,
                "selected_ids": [s.id for s in sources if s.id in selected], "selected_count": len(selected),
                "dataset_sha256": file_hash(data / f"{config.split}.jsonl"),
                "catalog_sha256": file_hash(data / f"{config.split}_tools_catalog.json"),
                "catalog_version": catalog["schema_version"]}
    return PreparedDataset(tuple(samples), catalog, metadata), errors


def require_evaluation_assets(run_config, errors):
    """Existence checks only; organizer state contents belong to ToolEnv."""
    base = run_config.data_root / run_config.split
    missing_states = []
    for source_id in run_config.selected_ids:
        try:
            marker = contained(base, f'{run_config.split}_environment/{source_id}/state.json',
                               allow_environment=True)
            if not marker.is_file():
                missing_states.append(source_id)
        except PipelineError as exc:
            if exc.code != 'ASSET_MISSING':
                raise
            missing_states.append(source_id)
    missing = set(missing_states) | {sid for sid,value in errors.items()
                                    if value['error']['code'] == 'ASSET_MISSING'}
    if missing:
        raise PipelineError('ASSET_MISSING',
            f'Required evaluation assets missing for {len(missing)}/{len(run_config.selected_ids)} samples; '
            f'ToolEnv state files unavailable for {len(missing_states)}. '
            f'data_root={run_config.data_root}. Configure the original complete dataset; '
            'state contents are read only by ToolEnv.', 'preflight')


def evaluation_input_preflight(config, *, partition=None, runtime_loader=None, input_mode='audio'):
    """Validate real Validation inputs/runtime before loading any model."""
    from .data import read_train, validate_split
    if input_mode not in {'audio','transcript'}:
        raise ValueError('Unknown evaluation input mode')
    if partition is None:
        data = config.require('data_root') / 'train'
        partition = validate_split(config.require('split_manifest'),data/'train.jsonl',
            data/'train_tools_catalog.json',read_train(data/'train.jsonl'))
    run_config = RunConfig(data_root=config.require('data_root'),runtime_dir=config.require('runtime_dir'),
        split='train',input_mode=input_mode,selected_ids=tuple(partition['validation_ids']),limits=limits())
    dataset, errors = evaluation_dataset(run_config)
    require_evaluation_assets(run_config, errors)
    if runtime_loader is None:
        from ..runtime import load_runtime
        runtime_loader = load_runtime
    factory = runtime_loader(run_config,dataset)
    from collections import Counter
    return {'status':'ready','data_root':str(run_config.data_root),'expected':len(run_config.selected_ids),
            'prepared':len(dataset.samples),'unsupported_inputs':len(errors),
            'unsupported_by_code':dict(Counter(v['error']['code'] for v in errors.values())),
            'runtime':factory.metadata,'models_loaded':False,'environment_contents_read':False}


def limits() -> Limits:
    return Limits(LIMITS["max_steps"], LIMITS["timeout_seconds"], LIMITS["context_tokens"],
                  LIMITS["output_tokens"], LIMITS["response_bytes"])


def gold_references(train_path: Path, ids: list[str]) -> dict[str, list[dict]]:
    """Evaluation-only reader of label.tool_calls; never an inference input."""
    visible_path(train_path)
    wanted, references = set(ids), {}
    with train_path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                record = loads(line)
                if record.get("id") in wanted:
                    references[record["id"]] = record["label"]["tool_calls"]
    if set(references) != wanted:
        raise ValueError("Missing gold references for expected Validation IDs")
    return references


class RecordingTrace:
    """Forward to the durable trace while keeping bounded native diagnostics in memory."""

    def __init__(self, inner):
        self.inner, self.native = inner, {"rejections": [], "generations": 0, "eos_valid": 0, "format_valid": 0}

    def emit(self, kind, *, step=None, payload=None, **metadata):
        if kind == "validation_result" and metadata.get("scope") == "native_shape_and_eligibility" \
                and metadata.get("accepted") is False:
            self.native["rejections"].append(metadata.get("code"))
        if kind == "native_generation":
            self.native["generations"] += 1
            self.native["eos_valid"] += metadata.get("eos_observed") is True
            self.native["format_valid"] += metadata.get("parse") in {"call", "final"}
        self.inner.emit(kind, step=step, payload=payload, **metadata)


def outcome_record(outcome, native: dict) -> dict:
    source = outcome.result or outcome.diagnostic or {}
    return {"id": outcome.id, "status": outcome.status, "stop_reason": outcome.stop_reason,
            "error_code": (outcome.error or {}).get("code"), "error_stage": (outcome.error or {}).get("stage"),
            "elapsed": outcome.elapsed, "steps": outcome.steps, "timings": outcome.timings,
            "attempted_calls": source.get("tool_calls", []), "state_hash": source.get("state_hash"),
            "authoritative": outcome.result is not None, "native": native}


def run_closed_loop(*, config, suite_dir: Path, experiment: str, mode: str, planner, asr=None,
                    runtime_loader: Callable, model_identity: dict, continue_on_error: bool = False,
                    trace_payloads: bool = False, clock=time.monotonic, full_audio=False,
                    selected_ids=None, output_group="evaluations") -> dict:
    """Evaluate exactly the suite's Validation sources in one explicitly requested run."""
    loaded = load_suite(suite_dir)
    policy = sealed_policy(suite_dir)
    readiness = evaluation_readiness(config, suite_dir, mode="G" if full_audio else mode)
    expected = loaded["partition"]["validation_ids"] if selected_ids is None else list(selected_ids)
    if not set(expected) <= set(loaded["partition"]["validation_ids"]):
        raise ValueError("Evaluation selection must stay in Validation")
    if mode == "A" and asr is None:
        raise PipelineError("MODEL_UNAVAILABLE", "A mode requires the fixed cache-backed ASR adapter", "preflight")
    run_config = RunConfig(data_root=config.require("data_root"), runtime_dir=config.require("runtime_dir"),
                           split="train", input_mode="transcript" if mode == "G" and not full_audio else "audio",
                           selected_ids=tuple(expected), limits=limits(), seed=SEEDS["inference"],
                           continue_on_error=continue_on_error, trace_payloads=trace_payloads)
    dataset, input_errors = evaluation_dataset(run_config)
    require_evaluation_assets(run_config, input_errors)
    factory = runtime_loader(run_config, dataset)
    directory = new_directory(suite_dir / output_group, f"{experiment}-{mode}-closed-loop")
    (directory / "traces").mkdir()
    manifest = {"schema": EVALUATION_SCHEMA, "evaluator": EVALUATOR_VERSION, "evaluation_id": directory.name,
                "experiment": experiment, "mode": mode, "protocol": "full_audio" if full_audio else "closed_loop", "started_at": now(),
                "suite_id": loaded["suite"]["suite_id"], "suite_seal": loaded["seal"]["identity"],
                "selection_policy_sha256": policy["policy_sha256"], "policy_sealed_at": policy["sealed_at"],
                "identities": native_identities(), "model": model_identity, "planner_metadata": planner.metadata,
                "runtime": factory.metadata, "dataset": dataset.metadata, "limits": vars(run_config.limits),
                "seed": run_config.seed, "decode": {"do_sample": False, "num_beams": 1, "selection_filter": False},
                "continue_on_error": continue_on_error, "trace_payloads": trace_payloads, "status": "running",
                "readiness": readiness, "input_identity": readiness["inputs"],
                "asr": None if asr is None else asr.metadata}
    manifest.update(evaluator_code=evaluator_binding(), execution_profile=execution_profile(planner))
    write_json(directory / "manifest.started.json", manifest)
    from .progress import Progress
    progress = Progress(f'eval {experiment} {mode} '+('audio' if full_audio else 'closed-loop'),len(expected))
    outcomes, stopped = [], False
    samples = {s.id: s for s in dataset.samples}
    for source_id in dataset.metadata["selected_ids"]:
        if stopped:
            outcomes.append({"id": source_id, "status": "not_attempted", "attempted_calls": [], "elapsed": None})
            progress.advance(len(outcomes),'not_attempted')
            continue
        if source_id in input_errors:
            error = input_errors[source_id]["error"]
            inner = Trace(directory / "traces" / f"{source_id}.jsonl", directory.name, source_id, payloads=False)
            try:
                inner.emit("sample_started", input_mode=run_config.input_mode)
                inner.emit("sample_failed", error=error)
            finally:
                inner.close()
            outcomes.append({"id": source_id, "status": "failed", "attempted_calls": [], "elapsed": input_errors[source_id]["elapsed"],
                "elapsed_scope": "failed_input_projection_only",
                "state_hash": None, "error_code": error["code"], "error_stage": "input_projection",
                "stop_reason": "unsupported_input", "steps": 0, "timings": {}, "authoritative": False,
                "native": {"rejections": [], "generations": 0, "eos_valid": 0}})
            if not continue_on_error:
                stopped = True
            progress.advance(len(outcomes),'failed input')
            continue
        sample = samples[source_id]
        inner = Trace(directory / "traces" / f"{sample.id}.jsonl", directory.name, sample.id, payloads=trace_payloads)
        trace = RecordingTrace(inner)
        try:
            outcome = run_sample(sample, planner, asr, factory, trace, run_config.limits, split="train",
                                 data_root=run_config.data_root, clock=clock)
        finally:
            inner.close()
        outcomes.append(outcome_record(outcome, trace.native))
        progress.advance(len(outcomes),outcome.status)
        if outcome.status == "failed" and not continue_on_error:
            stopped = True  # Fail-fast: remaining sources are recorded as not_attempted.
    return finalize(directory, manifest, outcomes, expected, config)


def finalize(directory: Path, manifest: dict, outcomes: list[dict], expected: list[str], config) -> dict:
    actual = input_identity(config, load_suite(directory.parent.parent),
                            mode="G" if manifest["protocol"] == "full_audio" else manifest["mode"])
    if manifest.get("input_identity") != actual:
        raise ValueError("Evaluation inputs changed during execution")
    train_path = config.require("data_root") / "train" / "train.jsonl"
    _, specs = load_catalog(config.require("data_root") / "train" / "train_tools_catalog.json")
    references = gold_references(train_path, expected)
    report, per_source = closed_loop_metrics(outcomes, references, expected, fuzzy_keys(specs),
        latency_scope="full_audio" if manifest["protocol"] == "full_audio" else
            "planner_tools_cached_transcripts" if manifest["mode"] == "A" else "planner_tools_gold_transcripts")
    from .metrics import ratio
    generations = sum(o.get("native", {}).get("generations", 0) for o in outcomes)
    for name, key in (("native_format_validity", "format_valid"), ("assistant_eos_validity", "eos_valid")):
        report["metrics"][name] = ratio(sum(o.get("native", {}).get(key, 0) for o in outcomes), generations,
                                      diagnostic_scope="actual_native_generations")
    successes = [o for o in outcomes if o["status"] in {"completed", "needs_info"}]
    rows = [{"id": o["id"], "tool_calls": o["attempted_calls"], "state_hash": o["state_hash"]} for o in successes]
    for row in rows:
        validate_prediction(row)
    complete = len(rows) == len(expected)
    hashes = {"outcomes": write_jsonl(directory / "outcomes.jsonl", outcomes),
              "per_sample_metrics": write_jsonl(directory / "per-sample-metrics.jsonl", per_source),
              "errors": write_jsonl(directory / "errors.jsonl", [o for o in outcomes if o["status"] == "failed"]),
              "fixed_cases": write_json(directory / "fixed-10-cases.json", fixed_cases(outcomes))}
    name = "predictions.jsonl" if complete else "predictions.partial.jsonl"  # Never finalize an incomplete file.
    hashes["predictions"] = write_jsonl(directory / name, rows)
    status = "completed" if report["counts"]["full_coverage"] else "partial"
    metrics = {"schema": EVALUATION_SCHEMA, "experiment": manifest["experiment"], "mode": manifest["mode"],
               "protocol": manifest["protocol"], "status": status, "winner_status": "none",
               "deployment_acceptance_status": "unverified", **report}
    hashes["metrics"] = write_json(directory / "metrics.json", metrics)
    manifest.update(status=status, ended_at=now(), counts=report["counts"], artifact_hashes=hashes,
                    predictions_file=name, reference_reader="label.tool_calls (evaluation-only)",
                    state_reference={"trusted": False, "reason": "no trusted reference evaluator configured"})
    write_json(directory / "manifest.json", manifest)
    return {"status": status, "evaluation_dir": str(directory), "counts": report["counts"],
            "tool_call_f1": report["metrics"]["tool_call_f1"]}


# ------------------------------------------------------------- teacher forced

def usable_reference_rows(suite_dir: Path, config=None) -> tuple[list[dict], dict]:
    """Validation rows plus statuses; quarantined references stay in the denominator report."""
    rows = read_jsonl(suite_dir / "data" / "validation.teacher-forced.jsonl")
    audits = {r["row_id"]: r for r in read_jsonl(suite_dir / "data" / "quality-audit.jsonl")
              if r["partition"] == "validation"}
    if config is None:
        from .config import config_from_suite
        config = config_from_suite(load_suite(suite_dir)["suite"])
    corpus = accepted_corpus(config, suite_dir)
    token_ids = {r["row_id"] for r in corpus["rows"]}
    usable = [row for row in rows if audits[row["row_id"]]["status"] == "accepted" and row["row_id"] in token_ids]
    report = {"raw_candidates": len(audits), "rendered_rows": len(rows), "usable": len(usable),
              "by_status": {s: sum(1 for a in audits.values() if a["status"] == s)
                            for s in ("accepted", "needs_review", "quarantined")}}
    return usable, report


def run_teacher_forced(*, suite_dir: Path, experiment: str, mode: str, backend, model_identity: dict,
                       transcripts=None, config=None) -> dict:
    """backend.decide(messages, tools, allowed) -> NativeParse; backend.nll(row) -> float|None."""
    loaded = load_suite(suite_dir)
    policy = sealed_policy(suite_dir)
    if config is None:
        from .config import config_from_suite
        config = config_from_suite(loaded["suite"])
    readiness = evaluation_readiness(config, suite_dir, teacher_forced=True, mode=mode)
    from .asr_views import CacheASR
    if mode == "A" and not isinstance(transcripts, CacheASR):
        raise PipelineError("MODEL_UNAVAILABLE", "Teacher-forced A needs the fixed Validation ASR cache", "preflight")
    rows, denominators = usable_reference_rows(suite_dir, config)
    if mode == "A":
        from .data import read_train
        sources = {s.id: s.record for s in read_train(config.require("data_root") / "train/train.jsonl")}
        _, specs = load_catalog(config.require("data_root") / "train/train_tools_catalog.json")
    directory = new_directory(suite_dir / "evaluations", f"{experiment}-{mode}-teacher-forced")
    from .progress import Progress
    progress = Progress(f'eval {experiment} {mode} teacher-forced',len(rows))
    items = []
    for row in rows:
        allowed = [tool["function"]["name"] for tool in row["input"]["tools"]]
        from .tokenization import TokenizationError
        from ..adapters.qwen_native import NativeParse
        try:
            if mode == "A":
                row = transcripts.project_row(row, sources[row["provenance"]["source_id"]], specs)
            parse = backend.decide(row["input"]["messages"], row["input"]["tools"], allowed)
            nll = backend.nll(row) if hasattr(backend, "nll") else None
        except (PipelineError, TokenizationError) as exc:
            parse, nll = NativeParse("rejected", code=exc.code), None
        predicted = None if parse.kind == "rejected" else (
            {"action": "finish"} if parse.kind == "final" else
            {"action": "call", "name": parse.name, "arguments": parse.arguments})
        items.append({"row_id": row["row_id"], "target_type": row["target_type"],
                      "decision_index": row["provenance"]["decision_index"],
                      "target": target_semantics(row["target"]), "predicted": predicted, "code": parse.code,
                      "eos_valid": parse.metadata.get("eos_observed") is True,
                      "nll": nll})
        progress.advance(len(items))
    metrics = teacher_forced_metrics(items)
    hashes = {"teacher_forced": write_jsonl(directory / "teacher-forced.jsonl", items)}
    hashes["metrics"] = write_json(directory / "metrics.json", {
        "schema": EVALUATION_SCHEMA, "experiment": experiment, "mode": mode, "protocol": "teacher_forced",
        "status": "completed", "denominators": denominators, "metrics": metrics,
        "note": "oracle gold prefixes; diagnostic only, never closed-loop evidence"})
    write_json(directory / "manifest.json", {
        "schema": EVALUATION_SCHEMA, "evaluator": EVALUATOR_VERSION, "evaluation_id": directory.name,
        "experiment": experiment, "mode": mode, "protocol": "teacher_forced", "status": "completed",
        "suite_id": loaded["suite"]["suite_id"], "selection_policy_sha256": policy["policy_sha256"],
        "identities": native_identities(), "model": model_identity, "artifact_hashes": hashes,
        "evaluator_code": evaluator_binding(),
        "readiness": readiness, "input_identity": readiness["inputs"],
        "rows_sha256": file_hash(suite_dir / "data" / "validation.teacher-forced.jsonl"), "ended_at": now()})
    return {"status": "completed", "evaluation_dir": str(directory), "denominators": denominators,
            "next_action_accuracy": metrics["next_action_accuracy"]}


class TransformersBackend:
    """Teacher-forced decisions/NLL through an already-loaded LocalPlanner (explicit only)."""

    def __init__(self, planner):
        self.planner = planner

    def decide(self, messages, tools, allowed):
        # Same constrained native generation path as closed-loop inference.
        return self.planner.generate_native(messages, tools, LIMITS["timeout_seconds"])

    def nll(self, row):
        from .tokenization import supervised

        torch = self.planner.torch
        sup = supervised(self.planner.tokenizer, row["input"]["messages"], row["input"]["tools"], row["target"])
        ids = torch.tensor([sup["input_ids"]]).to(self.planner.device)
        labels = torch.tensor([sup["labels"]]).to(self.planner.device)
        with torch.inference_mode():
            logits = self.planner.model(input_ids=ids).logits[:, :-1].float()
        loss = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.shape[-1]), labels[:, 1:].reshape(-1),
                                                 ignore_index=-100, reduction="sum")
        return float(loss) / sup["completion_tokens"]


def identity_of_model(model_dir: Path) -> dict:
    from .model_identity import snapshot_identity
    return snapshot_identity(model_dir)

