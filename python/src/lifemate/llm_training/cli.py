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

NOT_IMPLEMENTED = {"gpu-preflight": "LL025", "probe": "LL027", "latency-pilot": "LL032", "train": "LL029",
                   "export": "LL031", "verify-export": "LL031", "build-asr-views": "LL036"}
OVERRIDES = ("data_root", "model_dir", "asr_model_dir", "split_manifest", "fit_asr_cache",
             "validation_asr_cache", "output_root", "runtime_dir", "native_decoder_proof", "manual_reviews")
EXIT = {"ok": 0, "error": 1, "invalid": 2, "not_implemented": 3, "blocked": 4}


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
    child = command("verify-resources", config=True, suite="optional")
    child.add_argument("--phase", default="prepare", choices=("prepare", "decoder-poc", "token-audit", "evaluate-G",
                                                              "evaluate-A", "pilot", "train", "compare"))
    child.add_argument("--skip-weight-hashes", action="store_true")
    command("preflight", suite="required", experiment=True)
    child = command("token-audit", suite="optional")
    child.add_argument("--scope", required=True, choices=("decoder-poc", "clean", "asr"))
    command("seal-selection-policy", suite="required").add_argument("--policy", type=Path, required=True)
    child = command("evaluate", suite="required", experiment=True)
    child.add_argument("--mode", required=True, choices=MODES)
    child.add_argument("--protocol", default="closed_loop", choices=("closed_loop", "teacher_forced"))
    child.add_argument("--export", type=Path)
    child.add_argument("--device", default="cuda", choices=("cpu", "cuda"))
    child.add_argument("--continue-on-error", action="store_true")
    child.add_argument("--trace-payloads", action="store_true")
    command("compare", suite="required").add_argument("--runs", type=Path, required=True)
    for name in NOT_IMPLEMENTED:
        child = command(name, suite="optional", experiment=name in {"probe", "latency-pilot", "train", "export",
                                                                    "verify-export"})
        child.add_argument("--profile")
        child.add_argument("--resume-from", type=Path)
        child.add_argument("--policy-report", type=Path)
        child.add_argument("--checkpoint")
        child.add_argument("--export", type=Path)
        child.add_argument("--fit-cache", type=Path)
    return root


def resolve(args):
    overrides = {key: getattr(args, key, None) for key in OVERRIDES}
    if args.config is not None:
        return load_config(args.config, project_root=args.project_root, overrides=overrides)
    suite_dir = getattr(args, "suite_dir", None)
    if suite_dir is None:
        raise UsageError("--config or --suite-dir is required")
    from .storage import read_json

    return config_from_suite(read_json(suite_dir / "suite.json"), project_root=args.project_root, overrides=overrides)


def suite_path(config, args) -> Path:
    return contained_output(config.require("output_root"), args.suite_dir)


def run(args) -> tuple[str, dict]:
    if args.command in NOT_IMPLEMENTED:
        if getattr(args, "experiment", None) == "L0" and args.command in {"train", "probe", "export"}:
            return "invalid", {"status": "failed_preflight", "reason": "L0 is the pretrained baseline and has no training phase"}
        return "not_implemented", {"status": "not_implemented", "command": args.command,
                                   "task": NOT_IMPLEMENTED[args.command],
                                   "reason": "outside the LL001-LL024 implementation scope"}
    if args.command == "status":
        return "ok", status(args)
    config = resolve(args)
    if args.command == "prepare":
        from .corpus import PreparationError, prepare

        try:
            return "ok", prepare(config, args.suite_dir, draft=args.draft_without_proof)
        except PreparationError as exc:
            return ("blocked" if exc.status == "blocked_dependency" else "invalid"), {
                "status": exc.status, "reason": exc.reason, **exc.detail}
    if args.command == "verify-resources":
        from .inventory import resource_report

        report = resource_report(config, args.phase, suite_dir=args.suite_dir,
                                 hash_weights=not args.skip_weight_hashes)
        return ("ok" if report["status"] == "ready" else "blocked"), report
    if args.command == "preflight":
        from .inventory import preflight

        report = preflight(config, suite_path(config, args), args.experiment)
        return ("invalid" if report["status"] == "failed_preflight" else "blocked"), report
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

        return "ok", compare(suite_path(config, args), loads(args.runs.read_text(encoding="utf-8")))
    if args.command == "evaluate":
        return evaluate(config, args)
    raise UsageError("Unknown command")


def status(args) -> dict:
    """Model-free view of a suite's artifacts; reads no models, data or environments."""
    from .storage import read_json

    if args.suite_dir is None:
        return {"status": "ok", "package": "lifemate.llm_training", "implemented_tasks": "LL001-LL024",
                "not_implemented_commands": NOT_IMPLEMENTED}
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
        target = args.output_root or (config.require("output_root") / "decoder-poc")
        output = contained_output(config.require("output_root"), target)
        catalog = config.require("data_root") / "train" / "train_tools_catalog.json"
        outcome = run_proof(output, config.paths["model_dir"], catalog)
        return {"passed": "ok", "blocked": "blocked"}.get(outcome["status"], "error"), outcome
    if args.scope == "asr":
        return "blocked", {"status": "blocked_dependency", "reason": "approved ASR views need LL035-LL038"}
    from .corpus import load_suite
    from .storage import new_directory, now, read_jsonl, write_json
    from .tokenization import audit_rows, flag_equivalent, load_tokenizer, proof_binding

    suite_dir = suite_path(config, args)
    load_suite(suite_dir)
    tokenizer = load_tokenizer(config.require("model_dir"))
    rows = read_jsonl(suite_dir / "data" / "fit.clean.jsonl") + read_jsonl(suite_dir / "data" / "validation.teacher-forced.jsonl")
    result = audit_rows(tokenizer, rows)
    broken = [r for r in result["rows"] if r.get("reason") in {"SERIALIZATION_MISMATCH", "TOKEN_BOUNDARY_ERROR",
                                                                 "MISSING_ASSISTANT_EOS"}]
    flags = all(flag_equivalent(tokenizer, r["input"]["messages"], r["input"]["tools"]) for r in rows[:16])
    status_value = "passed" if not broken and flags else "failed"
    directory = new_directory(suite_dir / "token-audits", "clean")
    write_json(directory / "token-audit.json", {"scope": "clean", "status": status_value, "recorded_at": now(),
                                                "binding": proof_binding(config.paths["model_dir"]),
                                                "flag_equivalence_sample": flags, **result})
    return ("ok" if status_value == "passed" else "error"), {"status": status_value, "directory": str(directory),
                                                             "counts": result["counts"], "broken_contract_rows": len(broken)}


def evaluate(config, args) -> tuple[str, dict]:
    if args.mode == "A":
        return "blocked", {"status": "blocked_dependency", "reason": "cache-backed A-mode ASR adapter is LL040"}
    if EXPERIMENTS[args.experiment]["trainable"]:
        return "blocked", {"status": "blocked_dependency",
                           "reason": "trained experiments need a verified actual export (LL031)"}
    if args.export is not None:
        return "invalid", {"status": "failed_preflight", "reason": "L0 evaluates the pinned pretrained model only"}
    from ..adapters.planner import LocalPlanner
    from ..runtime import load_runtime
    from .evaluation import TransformersBackend, identity_of_model, limits, run_closed_loop, run_teacher_forced

    suite_dir = suite_path(config, args)
    model_dir = config.require("model_dir")
    planner = LocalPlanner(model_dir, args.device, limits(), 20261027)
    identity = identity_of_model(model_dir)
    if args.protocol == "teacher_forced":
        return "ok", run_teacher_forced(suite_dir=suite_dir, experiment=args.experiment, mode=args.mode,
                                        backend=TransformersBackend(planner), model_identity=identity)
    return "ok", run_closed_loop(config=config, suite_dir=suite_dir, experiment=args.experiment, mode=args.mode,
                                 planner=planner, runtime_loader=load_runtime, model_identity=identity,
                                 continue_on_error=args.continue_on_error, trace_payloads=args.trace_payloads)


def main(argv=None) -> int:
    try:
        args = parser().parse_args(argv)
        kind, summary = run(args)
    except (UsageError, ConfigError) as exc:
        kind, summary = "invalid", {"status": "failed_preflight", "reason": str(exc)}
    except Exception as exc:  # Bounded, sanitized summary; details stay out of stdout.
        from ..contracts import PipelineError

        if isinstance(exc, PipelineError):
            kind, summary = "error", {"status": "failed", "error": exc.record()}
        else:
            kind, summary = "error", {"status": "failed", "error": f"{type(exc).__name__}"}
        print(f"llm_training failed: {type(exc).__name__}: {str(exc)[:300]}", file=sys.stderr)
    print(dumps(summary))
    return EXIT[kind]
