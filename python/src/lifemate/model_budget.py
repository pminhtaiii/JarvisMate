"""LifeMate logical parameter budgets, independent of storage precision."""
from __future__ import annotations


def check_budget(asr: int, planner: int | None = None, *, extra: int = 0,
                 context_tokens: int = 16384) -> dict:
    for name, count in (("ASR", asr), ("extra", extra)):
        if type(count) is not int or count < 0 or (name == "ASR" and count == 0):
            raise ValueError(f"Invalid {name} logical parameter count")
    if type(context_tokens) is not int or not 0 < context_tokens <= 16384:
        raise ValueError("Planner context must be <=16384 tokens")
    if planner is not None and (type(planner) is not int or not 0 < planner < 5_000_000_000):
        raise ValueError("LLM must have fewer than 5B logical parameters")
    total = asr + extra + (planner or 0)
    if total >= 6_000_000_000:
        raise ValueError("Deployed models must have fewer than 6B logical parameters")
    return {"asr_parameters": asr, "planner_parameters": planner, "extra_parameters": extra,
            "total_parameters": total, "context_tokens": context_tokens,
            "status": "checked" if planner is not None else "planner_unverified"}
