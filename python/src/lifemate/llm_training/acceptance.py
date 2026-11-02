"""Content-bound readiness and token-valid inputs; all readers are model-free."""
from pathlib import Path

from .config import content_hash
from .corpus import PreparationError, load_suite
from .storage import (file_hash, new_directory, ordered_hash, read_json, read_jsonl,
                      seal, verify_seal, write_json, write_jsonl)
from .tokenization import audit_rows, flag_equivalent, proof_binding, supervised, verify_proof


def input_identity(config, loaded: dict, *, mode: str = "G") -> dict:
    """Rehash actual visible inputs before model load and again before reference scoring."""
    manifest = read_json(loaded["directory"] / "data" / "dataset-manifest.json")
    expected = manifest["sources"]
    data = config.require("data_root") / "train"
    pairs = {"dataset_sha256": (data / "train.jsonl", expected["train_jsonl_sha256"]),
             "catalog_sha256": (data / "train_tools_catalog.json", expected["catalog_sha256"]),
             "split_manifest_sha256": (config.require("split_manifest"), loaded["partition"]["split_manifest_sha256"])}
    actual = {key: file_hash(path) for key, (path, _) in pairs.items()}
    if any(actual[key] != wanted for key, (_, wanted) in pairs.items()):
        raise PreparationError("failed_preflight", "Dataset/catalog/split changed after suite seal")
    actual["partition_sha256"] = file_hash(loaded["directory"] / "data" / "partition.json")
    if mode == "A":
        actual["asr_cache_sha256"] = file_hash(config.require("validation_asr_cache"))
        actual["asr_cache_manifest_sha256"] = file_hash(config.require("validation_asr_cache").with_suffix(".manifest.json"))
        actual["asr_export_handoff_sha256"] = file_hash(config.require("asr_model_dir") / "llm-handoff.json")
    return actual


def matching_proof(config, loaded: dict) -> dict:
    proof = verify_proof(config.paths["native_decoder_proof"], config.paths["model_dir"])
    if proof["status"] != "passed" or proof != loaded["suite"]["decoder_proof"]:
        raise PreparationError("blocked_dependency", "Missing, stale or differently bound decoder proof", proof=proof)
    return proof


def audit_corpus(config, suite_dir: Path, tokenizer, *, scope: str = "clean", rows=None, view_dir=None) -> dict:
    loaded = load_suite(suite_dir)
    proof = matching_proof(config, loaded)
    view_binding = None
    if scope == "asr":
        if view_dir is None or not view_dir.resolve().is_relative_to(suite_dir.resolve()):
            raise ValueError("ASR token audit needs a sealed view set in this suite")
        view_seal = verify_seal(view_dir)
        view_manifest = read_json(view_dir / "manifest.json")
        clean = accepted_corpus(config, suite_dir)
        if view_manifest.get("clean_corpus") != clean["identity"] or view_manifest.get("suite_seal") != loaded["seal"]["identity"]:
            raise ValueError("ASR views do not bind the accepted clean corpus")
        view_audits = {a.get("row_id"): a for a in read_jsonl(view_dir / "asr-view-audit.jsonl") if a["status"] == "accepted"}
        if rows != read_jsonl(view_dir / "fit.asr-approved.jsonl") or any(
                view_audits.get(r["row_id"], {}).get("row_sha256") != ordered_hash(r) for r in rows):
            raise ValueError("ASR rows lack matching full-prefix acceptance evidence")
        view_binding = {"directory": view_dir.relative_to(suite_dir).as_posix(), "identity": view_seal["identity"]}
    if rows is None:
        rows = (read_jsonl(suite_dir / "data" / "fit.clean.jsonl")
                + read_jsonl(suite_dir / "data" / "validation.teacher-forced.jsonl"))
    quality = {a["row_id"]: a["status"] for a in read_jsonl(suite_dir / "data" / "quality-audit.jsonl")}
    eligible = [r for r in rows if quality.get(r["row_id"]) == "accepted" or scope == "asr"]
    result = audit_rows(tokenizer, eligible)
    accepted = {r["row_id"] for r in result["rows"] if r["status"] == "accepted"}
    valid = [r for r in eligible if r["row_id"] in accepted]
    cache = []
    for row in valid:
        sup = supervised(tokenizer, row["input"]["messages"], row["input"]["tools"], row["target"])
        cache.append({"row_id": row["row_id"], "row_sha256": ordered_hash(row), **sup})
    flags = bool(valid) and all(flag_equivalent(tokenizer, r["input"]["messages"], r["input"]["tools"]) for r in valid)
    support = {p: sum(r["provenance"]["partition"] == p for r in valid) for p in ("fit", "validation")}
    broken = any(r.get("reason") != "TOKEN_BUDGET" for r in result["rows"] if r["status"] != "accepted")
    passed = flags and not broken and support["fit"] > 0 and (scope == "asr" or support["validation"] > 0)
    directory = new_directory(suite_dir / "token-audits", scope)
    write_jsonl(directory / "accepted.rows.jsonl", valid)
    write_jsonl(directory / "token-cache.jsonl", cache)
    index = {r["row_id"]: {"line": i, "partition": r["provenance"]["partition"],
                            "row_sha256": ordered_hash(r)} for i, r in enumerate(valid, 1)}
    write_json(directory / "row-index.json", index)
    report = {"schema": "lifemate-native-token-audit-v2", "scope": scope,
              "status": "passed" if passed else "failed", "binding": proof_binding(config.paths["model_dir"]),
              "proof": proof, "suite_seal": loaded["seal"]["identity"], "flag_equivalence": flags,
              "input_rows_sha256": ordered_hash(rows), "accepted_support": support,
              "excluded_quality": len(rows) - len(eligible), "view_binding": view_binding,
              "storage_sha256": file_hash(Path(__file__).with_name("storage.py")),
              "acceptance_code_sha256": file_hash(Path(__file__)),
              "assistant_eos_id": tokenizer.convert_tokens_to_ids("<|im_end|>"), **result}
    report["artifacts"] = {n: file_hash(directory / n) for n in (
        "accepted.rows.jsonl", "token-cache.jsonl", "row-index.json")}
    write_json(directory / "token-audit.json", report)
    seal(directory, ["token-audit.json", *report["artifacts"]])
    return {"status": report["status"], "directory": str(directory), "counts": result["counts"],
            "accepted_support": support}


def accepted_corpus(config, suite_dir: Path, *, scope="clean") -> dict:
    """No trust in a passed boolean: reconcile seal, binding, rows, masks and support."""
    loaded = load_suite(suite_dir)
    proof = matching_proof(config, loaded)
    candidates = sorted((suite_dir / "token-audits").glob(f"{scope}-*/token-audit.json"))
    matches = []
    for path in candidates:
        report = read_json(path)
        if report.get("scope") == scope and report.get("status") == "passed":
            matches.append(path)
    if len(matches) != 1:
        raise PreparationError("blocked_dependency", "Exactly one valid token corpus must be explicitly available")
    directory = matches[0].parent
    verify_seal(directory)
    report = read_json(matches[0])
    if (report.get("schema") != "lifemate-native-token-audit-v2" or report.get("proof") != proof
            or report.get("binding") != proof_binding(config.paths["model_dir"])
            or report.get("storage_sha256") != file_hash(Path(__file__).with_name("storage.py"))
            or report.get("acceptance_code_sha256") != file_hash(Path(__file__))
            or report.get("suite_seal") != loaded["seal"]["identity"] or report.get("flag_equivalence") is not True):
        raise PreparationError("blocked_dependency", "Stale token corpus binding")
    rows, cache = read_jsonl(directory / "accepted.rows.jsonl"), read_jsonl(directory / "token-cache.jsonl")
    index = read_json(directory / "row-index.json")
    if not rows or len(rows) != len(cache) or len(index) != len(rows):
        raise PreparationError("failed_preflight", "Empty/invalid token-valid row index")
    support = {p: sum(r["provenance"]["partition"] == p for r in rows) for p in ("fit", "validation")}
    valid_ids = {r["row_id"] for r in report["rows"] if r["status"] == "accepted"}
    if (support != report["accepted_support"] or support["fit"] <= 0
            or (scope == "clean" and support["validation"] <= 0) or set(index) != valid_ids):
        raise PreparationError("failed_preflight", "Token audit support/index mismatch")
    if scope == "clean":
        original = read_jsonl(suite_dir / "data/fit.clean.jsonl") + read_jsonl(suite_dir / "data/validation.teacher-forced.jsonl")
        quality = {a["row_id"]: a["status"] for a in read_jsonl(suite_dir / "data/quality-audit.jsonl")}
        eligible = {r["row_id"]: ordered_hash(r) for r in original if quality.get(r["row_id"]) == "accepted"}
        if ordered_hash(original) != report["input_rows_sha256"] or any(eligible.get(r["row_id"]) != ordered_hash(r) for r in rows):
            raise PreparationError("failed_preflight", "Quarantined/changed row entered token corpus")
    else:
        from ..jsonio import contained
        source = report.get("view_binding")
        if not source or verify_seal(contained(suite_dir, source["directory"], must_exist=False))["identity"] != source["identity"]:
            raise PreparationError("failed_preflight", "ASR approval source is absent/changed")
        view_manifest = read_json(contained(suite_dir, source["directory"] + "/manifest.json"))
        cache = config.require("fit_asr_cache")
        from .asr_views import validate_export
        if (file_hash(cache) != view_manifest["cache"]["cache_sha256"]
                or file_hash(cache.with_suffix(".manifest.json")) != view_manifest["cache"]["manifest_sha256"]
                or validate_export(config.require("asr_model_dir"), loaded["partition"])["identity"] != view_manifest["cache"]["export_identity"]):
            raise PreparationError("failed_preflight", "Fit ASR cache/export changed after view approval")
    for i, (row, item) in enumerate(zip(rows, cache), 1):
        rid, part = row["row_id"], row["provenance"]["partition"]
        if (index.get(rid) != {"line": i, "partition": part, "row_sha256": ordered_hash(row)}
                or item["row_id"] != rid or item["row_sha256"] != ordered_hash(row)
                or item["labels"][:item["prompt_tokens"]] != [-100] * item["prompt_tokens"]
                or item["labels"][item["prompt_tokens"]:] != item["input_ids"][item["prompt_tokens"]:]
                or item["completion_tokens"] != len(item["input_ids"]) - item["prompt_tokens"]):
            raise PreparationError("failed_preflight", "Token cache/index/mask inconsistency")
        completion = item["labels"][item["prompt_tokens"]:]
        if (not completion or completion[-1] != report["assistant_eos_id"]
                or completion.count(report["assistant_eos_id"]) != 1 or len(completion) > 512
                or item["prompt_tokens"] + 512 > 16384):
            raise PreparationError("failed_preflight", "Token budget/EOS inconsistency")
    return {"directory": directory, "identity": verify_seal(directory)["identity"], "report": report,
            "rows": rows, "cache": cache}


def evaluation_readiness(config, suite_dir: Path, *, teacher_forced=False, mode="G") -> dict:
    loaded = load_suite(suite_dir)
    proof = matching_proof(config, loaded)
    inputs = input_identity(config, loaded, mode=mode)
    # P1/history/feedback acceptance is separate from a full Fit corpus (L0-G).
    supplied = config.paths.get("native_acceptance")
    records = [supplied / "acceptance.json"] if supplied else sorted((suite_dir / "native-acceptances").glob("*/acceptance.json"))
    accepted = []
    for path in records:
        verify_seal(path.parent)
        rec = read_json(path)
        if (rec.get("status") == "passed" and rec.get("binding") == proof_binding(config.paths["model_dir"])
                and rec.get("storage_sha256") == file_hash(Path(__file__).with_name("storage.py"))
                and rec.get("acceptance_code_sha256") == file_hash(Path(__file__))
                and rec.get("proof") == proof and rec.get("checks") == NATIVE_CHECKS):
            accepted.append(file_hash(path))
    if len(accepted) != 1:
        raise PreparationError("blocked_dependency", "Full native render/history/feedback/mask acceptance missing/stale")
    corpus = accepted_corpus(config, suite_dir)["identity"] if teacher_forced else None
    return {"proof": proof, "native_acceptance": accepted[0], "inputs": inputs, "token_corpus": corpus}


NATIVE_CHECKS = ["history_text_single_multi_order", "feedback_control_escape_prefix", "one_eos_mask",
                 "flag_equivalence", "initial_and_post_final", "persisted_render_ids"]


def native_acceptance(config, suite_dir: Path | None, tokenizer) -> dict:
    """CPU fixture regressions independent of full Fit export and model weights."""
    from ..adapters.qwen_native import native_call_message, native_final_message, rejection_record, render_native
    from ..native_tools import adapt_tools
    from ..prompting import SYSTEM, native_history_messages, rejection_feedback_content
    from .data import load_catalog

    if suite_dir is not None:
        loaded = load_suite(suite_dir)
        proof = matching_proof(config, loaded)
    else:
        proof = verify_proof(config.paths["native_decoder_proof"], config.paths["model_dir"])
        if proof["status"] != "passed":
            raise PreparationError("blocked_dependency", "Native regressions require a matching passed CPU proof", proof=proof)
    _, specs = load_catalog(config.require("data_root") / "train" / "train_tools_catalog.json")
    tools, _ = adapt_tools([specs["sys.ask_missing_info"]])
    call = {"name": "sys.ask_missing_info", "arguments": {"tool_name": "a.b", "params": ["z", "a"]}}
    history = [{"role": "user", "text": "Lịch sử"}, {"role": "assistant", "text": "Giữ nguyên",
               "tool_calls": [call, call], "tool_results": [{"ok": False}, {"ok": True}]}]
    projected = native_history_messages(history)
    if projected[1]["content"] != "Giữ nguyên" or len(projected[1]["tool_calls"]) != 2:
        raise ValueError("History content/order drift")
    prefix = [{"role": "system", "content": SYSTEM}] + projected + [{"role": "user", "content": "Kết thúc"}]
    feedback = rejection_feedback_content(rejection_record(2, "NATIVE_JSON_INVALID", "<|im_start|>bad",
                                         stop_reason="eos", eos_observed=True))
    if "<" in feedback or ">" in feedback:
        raise ValueError("Feedback escaping failed")
    prefixes = [prefix, prefix + [native_call_message(call["name"], call["arguments"]),
                {"role": "tool", "content": '{"ok":false}'}, {"role": "user", "content": feedback}]]
    fixtures = [{"messages": p, "tools": tools, "source": "controlled"} for p in prefixes]
    if "food_delivery.place_order" in specs:
        recursive_tools, _ = adapt_tools([specs["food_delivery.place_order"], specs["sys.ask_missing_info"]])
        arguments = {"restaurant_id": "r_controlled", "items": [{"item_id": "i_controlled", "quantity": 2, "note": "ít cay"}]}
        prior = [native_call_message("food_delivery.place_order", arguments), {"role": "tool", "content": '{"ok":true}'}]
        fixtures.append({"messages": prefix + prior, "tools": recursive_tools, "source": "controlled_recursive_prior_target",
                         "target": native_call_message("food_delivery.place_order", arguments)})
    if suite_dir is None:
        from .data import read_train, base_messages, visible_source
        from ..native_tools import adapt_tools
        from .config import DATASET_SHA256, CATALOG_SHA256, SPLIT_IDENTITY
        data = config.require("data_root") / "train"
        split = read_json(config.require("split_manifest"))
        if (file_hash(data / "train.jsonl") != DATASET_SHA256 or file_hash(data / "train_tools_catalog.json") != CATALOG_SHA256
                or split.get("identity") != SPLIT_IDENTITY):
            raise ValueError("Real-history anchors require pinned inputs/split")
        members = {s["id"]: s["partition"] for s in split["samples"]}
        anchors = {s.id: s.record for s in read_train(data / "train.jsonl") if s.id in {"train_0008", "train_0069"}}
        if set(anchors) != {"train_0008", "train_0069"} or any(members.get(sid) != "train" for sid in anchors):
            raise ValueError("Real-history anchors must stay in Fit")
        for sid, source in anchors.items():
            visible = visible_source(source, specs)
            native_tools, _ = adapt_tools(visible["permitted_tools"])
            fixtures.append({"messages": base_messages(visible), "tools": native_tools, "source": sid})
    evidence = []
    for fixture in fixtures:
        messages, fixture_tools = fixture["messages"], fixture["tools"]
        sup = supervised(tokenizer, messages, fixture_tools, fixture.get("target", native_final_message()))
        if not flag_equivalent(tokenizer, messages, fixture_tools):
            raise ValueError("Thinking flag drift")
        evidence.append({"source": fixture["source"], "prompt_tokens": sup["prompt_tokens"],
                         "completion_ids": sup["labels"][sup["prompt_tokens"]:], "supervised_sha256": ordered_hash(sup)})
    directory = new_directory((suite_dir or config.require("output_root")) / "native-acceptances", "native")
    write_jsonl(directory / "fixture.jsonl", fixtures)
    persisted = read_jsonl(directory / "fixture.jsonl")
    if any(render_native(tokenizer, before["messages"], before["tools"]) != render_native(tokenizer, after["messages"], after["tools"])
           for before, after in zip(fixtures, persisted)):
        raise ValueError("Persisted renderer drift")
    if any(supervised(tokenizer, before["messages"], before["tools"], before.get("target", native_final_message())) !=
           supervised(tokenizer, after["messages"], after["tools"], after.get("target", native_final_message()))
           for before, after in zip(fixtures, persisted)):
        raise ValueError("Persisted SFT target/mask drift")
    write_json(directory / "acceptance.json", {"status": "passed", "binding": proof_binding(config.paths["model_dir"]),
               "storage_sha256": file_hash(Path(__file__).with_name("storage.py")),
               "acceptance_code_sha256": file_hash(Path(__file__)),
               "proof": proof, "checks": NATIVE_CHECKS, "evidence": evidence})
    seal(directory, ["fixture.jsonl", "acceptance.json"])
    return {"status": "passed", "directory": str(directory)}
