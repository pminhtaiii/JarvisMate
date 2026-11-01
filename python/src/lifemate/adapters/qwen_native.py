"""Native Qwen tool-calling codec, strict parser, rejection feedback and decoder.

This is the single production boundary for SFT targets, teacher-forced diagnostics
and closed-loop inference (specs §4). The pinned tokenizer chat template owns all
rendered bytes; nothing here hand-writes ChatML. Accepted native outputs are
normalized into the existing internal Python decision used by ``agent.parse_action``;
that internal object is never a model-facing target or assistant content.

Importing this module never imports Torch, Transformers or LMFE.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from ..jsonio import dumps

PROTOCOL_VERSION = "qwen3-native-next-action-v1"
DECODER_VERSION = "lifemate-qwen-native-single-v2"
TERMINAL_POLICY = "lifemate-native-final-vi-v1"
REJECTION_SCHEMA = "lifemate-native-rejection-v1"
FINAL_CONTENT = unicodedata.normalize("NFC", "Đã kết thúc.")
ASSISTANT_EOS_TOKEN = "<|im_end|>"
CALL_OPEN, CALL_CLOSE = "<tool_call>\n", "\n</tool_call>"
PREVIEW_BYTES = 4096
MAX_REPAIRS = 2  # Total repair generations per source, never reset (specs §4.4).
STOP_REASONS = ("eos", "max_tokens", "deadline", "unknown", None)
TOOL_NAME = re.compile(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*")

REJECTION_CODES = ("NATIVE_UNAVAILABLE_TOOL", "NATIVE_JSON_INVALID", "NATIVE_MULTI_CALL",
                   "NATIVE_EMPTY", "NATIVE_FINAL_INVALID", "NATIVE_EOS_MISSING",
                   "NATIVE_TRUNCATED", "NATIVE_INTERNAL_ERROR")
# Complete EOS-terminated malformed/name/multi/unknown-final proposals may be repaired.
REPAIRABLE = frozenset({"NATIVE_UNAVAILABLE_TOOL", "NATIVE_JSON_INVALID",
                        "NATIVE_MULTI_CALL", "NATIVE_FINAL_INVALID"})
_MESSAGE_SUFFIX = " Hãy chỉ trả về một lời gọi hàm native hợp lệ, hoặc câu kết thúc theo chính sách."
MESSAGES = {
    "NATIVE_JSON_INVALID": "Đề xuất chưa được gửi tới công cụ. Hãy sửa cú pháp và chỉ trả về một lời gọi hàm native hợp lệ, hoặc câu kết thúc theo chính sách.",
    "NATIVE_UNAVAILABLE_TOOL": "Đề xuất chưa được gửi tới công cụ. Tên hàm không có trong danh sách công cụ được cung cấp." + _MESSAGE_SUFFIX,
    "NATIVE_MULTI_CALL": "Đề xuất chưa được gửi tới công cụ. Mỗi lượt chỉ được có một lời gọi hàm." + _MESSAGE_SUFFIX,
    "NATIVE_EMPTY": "Đề xuất chưa được gửi tới công cụ. Câu trả lời rỗng." + _MESSAGE_SUFFIX,
    "NATIVE_FINAL_INVALID": "Đề xuất chưa được gửi tới công cụ. Câu trả lời không phải lời gọi hàm và không đúng câu kết thúc." + _MESSAGE_SUFFIX,
    "NATIVE_EOS_MISSING": "Đề xuất chưa được gửi tới công cụ. Câu trả lời không kết thúc hợp lệ.",
    "NATIVE_TRUNCATED": "Đề xuất chưa được gửi tới công cụ. Câu trả lời bị cắt do giới hạn.",
    "NATIVE_INTERNAL_ERROR": "Đề xuất chưa được gửi tới công cụ. Lỗi nội bộ của bộ giải mã.",
}


def policy_identity() -> dict:
    """Content identities of the native model-facing policy (not accepted hashes)."""
    return {"protocol": PROTOCOL_VERSION, "decoder": DECODER_VERSION,
            "terminal_policy": TERMINAL_POLICY, "rejection_schema": REJECTION_SCHEMA,
            "final_content_sha256": hashlib.sha256(FINAL_CONTENT.encode("utf-8")).hexdigest(),
            "messages_sha256": hashlib.sha256(dumps(MESSAGES).encode("utf-8")).hexdigest(),
            "preview_bytes": PREVIEW_BYTES, "max_repairs": MAX_REPAIRS}


# ---------------------------------------------------------------- native messages

def _name(name: Any) -> str:
    if not isinstance(name, str) or not TOOL_NAME.fullmatch(name):
        raise ValueError("Native tool names must be plain catalog identifiers")
    return name


def native_call_message(name: str, arguments: dict, content: str = "") -> dict:
    """One assistant message with exactly one nested function/object tool call."""
    if not isinstance(arguments, dict):
        raise ValueError("Native call arguments must be an object")
    dumps(arguments)  # Finite JSON only.
    return {"role": "assistant", "content": content, "tool_calls": [
        {"type": "function", "function": {"name": _name(name), "arguments": copy.deepcopy(arguments)}}]}


def native_final_message() -> dict:
    return {"role": "assistant", "content": FINAL_CONTENT}


def tool_message(result: Any) -> dict:
    """Deterministic full JSON of one actual (or strictly previous gold) result."""
    if not isinstance(result, dict):
        raise ValueError("Tool results must be JSON objects")
    return {"role": "tool", "content": dumps(result)}


def call_completion_text(name: str, arguments: dict) -> str:
    """Expected assistant body for one call, matching the pinned template's tojson.

    Used for serialization round trips and as the decoder's literal wrapper bytes; the
    CPU proof must confirm it equals the bytes the actual tokenizer template renders.
    """
    body = json.dumps({"name": _name(name), "arguments": arguments}, ensure_ascii=False, allow_nan=False)
    return CALL_OPEN + body + CALL_CLOSE


def call_prefix_text(name: str) -> str:
    return CALL_OPEN + '{"name": ' + json.dumps(_name(name)) + ', "arguments": '


CALL_SUFFIX_TEXT = "}" + CALL_CLOSE


def target_semantics(message: dict) -> dict:
    """Normalize a native assistant target/proposal for validation and metrics only."""
    calls = message.get("tool_calls")
    if calls:
        if len(calls) != 1 or message.get("content", "") != "":
            raise ValueError("A native target has exactly one call and no content")
        function = calls[0]["function"]
        return {"action": "call", "name": function["name"], "arguments": copy.deepcopy(function["arguments"])}
    if message.get("content") != FINAL_CONTENT:
        raise ValueError("A native final target must use the exact terminal policy")
    return {"action": "finish"}


# --------------------------------------------------------------- rejection feedback

def bounded_preview(raw: str, limit: int = PREVIEW_BYTES) -> tuple[str, int, bool]:
    """(preview, full UTF-8 byte count, truncated), cut on a code-point boundary."""
    encoded = raw.encode("utf-8")
    preview = encoded[:limit].decode("utf-8", errors="ignore")
    return preview, len(encoded), len(encoded) > limit


def rejection_record(step: int, code: str, raw: str, *, stop_reason: str | None,
                     eos_observed: bool | None, repairable: bool | None = None) -> dict:
    if code not in REJECTION_CODES or stop_reason not in STOP_REASONS:
        raise ValueError("Unknown native rejection code or stop reason")
    if type(step) is not int or step < 1 or eos_observed not in (True, False, None):
        raise ValueError("Invalid rejection step/EOS metadata")
    preview, size, truncated = bounded_preview(raw if isinstance(raw, str) else "")
    if repairable is None:  # Decided by Python policy, never by model output.
        repairable = code in REPAIRABLE and stop_reason == "eos" and eos_observed is True
    return {"schema": REJECTION_SCHEMA, "kind": "native_rejection", "step": step, "code": code,
            "message": MESSAGES[code], "raw_native_output": preview, "raw_output_bytes": size,
            "raw_output_truncated": truncated, "stop_reason": stop_reason,
            "eos_observed": eos_observed, "repairable": bool(repairable)}


def rejection_feedback_content(record: dict) -> str:
    """Model-facing user content for a rejection; reversible JSON with < and > escaped.

    Escaping keeps ChatML/tool-tag-looking previews from tokenizing as control tokens.
    JSON text can contain angle brackets only inside strings, so this is lossless.
    """
    if record.get("schema") != REJECTION_SCHEMA:
        raise ValueError("Not a canonical native rejection record")
    return dumps(record).replace("<", "\\u003c").replace(">", "\\u003e")


def fingerprint(code: str, raw: str) -> str:
    """Repeat identity from the full output, never the truncated preview."""
    return hashlib.sha256((code + "\0" + raw).encode("utf-8")).hexdigest()


class NativeProposalRejected(Exception):
    """A native proposal was rejected before any dispatch; carries the bounded record."""

    def __init__(self, record: dict, *, full_output_sha256: str, diagnostics: dict | None = None):
        super().__init__(record["code"])
        self.record, self.full_output_sha256 = record, full_output_sha256
        self.diagnostics = diagnostics or {}


# ------------------------------------------------------------------ strict parsing

@dataclass(frozen=True)
class NativeParse:
    kind: str  # "call", "final" or "rejected"
    name: str | None = None
    arguments: dict | None = None
    code: str | None = None
    detail: str = ""
    text: str = ""
    metadata: dict = field(default_factory=dict)

    def internal(self) -> str:
        """Serialized internal decision for agent.parse_action (Python boundary only)."""
        if self.kind == "call":
            return dumps({"action": "call", "name": self.name, "arguments": self.arguments})
        if self.kind == "final":
            return dumps({"action": "finish"})
        raise ValueError("Rejected proposals have no internal decision")


def _strict_decoder():
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("Nonfinite JSON value")

    return json.JSONDecoder(object_pairs_hook=pairs, parse_constant=constant)


def _reject(code: str, detail: str, text: str) -> NativeParse:
    return NativeParse("rejected", code=code, detail=detail[:200], text=text)


def parse_native_text(text: str, allowed: Sequence[str]) -> NativeParse:
    """Whole-response parse of a complete EOS-terminated assistant body.

    Accepts exactly one wrapped call ``{"name", "arguments"}`` or the exact final
    content. Wrappers are recognized only outside JSON strings: the JSON object is
    consumed structurally before the closing tag. Multi-call responses are rejected
    whole; nothing is salvaged.
    """
    if not isinstance(text, str):
        return _reject("NATIVE_INTERNAL_ERROR", "non-text body", "")
    if text == "":
        return _reject("NATIVE_EMPTY", "empty response", text)
    if text == FINAL_CONTENT:
        return NativeParse("final", text=text)
    if not text.startswith(CALL_OPEN):
        return _reject("NATIVE_FINAL_INVALID", "neither one native call nor the exact final", text)
    position = len(CALL_OPEN)
    try:
        value, end = _strict_decoder().raw_decode(text, position)
    except (ValueError, RecursionError) as exc:
        return _reject("NATIVE_JSON_INVALID", str(exc), text)
    try:
        dumps(value)  # Rejects numeric overflow such as 1e999.
    except (ValueError, TypeError):
        return _reject("NATIVE_JSON_INVALID", "nonfinite value", text)
    rest = text[end:]
    if rest != CALL_CLOSE:
        if rest.startswith(CALL_CLOSE) and CALL_OPEN.strip() in rest[len(CALL_CLOSE):]:
            return _reject("NATIVE_MULTI_CALL", "more than one tool call", text)
        return _reject("NATIVE_JSON_INVALID", "content outside the single wrapped call", text)
    if (not isinstance(value, dict) or set(value) != {"name", "arguments"}
            or not isinstance(value["name"], str) or not isinstance(value["arguments"], dict)):
        return _reject("NATIVE_JSON_INVALID", "call JSON must contain only name and object arguments", text)
    if value["name"] not in allowed:
        return _reject("NATIVE_UNAVAILABLE_TOOL", "tool name is not permitted", text)
    return NativeParse("call", name=value["name"], arguments=value["arguments"], text=text)


def classify_stop(ids: Sequence[int], *, eos_id: int, max_new_tokens: int,
                  deadline_expired: bool = False) -> tuple[str, bool]:
    """(stop_reason, eos_observed) from raw generated IDs, before any decoding."""
    if ids and ids[-1] == eos_id:
        return "eos", True
    if deadline_expired:
        return "deadline", False
    if len(ids) >= max_new_tokens:
        return "max_tokens", False
    return "unknown", False


def parse_native_ids(ids: Sequence[int], *, eos_id: int, pad_id: int | None,
                     decode: Callable[[list[int]], str], allowed: Sequence[str],
                     max_new_tokens: int, response_bytes: int = 65_536,
                     deadline_expired: bool = False, internal_error: str | None = None,
                     special_ids: frozenset[int] = frozenset()) -> NativeParse:
    """Classify raw generated token IDs, then parse the body before EOS.

    Trailing padding (which must differ from the assistant EOS) is stripped and
    recorded. Exactly one pinned assistant EOS must end the response; a closed
    wrapper, padding/endoftext or a stop substring never substitutes for it.
    """
    raw = [int(i) for i in ids]
    unpadded = raw
    if pad_id is not None and pad_id != eos_id:
        while unpadded and unpadded[-1] == pad_id:
            unpadded = unpadded[:-1]
    stop, eos = classify_stop(unpadded, eos_id=eos_id, max_new_tokens=max_new_tokens,
                              deadline_expired=deadline_expired)
    body_ids = unpadded[:-1] if eos else unpadded
    text = decode(body_ids)
    metadata = {"generated_tokens": len(raw), "unpadded_tokens": len(unpadded), "stop_reason": stop,
                "eos_observed": eos, "output_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "output_bytes": len(text.encode("utf-8"))}

    def result(parse: NativeParse) -> NativeParse:
        return NativeParse(parse.kind, parse.name, parse.arguments, parse.code, parse.detail, text, metadata)

    if internal_error:
        return result(_reject("NATIVE_INTERNAL_ERROR", internal_error, text))
    if len(text.encode("utf-8")) > response_bytes:
        return result(_reject("NATIVE_TRUNCATED", "response exceeds byte bound", text))
    if not eos:
        code = "NATIVE_TRUNCATED" if stop in {"max_tokens", "deadline"} else "NATIVE_EOS_MISSING"
        return result(_reject(code, f"no assistant EOS ({stop})", text))
    if eos_id in body_ids or any(i in special_ids for i in body_ids):
        return result(_reject("NATIVE_JSON_INVALID", "control token inside the response body", text))
    return result(parse_native_text(text, allowed))


# ------------------------------------------------------------- shared renderer

def render_native(tokenizer, messages: list[dict], tools: list[dict], *,
                  add_generation_prompt: bool = True) -> tuple[str, list[int]]:
    """Render through the pinned chat template with tools=; return text and IDs.

    The text path (tokenize=False, then add_special_tokens=False) must equal the
    direct tokenize=True path; otherwise the shared contract is broken.
    """
    text = tokenizer.apply_chat_template(messages, tools=tools, tokenize=False,
                                         add_generation_prompt=add_generation_prompt)
    ids = list(tokenizer(text, add_special_tokens=False)["input_ids"])
    direct = tokenizer.apply_chat_template(messages, tools=tools, tokenize=True,
                                           add_generation_prompt=add_generation_prompt)
    if hasattr(direct, "keys") and "input_ids" in direct:
        direct = direct["input_ids"]
    if list(direct) != ids:
        raise ValueError("Rendered text and direct template token IDs differ")
    return text, ids


def assistant_eos_id(tokenizer) -> int:
    value = tokenizer.convert_tokens_to_ids(ASSISTANT_EOS_TOKEN)
    if type(value) is not int or value < 0 or value == getattr(tokenizer, "unk_token_id", None):
        raise ValueError("Pinned tokenizer lacks the assistant end token")
    return value


# ------------------------------------------------------------- decoder composition

def decoder_argument_schemas(tool: dict) -> list[dict]:
    """Decoder-only argument schema branches; never model-visible.

    Organizer extensions are removed only from this projection (the native function
    definitions keep them). x-one-of becomes one branch per group requiring that group
    in addition to ``required``; a value satisfying several groups is accepted by any
    of them (at-least-one, not exclusive oneOf). Strictness differences from organizer
    validation: unknown argument keys and empty required strings/arrays are excluded
    at decode time (the organizer treats empty required values as missing).
    """
    def normalize(schema, required=False):
        result = copy.deepcopy(schema)
        for key in [k for k in result if isinstance(k, str) and k.startswith("x-")] + ["description"]:
            result.pop(key, None)
        if result.get("type") == "object":
            required_keys = result.get("required", [])
            result["properties"] = {k: normalize(v, k in required_keys)
                                    for k, v in result.get("properties", {}).items()}
            result["additionalProperties"] = False
        if result.get("type") == "string" and required:
            result["minLength"] = max(1, result.get("minLength", 0))
        if result.get("type") == "array":
            result["items"] = normalize(result.get("items", {}))
            if required:
                result["minItems"] = max(1, result.get("minItems", 0))
        return result

    parameters = copy.deepcopy(tool["parameters"])
    groups = parameters.pop("x-one-of", None) or [[]]
    branches = []
    for group in groups:
        branch = copy.deepcopy(parameters)
        branch["required"] = list(dict.fromkeys(branch.get("required", []) + list(group)))
        branches.append(normalize(branch))
    return branches


def decoder_accepts(value: Any, schema: dict) -> bool:
    """Pure check of the JSON-structure subset the decoder projection enforces.

    Formats and numeric ranges stay with organizer validation; this mirrors type,
    enum, required, unknown-key, nested object/array and min-length constraints.
    """
    kind = schema.get("type")
    checks = {"string": lambda v: isinstance(v, str), "integer": lambda v: type(v) is int,
              "number": lambda v: type(v) in (int, float), "boolean": lambda v: type(v) is bool,
              "array": lambda v: isinstance(v, list), "object": lambda v: isinstance(v, dict)}
    if kind in checks and not checks[kind](value):
        return False
    if "enum" in schema and not any(v == value and type(v) is type(value) for v in schema["enum"]):
        return False
    if kind == "string" and len(value) < schema.get("minLength", 0):
        return False
    if kind == "array":
        return len(value) >= schema.get("minItems", 0) and all(
            decoder_accepts(item, schema.get("items", {})) for item in value)
    if kind == "object":
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False and set(value) - set(props):
            return False
        if any(key not in value for key in schema.get("required", [])):
            return False
        return all(decoder_accepts(item, props.get(key, {})) for key, item in value.items())
    return True


def decoder_accepts_call(tool: dict, arguments: dict) -> bool:
    return any(decoder_accepts(arguments, branch) for branch in decoder_argument_schemas(tool))


DECODER_CONFIG = {"library": "lm-format-enforcer", "required_version": "0.11.3",
                  "max_consecutive_whitespaces": 2, "force_json_field_order": False,
                  "max_json_array_length": 16_384, "forced_initial_tool_tag": False,
                  "unconstrained_fallback": False, "branches": "single_call|ordinary_final"}


def native_decoder_parser(tools: list[dict], config):
    """LMFE union of one wrapped call per tool/schema branch and the exact final."""
    from lmformatenforcer import JsonSchemaParser
    from lmformatenforcer.characterlevelparser import SequenceParser, StringParser, UnionParser

    branches = [StringParser(FINAL_CONTENT)]
    for tool in tools:
        prefix = call_prefix_text(tool["name"])
        for schema in decoder_argument_schemas(tool):
            # LMFE treats empty properties as a free-form dictionary; encode {} literally.
            if not schema["properties"]:
                branches.append(StringParser(prefix + "{}" + CALL_SUFFIX_TEXT))
            else:
                branches.append(SequenceParser([StringParser(prefix), JsonSchemaParser(schema, config=config),
                                                StringParser(CALL_SUFFIX_TEXT)]))
    return UnionParser(branches)


class GuardedPrefix:
    """Fail-closed wrapper around a prefix-allowed-tokens function.

    Records backend exceptions and forced stops: when the backend allows only EOS
    while the decoded body is not a complete accepted response, generation is marked
    as an internal constraint failure so the output can never become a final/call.
    """

    def __init__(self, function, *, prompt_length: int, eos_id: int, decode, allowed: Sequence[str]):
        self.function, self.prompt_length, self.eos_id = function, prompt_length, eos_id
        self.decode, self.allowed = decode, list(allowed)
        self.error: str | None = None

    def __call__(self, batch_id, sent):
        if self.error is not None:
            return [self.eos_id]
        try:
            allowed = list(self.function(batch_id, sent))
        except Exception as exc:  # Translate backend failure into a recorded internal error.
            self.error = f"constraint backend raised {type(exc).__name__}"
            return [self.eos_id]
        if not allowed:
            self.error = "constraint backend allowed no token"
            return [self.eos_id]
        if allowed == [self.eos_id]:
            generated = list(sent.tolist() if hasattr(sent, "tolist") else sent)[self.prompt_length:]
            if parse_native_text(self.decode(generated), self.allowed).kind == "rejected":
                self.error = "constraint backend forced a stop on an incomplete response"
        return allowed


class NativeConstraint:
    """Shared LMFE tokenizer data; a fresh parser per decision (lazy LMFE import)."""

    def __init__(self, tokenizer):
        from importlib.metadata import version
        from lmformatenforcer import CharacterLevelParserConfig
        from lmformatenforcer.integrations.transformers import (
            build_token_enforcer_tokenizer_data, build_transformers_prefix_allowed_tokens_fn)

        self.build_prefix = build_transformers_prefix_allowed_tokens_fn
        self.config = CharacterLevelParserConfig(
            max_consecutive_whitespaces=DECODER_CONFIG["max_consecutive_whitespaces"],
            force_json_field_order=DECODER_CONFIG["force_json_field_order"],
            max_json_array_length=DECODER_CONFIG["max_json_array_length"])
        self.tokenizer_data = build_token_enforcer_tokenizer_data(tokenizer)
        self.metadata = DECODER_CONFIG | {"version": version("lm-format-enforcer"), "decoder": DECODER_VERSION}

    def prefix(self, tools: list[dict]):
        from dataclasses import replace

        config = replace(self.config, alphabet=self.tokenizer_data.tokenizer_alphabet)
        return self.build_prefix(self.tokenizer_data, native_decoder_parser(tools, config))
