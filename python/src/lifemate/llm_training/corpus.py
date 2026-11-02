"""Model-free native corpus preparation, sealed suites and selection policy (LL012, LL002).

``prepare`` verifies a supplied matching decoder-proof record (never runs it), the
frozen split and pinned hashes, expands and audits every Train source, then writes
row/audit/index artifacts atomically and seals the immutable suite core. A draft
(explicitly requested, no proof) is never sealed and cannot feed training/evaluation.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from ..contracts import PipelineError
from ..jsonio import digest
from ..prompting import PROMPT_HASH, PROMPT_VERSION, SYSTEM
from ..adapters.qwen_native import FINAL_CONTENT, MESSAGES, policy_identity
from .audit import AuditContractError, audit_expansion, load_organizer_validator, load_reviews
from .config import (EXPERIMENTS, EXPORTER_VERSION, LIMITS, QUALITY_POLICY, SEEDS, SuiteConfig,
                     content_hash, contained_output, native_identities, validate_selection_policy)
from .data import DataContractError, PRODUCTION, SplitExpectation, expand_source, load_catalog, read_train, validate_split
from .storage import (create_fresh, file_hash, new_directory, read_json, read_jsonl, seal, source_provenance,
                      verify_seal, write_json, write_jsonl)
from .tokenization import TOKENIZATION_CONTRACT, tokenizer_identity, verify_proof

SUITE_SCHEMA = "lifemate-native-suite-v1"
CORE_FILES = ("suite.json", "models.json", "prompt-contract.json", "native-format-contract.json",
              "environment-lock.json", "data/partition.json", "data/dataset-manifest.json",
              "data/fit.clean.jsonl", "data/validation.teacher-forced.jsonl", "data/quality-audit.jsonl",
              "data/quarantine.jsonl", "data/token-audit.json", "data/row-index.json")


def foundation_code():
    return {name: file_hash(Path(__file__).with_name(name)) for name in ("data.py", "audit.py", "corpus.py", "storage.py")}


class PreparationError(ValueError):
    def __init__(self, status: str, reason: str, **detail):
        super().__init__(reason)
        self.status, self.reason, self.detail = status, reason, detail


def _row_identities(partition: dict, proof: dict, tokenizer: dict | None, expected: SplitExpectation) -> dict:
    return native_identities() | {
        "dataset_sha256": expected.dataset_sha256, "catalog_sha256": expected.catalog_sha256,
        "split_identity": partition["split_identity"], "exporter": EXPORTER_VERSION,
        "serializer": "lifemate-native-assistant-serializer-v1", "quality_policy": QUALITY_POLICY,
        "decoder_proof": proof.get("manifest_sha256"), "tokenizer": None if tokenizer is None else content_hash(tokenizer),
        "asr_cache": None}


def _counts(records: list[dict]) -> dict:
    """Status totals count each row once even with several reasons."""
    out = {"rows": len(records), "by_status": Counter(), "by_partition_type_status": Counter(),
           "by_tool_status": Counter(), "by_reason": Counter(), "by_basis": Counter(), "sources_by_status": {}}
    sources: dict[str, set] = {}
    for r in records:
        out["by_status"][r["status"]] += 1
        out["by_partition_type_status"][f"{r['partition']}/{r['target_type']}/{r['status']}"] += 1
        out["by_tool_status"][f"{r.get('tool') or '-'}/{r['status']}"] += 1
        out["by_basis"][str(r["acceptance_basis"])] += 1
        for reason in r["reasons"]:
            out["by_reason"][reason] += 1
        sources.setdefault(r["status"], set()).add(r["source_id"])
    out["sources_by_status"] = {k: len(v) for k, v in sources.items()}
    return {k: (dict(v) if isinstance(v, Counter) else v) for k, v in out.items()}


def prepare(config: SuiteConfig, suite_dir: Path, *, draft: bool = False,
            expected: SplitExpectation = PRODUCTION) -> dict:
    suite_dir = contained_output(config.paths["output_root"], suite_dir)
    data_root, model_dir = config.require("data_root"), config.paths["model_dir"]
    proof = verify_proof(config.paths["native_decoder_proof"], model_dir)
    if proof["status"] != "passed" and not draft:
        raise PreparationError("blocked_dependency", "Full export requires a matching passed CPU decoder proof",
                               proof=proof)
    train_path, catalog_path = data_root / "train" / "train.jsonl", data_root / "train" / "train_tools_catalog.json"
    try:
        sources = read_train(train_path)
        partition = validate_split(config.require("split_manifest"), train_path, catalog_path, sources, expected)
        catalog, specs = load_catalog(catalog_path)
        schema_error = load_organizer_validator(config.require("runtime_dir"))
        reviews_path = config.paths["manual_reviews"]
        reviews = load_reviews(read_jsonl(reviews_path)) if reviews_path is not None else {}
        tokenizer = tokenizer_identity(model_dir)
        identities = _row_identities(partition, proof, tokenizer, expected)
        records, rows = [], {"fit": [], "validation": []}
        for source in sources:
            expansion = expand_source(source, partition, specs, identities)
            audits = audit_expansion(expansion, specs, schema_error, reviews)
            for candidate, record in zip(expansion["candidates"], audits):
                row = candidate["row"]
                calls = row["target"].get("tool_calls") if row["target"] else None
                record["tool"] = calls[0]["function"].get("name") if calls else None
                records.append(record)
                if row["input"] is None:
                    continue
                if record["partition"] == "validation":
                    rows["validation"].append(row)
                elif record["status"] == "accepted":
                    rows["fit"].append(row)  # Only accepted Fit rows can ever be trained on.
    except (DataContractError, AuditContractError, PipelineError, OSError) as exc:
        raise PreparationError("failed_preflight", str(exc)) from exc
    if any(r["provenance"]["partition"] != "fit" for r in rows["fit"]):
        raise PreparationError("failed_preflight", "Validation row reached the Fit corpus")
    create_fresh(suite_dir)
    (suite_dir / "data").mkdir()
    index, files = {}, {}
    for name, key in (("fit.clean.jsonl", "fit"), ("validation.teacher-forced.jsonl", "validation")):
        files[name] = write_jsonl(suite_dir / "data" / name, rows[key])
        for line, row in enumerate(rows[key], 1):
            index[row["row_id"]] = {"file": f"data/{name}", "line": line, "base_row_id": row["provenance"]["base_row_id"],
                                    "source_id": row["provenance"]["source_id"], "target_type": row["target_type"],
                                    "decision_index": row["provenance"]["decision_index"]}
    quarantine = [r for r in records if r["status"] != "accepted"]
    files["quality-audit.jsonl"] = write_jsonl(suite_dir / "data" / "quality-audit.jsonl", records)
    files["quarantine.jsonl"] = write_jsonl(suite_dir / "data" / "quarantine.jsonl", quarantine)
    write_json(suite_dir / "data" / "partition.json", partition)
    write_json(suite_dir / "data" / "row-index.json", index)
    write_json(suite_dir / "data" / "token-audit.json", {
        "status": "not_run", "contract": TOKENIZATION_CONTRACT, "reason": "explicit token-audit --scope clean required",
        "context_tokens": LIMITS["context_tokens"], "reserved_output_tokens": LIMITS["output_tokens"]})
    counts = _counts(records)
    write_json(suite_dir / "data" / "dataset-manifest.json", {
        "schema": "lifemate-native-dataset-manifest-v1", "identities": identities,
        "sources": {"train_jsonl_sha256": digest(train_path), "catalog_sha256": digest(catalog_path),
                    "catalog_version": catalog["schema_version"], "split_identity": partition["split_identity"],
                    "source_count": len(sources)},
        "membership": {"fit": len(partition["fit_ids"]), "validation": len(partition["validation_ids"]),
                       "groups": partition["groups"]},
        "counts": counts, "file_sha256": files, "rows": {"fit_accepted": len(rows["fit"]),
                                                          "validation_rows": len(rows["validation"])},
        "manual_reviews": None if reviews_path is None else {"sha256": file_hash(reviews_path), "records": len(reviews)},
        "closed_loop_expected_sources": len(partition["validation_ids"])})
    write_json(suite_dir / "prompt-contract.json", {"prompt": PROMPT_VERSION, "prompt_sha256": PROMPT_HASH,
                                                    "system": SYSTEM, "final_content": FINAL_CONTENT,
                                                    "rejection_messages": MESSAGES})
    write_json(suite_dir / "native-format-contract.json", {"policy": policy_identity(), "decoder_proof": proof,
                                                           "tokenization": TOKENIZATION_CONTRACT})
    write_json(suite_dir / "models.json", {"base_model": native_identities()["base_model"], "tokenizer": tokenizer,
                                           "weights": "verified separately by verify-resources"})
    write_json(suite_dir / "environment-lock.json", {"status": "not_provided",
                                                     "reason": "platform locks are authored separately (LL046)"})
    status = "draft" if draft else "sealed"
    write_json(suite_dir / "suite.json", {
        "schema": SUITE_SCHEMA, "suite_id": suite_dir.name, "status": status, "config_identity": config.identity(),
        "config": {k: v for k, v in config.source.items() if k not in config.portable}, "portable_paths": config.portable,
        "execution_metadata": {"resolved_paths": {k: None if v is None else str(v) for k, v in config.paths.items()}
                               | {"project_root": str(config.project_root)}},
        "identities": identities, "seeds": SEEDS, "limits": LIMITS, "experiments": EXPERIMENTS,
        "foundation_code": foundation_code(),
        "decoder_proof": proof, "source": source_provenance(config.project_root),
        "counts": {"rows": counts["rows"], "by_status": counts["by_status"]}})
    if not draft:
        seal(suite_dir, CORE_FILES)
    return {"status": status, "suite_dir": str(suite_dir), "counts": counts["by_status"],
            "fit_rows": len(rows["fit"]), "validation_rows": len(rows["validation"])}


def load_suite(suite_dir: Path) -> dict:
    """A sealed, intact suite; drafts and modified suites are rejected."""
    try:
        seal_record = verify_seal(suite_dir)
        suite = read_json(suite_dir / "suite.json")
    except OSError as exc:
        raise PreparationError("failed_preflight", "Suite is missing, unsealed or modified") from exc
    if suite.get("schema") != SUITE_SCHEMA or suite.get("status") != "sealed":
        raise PreparationError("failed_preflight", "Only sealed native suites are usable")
    if suite.get("foundation_code") != foundation_code():
        raise PreparationError("failed_preflight", "Foundation code changed; re-audit/prepare a new suite")
    if suite["identities"]["protocol"] != native_identities()["protocol"] or suite["identities"]["prompt_sha256"] != PROMPT_HASH:
        raise PreparationError("failed_preflight", "Suite was prepared for a different native protocol/P1")
    return {"suite": suite, "seal": seal_record, "partition": read_json(suite_dir / "data" / "partition.json"),
            "directory": suite_dir}


def seal_selection_policy(suite_dir: Path, policy: dict) -> dict:
    """Seal the preregistered policy before any model outcome exists in this suite."""
    load_suite(suite_dir)
    validated = validate_selection_policy(policy)
    evaluations = suite_dir / "evaluations"
    if evaluations.exists() and any(evaluations.iterdir()):
        raise PreparationError("failed_preflight", "Model outcomes already exist; the policy can no longer be preregistered")
    parent = suite_dir / "selection-policies"
    if parent.exists() and any(parent.iterdir()):
        raise PreparationError("failed_preflight", "A selection policy is already sealed; a change needs a new suite")
    directory = new_directory(parent, "policy")
    write_json(directory / "policy.json", validated)
    record = seal(directory, ["policy.json"])
    return {"status": "sealed", "directory": str(directory), "policy_sha256": content_hash(validated),
            "sealed_at": record["sealed_at"]}


def sealed_policy(suite_dir: Path) -> dict:
    parent = suite_dir / "selection-policies"
    entries = sorted(p for p in parent.iterdir() if p.is_dir()) if parent.is_dir() else []
    if len(entries) != 1:
        raise PreparationError("blocked_dependency", "Exactly one sealed selection policy must precede model outcomes")
    record = verify_seal(entries[0])
    policy = validate_selection_policy(read_json(entries[0] / "policy.json"))
    return {"policy": policy, "policy_sha256": content_hash(policy), "sealed_at": record["sealed_at"],
            "directory": str(entries[0])}
