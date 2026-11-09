"""Offline empty/clarification diagnostics for integration runs (US4).

Train references are joined only after inference, from the run journal; nothing in
the inference path imports this module, so labels never reach ASR, planner or tools.
Train labels carry gold calls but no gold ``state_hash``: hash-gated scores are
reported as unavailable, never reconstructed. Failures and timeouts stay in every
denominator and are never counted as empty predictions.

    python -m lifemate.diagnostics --run RUN_ROOT --references DATA/train/train.jsonl \
        --catalog DATA/train/train_tools_catalog.json [--paired-audio AUDIO_RUN_ROOT] [--output report.json]
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

from .artifacts import JournalState, _check
from .contracts import JSON, PipelineError
from .jsonio import dumps, loads, read_json

ASK = "sys.ask_missing_info"


def read_journal(root: Path) -> JournalState:
    """Validate a finished run's journal read-only (no ownership is taken)."""
    state = JournalState()
    try:
        lines = (root / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise PipelineError("JOURNAL_INVALID", "Run journal is unreadable", "diagnostics") from exc
    for line in lines:
        record = loads(line)
        if not isinstance(record, dict) or record.pop("check", None) != _check(record):
            raise PipelineError("JOURNAL_INVALID", "Run journal checksum mismatch", "diagnostics")
        state.apply(record)
    return state


def read_references(path: Path, ids: set[str]) -> dict[str, JSON]:
    """Gold calls and visible structure for the selected IDs only."""
    references = {}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = loads(line)
            if row.get("id") in ids:
                label = row.get("label")
                if not isinstance(label, dict) or not isinstance(label.get("tool_calls"), list):
                    raise PipelineError("INPUT_INVALID", "Reference row lacks label.tool_calls", "diagnostics")
                references[row["id"]] = {"calls": label["tool_calls"], "history_turns": len(row.get("history") or [])}
    return references


def fuzzy_fields(catalog: JSON) -> dict[str, set[str]]:
    fields = {}
    for app in catalog.get("apps", []):
        for tool in app.get("tools", []):
            properties = tool.get("parameters", {}).get("properties", {})
            fields[tool["name"]] = {k for k, v in properties.items() if isinstance(v, dict) and v.get("x-match") == "fuzzy"}
    return fields


def tokens(value) -> list[str]:
    return re.findall(r"\w+", unicodedata.normalize("NFC", str(value)).lower())


def token_f1(predicted, gold) -> float:
    left, right = tokens(predicted), tokens(gold)
    if not left or not right:
        return float(left == right)
    common = sum(min(left.count(t), right.count(t)) for t in set(left))
    if not common:
        return 0.0
    precision, recall = common / len(left), common / len(right)
    return 2 * precision * recall / (precision + recall)


def calls_match(predicted: JSON, gold: JSON, fuzzy: dict[str, set[str]]) -> bool:
    if predicted.get("name") != gold.get("name"):
        return False
    left, right = predicted.get("arguments", {}), gold.get("arguments", {})
    if set(left) != set(right):
        return False
    loose = fuzzy.get(gold["name"], set())
    return all(token_f1(left[k], right[k]) > 0.6 if k in loose else left[k] == right[k] for k in right)


def match_calls(predicted: list[JSON], gold: list[JSON], fuzzy) -> JSON:
    """Benchmark call matching: each call matches at most once; order is ignored."""
    unused = list(range(len(gold)))
    matched = 0
    for call in predicted:
        for index in unused:
            if calls_match(call, gold[index], fuzzy):
                unused.remove(index)
                matched += 1
                break
    unmatched = len(predicted) - matched
    if not gold:
        return {"matched": 0, "unmatched": unmatched, "f1_without_state_gate": float(not predicted)}
    precision = matched / (matched + unmatched) if predicted else 0.0
    recall = matched / len(gold)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"matched": matched, "unmatched": unmatched, "f1_without_state_gate": f1}


def ask(calls: list[JSON]) -> JSON | None:
    return next((c for c in calls if c.get("name") == ASK), None)


def sample_row(sample_id: str, reference: JSON, state: JournalState, fuzzy) -> JSON:
    attempt = state.by_sample.get(sample_id)
    terminal = state.terminal.get(attempt) if attempt else None
    status = terminal["status"] if terminal else ("uncertain" if attempt else "not_attempted")
    gold = reference["calls"]
    gold_ask = ask(gold)
    row = {"id": sample_id, "status": status,
           "error": terminal["error"].get("code") if terminal and terminal["type"] == "fail" else None,
           "groups": {"empty_gold": not gold, "clarification_gold": gold_ask is not None,
                      "clarification_after_calls": gold_ask is not None and gold.index(gold_ask) > 0,
                      "single_call": len(gold) == 1 and gold_ask is None,
                      "multi_call": len(gold) >= 2, "history": reference["history_turns"] > 0}}
    if terminal is None or terminal["type"] != "accept":
        return row | {"accepted": False}
    predicted = terminal["prediction"]["tool_calls"]
    predicted_ask = ask(predicted)
    match = match_calls(predicted, gold, fuzzy)
    row.update(accepted=True, predicted_empty=not predicted, predicted_clarification=predicted_ask is not None,
               clarification_waiting=status == "needs_info", match=match,
               exact_calls=match["matched"] == len(gold) == len(predicted))
    if predicted_ask is not None and gold_ask is not None:
        p, g = predicted_ask.get("arguments", {}), gold_ask.get("arguments", {})
        row["clarification_tool_correct"] = p.get("tool_name") == g.get("tool_name")
        row["clarification_params_correct"] = sorted(p.get("params") or []) == sorted(g.get("params") or [])
    return row


def ratio(numerator: int, denominator: int) -> JSON:
    return {"count": numerator, "denominator": denominator,
            "rate": numerator / denominator if denominator else None}


def summarize(rows: list[JSON]) -> JSON:
    accepted = [r for r in rows if r["accepted"]]
    failures = [r for r in rows if not r["accepted"]]
    empty_gold = [r for r in rows if r["groups"]["empty_gold"]]
    nonempty_gold = [r for r in rows if not r["groups"]["empty_gold"]]
    clar_gold = [r for r in rows if r["groups"]["clarification_gold"]]
    clar_pred = [r for r in accepted if r["predicted_clarification"]]
    both = [r for r in clar_pred if r["groups"]["clarification_gold"]]
    groups = {}
    for name in ("empty_gold", "clarification_gold", "clarification_after_calls", "single_call", "multi_call", "history"):
        members = [r for r in rows if r["groups"][name]]
        groups[name] = {"samples": len(members),
                        "exact_calls": ratio(sum(r.get("exact_calls") is True for r in members), len(members)),
                        "failed_or_timeout": sum(not r["accepted"] for r in members)}
    return {
        "samples": len(rows), "accepted": len(accepted),
        "accepted_statuses": {s: sum(r["status"] == s for r in accepted)
                              for s in ("completed", "needs_info", "partial")},
        "coverage_note": "Accepted coverage includes partial execution and does not establish correctness",
        "runtime_failures": {s: sum(r["status"] == s for r in failures)
                             for s in ("timeout", "failed", "uncertain", "not_attempted")},
        "empty": {"empty_gold_correct": ratio(sum(r.get("predicted_empty") is True for r in empty_gold), len(empty_gold)),
                  "empty_gold_with_calls": sum(r.get("predicted_empty") is False for r in empty_gold),
                  "empty_gold_failed_or_timeout": sum(not r["accepted"] for r in empty_gold),
                  "false_empty": ratio(sum(r.get("predicted_empty") is True for r in nonempty_gold), len(nonempty_gold))},
        "clarification": {
            "precision": ratio(len(both), len(clar_pred)), "recall": ratio(len(both), len(clar_gold)),
            "intended_tool_correct": ratio(sum(r.get("clarification_tool_correct") is True for r in both), len(both)),
            "missing_params_correct": ratio(sum(r.get("clarification_params_correct") is True for r in both), len(both)),
            "unnecessary": ratio(sum(not r["groups"]["clarification_gold"] for r in clar_pred), len(clar_pred)),
            "unsuccessful": sum(not r["clarification_waiting"] for r in clar_pred),
            "gold_failed_or_timeout": sum(not r["accepted"] for r in clar_gold)},
        "groups": groups,
        "unavailable": {"state_hash_match": "Train labels carry no gold state_hash",
                        "official_score": "Requires organizer replay; not reconstructed"},
    }


def paired(transcript: list[JSON], audio: list[JSON]) -> JSON:
    """Attribute differences on identical IDs: transcript exact but audio not suggests speech error."""
    by_id = {r["id"]: r for r in audio}
    counts = {"both_exact": 0, "speech_attributed": 0, "audio_only_exact": 0, "both_inexact": 0,
              "failure_in_either": 0, "missing_pair": 0}
    speech = []
    for row in transcript:
        other = by_id.get(row["id"])
        if other is None:
            counts["missing_pair"] += 1
        elif not row["accepted"] or not other["accepted"]:
            counts["failure_in_either"] += 1
        elif row["exact_calls"] and other["exact_calls"]:
            counts["both_exact"] += 1
        elif row["exact_calls"]:
            counts["speech_attributed"] += 1
            speech.append(row["id"])
        elif other["exact_calls"]:
            counts["audio_only_exact"] += 1
        else:
            counts["both_inexact"] += 1
    return {"counts": counts, "speech_attributed_ids": speech}


def report(run: Path, references: Path, catalog: Path) -> JSON:
    state = read_journal(run)
    selected = list(state.header.get("selected_ids", []))
    refs = read_references(references, set(selected))
    missing = [i for i in selected if i not in refs]
    if missing:
        raise PipelineError("INPUT_INVALID", "References lack selected IDs", "diagnostics")
    fuzzy = fuzzy_fields(read_json(catalog, "CATALOG_INVALID"))
    rows = [sample_row(i, refs[i], state, fuzzy) for i in selected]
    return {"run_sha256": state.header.get("run_sha256"), "selected_ids": selected,
            "summary": summarize(rows), "samples": rows}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m lifemate.diagnostics")
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--references", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--paired-audio", type=Path, help="Audio run on the same IDs; --run is the transcript run")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = report(args.run, args.references, args.catalog)
        if args.paired_audio is not None:
            audio = report(args.paired_audio, args.references, args.catalog)
            result["paired"] = paired(result["samples"], audio["samples"]) | {
                "audio_run_sha256": audio["run_sha256"], "audio_summary": audio["summary"]}
        text = dumps(result)
        if args.output is not None:
            args.output.write_text(text + "\n", encoding="utf-8")
        print(dumps({"status": "reported", "summary": result["summary"], "paired": result.get("paired", {}).get("counts")}))
        return 0
    except (PipelineError, OSError, ValueError) as exc:
        code = exc.record() if isinstance(exc, PipelineError) else {"code": "INPUT_INVALID", "message": type(exc).__name__}
        print(dumps({"status": "failed", "error": code}), file=sys.stdout)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
