"""`python -m lifemate.training`: offline operations outside the inference path."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..contracts import Limits, PipelineError
from ..jsonio import dumps
from .data import DEFAULT_SEED, DEFAULT_VALIDATION_FRACTION, export, partition
from .export import merge
from .fit import fit


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise PipelineError("INPUT_INVALID", "Invalid command arguments; consult --help", "arguments")


def parser() -> Parser:
    root = Parser(prog="python -m lifemate.training", description="Offline LifeMate planner-training tools")
    sub = root.add_subparsers(dest="command", required=True, parser_class=Parser)
    split = sub.add_parser("partition", help="Freeze a grouped Train fit/validation partition")
    split.add_argument("--data-root", required=True, type=Path)
    split.add_argument("--output", required=True, type=Path)
    split.add_argument("--seed", default=DEFAULT_SEED, type=int)
    split.add_argument("--validation-fraction", default=DEFAULT_VALIDATION_FRACTION, type=float)
    split.add_argument("--decisions", type=Path, help="Reviewed group/separate decisions for candidate pairs")
    rows = sub.add_parser("export", help="Export audited fit-only native next-action SFT rows")
    rows.add_argument("--data-root", required=True, type=Path)
    rows.add_argument("--partition", required=True, type=Path)
    rows.add_argument("--base-model", required=True, type=Path)
    rows.add_argument("--output", required=True, type=Path, help="New directory; never overwritten")
    rows.add_argument("--validation-diagnostics", action="store_true",
                      help="Also write teacher-forced validation rows to a separate diagnostic file")
    rows.add_argument("--context-tokens", default=Limits.context_tokens, type=int)
    rows.add_argument("--output-tokens", default=Limits.output_tokens, type=int)
    train = sub.add_parser("fit", help="Fit a LoRA/QLoRA adapter on audited fit rows")
    train.add_argument("--config", required=True, type=Path, help="JSON fit configuration")
    train.add_argument("--preflight-only", action="store_true",
                       help="Audit inputs, packages, device and memory without updating weights")
    join = sub.add_parser("merge", help="Merge an adapter onto its original base for deployment")
    join.add_argument("--base-model", required=True, type=Path)
    join.add_argument("--adapter", required=True, type=Path, help="A checkpoint directory written by fit")
    join.add_argument("--output", required=True, type=Path, help="New directory; never overwritten")
    return root


def main(argv=None) -> int:
    try:
        args = parser().parse_args(argv)
        if args.command == "fit":
            manifest = fit(args.config, preflight_only=args.preflight_only)
            print(dumps({"status": manifest["status"], "output": manifest["output_dir"],
                         "checkpoints": [c["path"] for c in manifest["checkpoints"]],
                         "memory": manifest.get("memory")}))
            return 0
        if args.command == "merge":
            marker = merge(args.base_model, args.adapter, args.output)
            print(dumps({"status": marker["status"], "output": str(args.output.resolve()),
                         "parameters": marker["parameters"], "reload_verified": marker["reload_verified"]}))
            return 0
        if args.command == "export":
            limits = Limits(context_tokens=args.context_tokens, output_tokens=args.output_tokens)
            manifest = export(args.data_root, args.partition, args.base_model, args.output,
                              validation_diagnostics=args.validation_diagnostics, limits=limits)
            print(dumps({"status": "completed", "output": str(args.output.resolve()),
                         "rows": {side: summary["rows"] for side, summary in manifest["rows"].items()},
                         "exclusions": manifest["exclusions"]["by_reason"]}))
            return 0
        manifest = partition(args.data_root, args.output, seed=args.seed,
                             validation_fraction=args.validation_fraction, decisions_path=args.decisions)
        print(dumps({"status": "completed", "output": str(args.output.resolve()),
                     "grouping_method": manifest["grouping_method"], "counts": manifest["counts"],
                     "smoke_ids_absent": manifest["smoke_ids"]["absent"]}))
        return 0
    except PipelineError as exc:
        print(dumps({"status": "failed", "error": exc.record()}))
        return 2 if exc.code in {"INPUT_INVALID", "ASSET_MISSING", "CATALOG_INVALID"} else 1


if __name__ == "__main__":
    sys.exit(main())
