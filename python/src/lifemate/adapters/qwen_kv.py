"""Per-sample exact-token reuse for the pinned Transformers 4.57.1 Qwen3 path.

No model/tool inference lives here. Unsupported caches fall back before generation;
model/CUDA exceptions are never retried or converted into a successful decision.
"""
from __future__ import annotations

import copy
import time
from collections import Counter
from contextlib import contextmanager


class SampleKVCache:
    def __init__(self, enabled: bool, context_tokens: int):
        self.enabled, self.limit = enabled, context_tokens
        self.sample_id = None
        self.cache, self.tokens = None, []
        self.reset_metrics()

    def reset_metrics(self):
        self.metrics = dict(kv_cache_enabled=self.enabled, kv_cache_hits=0, kv_cache_misses=0,
                            kv_cache_invalidations=0, kv_cache_reused_tokens=0,
                            kv_cache_new_prefill_tokens=0, kv_cache_invalidation_reasons={},
                            planner_prefill_seconds=0.0, planner_decode_seconds=0.0,
                            planner_total_seconds=0.0, kv_cache_peak_memory_bytes=None)

    def snapshot(self):
        return copy.deepcopy(self.metrics)

    def clear(self, reason=None):
        if reason is not None and self.enabled:
            self.metrics["kv_cache_invalidations"] += 1
            reasons = Counter(self.metrics["kv_cache_invalidation_reasons"])
            reasons[reason] += 1
            self.metrics["kv_cache_invalidation_reasons"] = dict(reasons)
        self.cache, self.tokens = None, []

    def start_sample(self, sample_id):
        self.clear()
        self.sample_id = sample_id
        self.reset_metrics()

    def end_sample(self):
        self.clear()
        self.sample_id = None

    def compatible(self, cache, model, hf):
        # Sliding/quantized/static/offloaded layers and dynamic RoPE need separate proofs.
        from transformers.cache_utils import DynamicCache, DynamicLayer

        return (hf.__version__ == "4.57.1" and type(cache) is DynamicCache
                and not model.training and model.config.model_type == "qwen3"
                and not model.config.rope_scaling
                and all(t == "full_attention" for t in model.config.layer_types)
                and len(cache.layers) == model.config.num_hidden_layers
                and all(type(layer) is DynamicLayer and layer.is_initialized
                        and layer.keys is not None and layer.values is not None
                        and layer.keys.ndim == layer.values.ndim == 4
                        and layer.keys.shape == layer.values.shape
                        and layer.keys.shape[1] == model.config.num_key_value_heads
                        and layer.keys.shape[-1] == model.config.head_dim
                        and layer.keys.device == model.device and layer.values.device == model.device
                        and layer.keys.dtype == model.dtype and layer.values.dtype == model.dtype
                        and layer.keys.shape[0] == layer.values.shape[0] == 1
                        for layer in cache.layers))

    def prepare(self, ids, model, hf, torch):
        """Full canonical input stays with generate/LMFE; cache_position slices model inputs."""
        if not self.enabled:
            return {}, 0
        if (self.sample_id is None or hf.__version__ != "4.57.1"
                or torch.__version__.split("+")[0] != "2.9.0" or model.training
                or model.config.model_type != "qwen3" or model.config.rope_scaling
                or any(t != "full_attention" for t in model.config.layer_types)
                or not model.config.use_cache or not model.generation_config.use_cache
                or model.generation_config.cache_implementation is not None):
            self.clear("unsupported_model_or_session")
            return {}, 0
        reused = 0
        if self.cache is not None:
            if (not self.compatible(self.cache, model, hf)
                    or self.cache.get_seq_length() != len(self.tokens)
                    or any(layer.get_seq_length() != len(self.tokens) for layer in self.cache.layers)):
                self.clear("invalid_cache_length_or_type")
            else:
                for left, right in zip(self.tokens, ids):
                    if left != right:
                        break
                    reused += 1
                # At least one input must be forwarded to recover next-token logits.
                reused = min(reused, len(ids) - 1)
                if reused < len(self.tokens):
                    reasons = Counter(self.metrics["kv_cache_invalidation_reasons"])
                    reasons["prefix_divergence_or_replay"] += 1
                    self.metrics["kv_cache_invalidation_reasons"] = dict(reasons)
                    self.metrics["kv_cache_invalidations"] += 1
                if reused:
                    self.cache.crop(reused)
                    self.tokens = self.tokens[:reused]
                else:
                    self.clear()
        if self.cache is None:
            self.cache = hf.DynamicCache(config=model.config)
        return {"past_key_values": self.cache, "use_cache": True,
                "cache_position": torch.arange(reused, len(ids), device=model.device)}, reused

    def remember(self, forwarded, cache, model, hf):
        if not self.enabled or self.sample_id is None:
            return
        if (cache is None or not self.compatible(cache, model, hf)
                or not 0 < len(forwarded) <= self.limit
                or any(layer.get_seq_length() != len(forwarded) for layer in cache.layers)):
            self.clear("unverifiable_forwarded_prefix")
            return
        self.cache, self.tokens = cache, forwarded
        storages = {}
        for layer in cache.layers:
            for tensor in (layer.keys, layer.values):
                storage = tensor.untyped_storage()
                storages[(str(tensor.device), storage.data_ptr())] = storage.nbytes()
        measured = sum(storages.values())
        self.metrics["kv_cache_peak_memory_bytes"] = max(
            measured, self.metrics["kv_cache_peak_memory_bytes"] or 0)


class ForwardMeasurement:
    """Measure first model forward (prefill) and later forwards (decode) separately.

    CUDA events measure device forward time without synchronizing every token. CPU
    uses perf_counter. Grammar, tokenization and sampling are in total time only.
    """
    def __init__(self, planner, reused):
        self.planner, self.reused = planner, reused
        self.inputs, self.spans = [], []
        self.cache = None
        self.started = None

    def before(self, module, args, kwargs):
        torch = self.planner.torch
        if self.planner.device.startswith("cuda"):
            self.started = torch.cuda.Event(enable_timing=True)
            self.started.record(torch.cuda.current_stream(self.planner.device))
        else:
            self.started = time.perf_counter()
        if self.planner.kv.enabled:
            self.inputs.append(kwargs["input_ids"].detach())
        self.current_tokens = int(kwargs["input_ids"].shape[-1])

    def after(self, module, args, kwargs, output):
        torch = self.planner.torch
        if self.planner.device.startswith("cuda"):
            ended = torch.cuda.Event(enable_timing=True)
            ended.record(torch.cuda.current_stream(self.planner.device))
        else:
            ended = time.perf_counter()
        if not self.spans:
            # Count work after the first successful forward, not at cache planning
            # time: an already-exhausted deadline must not invent reused tokens.
            metrics = self.planner.kv.metrics
            metrics["kv_cache_hits" if self.reused else "kv_cache_misses"] += 1
            metrics["kv_cache_reused_tokens"] += self.reused
            metrics["kv_cache_new_prefill_tokens"] += self.current_tokens
        self.spans.append((self.started, ended, self.current_tokens))
        self.cache = output.past_key_values if self.planner.kv.enabled else None

    @contextmanager
    def attach(self):
        # Library doubles do not measure real forward time; never invent timings.
        torch = self.planner.torch
        if not hasattr(torch, "nn") or not isinstance(self.planner.model, torch.nn.Module):
            yield
            return
        before = self.planner.model.register_forward_pre_hook(self.before, with_kwargs=True)
        after = self.planner.model.register_forward_hook(self.after, with_kwargs=True)
        try:
            yield
        finally:
            before.remove()
            after.remove()

    def finish(self, canonical_ids):
        kv = self.planner.kv
        if not self.spans:
            return {"planner_prefill_seconds": None, "planner_decode_seconds": None,
                    "kv_cache_new_prefill_tokens": None}
        def seconds(span):
            start, end, _ = span
            return start.elapsed_time(end) / 1000 if self.planner.device.startswith("cuda") else end - start
        prefill, decode = seconds(self.spans[0]), sum(seconds(s) for s in self.spans[1:])
        if kv.metrics["planner_prefill_seconds"] is not None:
            kv.metrics["planner_prefill_seconds"] += prefill
        if kv.metrics["planner_decode_seconds"] is not None:
            kv.metrics["planner_decode_seconds"] += decode
        if kv.enabled and self.inputs:
            forwarded = self.planner.torch.cat(self.inputs, dim=-1)[0].cpu().tolist()
            kv.remember(canonical_ids[:self.reused] + forwarded, self.cache, self.planner.model, self.planner.hf)
        return {"planner_prefill_seconds": prefill, "planner_decode_seconds": decode,
                "kv_cache_new_prefill_tokens": self.spans[0][2]}
