"""Reviewed slot evaluation; no annotations means unavailable, never fabricated accuracy."""
from __future__ import annotations

import hashlib
import re
import unicodedata

TYPES = {"money", "time", "address", "proper_name", "english_span"}


def canonical(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).lower().split())


def match_counts(gold: list[dict], predictions: list[dict]) -> tuple[int, int, int]:
    assigned = {}

    def visit(index, seen):
        item = gold[index]
        allowed = {item["canonical"], *item.get("alternatives", [])}
        for j, pred in enumerate(predictions):
            if j in seen or item["type"] != pred["type"] or pred["canonical"] not in allowed:
                continue
            seen.add(j)
            if j not in assigned or visit(assigned[j], seen):
                assigned[j] = index
                return True
        return False

    for i in range(len(gold)):
        visit(i, set())
    return len(assigned), len(gold) - len(assigned), len(predictions) - len(assigned)


class SlotEvaluator:
    def __init__(self, validation: list[dict], annotations: list | None, rules: dict | None):
        self.gold, self.rules = {}, rules
        self.count = len(validation)
        if annotations is None:
            self.status = "unavailable"
            return
        if not isinstance(rules, dict) or rules.get("source_partition") != "train":
            raise ValueError("Extractor rules must declare Train-only development provenance")
        if not isinstance(rules.get("patterns"), list):
            raise ValueError("Extractor patterns must be a list")
        for pattern in rules["patterns"]:
            if (not isinstance(pattern, dict) or pattern.get("type") not in TYPES
                    or not isinstance(pattern.get("pattern"), str)):
                raise ValueError("Unknown slot type")
            mapping = pattern.get("canonical_map", {})
            if not isinstance(mapping, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                                    for k, v in mapping.items()):
                raise ValueError("Canonical map must contain strings")
            re.compile(pattern["pattern"])
        indexed = {r["utterance_id"]: r for r in validation}
        for annotation in annotations:
            uid = annotation["utterance_id"]
            if (uid not in indexed or uid in self.gold or annotation.get("annotation_status") != "reviewed"
                    or not annotation.get("reviewer")):
                raise ValueError("Slot annotation must uniquely cover reviewed Validation rows")
            reference = indexed[uid]["reference"]
            if annotation["reference_sha256"] != hashlib.sha256(reference.encode("utf-8")).hexdigest():
                raise ValueError("Slot annotation reference changed")
            for item in annotation["slots"]:
                span = item.get("span")
                if not isinstance(span, list) or len(span) != 2 or any(type(v) is not int for v in span):
                    raise ValueError("Slot span must contain two integer offsets")
                start, end = span
                alternatives = item.get("alternatives", [])
                if (item["type"] not in TYPES or not 0 <= start < end <= len(reference)
                        or reference[start:end] != item["surface"] or not isinstance(item["canonical"], str)):
                    raise ValueError("Invalid slot span/canonical value")
                if (not isinstance(alternatives, list) or any(not isinstance(v, str) for v in alternatives)
                        or type(item.get("unscorable", False)) is not bool):
                    raise ValueError("Invalid slot alternatives/unscorable flag")
            self.gold[uid] = annotation["slots"]
        if set(self.gold) != set(indexed):
            raise ValueError("Gold slot annotations must cover the full frozen Validation selection")
        self.status = "available" if rules.get("validated") is True and rules.get("reviewer") else "proxy"

    def extract(self, prediction: str) -> list[dict]:
        """Receives prediction only; never uses gold spans/values as a search bank."""
        result = []
        for rule in self.rules["patterns"]:
            for match in re.finditer(rule["pattern"], prediction, flags=re.IGNORECASE):
                value = canonical(match.groupdict().get("value") or match.group(0))
                value = rule.get("canonical_map", {}).get(value, value)
                result.append({"type": rule["type"], "canonical": value})
        return result

    def summarize(self, rows: list[dict]) -> dict:
        if self.status == "unavailable":
            return {"status": self.status, "critical_slot_accuracy": None, "annotation_coverage": 0}
        counts = {kind: [0, 0, 0] for kind in TYPES}
        exact, eligible = 0, 0
        for row in rows:
            gold = self.gold[row["utterance_id"]]
            predictions = self.extract(row["prediction"] if row["status"] == "ok" else "")
            scorable = [s for s in gold if not s.get("unscorable", False)]
            for kind in TYPES:
                metrics = match_counts([s for s in scorable if s["type"] == kind],
                                       [s for s in predictions if s["type"] == kind])
                counts[kind] = [a + b for a, b in zip(counts[kind], metrics)]
            if scorable:
                eligible += 1
                tp, fn, fp = match_counts(scorable, predictions)
                exact += fn == 0 and fp == 0
        def values(numbers):
            tp, fn, fp = numbers
            return {"tp": tp, "fn": fn, "fp": fp, "support": tp + fn,
                    "accuracy": tp / (tp + fn) if tp + fn else None,
                    "precision": tp / (tp + fp) if tp + fp else None,
                    "f1": 2*tp / (2*tp + fn + fp) if 2*tp + fn + fp else None}
        total = values([sum(v[i] for v in counts.values()) for i in range(3)])
        return {"status": self.status, "critical_slot_accuracy": total["accuracy"] if self.status == "available" else None,
                "CSA_proxy": total["accuracy"] if self.status == "proxy" else None,
                "annotation_coverage": len(self.gold) / self.count, "total": total,
                "unscorable_gold": sum(bool(s.get("unscorable")) for v in self.gold.values() for s in v),
                "per_type": {k: values(v) for k, v in counts.items()},
                "critical_utterance_exact": exact / eligible if eligible else None}
