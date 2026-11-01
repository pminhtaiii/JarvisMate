"""`python -m lifemate.training`: offline operations outside the inference path."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..contracts import PipelineError
from ..jsonio import dumps
from .data import DEFAULT_SEED, DEFAULT_VALIDATION_FRACTION, partition


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
    return root


def main(argv=None) -> int:
    try:
        args = parser().parse_args(argv)
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
