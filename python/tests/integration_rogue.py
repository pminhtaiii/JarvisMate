"""Protocol-misbehaving worker for supervisor IPC tests: ``-m integration_rogue MODE``."""
import argparse
import os
import sys
import time
from pathlib import Path

from lifemate.artifacts import FileLock
from lifemate.worker import HEADER, encode_frame, read_frame


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode")
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--generation", type=int)
    args = parser.parse_args()
    lock = FileLock(args.run_root / "workers" / f"gen-{args.generation}.lock")
    assert lock.acquire()
    out, source = sys.stdout.buffer, sys.stdin.buffer

    def send(message):
        out.write(encode_frame(message))
        out.flush()

    if args.mode == "no_ready":
        time.sleep(3600)
    send({"type": "ready", "generation": args.generation, "pid": os.getpid(), "startup_seconds": 0})
    if args.mode == "never_read":
        time.sleep(3600)
    message = read_frame(source)
    if args.mode == "partial":
        frame = encode_frame({"type": "result_ready", "attempt_id": message["attempt_id"]})
        out.write(frame[:HEADER.size + 5])
        out.flush()
    elif args.mode == "stale":
        send({"type": "result_ready", "generation": args.generation, "attempt_id": "0" * 32,
              "sample_id": message["sample_id"], "status": "completed", "files": []})
        send({"type": "result_ready", "generation": args.generation + 7, "attempt_id": message["attempt_id"],
              "sample_id": message["sample_id"], "status": "completed", "files": []})
    elif args.mode == "garbage":
        out.write(HEADER.pack(2 ** 31) + b"x")
        out.flush()
    elif args.mode == "late":
        time.sleep(float(message["budget_seconds"]) + 0.5)
        send({"type": "result_ready", "generation": args.generation, "attempt_id": message["attempt_id"],
              "sample_id": message["sample_id"], "status": "completed", "files": ["outcome.json"]})
    time.sleep(3600)


if __name__ == "__main__":
    main()
