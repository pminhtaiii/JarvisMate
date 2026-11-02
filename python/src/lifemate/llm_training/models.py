"""Explicit pinned Qwen loading and adapter-only LoRA/genuine NF4 training."""
from pathlib import Path
import re

from .model_identity import snapshot_identity
from .resources import checked_packages
from .tokenization import load_tokenizer

TARGET = re.compile(r"(?:.*\.)?layers\.(\d+)\.self_attn\.(q_proj|k_proj|v_proj|o_proj)$")


def adapter_targets(model):
    names = [name for name, module in model.named_modules() if TARGET.fullmatch(name)]
    expected = {(i, p) for i in range(model.config.num_hidden_layers) for p in ("q_proj", "k_proj", "v_proj", "o_proj")}
    actual = {(int(TARGET.fullmatch(n)[1]), TARGET.fullmatch(n)[2]) for n in names}
    if actual != expected or len(names) != len(expected):
        raise ValueError("LoRA requires q/k/v/o in every decoder self-attention layer")
    return names


def assert_adapter_only(model):
    trainable = {n: p for n, p in model.named_parameters() if p.requires_grad}
    if not trainable or any(not (".lora_A." in n or ".lora_B." in n) for n in trainable):
        raise ValueError("Only adapter A/B matrices may be trainable")
    for name in trainable:
        if not any(".self_attn." + projection + "." in name for projection in ("q_proj", "k_proj", "v_proj", "o_proj")):
            raise ValueError("Adapter outside approved attention scope")
    return {"trainable_names": list(trainable), "trainable_parameters": sum(p.numel() for p in trainable.values())}


def inject_lora(model, *, rank=8, alpha=16, dropout=.05):
    from peft import LoraConfig, get_peft_model
    targets = adapter_targets(model)
    for p in model.parameters():
        p.requires_grad_(False)
    model = get_peft_model(model, LoraConfig(task_type="CAUSAL_LM", r=rank, lora_alpha=alpha,
        lora_dropout=dropout, target_modules=targets, bias="none", modules_to_save=None))
    # from_pretrained leaves the base in eval mode. PEFT's new wrapper can be in
    # training mode while its base decoder is not, disabling checkpointing there.
    model.train()
    return model, assert_adapter_only(model)


def prepare_nf4_training(model, dtype):
    """Restore frozen embedding/norm weights to the configured compute dtype.

    PEFT upcasts every non-quantized parameter, including Qwen's large tied
    embedding/head. Its FP32 embedding output also doubles residual/checkpoint
    activations. Qwen3RMSNorm also promotes outputs when its weight is FP32.
    Its normalization arithmetic remains FP32 inside forward, even with BF16/FP16
    weights. Completion cross entropy and PEFT adapter parameters remain FP32.
    """
    import torch
    from peft import prepare_model_for_kbit_training
    from transformers.models.qwen3.modeling_qwen3 import Qwen3RMSNorm
    if dtype not in (torch.bfloat16, torch.float16):
        raise ValueError("NF4 embedding precision must match the BF16/FP16 compute profile")
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True,
                                           gradient_checkpointing_kwargs={"use_reentrant": False})
    embedding, head = model.get_input_embeddings(), model.get_output_embeddings()
    if not model.config.tie_word_embeddings or embedding.weight is not head.weight:
        raise ValueError("Pinned Qwen requires a genuinely shared embedding/output weight")
    embedding.to(dtype=dtype)
    norms = [module for module in model.modules() if isinstance(module, Qwen3RMSNorm)]
    if not norms:
        raise ValueError("Pinned Qwen RMS normalization modules are required")
    for module in norms:
        module.to(dtype=dtype)
    if head.weight.dtype != dtype or embedding.weight.requires_grad:
        raise ValueError("Frozen tied embedding/head precision was not preserved")
    return model


def load_training_model(directory: Path, settings: dict):
    identity = snapshot_identity(directory)
    method, precision = settings["method"], settings["precision"]
    checked_packages(nf4=method == "nf4")
    import torch
    import transformers as hf
    from ..adapters.common import dependencies
    dependencies("cuda", settings["seed"])
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    dtype = torch.bfloat16 if precision == "bf16" else torch.float16
    if precision == "bf16" and not torch.cuda.is_bf16_supported():
        raise ValueError("Configured BF16 unsupported; no silent precision change")
    kwargs = {"local_files_only": True, "trust_remote_code": False, "dtype": dtype,
              "attn_implementation": "sdpa", "device_map": {"": 0}}
    if not torch.backends.cuda.is_flash_attention_available():
        from ..adapters.planner import sdpa_expanded_kv
        hf.AttentionInterface.register("lifemate_sdpa_expanded_kv", sdpa_expanded_kv)
        hf.AttentionMaskInterface.register("lifemate_sdpa_expanded_kv", hf.AttentionMaskInterface()["sdpa"])
        kwargs["attn_implementation"] = "lifemate_sdpa_expanded_kv"
    if method == "nf4":
        kwargs["quantization_config"] = hf.BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=dtype)
    model = hf.AutoModelForCausalLM.from_pretrained(directory, **kwargs)
    logical = identity["logical_parameters"]
    if logical != 4_022_468_096:
        raise ValueError("Pinned unquantized weight-header logical count mismatch")
    if method == "nf4":
        import bitsandbytes as bnb
        quantized = [m for m in model.modules() if isinstance(m, bnb.nn.Linear4bit)]
        if not quantized or any(m.weight.quant_type != "nf4" or m.weight.quant_state is None
                                or m.weight.quant_state.state2 is None for m in quantized):
            raise ValueError("Genuine NF4 with double quantization required")
        model = prepare_nf4_training(model, dtype)
    else:
        if logical != 4_022_468_096:
            raise ValueError("Pinned base logical parameter count mismatch")
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        model.enable_input_require_grads()
    model.config.use_cache = False
    model, adapter = inject_lora(model, rank=settings["rank"], alpha=settings["alpha"], dropout=settings["dropout"])
    layers = model.get_base_model().model.layers
    checkpointing = bool(layers) and all(layer.training and layer.gradient_checkpointing for layer in layers)
    if not checkpointing:
        raise ValueError("Every base decoder layer must be training with gradient checkpointing active")
    if any(p.device.type != "cuda" for p in model.parameters()):
        raise ValueError("CPU offload/substitution is forbidden for this qualification")
    tokenizer = load_tokenizer(directory)
    return model, tokenizer, {"base": identity, "logical_base_parameters": logical, "adapter": adapter,
                              "method": method, "precision": precision, "attention": kwargs["attn_implementation"],
                              "embedding_dtype":str(model.get_input_embeddings().weight.dtype),
                              "output_head_dtype":str(model.get_output_embeddings().weight.dtype),
                              "nf4_frozen_precision_policy":"embedding_and_norm_weights_compute_dtype_rms_math_fp32" if method=='nf4' else None,
                              "gradient_checkpointing": {"active": checkpointing, "decoder_layers":len(layers),
                                  "model_training":model.training, "use_reentrant":False}}


def planner_for_loaded(model, tokenizer):
    """Reuse the production native generation boundary without loading a second base."""
    import torch
    import transformers
    from ..adapters.planner import LocalPlanner
    from ..adapters.qwen_native import NativeConstraint, assistant_eos_id
    from .evaluation import limits
    planner = LocalPlanner.__new__(LocalPlanner)
    planner.model, planner.tokenizer, planner.torch, planner.hf = model, tokenizer, torch, transformers
    planner.device = next(model.parameters()).device.type
    planner.limits, planner.cpu_offload, planner.selection_filter = limits(), False, False
    planner.eos_id, planner.pad_id = assistant_eos_id(tokenizer), tokenizer.pad_token_id
    planner.special_ids = frozenset(i for i in tokenizer.all_special_ids if i != planner.eos_id)
    planner.constraint = NativeConstraint(tokenizer)
    planner.metadata, planner.last_generation, planner.last_decision_details, planner._selection_filters = {}, None, [], {}
    return planner
