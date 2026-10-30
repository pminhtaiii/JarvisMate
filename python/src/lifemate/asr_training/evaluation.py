"""Parent-side evaluator. Inference subprocesses receive audio paths only."""
from __future__ import annotations

from pathlib import Path
import time
import sys

from asr.pretrained.data import audio_asset
from asr.pretrained.metrics import summarize, NORMALIZATION
from asr.pretrained.runner import result_row, TIMING
from .slots import SlotEvaluator
from .storage import append, rows, read, write
from .workers import Session


def slot_evaluator(suite: Path, validation: list[dict]):
    path = suite / "data/slots.jsonl"
    return SlotEvaluator(validation, rows(path) if path.exists() else None,
                         read(suite / "data/slot-rules.json") if path.exists() else None)


def evaluate(job: dict, validation: list[dict], data_root: Path, output: Path, slots,
             *, session_factory=Session) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    config, results, initialization, failure, memory = job["config"], [], {}, None, None
    failure_status = None
    failure_memory = None
    representation = "native_nf4" if job.get("native") else "base_fp16" if config.get("experiment") == "E0" else "merged_fp16"
    def prediction_row(item, response):
        return result_row(item, response) | {"experiment": config.get("experiment"),
                "checkpoint_id": job.get("checkpoint"), "representation": representation}
    session = None
    try:
        session = session_factory(job)
        initialization = session.receive(config["load_timeout_seconds"])
        if initialization["status"] != "ready":
            failure_status = initialization["status"]
            failure_memory = initialization.get("memory")
            raise RuntimeError(initialization.get("error", "Model unavailable"))
        first = audio_asset(data_root / "train", validation[0]["audio"])
        warmup_started = time.perf_counter()
        response = session.request(first, config["timeout_seconds"])
        if response["status"] != "ok":
            failure_status, failure_memory = response["status"], response.get("memory")
            raise RuntimeError(response.get("error", "Warm-up failed"))
        initialization["warmup_seconds"] = time.perf_counter() - warmup_started
        for index, item in enumerate(validation, 1):
            print(f"{config.get('experiment','ASR')}: {index}/{len(validation)} {item['utterance_id']}",
                  file=sys.stderr, flush=True)
            started = time.perf_counter()
            try:
                response = session.request(audio_asset(data_root / "train", item["audio"]), config["timeout_seconds"])
                if response["status"] != "ok":
                    failure_status = response["status"]
                    failure_memory = response.get("memory")
                    response = {**response, "status": "error", "latency_seconds": time.perf_counter()-started}
            except TimeoutError as exc:
                response = {"status": "timeout", "error": str(exc), "latency_seconds": time.perf_counter()-started}
            except (OSError, RuntimeError) as exc:
                response = {"status": "error", "error": str(exc), "latency_seconds": time.perf_counter()-started}
            row = prediction_row(item, response)
            results.append(row)
            append(output / "transcripts.jsonl", row)
            if response["status"] != "ok":
                failure = response.get("error", "Inference failure")
                break
    except (OSError, RuntimeError, TimeoutError) as exc:
        failure = str(exc)
    finally:
        closing = session.close() if session else None
        memory = closing.get("memory") if closing else failure_memory or initialization.get("memory")
        for item in validation[len(results):]:
            row = prediction_row(item, {"status": "not_run", "error": failure or "Interrupted"})
            results.append(row)
            append(output / "transcripts.jsonl", row)
        metrics = summarize(results) | {"slots": slots.summarize(results), "memory": memory,
                   "initialization": initialization, "error": failure, "normalization": NORMALIZATION,
                   "timing": TIMING, "tool_call_f1": None, "final_state_match": None,
                   "pipeline_metrics_status": "unavailable: authoritative pipeline scoring was not run"}
        metrics["failure_status"] = failure_status
        metrics["representation"] = representation
        write(output / "metrics.json", metrics)
    return metrics
