"""Synthetic ASR-only records; no competition state or pretrained weights."""
import hashlib
from pathlib import Path
import struct
import wave
from unittest.mock import patch

from lifemate.jsonio import dumps, digest
from lifemate.asr_training.storage import write
from asr.pretrained.data import make_split
from lifemate.asr_training.data import project, prepare_suite


def make_audio(path: Path, value: int = 1):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(struct.pack("<h", value) * 160)


def fixture(root: Path):
    data = root / "data"
    train = data / "train"
    texts = ["Mua bánh mì", "Đặt báo thức", "Gửi thư cho Mai", "Tắt đèn phòng ngủ",
             "Mở bản đồ", "Đọc tin thể thao", "Phát nhạc Trịnh Công Sơn", "Tìm quán bún bò"]
    records = []
    for i, text in enumerate(texts):
        relative = f"audio/s{i}/current.wav"
        make_audio(train / relative, i + 1)
        records.append({"id": f"s{i}", "audio": relative, "audio_text": text, "history": [],
                        "context": {"sentinel": "CONTEXT_DO_NOT_EXPORT"},
                        "label": {"sentinel": "GOLD_TOOLS_DO_NOT_EXPORT"}})
    (train / "train.jsonl").write_text("".join(dumps(r)+"\n" for r in records), encoding="utf-8")
    split = make_split(data)
    path = root / "split.json"
    write(path, split)
    projected = project(data, path, expected_identity=split["identity"], expected_validation=2)
    model = root / "models/phowhisper-large"
    model.mkdir(parents=True)
    for name in ("config.json", "preprocessor_config.json", "tokenizer.json", "model.safetensors"):
        (model / name).write_text("{}", encoding="utf-8")
    write(model / "provenance.json", {"source": "vinai/PhoWhisper-large", "engine": "transformers",
          "revision": "a"*40, "parameter_count": 1_550_000_000, "generation_defaults": {},
          "assets": {p.name: digest(p) for p in model.iterdir()}})
    return data, path, split, projected, model


def suite_fixture(root: Path):
    data, path, split, projected, model = fixture(root)
    suite = root / "suite"
    with patch("lifemate.asr_training.data.ignored", side_effect=lambda p:p), \
         patch("lifemate.asr_training.data.project", return_value=projected):
        metadata = prepare_suite(suite, data, path, model)
    return suite, metadata, projected


def annotation(row, values):
    slots = []
    for kind, surface, value in values:
        start = row["reference"].index(surface)
        slots.append({"type":kind,"surface":surface,"span":[start,start+len(surface)],"canonical":value})
    return {"utterance_id":row["utterance_id"],"annotation_status":"reviewed","reviewer":"fixture-only",
            "reference_sha256":hashlib.sha256(row["reference"].encode()).hexdigest(),"slots":slots}
