"""Whisper LoRA/NF4 construction with exact scope checks and local-only assets."""
from __future__ import annotations

from pathlib import Path
import os
import random
import re

from asr.pretrained.models import offline, read_samples
from lifemate.model_budget import check_budget
from .augmentation import augment
from .resources import Unsupported


def dependencies(seed: int):
    offline()
    # Set before CUDA context creation; required by deterministic cuBLAS kernels.
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    import numpy as np
    import torch
    import transformers
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.benchmark = False
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
    torch.use_deterministic_algorithms(True)
    return torch, transformers, np


def target_names(model, scope: str) -> list[str]:
    decoder = r"model\.decoder\.layers\.\d+\.(self_attn|encoder_attn)\.(q_proj|v_proj)"
    encoder = r"model\.encoder\.layers\.\d+\.self_attn\.(q_proj|v_proj)"
    if scope not in {"decoder", "encoder_decoder"}:
        raise ValueError("Invalid LoRA target scope")
    names = [name for name, _ in model.named_modules() if re.fullmatch(decoder, name)
             or (scope == "encoder_decoder" and re.fullmatch(encoder, name))]
    if not names or (scope == "encoder_decoder" and not any(".encoder." in n for n in names)):
        raise Unsupported("Whisper module names do not match the declared adapter scope")
    return names


def inject(model, config: dict):
    from peft import LoraConfig, get_peft_model
    names = target_names(model, config["scope"])
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    # Generic PeftModel forwards Whisper input_features; text seq2seq wrappers can inject input_ids.
    model = get_peft_model(model, LoraConfig(r=config["rank"], lora_alpha=config["alpha"],
                                           lora_dropout=config["dropout"], bias="none",
                                           target_modules=names, task_type=None))
    validate_trainable(model, config["scope"])
    return model, names


def validate_trainable(model, scope: str) -> dict:
    names = [n for n, p in model.named_parameters() if p.requires_grad]
    if not names or any("lora_A" not in n and "lora_B" not in n for n in names):
        raise Unsupported("Only LoRA A/B parameters may be trainable")
    has_encoder = any(".encoder." in n for n in names)
    if has_encoder != (scope == "encoder_decoder") or not any(".decoder." in n for n in names):
        raise Unsupported("LoRA trainable scope is incorrect")
    return {"trainable": names, "adapter_parameters": sum(p.numel() for p in model.parameters() if p.requires_grad)}


def gradient_report(model, scope: str) -> dict:
    report = {"encoder": 0., "decoder": 0.}
    for name, p in model.named_parameters():
        if not p.requires_grad:
            if p.grad is not None:
                raise Unsupported("Frozen base received a gradient")
            continue
        if p.grad is None or not p.grad.isfinite().all():
            raise Unsupported(f"Missing/non-finite gradient: {name}")
        group = "encoder" if ".encoder." in name else "decoder"
        report[group] += float(p.grad.detach().abs().sum())
    required = ("encoder", "decoder") if scope == "encoder_decoder" else ("decoder",)
    if any(report[group] == 0 for group in required):
        raise Unsupported("Adapter has zero gradients in a required scope")
    return report


def load(snapshot: str, config: dict, precision: str, *, training: bool,
         adapter_path: str | None = None, native: bool = False, device: str = "cuda"):
    torch, hf, np = dependencies(config["seed"])
    torch.set_num_threads(config["threads"])
    dtype = getattr(torch, precision)
    kwargs = {"local_files_only": True, "trust_remote_code": False, "dtype": dtype,
              "attn_implementation": "eager", "weights_only": True}
    if native:
        if device != "cuda":
            raise Unsupported("NF4 profile requires the actual target CUDA GPU")
        try:
            import bitsandbytes as bnb
            from peft import prepare_model_for_kbit_training
        except (ImportError, OSError) as exc:
            raise Unsupported("Install/probe the optional NF4 stack") from exc
        kwargs.update(quantization_config=hf.BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                      bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=dtype), device_map={"": 0})
    model = hf.WhisperForConditionalGeneration.from_pretrained(snapshot, **kwargs)
    processor = hf.WhisperProcessor.from_pretrained(snapshot, local_files_only=True, trust_remote_code=False)
    processor.tokenizer.set_prefix_tokens(language="vi", task="transcribe", predict_timestamps=False)
    if native:
        if not any(isinstance(m, bnb.nn.Linear4bit) for m in model.modules()):
            raise Unsupported("NF4 load did not create real Linear4bit modules")
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=training,
                    gradient_checkpointing_kwargs={"use_reentrant": False})
    else:
        model.to(device)
    targets = []
    if adapter_path:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, adapter_path, is_trainable=training, local_files_only=True)
        if not training and not native:
            model = model.merge_and_unload(safe_merge=True)
    elif training:
        model, targets = inject(model, config)
    if training:
        validate_trainable(model, config["scope"])
        model.config.use_cache = False
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        model.train()
    else:
        model.eval()
    return model, processor, targets


def prepare_labels(processor, model, text: str) -> list[int]:
    import unicodedata
    labels = processor.tokenizer(unicodedata.normalize("NFC", text).strip()).input_ids
    if labels and labels[0] == model.config.decoder_start_token_id:
        labels = labels[1:]
    if not labels or len(labels) > model.config.max_target_positions - 1:
        raise ValueError("Empty/overlong label; never truncate transcripts")
    return labels


def batch(row: dict, data_root: Path, processor, model, config: dict, epoch: int, noises: list, np, torch):
    from asr.pretrained.data import audio_asset
    samples = read_samples(audio_asset(data_root / "train", row["audio"]), np)
    log = None
    if config["experiment"] == "E4":
        samples, log = augment(samples, row, config, epoch, noises, np)
    encoded = processor(samples, sampling_rate=16000, return_tensors="pt", return_attention_mask=True)
    labels = prepare_labels(processor, model, row["reference"])
    device = next(model.parameters()).device
    # Non-quantized input frontend remains in model dtype; bnb compute dtype is configured separately.
    dtype = model.get_base_model().model.encoder.conv1.weight.dtype if hasattr(model, "get_base_model") else model.model.encoder.conv1.weight.dtype
    result = {"input_features": encoded["input_features"].to(device=device, dtype=dtype),
              "labels": torch.tensor([labels], dtype=torch.long, device=device)}
    if "attention_mask" in encoded:
        result["attention_mask"] = encoded["attention_mask"].to(device)
    return result, log


def generate(model, processor, path: Path, np, torch, *, max_new_tokens: int = 440) -> str:
    data = processor(read_samples(path, np), sampling_rate=16000, return_tensors="pt", return_attention_mask=True)
    device = next(model.parameters()).device
    base = model.get_base_model() if hasattr(model, "get_base_model") else model
    dtype = base.model.encoder.conv1.weight.dtype
    features = data["input_features"].to(device=device, dtype=dtype)
    mask = {"attention_mask": data["attention_mask"].to(device)} if "attention_mask" in data else {}
    with torch.inference_mode():
        output = model.generate(features, **mask, language="vi", task="transcribe",
                                do_sample=False, num_beams=1, max_new_tokens=max_new_tokens, return_timestamps=False)
    return processor.batch_decode(output, skip_special_tokens=True)[0].strip()
