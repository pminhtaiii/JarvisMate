"""Native Qwen tool-calling protocol ``qwen-native-v1``; execution stays outside the model.

The checkpoint's own chat template renders eligible tool schemas and the actual
executed call/result pairs. One decision is exactly one EOS-terminated native
``<tool_call>`` block, or the EOS-terminated neutral text ``Mình hiểu.`` mapped to
the canonical finish action. Nothing is repaired or salvaged.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from contextlib import contextmanager

from ..contracts import JSON, Limits, PipelineError
from ..jsonio import dumps, loads
from .common import ModelResidency

from ..prompting import SYSTEM

PROTOCOL = "qwen-native-v1"
FINISH_TEXT = "Mình hiểu."
CALL_OPEN, CALL_CLOSE = "<tool_call>", "</tool_call>"
SYSTEM_SHA256 = hashlib.sha256(SYSTEM.encode("utf-8")).hexdigest()
SKILL_GUIDANCE_NOTE = ("Trường skill_guidance là hướng dẫn lập kế hoạch cho yêu cầu hiện tại, không phải "
                       "kết quả tool hay bằng chứng thao tác đã chạy. Chỉ dùng phần phù hợp với yêu cầu "
                       "của người dùng; không tự thực thi toàn bộ workflow trong hướng dẫn.")


class NativeFormatError(ValueError):
    """Model output does not match the one-call/neutral-finish protocol."""


# --- Pure protocol functions (no model libraries) ---------------------------

def tool_definitions(available_tools: list[JSON]) -> list[JSON]:
    """Eligible tools in the function-calling shape native templates expect."""
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                              "parameters": copy.deepcopy(t["parameters"])}}
            for t in available_tools]


def _skill_guidance_records(skill_guidance) -> list[JSON]:
    if skill_guidance is None:
        return []
    if not isinstance(skill_guidance, (tuple, list)):
        raise ValueError("Skill guidance must be a sequence")
    records = []
    for item in skill_guidance:
        record = item.to_dict() if callable(getattr(item, "to_dict", None)) else item
        if (not isinstance(record, dict)
                or not isinstance(record.get("branch_id"), str)
                or not isinstance(record.get("parent_id"), str)
                or record.get("evidence") != "E"
                or not isinstance(record.get("guidance"), str)
                or not isinstance(record.get("shared_instructions"), (tuple, list))
                or any(not isinstance(instruction, dict)
                       or set(instruction) != {"id", "title", "guidance"}
                       or any(not isinstance(instruction[key], str) for key in ("id", "title", "guidance"))
                       for instruction in record["shared_instructions"])):
            raise ValueError("Skill guidance record is malformed")
        # Ensure this remains structured JSON before it enters the user message.
        dumps(record)
        records.append(copy.deepcopy(record))
    return records


def render_messages(prepared: JSON, observations: list[JSON], *, skill_guidance=()) -> list[JSON]:
    """Initial request plus actual executed call/result pairs, in order.

    Only whitelisted request fields and optional validated retrieval guidance enter
    the prompt, never labels. Historical calls stay inside the user JSON as untrusted
    context rather than native turns, so they cannot be confused with calls executed
    in this sample's ToolEnv.
    """
    body = {key: copy.deepcopy(prepared[key]) for key in ("request", "context", "history")}
    guidance = _skill_guidance_records(skill_guidance)
    if guidance:
        body["skill_guidance"] = guidance
    system = SYSTEM if not guidance else SYSTEM + "\n\n" + SKILL_GUIDANCE_NOTE
    messages = [{"role": "system", "content": system}, {"role": "user", "content": dumps(body)}]
    for observation in observations:
        messages.append({"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {
            "name": observation["name"], "arguments": copy.deepcopy(observation["arguments"])}}]})
        messages.append({"role": "tool", "content": dumps(observation["result"])})
    return messages


def render_prompt(tokenizer, prepared: JSON, observations: list[JSON], *, skill_guidance=()) -> str:
    """The one prompt rendering shared by inference and supervised export."""
    return tokenizer.apply_chat_template(
        render_messages(prepared, observations, skill_guidance=skill_guidance),
        tools=tool_definitions(prepared["available_tools"]),
        tokenize=False, add_generation_prompt=True, enable_thinking=False)


def completion_text(action: JSON) -> str:
    """Canonical completion body for one action, EOS excluded; the inverse of parse_completion.

    Spacing matches both the checkpoint template's assistant turns and the decoding grammar.
    """
    if action == {"action": "finish"}:
        return FINISH_TEXT
    if (not isinstance(action, dict) or set(action) != {"action", "name", "arguments"} or action["action"] != "call"
            or not isinstance(action["name"], str) or not isinstance(action["arguments"], dict)):
        raise NativeFormatError("Action must be one call or finish")
    body = json.dumps({"name": action["name"], "arguments": action["arguments"]}, ensure_ascii=False, allow_nan=False)
    return f"{CALL_OPEN}\n{body}\n{CALL_CLOSE}"


def parse_completion(text: str, eligible: set[str]) -> JSON:
    """Map one decoded completion (EOS already verified and removed) to a canonical action."""
    if not isinstance(text, str):
        raise NativeFormatError("Completion is not text")
    body = text.strip(" \n")  # Template-compatible outer whitespace only.
    if body == FINISH_TEXT:
        return {"action": "finish"}
    if (body.count(CALL_OPEN) != 1 or body.count(CALL_CLOSE) != 1
            or not body.startswith(CALL_OPEN) or not body.endswith(CALL_CLOSE)):
        raise NativeFormatError("Expected exactly one native tool call or the neutral finish text")
    inner = body[len(CALL_OPEN):-len(CALL_CLOSE)].strip(" \n")
    try:
        value = loads(inner)  # Rejects duplicate keys, NaN/Infinity and numeric overflow.
    except (ValueError, RecursionError) as exc:
        raise NativeFormatError("Tool call is not strict JSON") from exc
    if not isinstance(value, dict) or set(value) != {"name", "arguments"}:
        raise NativeFormatError("Tool call must contain exactly name and arguments")
    if not isinstance(value["name"], str) or value["name"] not in eligible:
        raise NativeFormatError("Tool call names an ineligible tool")
    if not isinstance(value["arguments"], dict):
        raise NativeFormatError("Tool call arguments must be an object")
    return {"action": "call", "name": value["name"], "arguments": value["arguments"]}


def completion_tokens(generated: list[int], eos_ids: set[int], max_new_tokens: int,
                      timed_out: bool) -> list[int]:
    """Inspect actual termination before any special-token removal.

    Timeout stays timeout; exhaustion without EOS is an output-limit failure even
    when the decoded text happens to look complete.
    """
    if timed_out:
        raise PipelineError("TIME_LIMIT", "Planner generation exceeded the sample deadline", "planner")
    if generated and generated[-1] in eos_ids:
        body = generated[:-1]
        if any(token in eos_ids for token in body):
            raise PipelineError("PLANNER_FORMAT", "Generation contains an interior EOS", "planner")
        return body
    if len(generated) >= max_new_tokens:
        raise PipelineError("OUTPUT_LIMIT", "Generation reached max_new_tokens without EOS", "planner")
    raise PipelineError("PLANNER_FORMAT", "Generation stopped without EOS", "planner")


# --- Constrained decoding ----------------------------------------------------

def tail_sequence():
    """SequenceParser that keeps LMFE's JSON free-text shortcut while its first part is open.

    LMFE's base SequenceParser reports no shortcut when it has several parts, which
    forces a pure-Python walk over the whole vocabulary trie for every token inside
    a string argument (measured: >200 s per token with the Qwen3 tokenizer). While the
    first part cannot end, the sequence's allowed characters are exactly the first
    part's, so its shortcut is valid; quote paths are still explored by add_character.
    """
    from lmformatenforcer.characterlevelparser import SequenceParser, UnionParser

    class TailSequence(SequenceParser):
        def add_character(self, new_character):
            legal = []
            for index, parser in enumerate(self.parsers):
                if new_character in parser.get_allowed_characters():
                    following = [parser.add_character(new_character)] + self.parsers[index + 1:]
                    legal.append(following[0] if len(following) == 1 else TailSequence(following))
                if not parser.can_end():
                    break
            return legal[0] if len(legal) == 1 else UnionParser(legal)

        def shortcut_key(self):
            first = self.parsers[0]
            return first.shortcut_key() if len(self.parsers) == 1 or not first.can_end() else None

    return TailSequence


def decoding_schema(tool: JSON) -> JSON:
    """One argument schema per tool for decoding; ToolEnv still validates x-one-of.

    Separate branches per ``x-one-of`` alternative stay simultaneously alive inside
    string values with different length bounds, which disables LMFE's free-text
    shortcut (measured: >13 s for one token, then a stall). A call violating an
    alternative group still reaches ``env.call`` and is logged and scored as attempted.
    """
    from .constrained import argument_schemas

    parameters = copy.deepcopy(tool["parameters"])
    parameters.pop("x-one-of", None)
    (schema,) = argument_schemas({"parameters": parameters})
    return schema


def native_parser(tools: list[JSON], config):
    """Union of the neutral finish and one schema-bound branch per eligible tool."""
    from lmformatenforcer import JsonSchemaParser
    from lmformatenforcer.characterlevelparser import StringParser, UnionParser

    SequenceParser = tail_sequence()

    branches = [StringParser(FINISH_TEXT)]
    for tool in tools:
        prefix = CALL_OPEN + '\n{"name": ' + json.dumps(tool["name"], ensure_ascii=False) + ', "arguments": '
        suffix = "}\n" + CALL_CLOSE
        schema = decoding_schema(tool)
        if not schema["properties"]:
            # LMFE treats empty properties as a free-form dict; pin zero-argument calls.
            branches.append(StringParser(prefix + "{}" + suffix))
        else:
            branches.append(SequenceParser([StringParser(prefix), JsonSchemaParser(schema, config=config),
                                            StringParser(suffix)]))
    return UnionParser(branches)


class NativeConstraint:
    def __init__(self, tokenizer):
        try:
            from importlib.metadata import version

            from lmformatenforcer import CharacterLevelParserConfig
            from lmformatenforcer.integrations.transformers import (
                build_token_enforcer_tokenizer_data, build_transformers_prefix_allowed_tokens_fn)

            self.build_prefix = build_transformers_prefix_allowed_tokens_fn
            # Field order is free: the schema and ToolEnv ignore it, and forcing LMFE's order
            # (required keys first) would push a fine-tuned model off its natural output.
            self.config = CharacterLevelParserConfig(max_consecutive_whitespaces=2, force_json_field_order=False,
                                                     max_json_array_length=16_384)
            self.tokenizer_data = build_token_enforcer_tokenizer_data(tokenizer)
            self.metadata = {"library": "lm-format-enforcer", "version": version("lm-format-enforcer"),
                             "grammar": PROTOCOL, "finish_text": FINISH_TEXT, "strict_field_order": False,
                             "max_consecutive_whitespaces": 2, "unconstrained_fallback": False}
        except Exception as exc:
            raise PipelineError("MODEL_UNAVAILABLE", "Cannot initialize native constraints; install inference extra",
                                "model_load") from exc

    def prefix(self, tools: list[JSON]):
        from dataclasses import replace

        config = replace(self.config, alphabet=self.tokenizer_data.tokenizer_alphabet)
        return self.build_prefix(self.tokenizer_data, native_parser(tools, config))


# --- Checkpoint-specific template validation --------------------------------

PROBE_TOOL = {"name": "probe.lookup", "description": "probe", "parameters": {
    "type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}}


def validate_template(tokenizer) -> JSON:
    """Prove this checkpoint's template renders native tools/calls/results and EOS turns."""
    def fail(message):
        return PipelineError("MODEL_UNAVAILABLE", "Planner template check failed: " + message, "model_load")

    template = getattr(tokenizer, "chat_template", None)
    if not isinstance(template, str) or not template:
        raise fail("no chat template")
    eos = tokenizer.eos_token
    if not isinstance(eos, str) or tokenizer.eos_token_id is None or tokenizer.eos_token_id not in tokenizer.all_special_ids:
        raise fail("EOS must be a single special token")
    prepared = {"request": "probe", "context": {}, "history": []}
    observation = {"name": PROBE_TOOL["name"], "arguments": {"q": "x"}, "result": {"ok": True, "probe": "result-7"}}
    try:
        rendered = tokenizer.apply_chat_template(
            render_messages(prepared, [observation]), tools=tool_definitions([PROBE_TOOL]),
            tokenize=False, add_generation_prompt=True, enable_thinking=False)
    except Exception as exc:
        raise fail("rendering native messages raised") from exc
    for marker in (PROBE_TOOL["name"], CALL_OPEN, CALL_CLOSE, "<tool_response>", "result-7", eos):
        if marker not in rendered:
            raise fail("rendered prompt lacks a native tool marker")
    tail = rendered[rendered.rfind(CALL_CLOSE):]
    if tail.count("<think>") != tail.count("</think>"):
        raise fail("generation prompt leaves thinking open")
    for text in (FINISH_TEXT, CALL_OPEN, CALL_CLOSE):
        if tokenizer.decode(tokenizer.encode(text, add_special_tokens=False)) != text:
            raise fail("tokenizer does not round-trip protocol text")
    return {"template_sha256": hashlib.sha256(template.encode("utf-8")).hexdigest(),
            "eos_token": eos, "eos_token_id": tokenizer.eos_token_id,
            "tool_call_token_ids": tokenizer.encode(CALL_OPEN, add_special_tokens=False),
            "thinking": "disabled" if "<think>" not in tail else "empty_block"}


# --- Local model adapter ------------------------------------------------------

class NativePlanner(ModelResidency):
    """Local Qwen3 snapshot decoding one constrained native decision per call."""

    def __init__(self, settings, limits: Limits, seed: int, *, reuse_kv_cache: bool = False):
        from .common import dependencies, metadata, model_directory, parameter_count, resolve_device
        from .planner import sdpa_expanded_kv

        if type(reuse_kv_cache) is not bool:
            raise PipelineError("INPUT_INVALID", "reuse_kv_cache must be a boolean", "configuration")
        path = model_directory(settings.model_path)
        device = resolve_device(settings.device)
        torch, hf, _ = dependencies(device.split(":")[0], seed)
        if device.startswith("cuda") and int(device.partition(":")[2] or 0) >= torch.cuda.device_count():
            raise PipelineError("MODEL_UNAVAILABLE", "Requested CUDA device is not visible", "model_load")
        self.torch, self.hf, self.device, self.limits = torch, hf, device, limits
        self.cpu_offload = settings.offload and device.startswith("cuda")
        from .qwen_kv import SampleKVCache

        self.kv = SampleKVCache(reuse_kv_cache, limits.context_tokens)
        dtype = getattr(torch, settings.dtype)
        attention = "sdpa" if device.startswith("cuda") else "eager"
        try:
            if device.startswith("cuda") and not torch.backends.cuda.is_flash_attention_available():
                attention = "lifemate_sdpa_expanded_kv"
                hf.AttentionInterface.register(attention, sdpa_expanded_kv)
                hf.AttentionMaskInterface.register(attention, hf.AttentionMaskInterface()["sdpa"])
            config = hf.AutoConfig.from_pretrained(path, local_files_only=True, trust_remote_code=False)
            if config.model_type != "qwen3":
                raise PipelineError("MODEL_UNAVAILABLE", "Native planner requires a Qwen3 checkpoint", "model_load")
            self.tokenizer = hf.AutoTokenizer.from_pretrained(path, local_files_only=True, trust_remote_code=False)
            self.template = validate_template(self.tokenizer)
            self.constraint = NativeConstraint(self.tokenizer)
            self.model = hf.AutoModelForCausalLM.from_pretrained(
                path, config=config, local_files_only=True, trust_remote_code=False, dtype=dtype,
                attn_implementation=attention, weights_only=True).to("cpu" if self.cpu_offload else device)
            self.model.eval()
            count = parameter_count(self.model, 5_000_000_000)
            # LMFE permits only tokenizer.eos_token_id at the end; it is the authoritative terminator.
            self.eos_ids = {self.tokenizer.eos_token_id}
            self.metadata = metadata(path, count, device, dtype, seed) | {
                "adapter": PROTOCOL, "protocol": PROTOCOL, "system_sha256": SYSTEM_SHA256,
                "context_limit": limits.context_tokens, "max_new_tokens": limits.output_tokens,
                "attention_implementation": attention, "cpu_offload": self.cpu_offload,
                "template": self.template, "structured_output": self.constraint.metadata,
                "reuse_kv_cache": reuse_kv_cache}
        except PipelineError:
            raise
        except Exception as exc:
            raise PipelineError("MODEL_UNAVAILABLE", "Cannot load the local Qwen checkpoint/tokenizer", "model_load") from exc

    def render(self, prepared: JSON, observations: list[JSON], *, skill_guidance=()) -> str:
        if not skill_guidance:
            return render_prompt(self.tokenizer, prepared, observations)
        return render_prompt(self.tokenizer, prepared, observations, skill_guidance=skill_guidance)

    def fit_skill_guidance(self, prepared: JSON, skill_guidance) -> tuple:
        """Keep the most relevant guidance that fits before the output reservation."""
        selected = tuple(skill_guidance)
        while selected:
            tokens = self.tokenizer(self.render(prepared, [], skill_guidance=selected),
                                    return_tensors="pt", add_special_tokens=False)
            if tokens["input_ids"].shape[-1] + self.limits.output_tokens <= self.limits.context_tokens:
                return selected
            selected = selected[:-1]
        return ()

    def start_sample(self, sample_id: str):
        self.kv.start_sample(sample_id)
        if self.device.startswith("cuda"):
            self.torch.cuda.reset_peak_memory_stats(self.device)

    def end_sample(self):
        self.kv.end_sample()

    def sample_metrics(self):
        return self.kv.snapshot()

    @contextmanager
    def inference_session(self):
        with super().inference_session():
            try:
                yield
            finally:
                # Release device tensors before ModelResidency moves the model.
                if self.cpu_offload:
                    self.kv.clear("cpu_offload")

    def decide(self, prepared: JSON, observations: list[JSON], remaining_seconds: float, *,
               skill_guidance=()) -> tuple[JSON, JSON]:
        from .common import stopping_criteria
        from .qwen_kv import ForwardMeasurement

        started = time.monotonic()
        measurement = None
        measured = None
        try:
            rendered = (self.render(prepared, observations, skill_guidance=skill_guidance)
                        if skill_guidance else self.render(prepared, observations))
            tokens = self.tokenizer(rendered, return_tensors="pt", add_special_tokens=False)
            length = tokens["input_ids"].shape[-1]
            if length + self.limits.output_tokens > self.limits.context_tokens:
                raise PipelineError("CONTEXT_LIMIT", "Prompt plus output reservation exceeds context", "planner")
            # Keep full canonical IDs for generate's processors and LMFE. Only the
            # model forward is sliced, using the validated cached-prefix positions.
            canonical_ids = tokens["input_ids"][0].tolist() if self.kv.enabled else []
            cache_args, reused = self.kv.prepare(canonical_ids, self.model, self.hf, self.torch)
            measurement = ForwardMeasurement(self, reused)
            stop = stopping_criteria(self.hf, remaining_seconds - (time.monotonic() - started))
            prefix = self.constraint.prefix(prepared["available_tools"])
            with self.torch.inference_mode(), measurement.attach():
                output = self.model.generate(
                    **{k: v.to(self.device) for k, v in tokens.items()}, do_sample=False, num_beams=1,
                    **cache_args,
                    max_new_tokens=self.limits.output_tokens, prefix_allowed_tokens_fn=prefix,
                    stopping_criteria=stop, eos_token_id=sorted(self.eos_ids),
                    pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id)
            if self.device.startswith("cuda"):
                self.torch.cuda.synchronize(self.device)
            measured = measurement.finish(canonical_ids)
            generated = [int(t) for t in output[0][length:]]
            elapsed = time.monotonic() - started
            body = completion_tokens(generated, self.eos_ids, self.limits.output_tokens,
                                     elapsed >= remaining_seconds)
            text = self.tokenizer.decode(body, skip_special_tokens=False)
            if any(token in text for token in self.tokenizer.all_special_tokens):
                raise PipelineError("PLANNER_FORMAT", "Completion contains special tokens", "planner")
            try:
                action = parse_completion(text, {t["name"] for t in prepared["available_tools"]})
            except NativeFormatError as exc:
                raise PipelineError("PLANNER_FORMAT", str(exc), "planner") from exc
            details = {"prompt_tokens": int(length), "generated_tokens": len(generated),
                       "seconds": elapsed, "terminated": "eos", "generated_token_ids": generated,
                       "canonical_action": copy.deepcopy(action),
                       "kv_cache_enabled": self.kv.enabled, "kv_cache_reused_tokens": reused, **measured}
            return action, details
        except PipelineError:
            self.kv.clear("planner_error")
            raise
        except Exception as exc:
            self.kv.clear("generation_error")
            raise PipelineError("PLANNER_ERROR", "Local native planner generation failed", "planner") from exc
        finally:
            if measurement is not None and measurement.started is not None and measured is None:
                # A failed forward/generation has no complete device measurement.
                # Do not publish partial sums as a measured total or retry CUDA work.
                self.kv.metrics["planner_prefill_seconds"] = None
                self.kv.metrics["planner_decode_seconds"] = None
            self.kv.metrics["planner_total_seconds"] += time.monotonic() - started
