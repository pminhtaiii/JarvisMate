"""Local Qwen planner adapter; execution remains outside the model.

Both protocols return the same canonical call/finish JSON to the runner. The native
protocol's model-facing serialization and strict decoding live in `qwen_protocol`.
"""
from __future__ import annotations

import copy
import hashlib
import time

from ..contracts import JSON, PLANNER_PROTOCOLS, Limits, PipelineError
from ..agent import parse_action
from ..metrics import Generation
from ..prompt_profiles import profile_identity, resolve_profile
from ..prompting import NATIVE_FINISH_TEXT, NATIVE_PROMPT_HASH, NATIVE_PROMPT_VERSION, NATIVE_SYSTEM, messages
from ..jsonio import dumps, loads
from ..selection import (FILTER_SYSTEM, filter_schema, referenced_records,
                         restrict_references, selected_ids)
from . import qwen_protocol
from .common import ModelResidency, dependencies, metadata, model_directory, parameter_count, stopping_criteria
from .constrained import ActionConstraint


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
    def __init__(self, path, device: str, limits: Limits, seed: int = 20261027, *, selection_filter=False,
                 cpu_offload=False, profile: JSON | None = None, examples: tuple[JSON, ...] = (),
                 few_shot_token_budget: int | None = None, protocol: str = "structured-v1"):
        if protocol not in PLANNER_PROTOCOLS:
            raise PipelineError("INPUT_INVALID", "Unsupported planner protocol", "configuration")
        self.protocol, self.native = protocol, protocol == qwen_protocol.PROTOCOL
        if self.native and (examples or (profile is not None and profile["profile"] != "baseline")):
            raise PipelineError("INPUT_INVALID", "qwen-native-v1 uses the baseline policy without examples",
                                "configuration")
        path = model_directory(path)
        torch, hf, _ = dependencies(device, seed)
        self.torch, self.hf, self.device, self.limits = torch, hf, device, limits
        self.cpu_offload = cpu_offload and device == "cuda"
        self.selection_filter = selection_filter
        self.profile = profile or resolve_profile("baseline")
        if self.native:
            self.profile = self.profile | {"version": NATIVE_PROMPT_VERSION, "sha256": NATIVE_PROMPT_HASH,
                                           "system": NATIVE_SYSTEM}
        self.system, self.examples = self.profile["system"], tuple(examples)
        self.few_shot_token_budget = few_shot_token_budget
        self.last_decision_details = []
        self.last_native_outputs = []
        self._selection_filters = {}
        self._generation_index = 0
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
            template = getattr(self.tokenizer, "chat_template", None)
            if self.native and not isinstance(template, str):
                raise PipelineError("MODEL_UNAVAILABLE", "Native protocol requires the checkpoint chat template",
                                    "model_load")
            self.constraint = ActionConstraint(self.tokenizer)
            self.model = hf.AutoModelForCausalLM.from_pretrained(
                path, config=config, local_files_only=True, trust_remote_code=False,
                dtype=dtype, attn_implementation=attention, weights_only=True).to("cpu" if self.cpu_offload else device)
            self.model.eval()
            count = parameter_count(self.model, 5_000_000_000)
            self.example_overhead_tokens = self._measure_example_overhead() if self.examples else None
            if (self.examples and few_shot_token_budget is not None
                    and self.example_overhead_tokens > few_shot_token_budget):
                raise PipelineError("CONTEXT_LIMIT",
                                    "Fixed demonstrations exceed the configured few-shot token budget", "configuration")
            self.metadata = metadata(path, count, device, dtype, seed) | {
                "context_limit": limits.context_tokens, "max_new_tokens": limits.output_tokens,
                "adapter": "qwen3-structured-react", "attention_implementation": attention,
                "structured_output": self.constraint.metadata,
                "cpu_offload": self.cpu_offload,
                "selection_filter": "task-completion-predicates-v1" if selection_filter else "disabled",
                "cuda_cache_policy": "release_before_action" if device == "cuda" else "not_applicable",
                "prompt_profile": profile_identity(self.profile),
                "example_overhead_tokens": self.example_overhead_tokens,
                "few_shot_token_budget": few_shot_token_budget}
            if self.native:
                self.metadata |= {
                    "adapter": "qwen3-native-tool-call", "structured_output": self.constraint.native_metadata,
                    "native_protocol": {"protocol": protocol, "final_text": NATIVE_FINISH_TEXT,
                                        "eos_token_id": self.tokenizer.eos_token_id,
                                        "chat_template_sha256": hashlib.sha256(template.encode()).hexdigest()}}
        except PipelineError:
            raise
        except Exception as exc:
            raise PipelineError("MODEL_UNAVAILABLE", "Cannot load the local Qwen checkpoint/tokenizer", "model_load") from exc

    def start_sample(self, sample_id: str) -> None:
        # A request's criteria stay fixed while its records change. Never reuse
        # model-derived criteria in another sample, even with identical text.
        self._selection_filters.clear()

    def set_metrics_recorder(self, recorder) -> None:
        super().set_metrics_recorder(recorder)
        self._generation_index = 0

    def next_action(self, planner_input: JSON, remaining_seconds: float) -> str:
        started = time.monotonic()
        self.last_decision_details = []
        self.last_native_outputs = []
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
        index = self._generation_index
        self._generation_index += 1
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
            generation_start = self._recorder.clock.offset() if self._recorder else None
            try:
                with self.torch.inference_mode():
                    output = self.model.generate(**{k: v.to(self.device) for k, v in tokens.items()},
                        do_sample=False, num_beams=1, max_new_tokens=self.limits.output_tokens,
                        prefix_allowed_tokens_fn=prefix, stopping_criteria=stop,
                        pad_token_id=self.tokenizer.eos_token_id)
            except Exception:
                if self._recorder:
                    self._recorder.unfinished("generation", generation_start, index=index, parent_stage="planner_decision")
                raise
            timed_out = time.monotonic() - started >= remaining_seconds
            generated = output[0][length:]
            if self._recorder:
                span = self._recorder.mark("generation", generation_start, index=index, parent_stage="planner_decision")
                stop_reason = ("deadline" if timed_out
                              else "max_tokens" if len(generated) >= self.limits.output_tokens else "eos")
                self._recorder.record_generation(Generation("selection_filter", index, seconds=span.duration,
                                                             input_tokens=length, output_tokens=len(generated),
                                                             stop_reason=stop_reason))
            if timed_out:
                raise PipelineError("TIME_LIMIT", "Selection generation exceeded deadline", "planner")
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

    def _measure_example_overhead(self) -> int:
        """Actual added tokens from the deployed chat template, examples only.

        Both renders share an identical neutral live-turn probe, so the delta is
        exactly the demonstrations' own tokens plus their delimiters/guard text.
        """
        probe = {"request": "", "context": {"current_time": "1970-01-01T00:00:00+00:00", "timezone": "UTC",
                 "location": {"lat": 0, "lng": 0},
                 "user_profile": {"name": "", "home_address": "", "work_address": "", "city": ""},
                 "installed_apps": {}}, "history": [], "available_tools": [], "observations": []}

        def rendered_length(examples):
            text = self.tokenizer.apply_chat_template(messages(probe, system=self.system, examples=examples),
                tokenize=False, add_generation_prompt=True, enable_thinking=False)
            return self.tokenizer(text, return_tensors="pt", add_special_tokens=False)["input_ids"].shape[-1]

        return rendered_length(self.examples) - rendered_length(())

    def _action(self, planner_input: JSON, remaining_seconds: float) -> str:
        started = time.monotonic()
        index = self._generation_index
        self._generation_index += 1
        try:
            if self.native:
                rendered = self.tokenizer.apply_chat_template(
                    qwen_protocol.render_messages(planner_input, system=self.system),
                    tools=qwen_protocol.render_tools(planner_input["available_tools"]),
                    tokenize=False, add_generation_prompt=True, enable_thinking=False)
            else:
                rendered = self.tokenizer.apply_chat_template(
                    messages(planner_input, system=self.system, examples=self.examples),
                    tokenize=False, add_generation_prompt=True, enable_thinking=False)
            tokens = self.tokenizer(rendered, return_tensors="pt", add_special_tokens=False)
            length = tokens["input_ids"].shape[-1]
            if self.examples and self.few_shot_token_budget is not None:
                # The cached init-time probe is a lower bound, not this decision's
                # actual delta; verify every live render against the configured budget.
                bare = self.tokenizer.apply_chat_template(
                    messages(planner_input, system=self.system, examples=()),
                    tokenize=False, add_generation_prompt=True, enable_thinking=False)
                bare_length = self.tokenizer(bare, return_tensors="pt", add_special_tokens=False)["input_ids"].shape[-1]
                if length - bare_length > self.few_shot_token_budget:
                    raise PipelineError("CONTEXT_LIMIT",
                                        "Fixed demonstrations exceed the configured few-shot token budget", "planner")
            if length + self.limits.output_tokens > self.limits.context_tokens:
                raise PipelineError("CONTEXT_LIMIT", "Prompt plus output reservation exceeds context", "planner")
            if self.device == "cuda" and remaining_seconds > 0:
                # Varying prompt sizes otherwise retain unused blocks across a long
                # batch, leaving less headroom on GPUs with limited dedicated VRAM.
                self.torch.cuda.empty_cache()
            remaining = remaining_seconds - (time.monotonic() - started)
            stop = stopping_criteria(self.hf, remaining)
            allowed = [tool["name"] for tool in planner_input["available_tools"]]
            prefix = (self.constraint.native_prefix if self.native
                      else self.constraint.prefix)(planner_input["available_tools"])
            tokens = {k: v.to(self.device) for k, v in tokens.items()}
            generation_start = self._recorder.clock.offset() if self._recorder else None
            try:
                with self.torch.inference_mode():
                    output = self.model.generate(
                        **tokens, do_sample=False, num_beams=1, max_new_tokens=self.limits.output_tokens,
                        prefix_allowed_tokens_fn=prefix,
                        stopping_criteria=stop, pad_token_id=self.tokenizer.eos_token_id)
            except Exception:
                if self._recorder:
                    self._recorder.unfinished("generation", generation_start, index=index, parent_stage="planner_decision")
                raise
            timed_out = time.monotonic() - started >= remaining_seconds
            generated = output[0][length:]
            if self.native:
                # Decoding with skip_special_tokens hides EOS; record the actual stop first.
                ended = len(generated) > 0 and int(generated[-1]) == self.tokenizer.eos_token_id
                stop_reason = ("deadline" if timed_out else "eos" if ended
                               else "max_tokens" if len(generated) >= self.limits.output_tokens else "unknown")
            else:
                stop_reason = ("deadline" if timed_out
                               else "max_tokens" if len(generated) >= self.limits.output_tokens else "eos")
            if self._recorder:
                span = self._recorder.mark("generation", generation_start, index=index, parent_stage="planner_decision")
                self._recorder.record_generation(Generation("planner_action", index, seconds=span.duration,
                                                             input_tokens=length, output_tokens=len(generated),
                                                             stop_reason=stop_reason))
            if self.native:
                return self._native_decision(generated, stop_reason, allowed)
            if timed_out:
                raise PipelineError("TIME_LIMIT", "Planner generation exceeded deadline", "planner")
            raw = self.tokenizer.decode(generated, skip_special_tokens=True)
            try:
                action = parse_action(raw, self.limits.response_bytes)
                if action["action"] == "call" and action["name"] not in allowed:
                    raise ValueError("Unavailable tool")
            except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
                # A deadline/token cut or decoder defect must never become a
                # malformed action cycling through all planner decisions.
                code = "OUTPUT_LIMIT" if len(generated) >= self.limits.output_tokens else "PLANNER_FORMAT"
                raise PipelineError(code, "Generation did not produce a complete valid constrained action",
                                    "planner") from exc
            return raw
        except PipelineError:
            raise
        except Exception as exc:
            raise PipelineError("PLANNER_ERROR", "Local planner generation failed", "planner") from exc

    def _native_decision(self, generated, stop_reason: str, allowed: list[str]) -> str:
        """Return canonical JSON only for one complete eligible decision ended by EOS."""
        text = self.tokenizer.decode(generated, skip_special_tokens=True)
        record = {"text": text, "stop_reason": stop_reason, "output_tokens": len(generated),
                  "decision": "rejected", "canonical_action": None}
        self.last_native_outputs.append(record)
        if stop_reason == "deadline":
            raise PipelineError("TIME_LIMIT", "Planner generation exceeded deadline", "planner")
        if stop_reason != "eos":
            # Even text that parses as a complete call is a cut, never a decision.
            code = "OUTPUT_LIMIT" if stop_reason == "max_tokens" else "PLANNER_ERROR"
            raise PipelineError(code, "Native generation ended without its terminal EOS", "planner")
        try:
            action = qwen_protocol.decode_decision(text, self.limits.response_bytes)
            if action["action"] == "call" and action["name"] not in allowed:
                raise ValueError("Unavailable tool")
        except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
            raise PipelineError("PLANNER_FORMAT", "Native generation is not one complete eligible decision",
                                "planner") from exc
        record.update(decision=action["action"], canonical_action=action)
        return dumps(action)
