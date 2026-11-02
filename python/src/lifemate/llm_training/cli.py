"""Manual native SFT command line (specs §11.3; LL001).

Each invocation runs one explicitly requested phase for at most one experiment/mode.
There is no --all, no automatic L0->L1->L2->L3 chaining and no hidden probe/export/
evaluation phase. Model-free commands (status, prepare, verify-resources, preflight,
seal-selection-policy, compare) never import model libraries; token-audit loads only a
local CPU tokenizer/backend; evaluate loads models only when explicitly invoked.
Stdout carries one JSON summary; diagnostics go to stderr.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..jsonio import dumps, loads
from .config import EXPERIMENTS, MODES, ConfigError, config_from_suite, contained_output, load_config

MODEL_PHASES = ("gpu-preflight", "probe", "latency-pilot", "train", "export", "verify-export", "build-asr-views")
OVERRIDES = ("data_root", "model_dir", "asr_model_dir", "split_manifest", "fit_asr_cache",
             "validation_asr_cache", "output_root", "runtime_dir", "native_decoder_proof", "manual_reviews",
             "environment_lock", "resource_qualification", "latency_decision", "native_acceptance")
EXIT = {"ok": 0, "error": 1, "invalid": 2, "blocked": 4}


class UsageError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError("Invalid command arguments; consult --help")


def parser() -> Parser:
    root = Parser(prog="python -m lifemate.llm_training", description="Manual native Qwen Next-Action SFT phases")
    sub = root.add_subparsers(dest="command", required=True, parser_class=Parser)

    def command(name, *, config=False, suite=False, experiment=False):
        child = sub.add_parser(name)
        child.add_argument("--config", type=Path, required=config)
        child.add_argument("--project-root", type=Path)
        for key in OVERRIDES:
            child.add_argument("--" + key.replace("_", "-"), type=Path)
        if suite:
            child.add_argument("--suite-dir", type=Path, required=suite == "required")
        if experiment:
            child.add_argument("--experiment", required=True, choices=sorted(EXPERIMENTS))
        return child

    command("status", suite="optional")
    command("prepare", config=True, suite="required").add_argument("--draft-without-proof", action="store_true")
    command("evaluation-inputs", config=True)
    child = command("verify-resources", config=True, suite="optional")
    child.add_argument("--phase", default="prepare", choices=("transfer", "prepare", "decoder-poc", "token-audit", "evaluate-G",
                                                              "evaluate-A", "pilot", "train", "compare"))
    child.add_argument("--skip-weight-hashes", action="store_true")
    child = command("preflight", suite="required", experiment=True)
    child.add_argument("--settings", type=Path)
    child.add_argument("--policy-report", type=Path)
    child = command("token-audit", suite="optional")
    child.add_argument("--scope", required=True, choices=("decoder-poc", "native", "clean", "asr"))
    child.add_argument("--view-dir", type=Path)
    command("seal-selection-policy", suite="required").add_argument("--policy", type=Path, required=True)
    child = command("evaluate", suite="required", experiment=True)
    child.add_argument("--mode", required=True, choices=MODES)
    child.add_argument("--protocol", default="closed_loop", choices=("closed_loop", "teacher_forced"))
    child.add_argument("--export", type=Path)
    child.add_argument("--device", default="cuda", choices=("cpu", "cuda"))
    child.add_argument("--continue-on-error", action="store_true")
    child.add_argument("--trace-payloads", action="store_true")
    child.add_argument("--full-audio", action="store_true")
    command("compare", suite="required").add_argument("--runs", type=Path, required=True)
    command("deployment-check", suite="required").add_argument("--evidence", type=Path, required=True)
    for name in MODEL_PHASES:
        child = command(name, suite="optional", experiment=name in {"probe", "latency-pilot", "train", "export",
                                                                    "verify-export"})
        child.add_argument("--profile")
        child.add_argument("--resume-from", type=Path)
        child.add_argument("--policy-report", type=Path)
        child.add_argument("--checkpoint")
        child.add_argument("--export", type=Path)
        child.add_argument("--fit-cache", type=Path)
        child.add_argument("--settings", type=Path)
        child.add_argument("--scope", choices=("early", "full"), default="full")
        child.add_argument("--smoke-fixtures", type=Path)
        child.add_argument("--run-dir", type=Path)
        child.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
        child.add_argument("--nf4", action="store_true")
        child.add_argument("--include-asr", action="store_true")
    return root


def resolve(args):
    overrides = {key: getattr(args, key, None) for key in OVERRIDES}
    if args.config is not None:
        return load_config(args.config, project_root=args.project_root, overrides=overrides)
    suite_dir = getattr(args, "suite_dir", None)
    if suite_dir is None:
        raise UsageError("--config or --suite-dir is required")
    from .storage import read_json
    if args.project_root is not None and not suite_dir.is_absolute():
        suite_dir = args.project_root / suite_dir

    return config_from_suite(read_json(suite_dir / "suite.json"), project_root=args.project_root, overrides=overrides)


def suite_path(config, args) -> Path:
    if args.suite_dir is None:
        raise UsageError("--suite-dir required for this phase")
    candidate = args.suite_dir if args.suite_dir.is_absolute() else config.project_root / args.suite_dir
    return contained_output(config.require("output_root"), candidate)


def run(args) -> tuple[str, dict]:
    if getattr(args, "experiment", None) == "L0" and args.command in {"train", "probe", "export"}:
        return "invalid", {"status": "failed_preflight", "reason": "L0 is the pretrained baseline and has no training phase"}
    if args.command == "status":
        return "ok", status(args)
    config = resolve(args)
    from ..jsonio import visible_path
    for key in ("suite_dir", "policy", "runs", "export", "settings", "smoke_fixtures", "run_dir", "resume_from",
                "fit_cache", "evidence", "view_dir", "policy_report"):
        value = getattr(args, key, None)
        if isinstance(value, Path):
            value = value if value.is_absolute() else config.project_root / value
            visible_path(value)
            setattr(args, key, value.resolve())
    if getattr(args, "checkpoint", None) not in {None, "best"}:
        value = Path(args.checkpoint)
        args.checkpoint = str(value if value.is_absolute() else config.project_root / value)
    if args.command in MODEL_PHASES:
        return execute_phase(config, args)
    if args.command == "prepare":
        from .corpus import PreparationError, prepare

        try:
            return "ok", prepare(config, suite_path(config, args), draft=args.draft_without_proof)
        except PreparationError as exc:
            return ("blocked" if exc.status == "blocked_dependency" else "invalid"), {
                "status": exc.status, "reason": exc.reason, **exc.detail}
    if args.command == "verify-resources":
        from .inventory import resource_report

        report = resource_report(config, args.phase, suite_dir=args.suite_dir,
                                 hash_weights=not args.skip_weight_hashes)
        return ("ok" if report["status"] == "ready" else "blocked"), report
    if args.command == 'evaluation-inputs':
        from .evaluation import evaluation_input_preflight
        from ..contracts import PipelineError
        try:
            return 'ok', evaluation_input_preflight(config)
        except PipelineError as exc:
            return 'blocked', {'status':'blocked_dependency','reason':str(exc),
                               'error':exc.record(),'models_loaded':False}
    if args.command == "preflight":
        from .inventory import preflight

        report = preflight(config, suite_path(config, args), args.experiment, settings_path=args.settings, policy_report=args.policy_report)
        return ("ok" if report["status"] == "ready" else "invalid" if report["status"] == "failed_preflight" else "blocked"), report
    if args.command == "token-audit":
        return token_audit(config, args)
    if args.command == "seal-selection-policy":
        from .corpus import PreparationError, seal_selection_policy

        try:
            return "ok", seal_selection_policy(suite_path(config, args), loads(args.policy.read_text(encoding="utf-8")))
        except (PreparationError, ConfigError) as exc:
            return "invalid", {"status": "failed_preflight", "reason": str(exc)}
    if args.command == "compare":
        from .reporting import compare

        return "ok", compare(suite_path(config, args), loads(args.runs.read_text(encoding="utf-8")), config=config)
    if args.command == "evaluate":
        return evaluate(config, args)
    if args.command == "deployment-check":
        from .deployment import deployment_check
        from .corpus import load_suite
        result = deployment_check(args.evidence, load_suite(suite_path(config, args))["partition"]["validation_ids"])
        return ("ok" if result["status"] == "passed" else "blocked"), result
    raise UsageError("Unknown command")


def status(args) -> dict:
    """Model-free view of a suite's artifacts; reads no models, data or environments."""
    from .storage import read_json

    if args.suite_dir is None:
        return {"status": "ok", "package": "lifemate.llm_training", "authored_scope": "LL001-LL048",
                "execution_acceptance": "see fine-tune-llm/HANDOFF.md; authoring does not pass RV gates"}
    if args.project_root is not None and not args.suite_dir.is_absolute():
        args.suite_dir = args.project_root / args.suite_dir
    suite = read_json(args.suite_dir / "suite.json")

    def listing(name):
        folder = args.suite_dir / name
        return sorted(p.name for p in folder.iterdir() if p.is_dir()) if folder.is_dir() else []

    return {"status": suite.get("status"), "suite_id": suite.get("suite_id"),
            "sealed": (args.suite_dir / "SEAL.json").is_file(), "decoder_proof": suite.get("decoder_proof"),
            "selection_policies": listing("selection-policies"), "token_audits": listing("token-audits"),
            "evaluations": listing("evaluations"), "comparisons": listing("comparisons"),
            "counts": suite.get("counts")}


def token_audit(config, args) -> tuple[str, dict]:
    if args.scope == "decoder-poc":
        from .decoder_poc import run_proof

        # --output-root is the proof parent for this scope; it also bounds writable paths.
        target = config.require("output_root") if args.output_root else (config.require("output_root") / "decoder-poc")
        output = contained_output(config.require("output_root"), target)
        catalog = config.require("data_root") / "train" / "train_tools_catalog.json"
        outcome = run_proof(output, config.paths["model_dir"], catalog)
        return {"passed": "ok", "blocked": "blocked"}.get(outcome["status"], "error"), outcome
    from .acceptance import audit_corpus, native_acceptance, matching_proof
    from .corpus import load_suite
    from .tokenization import load_tokenizer
    suite_dir = suite_path(config, args) if args.suite_dir else None
    if suite_dir is not None:
        matching_proof(config, load_suite(suite_dir))
    elif args.scope != "native":
        raise UsageError("--suite-dir required for corpus token auditing")
    rows = None
    if args.scope == "asr":
        from .storage import read_jsonl, verify_seal
        if args.view_dir is None:
            raise UsageError("ASR audit requires --view-dir from build-asr-views")
        verify_seal(args.view_dir)
        rows = read_jsonl(args.view_dir / "fit.asr-approved.jsonl")
    tokenizer = load_tokenizer(config.require("model_dir"))
    result = (native_acceptance(config, suite_dir, tokenizer) if args.scope == "native" else
              audit_corpus(config, suite_dir, tokenizer, scope=args.scope, rows=rows, view_dir=args.view_dir))
    return ("ok" if result["status"] == "passed" else "error"), result


def evaluate(config, args) -> tuple[str, dict]:
    if args.experiment == "L0" and args.export is not None:
        return "invalid", {"status": "failed_preflight", "reason": "L0 evaluates the pinned pretrained model only"}
    from ..adapters.planner import LocalPlanner
    from ..runtime import load_runtime
    from .evaluation import TransformersBackend, identity_of_model, limits, run_closed_loop, run_teacher_forced
    from .acceptance import evaluation_readiness
    from .corpus import load_suite, sealed_policy

    suite_dir = suite_path(config, args)
    if args.full_audio:
        if args.protocol != "closed_loop":
            raise UsageError("Full audio uses only closed loop")
        from .pilot import run_audio
        return "ok", run_audio(config, suite_dir, experiment=args.experiment, export=args.export, device=args.device,
                               continue_on_error=args.continue_on_error)
    readiness = evaluation_readiness(config, suite_dir, teacher_forced=args.protocol == "teacher_forced", mode=args.mode)
    sealed_policy(suite_dir)
    if args.protocol == 'closed_loop':
        from .evaluation import evaluation_input_preflight
        evaluation_input_preflight(config,partition=load_suite(suite_dir)['partition'],
                                   input_mode='transcript' if args.mode=='G' else 'audio')
    from .resources import validate_lock
    validate_lock(config)
    model_dir = config.require("model_dir")
    if args.experiment == "L0":
        identity = identity_of_model(model_dir)
    else:
        from .export import export_identity
        if args.export is None:
            raise UsageError("Trained evaluation requires --export")
        identity = export_identity(args.export, config, suite_dir)
        if identity["experiment"] != args.experiment:
            raise ValueError("Cross-experiment export rejected")
        model_dir = args.export / "model"
    asr = None
    if args.mode == "A":
        from .asr_views import CacheASR
        asr = CacheASR(config.require("validation_asr_cache"), config, load_suite(suite_dir)["partition"])
    planner = LocalPlanner(model_dir, args.device, limits(), 20261027)
    if args.protocol == "teacher_forced":
        return "ok", run_teacher_forced(suite_dir=suite_dir, experiment=args.experiment, mode=args.mode,
                                        backend=TransformersBackend(planner), model_identity=identity, transcripts=asr, config=config)
    return "ok", run_closed_loop(config=config, suite_dir=suite_dir, experiment=args.experiment, mode=args.mode,
                                 planner=planner, asr=asr, runtime_loader=load_runtime, model_identity=identity,
                                 continue_on_error=args.continue_on_error, trace_payloads=args.trace_payloads)


def execute_phase(config, args):
    permitted = {"resume_from": {"train"}, "policy_report": {"train"}, "checkpoint": {"export"},
                 "run_dir": {"export"}, "export": {"verify-export"}, "fit_cache": {"build-asr-views"},
                 "smoke_fixtures": {"probe"}, "profile": {"gpu-preflight", "latency-pilot"}, "nf4": {"gpu-preflight"},
                 "include_asr": {"probe"}, "settings": {"train", "probe", "gpu-preflight"}}
    for key, phases in permitted.items():
        if getattr(args, key, None) and args.command not in phases:
            raise UsageError(f"--{key.replace('_', '-')} is not used by {args.command}")
    if (args.command in {"train", "probe", "gpu-preflight"} and args.device != "cuda") or \
            (args.command != "probe" and args.scope != "full"):
        raise UsageError("Training/probes require explicit CUDA; smoke/full scope belongs to probe only")
    suite = suite_path(config, args) if args.suite_dir else None
    if args.command == "build-asr-views":
        from .asr_views import build_views
        if suite is None:
            raise UsageError("--suite-dir required")
        return "ok", build_views(config, suite, args.fit_cache or config.require("fit_asr_cache"),
                                  reviews_path=config.paths["manual_reviews"])
    if args.command == "latency-pilot":
        from .resources import validate_lock
        validate_lock(config)
        from .pilot import run_audio
        if suite is None:
            raise UsageError("--suite-dir required")
        return "ok", run_audio(config, suite, experiment=args.experiment, pilot=True, device=args.device, profile=args.profile)
    if args.command in {"export", "verify-export"}:
        from .resources import validate_lock
        validate_lock(config)
        from .export import export_model, verify_export
        if suite is None:
            raise UsageError("--suite-dir required")
        if args.command == "verify-export":
            if args.export is None:
                raise UsageError("--export required")
            result = verify_export(config, suite, args.export, device=args.device)
        else:
            if args.run_dir is None or args.checkpoint is None:
                raise UsageError("Export requires --run-dir and --checkpoint best or path")
            from .storage import read_json
            if args.checkpoint == "best":
                pointer = read_json(args.run_dir / "best.json")
                from ..jsonio import contained
                checkpoint = contained(suite if pointer.get("root") == "suite" else args.run_dir,
                                       pointer["checkpoint"], must_exist=False)
            else:
                checkpoint = Path(args.checkpoint)
            result = export_model(config, suite, args.run_dir, checkpoint)
        return ("ok" if result["status"] in {"passed", "exported_pending_verification"} else "error"), result
    from .trainer import training_settings
    from .resources import validate_lock
    validate_lock(config)
    settings = training_settings(args.settings or config.project_root / "fine-tune-llm/configs/training.json")
    if args.command == "gpu-preflight":
        from .resources import gpu_preflight
        result = gpu_preflight(config.require("output_root"), profile=args.profile or config.source["environment_profile"],
                               precision=settings["precision"], nf4=args.nf4)
    elif args.command == "probe":
        from .qualification import probe
        result = probe(config, suite, settings, scope=args.scope, smoke_fixtures=args.smoke_fixtures, include_asr=args.include_asr)
    else:
        from .trainer import train
        if suite is None:
            raise UsageError("--suite-dir required")
        result = train(config, suite, args.experiment, settings, resume=args.resume_from, policy_report=args.policy_report,
                       resource_record=config.require("resource_qualification"), latency_decision=config.require("latency_decision"))
    return ("ok" if result["status"] in {"passed", "passed_early_smoke", "completed_full_budget"} else "blocked"), result


def main(argv=None) -> int:
    try:
        args = parser().parse_args(argv)
        kind, summary = run(args)
    except (UsageError, ConfigError) as exc:
        kind, summary = "invalid", {"status": "failed_preflight", "reason": str(exc)}
    except Exception as exc:  # Bounded, sanitized summary; details stay out of stdout.
        from ..contracts import PipelineError
        from .corpus import PreparationError

        if isinstance(exc, PreparationError):
            kind, summary = "blocked" if exc.status == "blocked_dependency" else "invalid", {
                "status": exc.status, "reason": exc.reason, **exc.detail}
        elif isinstance(exc, PipelineError):
            kind, summary = "error", {"status": "failed", "error": exc.record()}
        else:
            kind, summary = "error", {"status": "failed", "error": f"{type(exc).__name__}"}
        print(f"llm_training failed: {type(exc).__name__}: {str(exc)[:300]}", file=sys.stderr)
    print(dumps(summary))
    return EXIT[kind]
