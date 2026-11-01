"""Schema-directed argument conversion and visible x-ref evidence checks."""
from __future__ import annotations

import copy
from .numbers import quantity
from .temporal import temporal

ARGUMENT_POLICY_VERSION = "vi-arguments-v2"


class ArgumentRejection(ValueError):
    def __init__(self, code: str, field: str, detail: str = ""):
        super().__init__(f"{code}: {field}")
        self.code, self.field = code, field
        self.detail = detail[:512]


def _format(schema):
    if schema.get("format") in {"date", "time", "date-time"}:
        return schema["format"]
    description = schema.get("description", "")
    if "ISO-8601" in description:
        return "date-time"
    if "YYYY-MM-DD" in description:
        return "date"
    if "HH:MM" in description:
        return "time"
    return None


def normalize_arguments(arguments, tool, context):
    """Return a copy; only typed numeric/temporal fields are changed.

    Unsupported or ambiguous expressions reject the proposal before any effect.
    Other schema errors remain the organizer validator's responsibility.
    """
    def convert(value, schema, field):
        if "enum" in schema or "x-ref" in schema:
            return copy.deepcopy(value)
        try:
            if isinstance(value, str) and schema.get("type") in {"integer", "number"}:
                converted = quantity(value, field, numeric_type=schema["type"])
                if schema["type"] == "integer" and not isinstance(converted, int):
                    raise ValueError("Fraction in integer field")
                return converted
            if isinstance(value, str) and _format(schema):
                return temporal(value, _format(schema), context)
        except (ValueError, OverflowError, ArithmeticError):
            raise ArgumentRejection("ARGUMENT_NORMALIZATION", field) from None
        if isinstance(value, list) and schema.get("type") == "array":
            return [convert(item, schema.get("items", {}), field) for item in value]
        if isinstance(value, dict) and schema.get("type") == "object":
            return {key: convert(item, schema.get("properties", {}).get(key, {}), key)
                    for key, item in value.items()}
        return copy.deepcopy(value)

    return convert(arguments, tool["parameters"], "arguments")


def check_references(arguments, tool, prepared, observations):
    """Require x-ref IDs in structured visible evidence; never query hidden state.

    This verifies evidence, not continued existence or the semantic choice of entity.
    Context/history may supply an ID directly. Current observations must be successful
    results of the referenced app, including create calls that return a new ID.
    """
    def ids(value):
        found = set()
        if isinstance(value, dict):
            for key, item in value.items():
                if (key == "id" or key.endswith("_id")) and isinstance(item, str):
                    found.add(item)
                found.update(ids(item))
        elif isinstance(value, list):
            for item in value:
                found.update(ids(item))
        return found

    baseline = ids(prepared["context"])
    for turn in prepared["history"]:
        # Proposed historical call arguments are not proof the call succeeded.
        for result in turn.get("tool_results", []):
            if result.get("ok") is True:
                baseline.update(ids(result))

    def check(value, schema, field):
        reference = schema.get("x-ref")
        if isinstance(reference, str) and isinstance(value, list):
            for item in value:
                check(item, {"x-ref": reference}, field)
        if isinstance(reference, str) and isinstance(value, str):
            app = reference.split(".")[0]
            known = set(baseline)
            for observation in observations:
                result = observation.get("result", {})
                if (observation.get("kind") == "tool_result"
                        and observation.get("name", "").startswith(app + ".")
                        and result.get("ok") is True):
                    known.update(ids(result))
            if value not in known:
                raise ArgumentRejection("UNGROUNDED_REFERENCE", field)
        if isinstance(value, list):
            for item in value:
                check(item, schema.get("items", {}), field)
        if isinstance(value, dict):
            for key, item in value.items():
                check(item, schema.get("properties", {}).get(key, {}), key)

    check(arguments, tool["parameters"], "arguments")
