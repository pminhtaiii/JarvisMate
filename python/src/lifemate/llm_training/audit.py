"""Three-level native-aware gold audit (specs §6; LL009-LL011).

Level 1 is deterministic and reproducible. Level 2 assigns explicit risk flags with
structured support paths; it screens, it does not certify semantics. Level 3 applies
recorded manual decisions that may accept a supported original target, keep it
pending or quarantine it, never rewrite it. Dependent prefixes/finals inherit the
worst upstream disposition. Organizer validation is loaded as a pure module only.
"""
from __future__ import annotations

import importlib.util
import re
import unicodedata
from pathlib import Path
from typing import Any, Callable

from ..adapters.qwen_native import (FINAL_CONTENT, call_completion_text, decoder_accepts_call,
                                    parse_native_text, target_semantics)
from ..jsonio import dumps, visible_path
from ..native_tools import SYSTEM_TOOL, CatalogAdapterError, restore_catalog_tools
from ..prompting import CONTROL_MARKERS
from .config import QUALITY_POLICY, content_hash

QUARANTINE = frozenset({"INVALID_SCHEMA", "UNAVAILABLE_TOOL", "PAIR_MISMATCH", "FUTURE_RESULT_LEAKAGE",
                        "TERMINAL_CONTINUATION", "SERIALIZATION_MISMATCH", "TOKEN_BOUNDARY_ERROR",
                        "TOKEN_BUDGET", "UNGROUNDED_ID", "NATIVE_FORMAT_INVALID", "NATIVE_MULTI_CALL",
                        "MISSING_ASSISTANT_EOS", "TOOL_ADAPTER_MISMATCH"})
REVIEW = frozenset({"HISTORY_PAIR_UNSUPPORTED", "HISTORY_ORDER_UNSUPPORTED", "AMOUNT_CURRENCY_RISK",
                    "RECIPIENT_AMBIGUITY", "PHONE_TIME_RISK", "NEGATION_CORRECTION_RISK",
                    "CONDITION_BRANCH_RISK", "ASR_AMBIGUITY", "GOLD_INCONSISTENCY", "MANUAL_REVIEW_REQUIRED"})
DEPENDENT = frozenset({"DEPENDENT_PREFIX", "DEPENDENT_FINISH"})
REASON_CODES = QUARANTINE | REVIEW | DEPENDENT
CRITICAL_APPS = frozenset({"banking", "ewallet", "bill_payment"})
NEGATION_CUES = ("đừng", "hủy", "huỷ", "thôi", "khỏi", "à không", "không phải", "nhầm", "sửa lại",
                 "đổi lại", "ý là", "không cần")
CONDITION_CUES = ("nếu ", "không thì", "trường hợp", "còn không", "nếu không")
NAME_FIELDS = ("name", "title", "display_name", "full_name")
REVIEW_SCHEMA = "lifemate-native-manual-review-v1"


class AuditContractError(ValueError):
    """A shared native contract (adapter/serializer) is broken: stop preparation."""


def load_organizer_validator(runtime_dir: Path) -> Callable:
    """Import only validate.py from the trusted runtime; no ToolEnv or package import."""
    path = runtime_dir / "validate.py"
    visible_path(path)
    spec = importlib.util.spec_from_file_location("_lifemate_pure_validate", path)
    if spec is None or spec.loader is None:
        raise AuditContractError("Organizer validate.py is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.schema_error


def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", text).lower()


def _walk(value: Any, path: str):
    """(path, key, value) for every scalar in a JSON value."""
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                yield from _walk(item, f"{path}.{key}")
            else:
                yield f"{path}.{key}", key, item
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, (dict, list)):
                yield from _walk(item, f"{path}[{index}]")
            else:
                yield f"{path}[{index}]", None, item


def _records(value: Any):
    """Every dict nested in a JSON value, with its parent list (for ambiguity checks)."""
    if isinstance(value, dict):
        for item in value.values():
            yield from _records(item)
        yield value, None
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                yield item, value
            yield from _records(item)


def evidence(expansion: dict, k: int) -> dict:
    """Visible evidence at decision k: request, context, history and strictly prior results."""
    visible, calls, results = expansion["visible"], expansion["calls"], expansion["results"] or []
    structured = {"context": visible["context"], "history": visible["history"],
                  "prefix": [{"arguments": calls[j].get("arguments"), "result": results[j]}
                             for j in range(min(k, len(results)))]}
    texts = [visible["request"]] + [t.get("text") for t in visible["history"]
                                    if isinstance(t, dict) and isinstance(t.get("text"), str)]
    return {"structured": structured, "texts": texts}


def _support(value: str, found: dict) -> list[str]:
    paths = [path for path, _, item in _walk(found["structured"], "evidence") if item == value]
    compact = re.sub(r"[\s.\-]", "", value)
    paths += [f"evidence.text[{i}]" for i, text in enumerate(found["texts"])
              if value in text or (compact and compact in re.sub(r"[\s.\-]", "", text))]
    return paths


def _is_id(key: str | None, schema: dict) -> bool:
    return isinstance(schema, dict) and ("x-ref" in schema or (isinstance(key, str) and (key == "id" or key.endswith("_id"))))


def level1(candidate: dict, expansion: dict, catalog_tools: dict, schema_error: Callable) -> None:
    row, reasons = candidate["row"], candidate["reasons"]
    target, binding = row["target"], candidate["binding"]
    try:
        if restore_catalog_tools(expansion["native_tools"], binding) != expansion["visible"]["permitted_tools"]:
            raise AuditContractError("Catalog adapter round trip changed schemas")
    except CatalogAdapterError as exc:
        raise AuditContractError(str(exc)) from exc
    calls = target.get("tool_calls") or []
    if len(calls) > 1:
        reasons.add("NATIVE_MULTI_CALL")
        return
    if row["target_type"] in {"initial_finish", "finish_after_calls"}:
        if target != {"role": "assistant", "content": FINAL_CONTENT} or parse_native_text(FINAL_CONTENT, []).kind != "final":
            raise AuditContractError("Native final serializer drifted from the terminal policy")
    else:
        function = calls[0].get("function", {}) if calls else {}
        name, arguments = function.get("name"), function.get("arguments")
        names = binding["names"]
        if name not in names:
            reasons.add("UNAVAILABLE_TOOL")
            return
        error = schema_error(name, arguments, catalog_tools, set(names))
        if error is not None:
            reasons.add("INVALID_SCHEMA")
            candidate["detail"]["schema_error"] = str(error)[:300]
        elif not decoder_accepts_call(catalog_tools[name], arguments):
            reasons.add("NATIVE_FORMAT_INVALID")  # Organizer-valid but outside the decoder language.
            candidate["detail"]["decoder"] = "decoder_stricter_than_organizer"
        try:
            parsed = parse_native_text(call_completion_text(name, arguments), names)
            if parsed.kind != "call" or target_semantics(target) != {
                    "action": "call", "name": parsed.name, "arguments": parsed.arguments}:
                reasons.add("SERIALIZATION_MISMATCH")
        except (ValueError, TypeError):
            reasons.add("SERIALIZATION_MISMATCH")
        if any(marker in dumps(arguments) for marker in CONTROL_MARKERS):
            reasons.add("TOKEN_BOUNDARY_ERROR")
    if row["input"] is not None:
        rendered = dumps(row["input"]["messages"])
        prior = [dumps(r) for r in (expansion["results"] or [])[:row["provenance"]["decision_index"]]]
        if any(marker in "".join(prior) for marker in CONTROL_MARKERS):
            reasons.add("TOKEN_BOUNDARY_ERROR")
        allowed_text = dumps(expansion["visible"]["history"]) + "".join(prior)
        sentinels = [dumps(r) for r in candidate["later_results"]] + [dumps(expansion["label_final_state"])]
        if any(len(s) >= 32 and s in rendered and s not in allowed_text for s in sentinels):
            reasons.add("FUTURE_RESULT_LEAKAGE")


def level2(candidate: dict, expansion: dict, catalog_tools: dict) -> None:
    row, reasons, detail = candidate["row"], candidate["reasons"], candidate["detail"]
    k = row["provenance"]["decision_index"]
    found = evidence(expansion, k)
    texts = " ".join(_norm(t) for t in found["texts"])
    if any(cue in texts for cue in NEGATION_CUES):
        reasons.add("NEGATION_CORRECTION_RISK")
    prior = (expansion["results"] or [])[:k]
    if any(cue in texts for cue in CONDITION_CUES) or any(
            r.get("ok") is False or r.get("done") is False for r in prior):
        reasons.add("CONDITION_BRANCH_RISK")
    if row["target_type"] == "finish_after_calls":
        if any(r.get("ok") is False or r.get("done") is False for r in prior):
            reasons.add("DEPENDENT_FINISH")  # Completion cannot be inferred from status alone.
        return
    if row["target_type"] == "initial_finish":
        return
    function = row["target"]["tool_calls"][0]["function"]
    name, arguments = function["name"], function["arguments"]
    tool = catalog_tools[name]
    properties = tool["parameters"].get("properties", {})
    zone = re.search(r"(Z|[+-]\d{2}:\d{2})$", expansion["visible"]["context"]["current_time"])
    offset = zone.group(1) if zone else ""
    support, slots = {}, []
    for key, value in arguments.items():
        schema = properties.get(key, {})
        values = value if isinstance(value, list) else [value]
        if _is_id(key, schema) and all(isinstance(v, str) for v in values):
            for item in values:
                paths = _support(item, found)
                support[key] = paths
                slots.append(key)
                if not paths:
                    reasons.add("UNGROUNDED_ID")
                for record, siblings in _records(found["structured"]):
                    if record.get("id") == item and siblings is not None:
                        names = [_norm(str(r.get(f))) for r in siblings if isinstance(r, dict)
                                 for f in NAME_FIELDS if r.get(f) is not None]
                        if len(names) != len(set(names)):
                            reasons.add("RECIPIENT_AMBIGUITY")
        elif "phone" in key and isinstance(value, str):
            slots.append(key)
            support[key] = _support(value, found)
            if not re.fullmatch(r"\+?\d+", value) or not support[key]:
                reasons.add("PHONE_TIME_RISK")
        elif schema.get("format") == "date-time" and isinstance(value, str):
            slots.append(key)
            if offset and not value.endswith(offset):
                reasons.add("PHONE_TIME_RISK")
        elif key == "amount" or "currency" in key:
            slots.append(key)
            literal = str(value)
            support[key] = _support(literal, found)
            if not support[key]:
                reasons.add("AMOUNT_CURRENCY_RISK")
    if tool.get("app") in CRITICAL_APPS and tool.get("kind") == "write":
        reasons.add("MANUAL_REVIEW_REQUIRED")  # Critical transaction mutations need Level 3.
        if "amount" in arguments:
            reasons.add("AMOUNT_CURRENCY_RISK")
    if name == SYSTEM_TOOL:
        asked = arguments.get("tool_name")
        params = arguments.get("params")
        known = catalog_tools.get(asked, {}).get("parameters", {}).get("properties", {})
        if asked not in expansion["visible"]["tool_names"] or not isinstance(params, list) or not set(params) <= set(known):
            reasons.add("GOLD_INCONSISTENCY")
    detail["support_paths"], detail["affected_slots"] = support, slots


def apply_review(candidate: dict, review: dict | None) -> None:
    """Level 3: accept supported original targets, keep pending or quarantine."""
    if review is None:
        return
    if review.get("original_target_sha256") != content_hash(candidate["row"]["target"]):
        candidate["detail"]["review_rejected"] = "original_target_hash_mismatch"
        return
    candidate["review"] = {k: review.get(k) for k in ("decision", "reviewer", "policy", "evidence_paths",
                                                      "affected_slots", "prefix_valid", "notes")}


def status_of(candidate: dict) -> tuple[str, str | None]:
    reasons, review = candidate["reasons"], candidate.get("review")
    if reasons & QUARANTINE:
        return "quarantined", None
    if review and review["decision"] == "quarantine":
        return "quarantined", None
    if reasons & (REVIEW | DEPENDENT):
        if review and review["decision"] == "accept" and review.get("prefix_valid") is True:
            return "accepted", "manual_review"
        return "needs_review", None
    return "accepted", "organizer_gold_screened"


def audit_expansion(expansion: dict, catalog_tools: dict, schema_error: Callable,
                    reviews: dict[str, dict] | None = None) -> list[dict]:
    """Audit every candidate row of one source and propagate dependent dispositions."""
    records = []
    upstream = None  # Worst status among earlier decisions of this source.
    for candidate in expansion["candidates"]:
        candidate["detail"] = {}
        row = candidate["row"]
        level = 1
        if not candidate["reasons"] & {"PAIR_MISMATCH"}:
            level1(candidate, expansion, catalog_tools, schema_error)
            if not candidate["reasons"] & QUARANTINE and row["input"] is not None:
                level2(candidate, expansion, catalog_tools)
                level = 2
        if upstream is not None:
            candidate["reasons"].add("DEPENDENT_FINISH" if row["target_type"] == "finish_after_calls" else "DEPENDENT_PREFIX")
        apply_review(candidate, (reviews or {}).get(row["row_id"]))
        status, basis = status_of(candidate)
        if upstream == "quarantined" and status != "quarantined":
            status, basis = "quarantined", None  # A quarantined prefix taints every later row.
        if candidate.get("review"):
            level = 3
        records.append({
            "schema": "lifemate-native-audit-record-v1", "policy": QUALITY_POLICY,
            "row_id": row["row_id"], "base_row_id": row["provenance"]["base_row_id"],
            "source_id": row["provenance"]["source_id"], "partition": row["provenance"]["partition"],
            "decision_index": row["provenance"]["decision_index"], "view": row["provenance"]["view"],
            "target_type": row["target_type"], "status": status, "acceptance_basis": basis,
            "reasons": sorted(candidate["reasons"]), "audit_level": level,
            "support_paths": candidate["detail"].get("support_paths", {}),
            "affected_slots": candidate["detail"].get("affected_slots", []),
            "prefix_status": "clean" if upstream is None else f"depends_on_{upstream}",
            "dependent_row_ids": [], "review": candidate.get("review"),
            "original_target_sha256": content_hash(row["target"]),
            "detail": {k: v for k, v in candidate["detail"].items() if k not in {"support_paths", "affected_slots"}},
        })
        if status != "accepted":
            upstream = "quarantined" if "quarantined" in (status, upstream) else "needs_review"
    for index, record in enumerate(records):
        if record["status"] != "accepted":
            record["dependent_row_ids"] = [r["row_id"] for r in records[index + 1:]]
    return records


def load_reviews(rows: list[dict]) -> dict[str, dict]:
    """Strict Level 3 records keyed by row_id; labels/results are never edited by review."""
    reviews = {}
    for review in rows:
        if (not isinstance(review, dict) or review.get("schema") != REVIEW_SCHEMA
                or review.get("decision") not in {"accept", "pending", "quarantine"}
                or not isinstance(review.get("row_id"), str) or not isinstance(review.get("reviewer"), str)
                or not isinstance(review.get("original_target_sha256"), str)
                or not isinstance(review.get("evidence_paths"), list)
                or not isinstance(review.get("prefix_valid"), bool) or review["row_id"] in reviews):
            raise AuditContractError("Invalid or duplicate manual review record")
        reviews[review["row_id"]] = review
    return reviews
