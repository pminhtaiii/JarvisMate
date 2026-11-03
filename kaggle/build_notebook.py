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
cmp = cmp.replace('N_EVAL, MAX_SEC = 30, 75', 'N_EVAL, MAX_SEC = 60, 75')
cmp = cmp.replace('MIN_SCORE = 0.25', 'MIN_SCORE = 0.0')
V2 = '["--read-prune-rate", "0.1", "--no-date-table", "--no-soft-nudge", "--no-read-notes"]'
THINK = '["--llm-model", "Qwen/Qwen3-4B", "--think-budget", "192"]'
cmp = cmp.replace('CONFIGS = {"qwen_fewshot": TB, "qwen_nofewshot": ["--no-few-shot"] + TB}',
                  'CONFIGS = {"v3": TB, "v3_nosoft": ["--no-soft-nudge"] + TB, "v2": ' + V2 + ' + TB, "v3_think": ' + THINK + ' + TB}')
cmp = cmp.replace('QUEUES = [["qwen_fewshot"], ["qwen_nofewshot"]]', 'QUEUES = [["v3", "v3_nosoft", "v2"], ["v3_think"]]')
assert '"v3_think"' in cmp and "N_EVAL, MAX_SEC = 60" in cmp, "compare cell layout changed"
cells[cmp_i] = code(cmp)

cells[0] = md("# LifeMate v3 (từ v2): ASR (zaic Whisper) + LLM (Qwen3-4B-Instruct-2507) trên Kaggle\n\n"
              "v2 so với v1 (23 điểm public): few-shot lấy 3 câu train giống nhất cho từng mẫu, nhắc lại khi model nói "
              "\"đã làm\" mà chưa gọi tool ghi, sửa nhà/công ty → địa chỉ profile và thành phố → IATA, chặn "
              "ask_missing_info trỏ vào tool đọc. Phần ASR: đưa N-best khi greedy và beam lệch nhau, gợi ý tên theo "
              "phát âm sau mỗi tool đọc, và giải mã Whisper lần 2 với prompt là tên trong dữ liệu.\n\n"
              "v3 thêm: bỏ bộ lọc tùy chọn của tool đọc mà gold hiếm dùng, bảng ngày tính sẵn, nhắc khi dừng sau khi đọc mà chưa "
              "thao tác, gợi ý tìm lại khi danh bạ rỗng, tóm tắt mưa/không mưa, dòng 'Điều kiện: ... → ĐÚNG/SAI'. "
              "Bước 2 so v3, v3 không nhắc mềm, v2 và v3 với Qwen3-4B có think (192 token) trên 60 mẫu train.")

out = HERE / "push"
out.mkdir(exist_ok=True)
nb = dict(src, cells=cells)
json.dump(nb, open(out / "lifemate-funreason-asr.ipynb", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
meta = json.load(open(HERE / "pulled" / "kernel-metadata.json", encoding="utf-8"))
meta.pop("id_no", None)
json.dump(meta, open(out / "kernel-metadata.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("notebook ->", out)
