"""Build the Kaggle notebook (v2) from lifemate_infer.py + system_prompt.txt, starting from the v1 notebook layout.

    python kaggle/build_notebook.py            # -> kaggle/push/lifemate-funreason-asr.ipynb + kernel-metadata.json
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
src = json.load(open(HERE / "lifemate_kaggle.ipynb", encoding="utf-8"))
cells = src["cells"]


def code(text):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": text.splitlines(keepends=True)}


def md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


def find(prefix):
    for i, c in enumerate(cells):
        if "".join(c["source"]).lstrip().startswith(prefix):
            return i
    raise SystemExit(f"cell not found: {prefix}")


cells[find("%%writefile system_prompt.txt")] = code("%%writefile system_prompt.txt\n" + (HERE / "system_prompt.txt").read_text(encoding="utf-8"))
cells[find("%%writefile lifemate_infer.py")] = code("%%writefile lifemate_infer.py\n" + (HERE / "lifemate_infer.py").read_text(encoding="utf-8"))

# Step 2: compare v2 against the v1 behaviour on the same train subset (gold transcripts -> LLM only).
cmp_i = find("# So sánh cấu hình LLM")
cmp = "".join(cells[cmp_i]["source"])
cmp = cmp.replace('N_EVAL, MAX_SEC = 30, 75', 'N_EVAL, MAX_SEC = 40, 75')
cmp = cmp.replace('MIN_SCORE = 0.25', 'MIN_SCORE = 0.0')
V1 = '["--fewshot-k", "0", "--no-nudge", "--no-fix-args", "--asr-nbest", "1", "--no-asr-pass2", "--no-asr-hints"]'
cmp = cmp.replace('CONFIGS = {"qwen_fewshot": TB, "qwen_nofewshot": ["--no-few-shot"] + TB}',
                  'CONFIGS = {"v2": TB, "v2_k5": ["--fewshot-k", "5"] + TB, "v1": ' + V1 + ' + TB}')
cmp = cmp.replace('QUEUES = [["qwen_fewshot"], ["qwen_nofewshot"]]', 'QUEUES = [["v2", "v1"], ["v2_k5"]]')
assert '"v2"' in cmp and "N_EVAL, MAX_SEC = 40" in cmp, "compare cell layout changed"
cells[cmp_i] = code(cmp)

cells[0] = md("# LifeMate v2: ASR (zaic Whisper) + LLM (Qwen3-4B-Instruct-2507) trên Kaggle\n\n"
              "v2 so với v1 (23 điểm public): few-shot lấy 3 câu train giống nhất cho từng mẫu, nhắc lại khi model nói "
              "\"đã làm\" mà chưa gọi tool ghi, sửa nhà/công ty → địa chỉ profile và thành phố → IATA, chặn "
              "ask_missing_info trỏ vào tool đọc. Phần ASR: đưa N-best khi greedy và beam lệch nhau, gợi ý tên theo "
              "phát âm sau mỗi tool đọc, và giải mã Whisper lần 2 với prompt là tên trong dữ liệu.\n\n"
              "Bước 2 so v2 với cấu hình v1 trên 40 mẫu train (transcript gốc), chọn cấu hình tốt nhất cho public_test.")

out = HERE / "push"
out.mkdir(exist_ok=True)
nb = dict(src, cells=cells)
json.dump(nb, open(out / "lifemate-funreason-asr.ipynb", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
meta = json.load(open(HERE / "pulled" / "kernel-metadata.json", encoding="utf-8"))
meta.pop("id_no", None)
json.dump(meta, open(out / "kernel-metadata.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("notebook ->", out)
