"""Shared native supervision boundaries, token budgets and proof bindings (LL016/LL017).

Supervision renders the same messages/tools as inference through the pinned template
(``adapters.qwen_native.render_native``). The completion is derived from actual
template IDs, never from concatenated fragments or character offsets: labels cover
one native call/final body plus exactly one assistant EOS; the template's newline
after EOS is excluded. Tokenizer loading is explicit and CPU-only; no weights.
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from ..adapters.qwen_native import (DECODER_CONFIG, FINAL_CONTENT, assistant_eos_id, call_completion_text,
                                    policy_identity, render_native)
from ..jsonio import digest, loads, visible_path
from ..prompting import PROMPT_HASH, PROMPT_VERSION
from ..contracts import PipelineError
from .config import LIMITS, content_hash
from .storage import file_hash, read_json, read_jsonl

TOKENIZATION_CONTRACT = "lifemate-native-tokenization-v1"
IGNORE_INDEX = -100
TOKENIZER_FILES = ("tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt",
                   "special_tokens_map.json", "added_tokens.json", "chat_template.jinja",
                   "generation_config.json", "config.json", "LICENSE")
NATIVE_CODE_FILES = ("native_tools.py", "adapters/qwen_native.py", "prompting.py",
                     "dataset.py", "agent.py", "adapters/common.py", "adapters/planner.py", "adapters/prefix_cache.py",
                     "adapters/fast_greedy.py",
                     "llm_training/tokenization.py", "llm_training/decoder_poc.py")
PROOF_SCHEMA = "lifemate-native-decoder-proof-v1"


class TokenizationError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def load_tokenizer(model_dir: Path):
    """Explicit local CPU tokenizer load (transformers imported lazily, offline)."""
    import os

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(model_dir, local_files_only=True, trust_remote_code=False)


def tokenizer_identity(model_dir: Path | None) -> dict | None:
    """Model-free hashes of present tokenizer/template/config files (no weights)."""
    if model_dir is None or not model_dir.is_dir():
        return None
    files = {name: digest(model_dir / name) for name in TOKENIZER_FILES if (model_dir / name).is_file()}
    template = None
    if (model_dir / "tokenizer_config.json").is_file():
        visible_path(model_dir / "tokenizer_config.json")
        config = loads((model_dir / "tokenizer_config.json").read_text(encoding="utf-8"))
        template = config.get("chat_template") if isinstance(config, dict) else None
    if template is None and (model_dir / "chat_template.jinja").is_file():
        template = (model_dir / "chat_template.jinja").read_text(encoding="utf-8")
    return {"files": files, "chat_template_sha256": None if template is None else content_hash(template)}


def native_code_identity() -> dict:
    package = Path(__file__).resolve().parents[1]
    return {name: file_hash(package / name) for name in NATIVE_CODE_FILES}


def backend_version() -> str | None:
    try:
        return version("lm-format-enforcer")
    except PackageNotFoundError:
        return None


def proof_packages() -> dict:
    result = {}
    for package in ("transformers", "tokenizers", "lm-format-enforcer", "pydantic", "pydantic-core", "interegular"):
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = None
    return result


def proof_binding(model_dir: Path | None) -> dict:
    """Everything a passed decoder proof is bound to; relevant changes need a new proof."""
    return {"policy": policy_identity(), "prompt": PROMPT_VERSION, "prompt_sha256": PROMPT_HASH,
            "native_code": native_code_identity(), "decoder_config": DECODER_CONFIG,
            "tokenizer": tokenizer_identity(model_dir), "contract": TOKENIZATION_CONTRACT}


def verify_proof(proof_dir: Path | None, model_dir: Path | None) -> dict:
    """Model-free check of a supplied proof record; never runs the proof itself."""
    if proof_dir is None:
        return {"status": "blocked_dependency", "reason": "native_decoder_proof is not configured"}
    try:
        outcome, manifest = read_json(proof_dir / "outcome.json"), read_json(proof_dir / "manifest.json")
    except OSError:
        return {"status": "blocked_dependency", "reason": "decoder proof record is unreadable"}
    if (manifest.get("schema") != PROOF_SCHEMA or outcome.get("schema") != PROOF_SCHEMA
            or manifest.get("scope") != "decoder_poc" or manifest.get("weights_loaded") is not False
            or manifest.get("gpu_used") is not False or outcome.get("status") != "passed"):
        return {"status": "blocked_dependency", "reason": f"decoder proof status is {outcome.get('status')!r}"}
    if outcome.get("manifest_sha256") != file_hash(proof_dir / "manifest.json"):
        return {"status": "blocked_dependency", "reason": "decoder proof outcome is not bound to its manifest"}
    try:
        validate_proof_evidence(proof_dir, manifest, outcome)
    except (OSError, ValueError, KeyError, TypeError, PipelineError) as exc:
        return {"status": "blocked_dependency", "reason": f"invalid proof evidence: {exc}"[:300]}
    current = proof_binding(model_dir)
    recorded = manifest.get("binding", {})
    differing = sorted(key for key in current if key != "decoder_config" and recorded.get(key) != current[key])
    if recorded.get("decoder_config") != current["decoder_config"]:
        differing.append("decoder_config")
    installed = backend_version()
    if installed is not None and installed != manifest.get("backend_version"):
        differing.append("backend_version")
    recorded_packages = manifest["package_versions"]
    for package, installed_version in proof_packages().items():
        if installed_version is not None and recorded_packages.get(package) != installed_version:
            differing.append("package:" + package)
    if differing:
        return {"status": "blocked_dependency", "reason": "decoder proof binding differs", "differing": differing}
    return {"status": "passed", "proof_id": manifest.get("proof_id"),
            "manifest_sha256": outcome["manifest_sha256"], "binding_sha256": content_hash(recorded)}


def validate_proof_evidence(directory: Path, manifest: dict, outcome: dict) -> None:
    """A passed marker cannot stand in for the nine executed token/parser groups."""
    from .decoder_poc import fixtures
    from ..adapters.qwen_native import target_semantics
    if set(manifest) != {"schema", "proof_id", "created_at", "binding", "backend_version", "fixtures_sha256",
                         "catalog_sha256", "scope", "weights_loaded", "gpu_used", "artifact_hashes", "package_versions"}:
        raise ValueError("manifest schema fields")
    if set(outcome) != {"schema", "status", "reason", "manifest_sha256", "cases", "passed_cases", "groups_covered", "recorded_at"}:
        raise ValueError("outcome schema fields")

    if manifest.get("backend_version") != DECODER_CONFIG["required_version"]:
        raise ValueError("backend is not pinned")
    packages = manifest.get("package_versions")
    if not isinstance(packages, dict) or set(packages) != set(proof_packages()) or packages.get("transformers") != "4.57.1":
        raise ValueError("CPU tokenizer/backend package binding missing")
    if manifest.get("fixtures_sha256") != content_hash(fixtures()):
        raise ValueError("fixture identity changed")
    for name in ("cases.jsonl", "token-prefix-checks.json"):
        if manifest.get("artifact_hashes", {}).get(name) != file_hash(directory / name):
            raise ValueError(f"artifact hash: {name}")
    cases = read_jsonl(directory / "cases.jsonl")
    walks = read_json(directory / "token-prefix-checks.json")
    by_name = {c["case"]: c for c in cases}
    if len(by_name) != len(cases) or set(by_name) != set(walks):
        raise ValueError("case membership/duplicates")
    mandatory = {c["case"] for c in fixtures()} | {
        "6-backend-exception", "6-backend-forced-stop", "8-eos-at-output-boundary",
        "8-token-cap-without-eos", "8-deadline-stop", "8-unknown-stop",
        "8-eos-after-deadline",
        "8-endoftext-is-not-eos", "8-no-thinking-flag-equivalence"}
    if set(by_name) not in (mandatory, mandatory | {"8-padding-after-eos"}):
        raise ValueError("required cases missing or unexpected")
    if (outcome.get("groups_covered") != list(range(1, 10)) or outcome.get("cases") != len(cases)
            or outcome.get("passed_cases") != len(cases)
            or sorted({c["group"] for c in cases}) != list(range(1, 10))):
        raise ValueError("group/count support")
    expected_fixtures = {c["case"]: c for c in fixtures()}
    for name, case in by_name.items():
        if case.get("passed") is not True:
            raise ValueError("failed case")
        fixture = expected_fixtures.get(name)
        if fixture and (case.get("kind"), case.get("group")) != (fixture["kind"], fixture["group"]):
            raise ValueError("fixture schema mismatch")
        walk = walks[name]
        if case["kind"] == "valid":
            semantic = target_semantics(fixture["target"])
            expected = ({"kind": "final"} if semantic["action"] == "finish" else
                        {"kind": "call", "name": semantic["name"], "arguments": semantic["arguments"]})
            ids, transitions = case["completion_ids"], walk["transitions"]
            if (not ids or len(ids) != len(transitions) or case.get("masked_prefix") is not True
                    or case.get("expected") != expected or case.get("observed") != expected or walk.get("accepted") is not True
                    or walk.get("rejected_at") is not None or walk.get("early_eos_at") is not None
                    or not all(t == {"index": i, "token": ids[i], "allowed": True,
                                    "eos_allowed": i == len(ids) - 1} for i, t in enumerate(transitions))):
                raise ValueError("invalid token-prefix evidence")
        elif case["kind"] == "invalid":
            if not isinstance(walk, dict) or walk.get("sequence_allowed") is not False or not walk.get("rejected_at"):
                raise ValueError("invalid negative token walk")
            observed = case["observed"]
            if fixture["expected_code"] != "DECODER_ONLY" and observed != {
                    "kind": "rejected", "code": fixture["expected_code"]}:
                raise ValueError("negative parser evidence")
        elif case["kind"] == "backend" and case.get("observed") != {
                "kind": "rejected", "code": "NATIVE_INTERNAL_ERROR"}:
            raise ValueError("backend failed open")


def supervised(tokenizer, messages: list[dict], tools: list[dict], target: dict, *,
               context_tokens: int = LIMITS["context_tokens"],
               output_tokens: int = LIMITS["output_tokens"]) -> dict:
    """Exact joint prefix plus one target response; raise TokenizationError otherwise."""
    prefix_text, prefix_ids = render_native(tokenizer, messages, tools, add_generation_prompt=True)
    full_text, full_ids = render_native(tokenizer, messages + [target], tools, add_generation_prompt=False)
    if not full_text.startswith(prefix_text) or full_ids[:len(prefix_ids)] != prefix_ids:
        raise TokenizationError("TOKEN_BOUNDARY_ERROR", "supervised render does not extend the inference prefix")
    eos = assistant_eos_id(tokenizer)
    completion = full_ids[len(prefix_ids):]
    if completion.count(eos) != 1:
        raise TokenizationError("MISSING_ASSISTANT_EOS", "target needs exactly one assistant end token")
    end = completion.index(eos)
    body, trailing = completion[:end], completion[end + 1:]
    if tokenizer.decode(trailing, skip_special_tokens=False) != "\n":
        raise TokenizationError("TOKEN_BOUNDARY_ERROR", "unexpected template suffix after assistant EOS")
    text = tokenizer.decode(body, skip_special_tokens=False)
    calls = target.get("tool_calls") or []
    expected = (call_completion_text(calls[0]["function"]["name"], calls[0]["function"]["arguments"])
                if calls else FINAL_CONTENT)
    if text != expected:
        raise TokenizationError("SERIALIZATION_MISMATCH", "template bytes differ from the decoder language")
    bos = getattr(tokenizer, "bos_token_id", None)
    if bos is not None and full_ids.count(bos) > 1:
        raise TokenizationError("TOKEN_BOUNDARY_ERROR", "duplicated BOS")
    supervised_ids = body + [eos]
    prompt_tokens, completion_tokens = len(prefix_ids), len(supervised_ids)
    if prompt_tokens + output_tokens > context_tokens or not 0 < completion_tokens <= output_tokens:
        raise TokenizationError("TOKEN_BUDGET", f"prompt={prompt_tokens} completion={completion_tokens}")
    return {"input_ids": prefix_ids + supervised_ids,
            "labels": [IGNORE_INDEX] * prompt_tokens + supervised_ids,
            "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
            "reserved_output_tokens": output_tokens, "total_tokens": prompt_tokens + completion_tokens,
            "completion_text": text}


def flag_equivalent(tokenizer, messages: list[dict], tools: list[dict]) -> bool:
    """Same native messages/tools render identically with and without enable_thinking."""
    plain = tokenizer.apply_chat_template(messages, tools=tools, tokenize=False, add_generation_prompt=True)
    flagged = tokenizer.apply_chat_template(messages, tools=tools, tokenize=False,
                                            add_generation_prompt=True, enable_thinking=False)
    return plain == flagged


def audit_rows(tokenizer, rows: list[dict]) -> dict:
    """Per-row native lengths and boundary outcomes; overflow is quarantined, never cut."""
    results, counts = [], {}
    for row in rows:
        entry = {"row_id": row["row_id"], "target_type": row["target_type"],
                 "partition": row["provenance"]["partition"]}
        try:
            audit = supervised(tokenizer, row["input"]["messages"], row["input"]["tools"], row["target"])
            entry.update(status="accepted", **{k: audit[k] for k in (
                "prompt_tokens", "completion_tokens", "reserved_output_tokens", "total_tokens")})
        except TokenizationError as exc:
            entry.update(status="quarantined", reason=exc.code, detail=exc.detail[:200])
        key = (entry["partition"], entry["target_type"], entry["status"])
        counts["/".join(key)] = counts.get("/".join(key), 0) + 1
        results.append(entry)
    return {"contract": TOKENIZATION_CONTRACT, "rows": results, "counts": counts}
