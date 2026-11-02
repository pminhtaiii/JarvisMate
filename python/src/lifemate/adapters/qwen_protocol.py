"""Qwen native function-calling serialization; the runner keeps execution authority.

Rendering is shared by inference and offline SFT export so both see identical turns.
Decoding is strict: one complete call or the exact neutral final text, never repaired.
"""
from __future__ import annotations

import re

from ..contracts import JSON
from ..jsonio import dumps, loads
from ..prompting import NATIVE_FINISH_TEXT

PROTOCOL = "qwen-native-v1"
CALL_OPEN, CALL_CLOSE = "<tool_call>\n", "\n</tool_call>"
_CALL = re.compile(re.escape(CALL_OPEN) + r"(.+)" + re.escape(CALL_CLOSE), re.DOTALL)


def render_tools(tools: list[JSON]) -> list[JSON]:
    """Only the sample's eligible tools, with catalog extensions kept verbatim."""
    return [{"type": "function", "function": {
        "name": tool["name"], "description": tool["description"], "parameters": tool["parameters"]}}
        for tool in tools]


def render_messages(value: JSON, *, system: str) -> list[JSON]:
    """Executed calls become tool_calls/tool turns; rejections stay correction data.

    Tool schemas travel through the template's `tools=` channel, so the user turn
    carries only the request, context and supplied history (history is not replayed).
    """
    turns = [{"role": "system", "content": system},
             {"role": "user", "content": dumps({k: value[k] for k in ("request", "context", "history")})}]
    for observation in value["observations"]:
        if observation["kind"] == "tool_result":
            turns.append({"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {
                "name": observation["name"], "arguments": observation["arguments"]}}]})
            turns.append({"role": "tool", "content": dumps(observation["result"])})
        else:
            # A rejected proposal never executed; it must not look like a tool result.
            turns.append({"role": "user", "content": dumps({"observation": observation})})
    return turns


def decode_decision(text: str, max_bytes: int = 65_536) -> JSON:
    """Map one native completion to the canonical call/finish decision.

    Raises ValueError for anything else. Tool eligibility is checked by the caller.
    """
    if not isinstance(text, str) or len(text.encode("utf-8")) > max_bytes:
        raise ValueError("Response is not bounded text")
    if text == NATIVE_FINISH_TEXT:
        return {"action": "finish"}
    match = _CALL.fullmatch(text)
    if match is None or "<tool_call>" in match.group(1) or "</tool_call>" in match.group(1):
        raise ValueError("Expected exactly one complete native tool call or the final text")
    body = loads(match.group(1))
    if (not isinstance(body, dict) or set(body) != {"name", "arguments"}
            or not isinstance(body["name"], str) or not body["name"]
            or not isinstance(body["arguments"], dict)):
        raise ValueError("Native call needs a name and object arguments")
    return {"action": "call", "name": body["name"], "arguments": body["arguments"]}
