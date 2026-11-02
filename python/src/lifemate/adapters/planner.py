"""Local Qwen native tool-calling adapter; execution remains outside the model.

The model sees native messages and ``tools=`` through the pinned chat template, and
generates one native call or the exact ordinary final under the native decoder.
Raw generated IDs and stop evidence are parsed before any decoding shortcut; only
the normalized internal decision crosses to the agent (specs §2.4, §4.4).
"""
from __future__ import annotations

import copy
import time
from contextlib import contextmanager

from ..contracts import JSON, Limits, PipelineError
from ..agent import parse_action
from ..native_tools import adapt_tools
from ..prompting import PROMPT_HASH, PROMPT_VERSION, native_messages
from ..jsonio import dumps, loads
from ..selection import (FILTER_SYSTEM, filter_schema, referenced_records,
                         restrict_references, selected_ids)
from .common import ModelResidency, dependencies, metadata, model_directory, parameter_count, stopping_criteria
from .qwen_native import (GuardedPrefix, NativeConstraint, NativeProposalRejected, assistant_eos_id,
                          fingerprint, parse_native_ids, policy_identity, rejection_record, render_native)
from .prefix_cache import ExactPrefixCache, POLICY as PREFIX_CACHE_POLICY
from .fast_greedy import generate as fast_generate, supported as supports_fast_generate, POLICY as GENERATION_POLICY


def sdpa_expanded_kv(module, query, key, value, attention_mask, dropout=0.0,
                     scaling=None, is_causal=None, **kwargs):
    """Keep SDPA's efficient kernel eligible on builds without FlashAttention.

    Native GQA only supports the flash/math kernels in the pinned PyTorch build.
    Expanding K/V heads costs linear memory instead of a quadratic score matrix.
    """
    import torch

    groups = query.shape[1] // key.shape[1]
    key = key.repeat_interleave(groups, dim=1)
    value = value.repeat_interleave(groups, dim=1)
    if attention_mask is not None and attention_mask.ndim == 4:
        attention_mask = attention_mask[:, :, :, :key.shape[-2]]
    if is_causal is None:
        is_causal = query.shape[2] > 1 and attention_mask is None and module.is_causal
    output = torch.nn.functional.scaled_dot_product_attention(
        query, key, value, attn_mask=attention_mask, dropout_p=dropout,
        scale=scaling, is_causal=is_causal)
    return output.transpose(1, 2).contiguous(), None


class LocalPlanner(ModelResidency):
    def __init__(self, path, device: str, limits: Limits, seed: int = 20261027, *, selection_filter=False, cpu_offload=False):
        path = model_directory(path)
        torch, hf, _ = dependencies(device, seed)
        self.torch, self.hf, self.device, self.limits = torch, hf, device, limits
        self.cpu_offload = cpu_offload and device == "cuda"
        if selection_filter:
            # The development selection filter emits custom JSON/feedback; the native
            # protocol keeps it disabled (specs §10.1, O13) rather than mixing formats.
            raise PipelineError("INPUT_INVALID", "Selection filter is unavailable for the native protocol", "model_load")
        self.selection_filter = selection_filter
        self.last_decision_details = []
        self.last_generation = None
        self._selection_filters = {}
        self._prefix_cache = None
        dtype = torch.float32 if device == "cpu" else torch.float16
        # Avoid materializing quadratic attention scores for long CUDA prompts.
        attention = "sdpa" if device == "cuda" else "eager"
        try:
            if device == "cuda" and not torch.backends.cuda.is_flash_attention_available():
                attention = "lifemate_sdpa_expanded_kv"
                hf.AttentionInterface.register(attention, sdpa_expanded_kv)
                hf.AttentionMaskInterface.register(attention, hf.AttentionMaskInterface()["sdpa"])
            config = hf.AutoConfig.from_pretrained(path, local_files_only=True, trust_remote_code=False)
            if config.model_type != "qwen3":
                raise PipelineError("MODEL_UNAVAILABLE", "Baseline planner requires a local Qwen3 checkpoint", "model_load")
            self.tokenizer = hf.AutoTokenizer.from_pretrained(path, local_files_only=True, trust_remote_code=False)
            self.eos_id = assistant_eos_id(self.tokenizer)
            self.pad_id = getattr(self.tokenizer, "pad_token_id", None)
            if self.pad_id == self.eos_id:
                raise PipelineError("MODEL_UNAVAILABLE", "Padding must differ from the assistant end token", "model_load")
            self.special_ids = frozenset(i for i in getattr(self.tokenizer, "all_special_ids", ()) if i != self.eos_id)
            try:
                self.constraint = NativeConstraint(self.tokenizer)
            except Exception as exc:
                raise PipelineError("MODEL_UNAVAILABLE", "Cannot initialize the native decoder; install inference extra",
                                    "model_load") from exc
            self.model = hf.AutoModelForCausalLM.from_pretrained(
                path, config=config, local_files_only=True, trust_remote_code=False,
                dtype=dtype, attn_implementation=attention, weights_only=True).to("cpu" if self.cpu_offload else device)
            self.model.eval()
            count = parameter_count(self.model, 5_000_000_000)
            self.metadata = metadata(path, count, device, dtype, seed) | {
                "context_limit": limits.context_tokens, "max_new_tokens": limits.output_tokens,
                "adapter": "qwen3-native-tool-calling", "attention_implementation": attention,
                "native_policy": policy_identity(), "prompt_version": PROMPT_VERSION, "prompt_sha256": PROMPT_HASH,
                "assistant_eos_id": self.eos_id, "pad_token_id": self.pad_id,
                "structured_output": self.constraint.metadata,
                "cpu_offload": self.cpu_offload,
                "selection_filter": "task-completion-predicates-v1" if selection_filter else "disabled",
                "cuda_cache_policy": "release_before_action" if device == "cuda" else "not_applicable"}
            self.metadata['prefix_cache_policy'] = PREFIX_CACHE_POLICY
            self.metadata['native_generation_policy'] = GENERATION_POLICY if supports_fast_generate(self.model) else 'hf_generate'
        except PipelineError:
            raise
        except Exception as exc:
            raise PipelineError("MODEL_UNAVAILABLE", "Cannot load the local Qwen checkpoint/tokenizer", "model_load") from exc

    def start_sample(self, sample_id: str) -> None:
        # A request's criteria stay fixed while its records change. Never reuse
        # model-derived criteria in another sample, even with identical text.
        self._selection_filters.clear()
        self._prefix_cache = ExactPrefixCache()

    @contextmanager
    def inference_session(self):
        with super().inference_session():
            try:
                yield
            finally:
                # Also clear on tool/engine failures outside generate_native.
                self._prefix_cache = None

    def next_action(self, planner_input: JSON, remaining_seconds: float) -> str:
        started = time.monotonic()
        self.last_decision_details = []
        raw = self._action(planner_input, remaining_seconds)
        if not self.selection_filter:
            return raw
        value = copy.deepcopy(planner_input)
        for attempt in range(2):
            action = parse_action(raw, self.limits.response_bytes)
            if action["action"] == "finish":
                return raw
            # This development policy is validated for task completion. Financial
            # choices, multi-stage edits and other domains need their own evaluation;
            # treating them as a simple conjunction can change their semantics.
            if action["name"] != "tasks.complete":
                return raw
            selection = referenced_records(value, action)
            if selection is None:
                return raw
            reference = selection["reference"]
            cache_key = (reference, action["name"])
            if cache_key not in self._selection_filters:
                response = self._select(value, selection, remaining_seconds - (time.monotonic() - started))
                detail = {"reference": reference, "proposed_action": action, "predicates": response,
                          "eligible_ids": None}
                self.last_decision_details.append(detail)
                selected_ids(selection, response)  # Validate before caching model output.
                self._selection_filters[cache_key] = response
            else:
                detail = {"reference": reference, "proposed_action": action,
                          "predicates": self._selection_filters[cache_key], "eligible_ids": None}
                self.last_decision_details.append(detail)
            response = self._selection_filters[cache_key]
            ids = selected_ids(selection, response)
            detail["eligible_ids"] = ids
            if ids is None or action["arguments"][selection["parameter"]] in ids:
                return raw
            # Regenerate a decision under a narrower view. Never substitute an ID
            # into a model call or execute the rejected proposal.
            value["available_tools"] = restrict_references(value["available_tools"], selection["reference"], ids,
                                                          tool_name=action["name"])
            value["observations"].append({"kind": "validation_rejection", "code": "SELECTION_MISMATCH",
                "rejected_response": raw, "message": "No tool was executed. Proposed ID does not satisfy "
                "the request-derived filters. Choose a permitted remaining ID, or finish if work is complete.",
                "filters": response["filters"], "eligible_ids": ids})
            if attempt == 0:
                raw = self._action(value, remaining_seconds - (time.monotonic() - started))
        raise PipelineError("NO_PROGRESS", "Selection correction budget exhausted", "planner")

    def _select(self, value, selection, remaining_seconds):
        started = time.monotonic()
        generated = None
        body = {k: value[k] for k in ("request", "context", "history")}
        body.update(records=selection["records"], proposed_tool=selection["tool"])
        turns = [{"role": "system", "content": FILTER_SYSTEM}, {"role": "user", "content": dumps(body)}]
        try:
            rendered = self.tokenizer.apply_chat_template(turns, tokenize=False,
                add_generation_prompt=True, enable_thinking=False)
            tokens = self.tokenizer(rendered, return_tensors="pt", add_special_tokens=False)
            length = tokens["input_ids"].shape[-1]
            if length + self.limits.output_tokens > self.limits.context_tokens:
                raise PipelineError("CONTEXT_LIMIT", "Selection prompt plus output exceeds context", "planner")
            if self.device == "cuda":
                self.torch.cuda.empty_cache()
            prefix = self.constraint.schema_prefix(filter_schema(selection["fields"]))
            stop = stopping_criteria(self.hf, remaining_seconds - (time.monotonic() - started))
            with self.torch.inference_mode():
                output = self.model.generate(**{k: v.to(self.device) for k, v in tokens.items()},
                    do_sample=False, num_beams=1, max_new_tokens=self.limits.output_tokens,
                    prefix_allowed_tokens_fn=prefix, stopping_criteria=stop,
                    pad_token_id=self.tokenizer.eos_token_id)
            if time.monotonic() - started >= remaining_seconds:
                raise PipelineError("TIME_LIMIT", "Selection generation exceeded deadline", "planner")
            generated = output[0][length:]
            raw = self.tokenizer.decode(generated, skip_special_tokens=True)
            if len(raw.encode("utf-8")) > self.limits.response_bytes:
                raise ValueError("Oversized selection response")
            return loads(raw)
        except PipelineError:
            raise
        except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
            code = "OUTPUT_LIMIT" if generated is not None and len(generated) >= self.limits.output_tokens else "PLANNER_FORMAT"
            raise PipelineError(code, "Invalid selection response", "planner") from exc
        except Exception as exc:
            raise PipelineError("PLANNER_ERROR", "Selection generation failed", "planner") from exc

    def _action(self, planner_input: JSON, remaining_seconds: float) -> str:
        try:
            tools, _ = adapt_tools(planner_input["available_tools"])
        except ValueError as exc:
            raise PipelineError("PLANNER_ERROR", "Permitted tools cannot be adapted to native functions", "planner") from exc
        parse = self.generate_native(native_messages(planner_input), tools, remaining_seconds)
        if parse.kind == "rejected":
            record = rejection_record(1, parse.code, parse.text, stop_reason=parse.metadata["stop_reason"],
                                      eos_observed=parse.metadata["eos_observed"])
            raise NativeProposalRejected(record, full_output_sha256=fingerprint(parse.code, parse.text),
                                         diagnostics=parse.metadata)
        return parse.internal()

    def generate_native(self, messages: list[JSON], native_tools: list[JSON], remaining_seconds: float):
        """One constrained native decision for exact messages/tools (shared by all paths)."""
        started = time.monotonic()
        self.last_generation = None
        cache = getattr(self,'_prefix_cache',None)
        try:
            _, prompt_ids = render_native(self.tokenizer, messages, native_tools)
            length = len(prompt_ids)
            if length + self.limits.output_tokens > self.limits.context_tokens:
                raise PipelineError("CONTEXT_LIMIT", "Prompt plus output reservation exceeds context", "planner")
            if self.device == "cuda" and remaining_seconds > 0:
                # Varying prompt sizes otherwise retain unused blocks across a long
                # batch, leaving less headroom on GPUs with limited dedicated VRAM.
                self.torch.cuda.empty_cache()
            remaining = remaining_seconds - (time.monotonic() - started)
            stop = stopping_criteria(self.hf, remaining)
            decoder_tools = [{"name": t["function"]["name"], "parameters": t["function"]["parameters"]}
                             for t in native_tools]
            allowed = [tool["name"] for tool in decoder_tools]

            def decode(ids):
                return self.tokenizer.decode(list(ids), skip_special_tokens=False)

            guard = GuardedPrefix(self.constraint.prefix(decoder_tools), prompt_length=length,
                                  eos_id=self.eos_id, decode=decode, allowed=allowed)
            inputs = self.torch.tensor([prompt_ids])
            cache_kwargs, reused = cache.prepare(prompt_ids) if cache is not None else ({},0)
            fast = supports_fast_generate(self.model)
            forward_calls = forced_tokens = None
            with self.torch.inference_mode():
                if fast:
                    output = fast_generate(self.model,prompt_ids,guard,torch=self.torch,device=self.device,
                        eos_id=self.eos_id,max_new_tokens=self.limits.output_tokens,
                        ends_at=started+remaining_seconds,past=cache_kwargs.get('past_key_values'))
                    full_ids, past = output.ids, output.past
                    forward_calls, forced_tokens = output.forward_calls, output.forced_tokens
                else:
                    output = self.model.generate(
                        input_ids=inputs.to(self.device), attention_mask=self.torch.ones_like(inputs).to(self.device),
                        do_sample=False, num_beams=1, max_new_tokens=self.limits.output_tokens,
                        prefix_allowed_tokens_fn=guard, stopping_criteria=stop,
                        eos_token_id=self.eos_id, pad_token_id=self.pad_id if self.pad_id is not None else self.eos_id,
                        **cache_kwargs)
                    sequences = output.sequences if cache is not None else output
                    full_ids = [int(i) for i in sequences[0].tolist()]
                    past = getattr(output,'past_key_values',None)
            expired = time.monotonic() - started >= remaining_seconds
            generated = full_ids[length:]
            parse = parse_native_ids(generated, eos_id=self.eos_id, pad_id=self.pad_id, decode=decode,
                                     allowed=allowed, max_new_tokens=self.limits.output_tokens,
                                     response_bytes=self.limits.response_bytes, deadline_expired=expired,
                                     internal_error=guard.error, special_ids=self.special_ids)
            self.last_generation = {"text": parse.text, "prompt_tokens": length, **parse.metadata,
                                    "parse": parse.kind, "code": parse.code,"cached_prefix_tokens":reused,
                                    "model_forward_calls":forward_calls,"forced_tokens":forced_tokens}
            if expired:
                # An expired sample deadline stays a failure, never a repair or final.
                raise PipelineError("TIME_LIMIT", "Planner generation exceeded deadline", "planner")
            if cache is not None:
                if parse.kind == 'call':
                    cache.commit(full_ids,past)
                else:
                    cache.clear()
            return parse
        except PipelineError:
            if cache is not None:
                cache.clear()
            raise
        except Exception as exc:
            if cache is not None:
                cache.clear()
            raise PipelineError("PLANNER_ERROR", "Local planner generation failed", "planner") from exc
