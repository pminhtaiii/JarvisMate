"""Render complete saved-experiment metrics and qualified selection conclusions."""
from __future__ import annotations

from .comparison_examples import escape, hints, ratio


def number(value, scale=1):
    return f"{value * scale:.3f}" if type(value) in (int, float) else "N/A"


def table(headers, entries, columns):
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for entry in entries:
        lines.append("| " + " | ".join(escape(column(entry)) for column in columns) + " |")
    return lines + [""]


def rankings(entries):
    valid = [r for r in entries if r["comparison_eligible"]]
    result = {}
    for key in ("normalized_wer", "normalized_cer", "raw_wer", "raw_cer", "mean_latency_seconds",
                "p95_latency_seconds", "train_peak_allocated_gib", "infer_peak_allocated_gib"):
        measured = [r for r in valid if r.get(key) is not None]
        best = min((r[key] for r in measured), default=None)
        result[key] = {"value": best, "experiments": [r["experiment"] for r in measured if r[key] == best]}
    return result


def regression_counts(predictions, experiment, control="E0"):
    base, candidate = predictions.get(control, {}), predictions.get(experiment, {})
    result = {"improved": 0, "regressed": 0, "tied": 0}
    for uid in base.keys() & candidate.keys():
        old, new = ratio(base[uid]), ratio(candidate[uid])
        if old is not None and new is not None:
            result["improved" if new < old else "regressed" if new > old else "tied"] += 1
    return result


def render(entries, predictions, decisions, validation, summary, control_comparison, recommendation):
    lines = ["# PhoWhisper-large: ASR Fine-tuning Experiment Comparison", "",
        f"Nguồn: artifacts đã lưu; {len(validation)} current utterances trong development Validation. "
        f"Có {sum(r['comparison_eligible'] for r in entries)}/5 runs completed tương thích được so sánh.",
        "Không training, inference, đọc WAV hoặc load weights. Best checkpoint và predictions gốc được giữ nguyên.",
        "CSV giữ các cột ratio cũ; cột *_pct là %, delta_*_pp là candidate trừ E0 theo percentage points (âm tốt hơn). N/A không phải 0.", "",
        "## Trạng thái và phạm vi", ""]
    lines += table(["Experiment", "Method", "Status", "Eligible", "Coverage", "Best step", "Best checkpoint"], entries,
        [lambda r:r["experiment"], lambda r:r["method"], lambda r:r["status"],
         lambda r:str(r["comparison_eligible"]), lambda r:number(r.get("coverage"), 100) + ("%" if r.get("coverage") is not None else ""),
         lambda r:str(r.get("best_step")) if r.get("best_step") is not None else "N/A",
         lambda r:r.get("checkpoint_id") or "N/A"])
    lines += ["## WER/CER trên toàn bộ Validation", ""]
    lines += table(["Experiment", "Raw WER (%)", "Raw CER (%)", "Norm WER (%)", "Norm CER (%)",
                    "Δ raw WER (pp)", "Δ raw CER (pp)", "Δ norm WER (pp)", "Δ norm CER (pp)"], entries,
        [lambda r:r["experiment"]] + [lambda r,k=k:number(r.get(k)) for k in
        ("raw_wer_pct", "raw_cer_pct", "normalized_wer_pct", "normalized_cer_pct", "delta_raw_wer_pp",
         "delta_raw_cer_pp", "delta_normalized_wer_pp", "delta_normalized_cer_pp")])
    lines += ["## Latency và VRAM", "",
              "VRAM là peak PyTorch allocated/reserved, gồm resident weights; không phải NVML/device peak. Training VRAM của E0 không áp dụng.", ""]
    lines += table(["Experiment", "Mean (s)", "P95 (s)", "RTF", "Train alloc (GiB)", "Train reserved (GiB)",
                    "Infer alloc (GiB)", "Infer reserved (GiB)"], entries,
        [lambda r:r["experiment"]] + [lambda r,k=k:number(r.get(k)) for k in
        ("mean_latency_seconds", "p95_latency_seconds", "rtf", "train_peak_allocated_gib", "train_peak_reserved_gib",
         "infer_peak_allocated_gib", "infer_peak_reserved_gib")])
    lines += ["## Critical slots", ""]
    lines += table(["Experiment", "Slot status", "CSA (%)", "Precision (%)", "Recall (%)", "F1 (%)", "Annotation coverage (%)"], entries,
        [lambda r:r["experiment"], lambda r:r.get("slot_status", "unavailable")] +
        [lambda r,k=k:number(r.get(k), 100) for k in
         ("critical_slot_accuracy", "slot_precision", "slot_recall", "slot_f1", "annotation_coverage")])
    lines += ["CSA = recall trên gold slots; precision/FP đi kèm để phản ánh predicted slots dư. Proxy không được coi là primary CSA.", "",
              "## Lý do N/A và runs bị loại", ""]
    for entry in entries:
        notes = entry.get("metric_notes") or "Primary metrics đầy đủ."
        lines.append(f"- {entry['experiment']}: {escape(entry.get('reason') or notes)}")
    lines += ["", "## Xếp hạng và kết luận", ""]
    for key, title in (("normalized_wer", "Normalized WER thấp nhất"), ("normalized_cer", "Normalized CER thấp nhất"),
                       ("raw_wer", "Raw WER thấp nhất"), ("raw_cer", "Raw CER thấp nhất"),
                       ("mean_latency_seconds", "Mean latency thấp nhất"), ("p95_latency_seconds", "P95 latency thấp nhất"),
                       ("train_peak_allocated_gib", "Training VRAM allocated thấp nhất"),
                       ("infer_peak_allocated_gib", "Inference VRAM allocated thấp nhất")):
        best = summary[key]
        scale = 100 if key.endswith(("wer", "cer")) else 1
        unit = "%" if scale == 100 else "GiB" if key.endswith("gib") else "s"
        lines.append(f"- {title}: {', '.join(best['experiments']) or 'N/A'} ({number(best['value'], scale)} {unit}).")
    for entry in entries:
        exp = entry["experiment"]
        if exp not in decisions:
            continue
        decision = decisions[exp]
        interval = decision.get("uncertainty", {}).get("wer_improvement_95ci")
        ci = f"[{interval[0]*100:.3f}, {interval[1]*100:.3f}] pp" if interval else "N/A"
        lines.append(f"- {exp}: Δ normalized WER {number(entry.get('delta_normalized_wer_pp'))} pp; "
                     f"promotion **{decision['status']}** ({escape(decision['reason'])}); "
                     f"paired group bootstrap 95% CI cho E0 − candidate: {ci}.")
    if decisions and all(d["status"] == "provisional" for d in decisions.values()):
        lines += ["", "Chưa đủ CSA/semantic evidence để promotion chính thức. Giữ E0 làm fallback; model có WER/CER tốt nhất chỉ là candidate provisional."]
    lines += ["", f"Đề xuất theo policy: **{recommendation['experiment']} — {recommendation['status']}** "
              f"({escape(recommendation['reason'])})."]
    if control_comparison:
        c = control_comparison
        ci = c["uncertainty"]["wer_improvement_95ci"]
        lines += ["", f"E4 so với control {c['control']}: Δ normalized WER {c['delta_wer_pp']:+.3f} pp, "
                  f"Δ normalized CER {c['delta_cer_pp']:+.3f} pp. CI 95% cho control − E4: [{ci[0]*100:.3f}, {ci[1]*100:.3f}] pp."]
        if ci[0] <= 0 <= ci[1]:
            lines.append("CI chứa 0: chưa chứng minh augmentation cải thiện ổn định so với control.")
        lines.append("Đây là so sánh best exports; matched-update evaluations được giữ riêng trong comparison-variants.csv.")
    lines += ["", "## Regression và error analysis toàn corpus", "",
              "S/D/I là substitutions/deletions/insertions từ normalized word alignment; insertions chỉ là dấu hiệu cần review, không tự chứng minh hallucination.", ""]
    errors = []
    for entry in entries:
        if not entry["comparison_eligible"]:
            continue
        counts = entry["normalized_wer_counts"]
        errors.append({"experiment": entry["experiment"], **counts,
                       **regression_counts(predictions, entry["experiment"])})
    lines += table(
            ["Experiment", "S", "D", "I", "Câu cải thiện vs E0", "Câu regression", "Câu bằng WER"], errors,
            [lambda r,k=k:str(r[k]) for k in ("experiment", "substitutions", "deletions", "insertions", "improved", "regressed", "tied")])
    lines += ["### Money, time, proper names và code-switch", "",
              "Chưa có gold nhãn loại lỗi; không suy CSA hoặc semantic accuracy từ WER. Bảng sau là nhóm câu có gợi ý từ khóa/viết hoa trong reference, không phải số lỗi slot. Mỗi ô là số câu có normalized word error bất kỳ trong nhóm đó. Các nhóm có thể chồng lấp.", ""]
    topic_rows = []
    for topic in ("money", "time", "proper_name", "code_switch"):
        ids = [r["utterance_id"] for r in validation if topic in hints(r["reference"])]
        row = {"topic": topic, "count": len(ids)}
        for exp, records in predictions.items():
            row[exp] = sum(records[uid]["scores"]["normalized"]["wer"]["errors"] > 0 for uid in ids)
        topic_rows.append(row)
    lines += table(["Reference hint", "Câu được gợi ý", "E0", "E1", "E2", "E3", "E4"], topic_rows,
        [lambda r:r["topic"], lambda r:str(r["count"])] +
        [lambda r,e=e:str(r[e]) if e in r else "N/A" for e in ("E0", "E1", "E2", "E3", "E4")])
    lines += ["Xem examples_10.md để đối chiếu reference/predictions và các đoạn thay thế, thêm, thiếu. Proper-name/code-switch hints cần người review xác nhận; không dùng chúng để promotion.", "",
              "## Giới hạn bằng chứng", "",
              "- Validation đã được dùng nhiều lần để chọn checkpoint: đây là development Validation.",
              "- 10 examples được chọn có chủ đích theo quy tắc cố định, không thay kết quả trên toàn corpus.",
              "- Latency là một lần đo theo protocol đã freeze; chênh lệch nhỏ chưa chứng minh tốc độ ổn định.",
              "- Native NF4 khác representation primary merged FP16; không tráo score hoặc VRAM giữa hai bản.",
              "- Tool-call F1/Final State Match và A30 full-pipeline compliance chưa có evidence trong comparison ASR này.", ""]
    return "\n".join(lines)
