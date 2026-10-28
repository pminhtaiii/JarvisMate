"""Direct CLI; stdout is a summary, predictions and traces are separate files."""
from __future__ import annotations

import argparse
import contextlib
import sys
import time
from pathlib import Path

from .adapters.asr import LocalASR
from .adapters.planner import LocalPlanner
from .agent import run_sample
from .artifacts import RunStore
from .contracts import Limits, PipelineError, RunConfig
from .dataset import preflight
from .jsonio import dumps
from .runtime import load_runtime


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's text can contain arbitrary supplied values; expose a stable bounded error.
        raise PipelineError("INPUT_INVALID", "Invalid command arguments; consult --help", "arguments")


def parser() -> Parser:
    root = Parser(prog="lifemate", description="Offline LifeMate development baseline")
    sub = root.add_subparsers(dest="command", required=True, parser_class=Parser)
    for command in ("check-data", "run"):
        child = sub.add_parser(command)
        child.add_argument("--data-root", required=True, type=Path)
        child.add_argument("--runtime-dir", required=True, type=Path)
        child.add_argument("--split", required=True, choices=("train", "public_test"))
        child.add_argument("--input-mode", required=True, choices=("transcript", "audio"))
        select = child.add_mutually_exclusive_group(required=True)
        select.add_argument("--id", action="append", default=[])
        select.add_argument("--all", action="store_true")
        if command == "run":
            child.add_argument("--planner-model", required=True, type=Path)
            child.add_argument("--asr-model", type=Path)
            child.add_argument("--model-offload", action="store_true",
                               help="CUDA audio: keep only the active ASR/planner on GPU; store the other in RAM")
            child.add_argument("--selection-filter", action="store_true",
                               help="Development: filter visible task records before tasks.complete")
            child.add_argument("--device", required=True, choices=("cpu", "cuda"))
            child.add_argument("--run-dir", required=True, type=Path)
            child.add_argument("--resume-from", type=Path,
                               help="Reuse completed rows from a stopped run into a NEW --run-dir")
            child.add_argument("--allow-mixed-resume", action="store_true",
                               help="Explicitly allow development results from another/unknown version")
            child.add_argument("--continue-on-error", action="store_true",
                               help="Record planner/sample budget failures and continue other samples")
            child.add_argument("--trace-payloads", action="store_true")
            child.add_argument("--max-steps", default=16, type=int)
            child.add_argument("--sample-timeout-seconds", default=30.0, type=float)
            child.add_argument("--context-limit", default=16_384, type=int)
            child.add_argument("--max-new-tokens", default=512, type=int)
    return root


def configuration(args) -> RunConfig:
    running = args.command == "run"
    limits = Limits(args.max_steps, args.sample_timeout_seconds,
                    args.context_limit, args.max_new_tokens) if running else Limits()
    return RunConfig(
        data_root=args.data_root.resolve(), runtime_dir=args.runtime_dir.resolve(),
        split=args.split, input_mode=args.input_mode, selected_ids=tuple(args.id),
        select_all=args.all, limits=limits,
        planner_model=args.planner_model if running else None,
        asr_model=args.asr_model if running else None,
        device=args.device if running else "cpu",
        run_dir=args.run_dir if running else None,
        trace_payloads=args.trace_payloads if running else False,
        resume_from=args.resume_from if running else None,
        continue_on_error=args.continue_on_error if running else False,
        allow_mixed_resume=args.allow_mixed_resume if running else False,
        selection_filter=args.selection_filter if running else False,
        model_offload=args.model_offload if running else False)


def main(argv=None, *, planner_factory=LocalPlanner, asr_factory=LocalASR,
         runtime_loader=load_runtime, clock=time.monotonic) -> int:
    store, sample_id = None, None
    started = clock()
    try:
        args = parser().parse_args(argv)
        config = configuration(args)
        if args.command == "run":
            output = config.run_dir.resolve()
            if output.is_relative_to(config.data_root) or output.is_relative_to(config.runtime_dir):
                raise PipelineError("INPUT_INVALID", "Run output must be outside organizer inputs")
            if config.resume_from is not None:
                source = config.resume_from.resolve()
                if (source == output or source.is_relative_to(config.data_root)
                        or source.is_relative_to(config.runtime_dir)):
                    raise PipelineError("INPUT_INVALID", "Resume source must be a separate run outside organizer inputs")
            store = RunStore(config)  # Preflight failures still receive a run manifest.
            if argv is not None:
                store.manifest["argv"] = list(argv)
                store.save()
        with contextlib.redirect_stdout(sys.stderr):
            dataset = preflight(config)
            factory = runtime_loader(config, dataset)
        if args.command == "check-data":
            print(dumps({"status": "validated", **dataset.metadata, "runtime": factory.metadata}))
            return 0
        print("[run] Fingerprinting code and local model files...", file=sys.stderr, flush=True)
        store.selected(dataset.metadata, factory.metadata)
        if config.resume_from is not None:
            store.restore(config.resume_from)
            if store.manifest["resume"]["development_composite"]:
                print("[run] MIXED DEVELOPMENT RESUME: retained rows come from other/unknown versions",
                      file=sys.stderr, flush=True)
        total = len(dataset.samples)
        reused = set(store.manifest["completed_ids"])
        print(f"[run] split={config.split} mode={config.input_mode} samples={total}",
              file=sys.stderr, flush=True)
        print(f"[run] output={store.manifest_path.parent}", file=sys.stderr, flush=True)
        print(f"[run] reused={len(reused)} remaining={total - len(reused)} "
              f"continue_on_error={config.continue_on_error}", file=sys.stderr, flush=True)
        if len(reused) < total:
            print("[run] Loading models...", file=sys.stderr, flush=True)
            initialized = clock()
            with contextlib.redirect_stdout(sys.stderr):
                planner = planner_factory(config.planner_model, config.device, config.limits, config.seed,
                    **({"selection_filter": True} if config.selection_filter else {}),
                    **({"cpu_offload": True} if config.model_offload else {}))
                asr = (asr_factory(config.asr_model, config.device, config.limits, config.seed,
                                  **({"cpu_offload": True} if config.model_offload else {}))
                       if config.input_mode == "audio" else None)
            total_params = planner.metadata["parameter_count"] + (asr.metadata["parameter_count"] if asr else 0)
            if planner.metadata["parameter_count"] >= 5_000_000_000 or total_params >= 6_000_000_000:
                raise PipelineError("MODEL_UNAVAILABLE", "Deployed model parameter budget exceeded", "model_load")
            store.manifest.update(model_initialization_seconds=clock() - initialized,
                                  models={"planner": planner.metadata, "asr": asr.metadata if asr else None},
                                  total_model_parameters=total_params)
            store.save()
            print(f"[run] Models ready ({store.manifest['model_initialization_seconds']:.1f}s)",
                  file=sys.stderr, flush=True)
        for position, sample in enumerate(dataset.samples, 1):
            if sample.id in reused:
                continue
            store.verify_code_snapshot()
            sample_id = sample.id
            print(f"[{position}/{total}] {sample.id} START", file=sys.stderr, flush=True)
            trace = store.trace(sample.id)
            try:
                with contextlib.redirect_stdout(sys.stderr):
                    outcome = run_sample(sample, planner, asr, factory, trace, config.limits,
                                         split=config.split, data_root=config.data_root, clock=clock)
            finally:
                trace.close()
            if outcome.status == "failed":
                print(f"[{position}/{total}] {sample.id} FAILED "
                      f"code={outcome.error['code']} elapsed={outcome.elapsed:.1f}s",
                      file=sys.stderr, flush=True)
                if config.continue_on_error and outcome.error["code"] in {
                        "STEP_LIMIT", "TIME_LIMIT", "CONTEXT_LIMIT", "PLANNER_ERROR", "PLANNER_FORMAT", "OUTPUT_LIMIT", "NO_PROGRESS"}:
                    store.sample_failed(outcome.error, sample.id)
                    sample_id = None
                    continue
                raise PipelineError(outcome.error["code"], outcome.error["message"], outcome.error["stage"])
            store.append(outcome)
            print(f"[{position}/{total}] {sample.id} {outcome.status} "
                  f"elapsed={outcome.elapsed:.1f}s steps={outcome.steps} "
                  f"progress={len(store.manifest['completed_ids']) / total:.1%} "
                  f"completed={len(store.manifest['completed_ids'])} failed={len(store.manifest['failed_ids'])}",
                  file=sys.stderr, flush=True)
            sample_id = None
        if store.manifest["failed_ids"]:
            error = store.manifest["failures"][-1]["error"]
            raise PipelineError(error["code"], "Batch finished with failed samples; resume to retry missing rows",
                                error["stage"])
        store.finish()
        print(dumps({"status": "completed", "manifest": str(store.manifest_path),
                     "predictions": str(store.final_path), "count": len(dataset.samples),
                     "coverage_scope": dataset.metadata["coverage_scope"],
                     "submission_ready": False, "elapsed": clock() - started}))
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        error = (PipelineError("INTERRUPTED", "Run interrupted; completed rows can be resumed", "orchestration")
                 if isinstance(exc, KeyboardInterrupt) else exc if isinstance(exc, PipelineError) else PipelineError(
                     "OUTPUT_IO", "Unexpected failure; run is incomplete", "orchestration"))
        record = error.record()
        if store is not None:
            try:
                store.fail(record, sample_id)
            except Exception:
                record = PipelineError("OUTPUT_IO", "Cannot save failure manifest; artifacts are incomplete", "output").record()
        print(dumps({"status": "failed", "error": record,
                     "manifest": str(store.manifest_path) if store else None,
                     "completed_ids": store.manifest["completed_ids"] if store else [],
                     "failed_ids": store.manifest["failed_ids"] if store else [],
                     "failed_id": sample_id, "elapsed": clock() - started}))
        print(f"LifeMate failed: {record['code']} ({record['stage']})", file=sys.stderr)
        if error.code == "INTERRUPTED":
            return 130
        return 2 if error.code in {"INPUT_INVALID", "ASSET_MISSING", "CATALOG_INVALID"} else 1
