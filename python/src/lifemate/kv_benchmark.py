"""Paired KV OFF/ON smoke16 runner/report. Never schedules jobs or resumes runs.

Run only on a separately allocated GPU, from branch 009; all artifacts go under a
new run root. Startup is reported separately from supervisor-measured sample time.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from .artifacts import atomic_json
from .configuration import load_config
from .contracts import PipelineError
from .diagnostics import read_journal
from .jsonio import dumps, loads

SMOKE16 = ("public_0099", "public_0110", "public_0187", "public_0213", "public_0240", "public_0287",
           "public_0340", "public_0342", "public_0356", "public_0363", "public_0606", "public_0391",
           "public_0329", "public_0336", "public_0699", "public_0403")


def toml_record(value: dict) -> str:
    def scalar(v):
        return str(v).lower() if isinstance(v, bool) else json.dumps(v, ensure_ascii=False)
    return "schema_version = 1\n" + "".join(
        f"\n[{section}]\n" + "".join(f"{key} = {scalar(v)}\n" for key, v in table.items())
        for section, table in value.items() if section != "schema_version")


def prepare(config_path: Path, ids_path: Path, root: Path) -> tuple[Path, Path]:
    config = load_config(config_path)
    ids = tuple(s.strip() for s in ids_path.read_text(encoding="utf-8").splitlines()
                if s.strip() and not s.lstrip().startswith("#"))
    if ids != SMOKE16:
        raise PipelineError("INPUT_INVALID", "Benchmark requires exactly the ordered smoke16 selection", "benchmark")
    if (config.mode != "audio" or config.split != "public_test" or config.timeout_seconds != 30
            or config.soft_timeout_seconds != 28 or config.max_steps != 16
            or config.planner.max_new_tokens != 512 or config.planner.context_tokens != 16384):
        raise PipelineError("INPUT_INVALID", "Use the unchanged branch-008 public audio inference budgets", "benchmark")
    root = root.resolve()
    for source in (config.data_root, config.runtime_dir, config.planner.model_path,
                   config.asr.model_path, config.output_root):
        if root == source or root.is_relative_to(source):
            raise PipelineError("INPUT_INVALID", "Benchmark root must be outside original inputs/artifacts", "benchmark")
    root.mkdir(parents=True, exist_ok=False)
    selected = root / "selection.txt"
    selected.write_text("\n".join(ids) + "\n", encoding="utf-8")
    paths = []
    for mode, enabled in (("off", False), ("on", True)):
        value = copy.deepcopy(config.record())
        value["execution"]["reuse_kv_cache"] = enabled
        value["data"].update(select_all=False, sample_ids_file=str(selected))
        value["output"]["root"] = str(root / mode)
        path = root / f"{mode}.toml"
        path.write_text(toml_record(value), encoding="utf-8")
        load_config(path)  # Validate generated config before starting either worker.
        paths.append(path)
    return tuple(paths)


def trial(root: Path) -> dict:
    manifest = loads((root / "manifest.json").read_text(encoding="utf-8"))
    state = read_journal(root)
    samples = {}
    for sample_id in manifest["identity"]["dataset"]["selected_ids"]:
        terminal = state.terminal.get(state.by_sample.get(sample_id), {})
        worker = terminal.get("metrics", {}).get("worker", {})
        metrics = worker.get("metrics", {})
        decisions = metrics.get("decisions", [])
        planner_stats = metrics.get("planner") or {}
        reused = planner_stats.get("kv_cache_reused_tokens", 0)
        new = planner_stats.get("kv_cache_new_prefill_tokens", 0)
        samples[sample_id] = {"status": terminal.get("status", "not_accepted"),
                              "stop_reason": worker.get("stop_reason"),
                              "accepted": terminal.get("type") == "accept",
                              "prediction": terminal.get("prediction"),
                              "sample_seconds": terminal.get("metrics", {}).get("attempt_seconds"),
                              "planner": metrics.get("planner"), "steps": decisions,
                              "reused_token_ratio": reused / (reused + new) if reused + new else None,
                              "peak_gpu_memory_bytes": worker.get("peak_memory_bytes")}
    return {"effective_config": manifest["effective_config"], "identity": manifest["identity"], "host": manifest["host"],
            "startup": manifest["timings"].get("startup"), "report": manifest["report"], "samples": samples}


def compare(root: Path) -> dict:
    off, on = trial(root / "off"), trial(root / "on")
    settings = []
    for record in (off, on):
        value = copy.deepcopy(record["effective_config"])
        value["execution"].pop("reuse_kv_cache")
        value["output"].pop("root")
        settings.append(value)
    hardware_equal = all(off["host"].get(k) == on["host"].get(k) for k in ("nvidia_smi", "visible_devices"))
    compatible = (settings[0] == settings[1] and hardware_equal and all(
        off["identity"][key] == on["identity"][key]
        for key in ("planner", "asr", "dataset", "code", "packages", "runtime_source_sha256")))
    comparisons = {}
    for sample_id in SMOKE16:
        left, right = off["samples"].get(sample_id, {}), on["samples"].get(sample_id, {})
        accepted = left.get("accepted") is True and right.get("accepted") is True
        normal = left.get("status") in {"completed", "needs_info"} and right.get("status") in {"completed", "needs_info"}
        def decisions(record, field):
            rows = record.get("steps", [])
            return [r[field] for r in rows] if rows and all(field in r for r in rows) else None
        tokens_left, tokens_right = decisions(left, "generated_token_ids"), decisions(right, "generated_token_ids")
        actions_left, actions_right = decisions(left, "canonical_action"), decisions(right, "canonical_action")
        comparisons[sample_id] = {
            "both_accepted": accepted, "both_normal_terminal": normal,
            "status_equal": left.get("status") == right.get("status"),
            "stop_reason_equal": left.get("stop_reason") == right.get("stop_reason"),
            "prediction_equal": left.get("prediction") == right.get("prediction") if accepted else None,
            "tokens_equal": tokens_left == tokens_right if tokens_left is not None and tokens_right is not None else None,
            "canonical_actions_equal": actions_left == actions_right if actions_left is not None and actions_right is not None else None}
    equivalent = compatible and all(r["both_accepted"] and r["status_equal"] and r["stop_reason_equal"]
                                    and r["prediction_equal"] is True
                                    and r["tokens_equal"] is True and r["canonical_actions_equal"] is True
                                    for r in comparisons.values())
    return {"compatible_inputs": compatible, "outputs_equivalent": equivalent,
            "normal_token_mismatches": [i for i, r in comparisons.items()
                                        if r["both_normal_terminal"] and r["tokens_equal"] is False],
            "off": off, "on": on, "comparison": comparisons,
            "measurement_note": "Forward prefill/decode measured separately; total includes render, grammar and sampling. "
                                "Partial/timeouts can differ with latency; inspect normal terminal token differences."}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--ids", type=Path)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        codes = []
        if not args.report_only:
            if args.config is None or args.ids is None:
                parser.error("--config and --ids are required for a new run")
            paths = prepare(args.config, args.ids, args.run_root)
            from .integration import main as run

            # Same process environment/GPU, separately spawned models and run roots.
            # Even if OFF has incomplete coverage, retain evidence and still measure ON.
            for path in paths:
                codes.append(run(["--config", str(path)]))
        report = compare(args.run_root)
        report["run_exit_codes"] = codes
        atomic_json(args.run_root / "comparison.json", report)
        print(dumps({"report": str(args.run_root / "comparison.json"),
                     "outputs_equivalent": report["outputs_equivalent"], "run_exit_codes": codes}))
        return 0 if report["outputs_equivalent"] and all(code == 0 for code in codes) else 1
    except (PipelineError, OSError, ValueError, KeyError) as exc:
        record = exc.record() if isinstance(exc, PipelineError) else {"code": "INPUT_INVALID", "message": str(exc)[:300]}
        print(dumps({"error": record}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
