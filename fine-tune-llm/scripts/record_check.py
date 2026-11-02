"""Run exactly one explicit check and preserve command/source/environment/output evidence."""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/"python/src"))


def main():
    from lifemate.llm_training.resources import host_inventory
    from lifemate.llm_training.storage import new_directory, source_provenance, write_json, file_hash
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--output-root", type=Path, default=Path(".agent-work/llm-implementation/checks"))
    parser.add_argument("--timeout", type=float, default=900.)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("One command after -- is required")
    directory = new_directory(args.output_root, args.label)
    root = Path(__file__).resolve().parents[2]
    evidence = {"label": args.label, "argv": command, "source": source_provenance(root),
                "environment": host_inventory(root), "cwd": str(root),
                "opt_in": {k: v for k, v in os.environ.items() if k.startswith("LIFEMATE_LLM_")}}
    write_json(directory/"started.json", evidence)
    started = time.monotonic()
    with (directory/"stdout.log").open("wb") as stdout, (directory/"stderr.log").open("wb") as stderr:
        try:
            result = subprocess.run(command, cwd=root, stdout=stdout, stderr=stderr, timeout=args.timeout)
            code, reason = result.returncode, None
        except subprocess.TimeoutExpired:
            code, reason = 124, "check_timeout; no downstream phase was invoked"
    evidence.update(exit_code=code, elapsed_seconds=time.monotonic()-started, reason=reason,
                    logs={name: file_hash(directory/name) for name in ("stdout.log", "stderr.log")})
    write_json(directory/"outcome.json", evidence)
    print(str(directory))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
