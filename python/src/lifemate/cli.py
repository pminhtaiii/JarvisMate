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
            child.add_argument("--device", required=True, choices=("cpu", "cuda"))
            child.add_argument("--run-dir", required=True, type=Path)
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
        trace_payloads=args.trace_payloads if running else False)


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
        store.selected(dataset.metadata, factory.metadata)
        initialized = clock()
        with contextlib.redirect_stdout(sys.stderr):
            planner = planner_factory(config.planner_model, config.device, config.limits, config.seed)
            asr = (asr_factory(config.asr_model, config.device, config.limits, config.seed)
                   if config.input_mode == "audio" else None)
        total_params = planner.metadata["parameter_count"] + (asr.metadata["parameter_count"] if asr else 0)
        if planner.metadata["parameter_count"] >= 5_000_000_000 or total_params >= 6_000_000_000:
            raise PipelineError("MODEL_UNAVAILABLE", "Deployed model parameter budget exceeded", "model_load")
        store.manifest.update(model_initialization_seconds=clock() - initialized,
                              models={"planner": planner.metadata, "asr": asr.metadata if asr else None},
                              total_model_parameters=total_params)
        store.save()
        for sample in dataset.samples:
            sample_id = sample.id
            trace = store.trace(sample.id)
            try:
                with contextlib.redirect_stdout(sys.stderr):
                    outcome = run_sample(sample, planner, asr, factory, trace, config.limits,
                                         split=config.split, data_root=config.data_root, clock=clock)
            finally:
                trace.close()
            if outcome.status == "failed":
                raise PipelineError(outcome.error["code"], outcome.error["message"], outcome.error["stage"])
            store.append(outcome)
            sample_id = None
        store.finish()
        print(dumps({"status": "completed", "manifest": str(store.manifest_path),
                     "predictions": str(store.final_path), "count": len(dataset.samples),
                     "coverage_scope": dataset.metadata["coverage_scope"],
                     "submission_ready": False, "elapsed": clock() - started}))
        return 0
    except Exception as exc:
        error = exc if isinstance(exc, PipelineError) else PipelineError(
            "OUTPUT_IO", "Unexpected failure; run is incomplete", "orchestration")
        record = error.record()
        if store is not None:
            try:
                store.fail(record, sample_id)
            except Exception:
                record = PipelineError("OUTPUT_IO", "Cannot save failure manifest; artifacts are incomplete", "output").record()
        print(dumps({"status": "failed", "error": record,
                     "manifest": str(store.manifest_path) if store else None,
                     "completed_ids": store.manifest["completed_ids"] if store else [],
                     "failed_id": sample_id, "elapsed": clock() - started}))
        print(f"LifeMate failed: {record['code']} ({record['stage']})", file=sys.stderr)
        return 2 if error.code in {"INPUT_INVALID", "ASSET_MISSING", "CATALOG_INVALID"} else 1
