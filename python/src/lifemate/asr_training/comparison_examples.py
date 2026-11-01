"""Deterministic illustrative cases and text-only error diagnostics, never slot gold."""
from __future__ import annotations

import csv
import html
import random
import re

from asr.pretrained.metrics import normalize
from .storage import EXPERIMENTS

HINTS = {
    "money": r"\b(?:\d[\d.,]*|một|hai|ba|bốn|tư|năm|sáu|bảy|tám|chín|mười|trăm|nghìn|ngàn|triệu|tỷ)\s+(?:nghìn|ngàn|triệu|tỷ|đồng|vnđ|vnd)\b|\b(?:số tiền|chuyển tiền|thanh toán)\b",
    "time": r"\b(giờ|phút|hôm|ngày|mai|tuần|tháng|tối|sáng)\b",
    "proper_name": r"\b[A-ZĐÀ-Ỵ][a-zà-ỹ]+(?:\s+[A-ZĐÀ-Ỵ][a-zà-ỹ]+)+\b",
    "code_switch": r"\b(email|meeting|team|deadline|online|zoom|google|drive|wifi|file|link|report|project|facebook|sale|customer|review|support)\b",
}


def escape(value):
    value = html.escape(str(value), quote=False)
    value = re.sub(r"([\\`*_{}\[\]~])", r"\\\1", value)
    return value.replace("|", "&#124;").replace("\r", "").replace("\n", "<br>")


def hints(reference):
    return [name for name, pattern in HINTS.items()
            if re.search(pattern, reference, flags=0 if name == "proper_name" else re.IGNORECASE)]


def ratio(row, mode="normalized", metric="wer"):
    counts = row["scores"][mode][metric]
    return counts["errors"] / counts["reference_units"] if counts["reference_units"] else None


def word_diff(reference, prediction):
    """Levenshtein alignment; same substitution/deletion/insertion tie order as WER."""
    ref, pred = reference.split(), prediction.split()
    costs = [[0] * (len(pred) + 1) for _ in range(len(ref) + 1)]
    for i in range(len(ref) + 1):
        costs[i][0] = i
    for j in range(len(pred) + 1):
        costs[0][j] = j
    for i in range(1, len(ref) + 1):
        for j in range(1, len(pred) + 1):
            costs[i][j] = min(costs[i-1][j-1] + (ref[i-1] != pred[j-1]),
                              costs[i-1][j] + 1, costs[i][j-1] + 1)
    i, j, operations = len(ref), len(pred), []
    while i or j:
        if i and j and ref[i-1] == pred[j-1] and costs[i][j] == costs[i-1][j-1]:
            operations.append(("equal", ref[i-1], pred[j-1])); i -= 1; j -= 1
        elif i and j and costs[i][j] == costs[i-1][j-1] + 1:
            operations.append(("substitute", ref[i-1], pred[j-1])); i -= 1; j -= 1
        elif i and costs[i][j] == costs[i-1][j] + 1:
            operations.append(("delete", ref[i-1], "")); i -= 1
        else:
            operations.append(("insert", "", pred[j-1])); j -= 1
    return list(reversed(operations))


def highlight(reference, prediction):
    parts = []
    for operation, ref, pred in word_diff(reference, prediction):
        if operation == "equal":
            parts.append(escape(pred))
        elif operation == "delete":
            parts.append(f"~~{escape(ref)}~~")
        else:
            parts.append(f"**{escape(pred)}**")
    return " ".join(parts) or "(empty prediction)"


def choose_cases(validation, predictions, best):
    """Two improvements, two regressions, topic hints, residual error, seed-42 fill."""
    chosen, reasons = [], {}
    index = {row["utterance_id"]: row for row in validation}
    def add(candidates, reason, limit=1):
        count = 0
        for uid in candidates:
            if uid not in reasons and len(chosen) < 10:
                chosen.append(uid); reasons[uid] = reason; count += 1
                if count >= limit:
                    break
    base, candidate = predictions.get("E0", {}), predictions.get(best, {})
    differences = {uid: ratio(base[uid]) - ratio(candidate[uid]) for uid in base.keys() & candidate.keys()
                   if ratio(base[uid]) is not None and ratio(candidate[uid]) is not None}
    add(sorted((u for u, d in differences.items() if d > 0), key=lambda u: (-differences[u], u)),
        f"largest normalized-WER improvement: {best} vs E0", 2)
    add(sorted((u for u, d in differences.items() if d < 0), key=lambda u: (differences[u], u)),
        f"largest normalized-WER regression: {best} vs E0", 2)
    ordered = sorted(index, key=lambda u: (-(ratio(candidate[u]) or 0) if u in candidate else 0, u))
    for topic in HINTS:
        add((u for u in ordered if topic in hints(index[u]["reference"])), f"reference topic hint: {topic}")
    add((u for u in ordered if u in candidate and (ratio(candidate[u]) or 0) > 0), "remaining candidate error")
    remaining = sorted(index)
    random.Random(42).shuffle(remaining)
    add(remaining, "seed-42 fill", 10)
    return [(index[uid], reasons[uid]) for uid in chosen]


def save_csv(path, fields, values):
    with path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({key: "N/A" if row.get(key) is None else row[key] for key in fields} for row in values)


def write_examples(report, validation, predictions, entries):
    eligible = [e for e in entries if e["comparison_eligible"] and e["experiment"] != "E0"]
    best = min(eligible, key=lambda e: (e["normalized_wer"], e["normalized_cer"], e["experiment"]))["experiment"] if eligible else "E0"
    cases = choose_cases(validation, predictions, best)
    fields = ["utterance_id", "ground_truth", "selection_reason", "topic_hints"]
    for exp in EXPERIMENTS:
        fields += [f"{exp}_prediction", f"{exp}_status"]
        fields += [f"{exp}_{mode}_{metric}_pct" for mode in ("raw", "normalized") for metric in ("wer", "cer")]
        fields += [f"{exp}_{kind}" for kind in ("substitutions", "deletions", "insertions")]
    values, table, sections = [], [], []
    for reference, reason in cases:
        uid = reference["utterance_id"]
        value = {"utterance_id": uid, "ground_truth": reference["reference"],
                 "selection_reason": reason, "topic_hints": ", ".join(hints(reference["reference"]))}
        cells = [escape(uid), escape(reference["reference"])]
        sections += [f"### {escape(uid)}", "", f"Selection: {escape(reason)}.",
                     f"Topic hints (heuristic, not gold): {escape(value['topic_hints']) or 'none'}.", "",
                     "| Model | Raw WER (%) | Raw CER (%) | Norm WER (%) | Norm CER (%) | S / D / I (norm words) |",
                     "|---|---:|---:|---:|---:|---|"]
        for exp in EXPERIMENTS:
            row = predictions.get(exp, {}).get(uid)
            if row is None:
                value.update({key: None for key in fields if key.startswith(exp + "_")})
                value[f"{exp}_status"] = "unavailable: run incomplete or incompatible"
                cells.append("N/A")
                sections.append(f"| {exp} | N/A | N/A | N/A | N/A | N/A |")
                continue
            value[f"{exp}_prediction"], value[f"{exp}_status"] = row["prediction"], row["status"]
            numbers = []
            for mode in ("raw", "normalized"):
                for metric in ("wer", "cer"):
                    result = ratio(row, mode, metric)
                    result = result * 100 if result is not None else None
                    value[f"{exp}_{mode}_{metric}_pct"] = result
                    numbers.append(f"{result:.2f}" if result is not None else "N/A")
            counts = row["scores"]["normalized"]["wer"]
            for kind in ("substitutions", "deletions", "insertions"):
                value[f"{exp}_{kind}"] = counts[kind]
            cells.append(highlight(reference["reference"], row["prediction"]))
            sections.append(f"| {exp} | " + " | ".join(numbers) +
                            f" | {counts['substitutions']} / {counts['deletions']} / {counts['insertions']} |")
        if uid in predictions.get("E0", {}) and uid in predictions.get(best, {}):
            delta = (ratio(predictions[best][uid]) or 0) - (ratio(predictions["E0"][uid]) or 0)
            sections += ["", f"{best} vs E0: normalized utterance WER delta {delta * 100:+.2f} pp."]
            changes = []
            for operation, ref, pred in word_diff(normalize(reference["reference"]), normalize(predictions[best][uid]["prediction"])):
                if operation == "substitute":
                    changes.append(f"thay ‘{escape(ref)}’ → ‘{escape(pred)}’")
                elif operation == "delete":
                    changes.append(f"thiếu ‘{escape(ref)}’")
                elif operation == "insert":
                    changes.append(f"thêm ‘{escape(pred)}’")
            diagnostic = "; ".join(changes[:8]) + ("; …" if len(changes) > 8 else "")
            sections.append(f"{best} normalized word edits: {diagnostic or 'không có word edits'}.")
        table.append("| " + " | ".join(cells) + " |")
        sections.append("")
        values.append(value)
    save_csv(report / "examples_10.csv", fields, values)
    introduction = ["# Ten illustrative saved ASR examples", "",
        "Selection is deterministic: up to two largest improvements and two regressions versus E0 for the lowest-WER eligible candidate, then topic coverage, a residual error and seed-42 fill; duplicate IDs are removed.",
        "These examples are selected illustrations, not a representative sample or a replacement for the full Validation scores.",
        "**Bold** = inserted/substituted prediction word; ~~strike~~ = missing reference word. Raw whitespace-word alignment is used for display; normalized metrics retain the frozen scorer.",
        "Money/time/name/code-switch labels are lexical review hints, not gold slot annotations. Insertions are not proof of hallucination; listening/context review is required.", "",
        "| ID | Ground Truth | E0 Prediction | E1 Prediction | E2 Prediction | E3 Prediction | E4 Prediction |",
        "|---|---|---|---|---|---|---|", *table, "", *sections]
    (report / "examples_10.md").write_text("\n".join(introduction), encoding="utf-8")
    return [{"utterance_id": r["utterance_id"], "selection_reason": r["selection_reason"],
             "topic_hints": r["topic_hints"]} for r in values]
