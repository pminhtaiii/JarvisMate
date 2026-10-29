"""Deterministic, Train-only speed/volume/non-speech-noise augmentation."""
from __future__ import annotations

import hashlib
from pathlib import Path

from asr.pretrained.models import read_samples
from asr.pretrained.data import inspect_audio
from lifemate.jsonio import digest, visible_path
from .storage import read


def load_noises(manifest: Path | None, data_root: Path) -> list[dict]:
    if manifest is None:
        raise ValueError("E4 requires a reviewed, licensed non-speech noise manifest")
    entries = read(manifest)
    if not isinstance(entries, list) or not entries:
        raise ValueError("Empty noise manifest")
    for entry in entries:
        path = Path(entry["path"]).resolve()
        visible_path(path)
        if path.is_relative_to(data_root.resolve()) or not entry.get("license"):
            raise ValueError("Noise must be licensed and outside the competition dataset")
        if entry.get("reviewed") is not True or entry.get("contains_speech") is not False:
            raise ValueError("Noise must be manually reviewed as non-speech")
        if digest(path) != entry["sha256"]:
            raise ValueError("Noise checksum mismatch")
        entry["audio_metadata"] = inspect_audio(path)
        entry["path"] = str(path)
    return entries


def augment(samples, row: dict, config: dict, epoch: int, noises: list[dict], np):
    if row.get("partition") != "train":
        raise ValueError("Augmentation may only receive Train rows")
    key = f"{config['seed']}:{epoch}:{row['utterance_id']}:augmentation-v1".encode()
    seed = int.from_bytes(hashlib.sha256(key).digest()[:8], "little")
    rng = np.random.default_rng(seed)
    result, log = samples.copy(), {"seed": seed, "utterance_id": row["utterance_id"], "epoch": epoch}
    if rng.random() >= .5:
        return result, log | {"clean": True}
    if rng.random() < .5:
        speed = float(rng.choice([.9, 1., 1.1]))
        count = int(round(len(result) / speed))
        if count > 480000:
            log["speed_fallback"] = "would_exceed_30_seconds"
            speed, count = 1., len(result)
        result = np.interp(np.arange(count) * speed, np.arange(len(result)), result).astype(np.float32)
        log["speed"] = speed
    if rng.random() < .5:
        gain_db = float(rng.uniform(-6, 6))
        gain = min(10**(gain_db / 20), .99 / max(float(np.max(np.abs(result))), 1e-10))
        result *= gain
        log["volume_gain"] = gain
    if rng.random() < .5:
        if not noises:
            raise ValueError("Noise asset missing; do not silently run an incomplete E4")
        entry = noises[int(rng.integers(len(noises)))]
        noise = read_samples(Path(entry["path"]), np)
        offset = int(rng.integers(len(noise)))
        noise = np.resize(np.roll(noise, -offset), len(result))
        signal_power, noise_power = float(np.mean(result**2)), float(np.mean(noise**2))
        if noise_power <= 0:
            raise ValueError("Noise asset is silent")
        snr = float(rng.uniform(15, 30))
        result += noise * (signal_power / (noise_power * 10**(snr / 10)))**.5
        log.update(noise_sha256=entry["sha256"], noise_offset=offset, snr_db=snr)
    if not len(result) or len(result) > 480000 or not np.isfinite(result).all() or np.max(np.abs(result)) >= 1:
        return samples.copy(), log | {"fallback": "invalid_or_clipping_transform"}
    return result, log
