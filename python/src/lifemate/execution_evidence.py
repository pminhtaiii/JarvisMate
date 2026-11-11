"""Small advisory facts derived from this sample's actual tool observations."""
# shortcut: only direct x-ref properties and known collection/item result shapes; add other envelopes when their source contract is confirmed.
from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy

from .contracts import JSON
from .jsonio import dumps


class EvidenceLedger:
    """Build bounded, provenance-carrying facts without interpreting user intent."""

    def __init__(self, available_tools: Sequence[JSON], *, max_observations: int = 16,
                 max_references_per_observation: int = 8, max_id_chars: int = 128,
                 max_chars: int = 4096):
        for value in (max_observations, max_references_per_observation, max_id_chars, max_chars):
            if type(value) is not int or value < 0:
                raise ValueError("Evidence bounds must be nonnegative integers")
        self.max_observations = min(max_observations, 16)
        self.max_references_per_observation = min(max_references_per_observation, 8)
        self.max_id_chars = min(max_id_chars, 128)
        self.max_chars = min(max_chars, 4096)
        self._collection_scopes: dict[str, set[str]] = {}
        self._argument_scopes: dict[str, dict[str, str]] = {}
        for tool in available_tools if isinstance(available_tools, (tuple, list)) else ():
            if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
                continue
            parameters = tool.get("parameters")
            properties = parameters.get("properties") if isinstance(parameters, dict) else None
            if not isinstance(properties, dict):
                continue
            argument_scopes = {}
            for field, schema in properties.items():
                if not isinstance(field, str) or not isinstance(schema, dict):
                    continue
                scope = schema.get("x-ref")
                if isinstance(scope, str) and scope.count(".") == 1:
                    argument_scopes[field] = scope
                    collection = scope.rsplit(".", 1)[1]
                    self._collection_scopes.setdefault(collection, set()).add(scope)
            self._argument_scopes[tool["name"]] = argument_scopes
        self._facts: list[JSON | None] = []
        self._used_chars = 0

    def sync(self, observations: Sequence[JSON]) -> list[JSON | None]:
        """Return one stable fact per observation, adding only newly appended rows."""
        if not isinstance(observations, (tuple, list)):
            return []
        target = min(len(observations), self.max_observations)
        if len(observations) < len(self._facts):
            self._facts.clear()
            self._used_chars = 0
        while len(self._facts) < target:
            index = len(self._facts)
            if self._used_chars >= self.max_chars:
                self._facts.append(None)
                continue
            fact = self._extract(index + 1, observations[index])
            size = len(dumps(fact).encode("utf-8")) if fact is not None else 0
            if fact is not None and self._used_chars + size <= self.max_chars:
                self._facts.append(fact)
                self._used_chars += size
            else:
                self._facts.append(None)
        return deepcopy(self._facts) + [None] * (len(observations) - len(self._facts))

    def _extract(self, step: int, observation) -> JSON | None:
        if not isinstance(observation, dict):
            return None
        name, result = observation.get("name"), observation.get("result")
        if not isinstance(name, str) or not name or len(name) > 128 or not isinstance(result, dict):
            return None
        status = ("error" if result.get("ok") is False else
                  "no_op" if result.get("done") is False else
                  "ok" if result.get("ok") is True else "unknown")
        fact: JSON = {"step": step, "tool": name, "status": status, "references": []}
        if status != "ok":
            return fact

        app = name.partition(".")[0]
        scopes = []
        for collection, values in sorted(self._collection_scopes.items()):
            matches = sorted(scope for scope in values if scope.startswith(app + "."))
            if len(matches) == 1 and collection in result and isinstance(result[collection], list):
                scopes.append(matches[0])
        scopes = scopes[:8]
        for scope in scopes:
            collection = scope.rsplit(".", 1)[1]
            records = result[collection]
            fact.setdefault("returned_counts", []).append({"scope": scope, "count": len(records)})
            if len(fact["references"]) >= self.max_references_per_observation:
                break
            for index, record in enumerate(records[:self.max_references_per_observation]):
                if len(fact["references"]) >= self.max_references_per_observation:
                    break
                if not isinstance(record, dict):
                    continue
                reference_id = record.get("id")
                if isinstance(reference_id, str) and reference_id and len(reference_id) <= self.max_id_chars:
                    fact["references"].append({"scope": scope, "path": f"{collection}[{index}].id",
                                                "id": reference_id})

        item = result.get("item")
        item_id = item.get("id") if isinstance(item, dict) else None
        direct_id = result.get("id")
        if (self.max_references_per_observation and not fact["references"]
                and isinstance(item_id, str) and item_id
                and len(item_id) <= self.max_id_chars and (direct_id is None or direct_id == item_id)):
            reference: JSON = {"path": "item.id", "id": item_id}
            arguments = observation.get("arguments")
            for field, scope in self._argument_scopes.get(name, {}).items():
                if isinstance(arguments, dict) and arguments.get(field) == item_id:
                    reference["scope"] = scope
                    break
            fact["references"].append(reference)
        return fact
