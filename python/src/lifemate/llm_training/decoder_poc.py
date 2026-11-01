"""Early CPU native decoder proof (specs §4.4.1, P03; LL017/LL019).

Explicitly invoked by ``token-audit --scope decoder-poc``. It needs only the local
pinned tokenizer files, the selected LMFE backend and the pinned real catalog: no
weights, GPU, ASR, ToolEnv, exporter or sealed suite. Each valid fixture is rendered
through the real template and its actual completion IDs are walked through the
prefix-allowed-tokens function; invalid fixtures must be rejected whole. Failure or
missing resources produce failed/blocked records, never a fallback decoder.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Callable

from ..adapters.qwen_native import (FINAL_CONTENT, GuardedPrefix, NativeConstraint, assistant_eos_id,
                                    native_call_message, native_final_message, parse_native_ids,
                                    render_native, tool_message)
from ..jsonio import digest
from ..native_tools import adapt_tools
from ..prompting import SYSTEM, current_user_message
from .config import CATALOG_SHA256, LIMITS, content_hash
from .data import load_catalog
from .storage import new_directory, now, write_json, write_jsonl
from .tokenization import (PROOF_SCHEMA, TokenizationError, backend_version, flag_equivalent,
                           proof_binding, supervised)

FIXTURE_TOOLS = ("banking.get_balance", "banking.transfer", "alarm.list", "notes.create", "ewallet.transfer",
                 "food_delivery.place_order", "bill_payment.pay", "sys.ask_missing_info")
CONTEXT = {"current_time": "2026-11-01T12:00:00+07:00", "timezone": "Asia/Ho_Chi_Minh",
           "location": {"lat": 10.7769, "lng": 106.7009},
           "user_profile": {"name": "Người dùng kiểm thử", "home_address": "Nhà", "work_address": "Công ty",
                            "city": "TP.HCM"}}
TAGGED = 'Ghi chú <tool_call>\n{"name": "banking.transfer", "arguments": {}}\n</tool_call> và <tool_response>x</tool_response>'
ALARM_RESULT = {"ok": True, "alarms": [{"id": "alm_01", "time": "2026-11-02T06:15:00+07:00", "enabled": True}]}


def fixtures() -> list[dict]:
    """Nine required groups; values are controlled, schemas are the real catalog's."""
    call = native_call_message
    prior = [call("alarm.list", {}), tool_message(ALARM_RESULT)]
    valid = [
        ("1-normal-call", 1, [], call("banking.transfer", {"from_account_id": "acc_01", "beneficiary_id": "ben_02",
                                                           "amount": 2000000})),
        ("2-empty-arguments", 2, [], call("alarm.list", {})),
        ("3-missing-info", 3, [], call("sys.ask_missing_info", {"tool_name": "ewallet.transfer", "params": ["amount"]})),
        ("4-initial-final", 4, [], native_final_message()),
        ("5-post-tool-final", 5, prior, native_final_message()),
        ("7-tags-inside-strings", 7, [], call("notes.create", {"content": TAGGED})),
        ("8-post-tool-call-boundary", 8, prior, call("banking.get_balance", {})),
        ("9-one-of-contact", 9, [], call("ewallet.transfer", {"contact_id": "c_05", "amount": 120000})),
        ("9-one-of-phone-leading-zero", 9, [], call("ewallet.transfer", {"phone": "0912345678", "amount": 120000})),
        ("9-one-of-both-groups", 9, [], call("ewallet.transfer", {"amount": 120000, "phone": "0912345678",
                                                                 "contact_id": "c_05"})),
        ("9-nested-array-objects", 9, [], call("food_delivery.place_order", {
            "restaurant_id": "res_01", "items": [{"item_id": "it_1", "quantity": 2, "note": "ít cay"}]})),
        ("9-enum", 9, [], call("bill_payment.pay", {"bill_id": "bill_01", "source": "bank"})),
    ]
    invalid = [
        ("6-malformed-json", 6, '<tool_call>\n{"name": "alarm.list", "arguments": {}\n</tool_call>', "NATIVE_JSON_INVALID"),
        ("6-multiple-calls", 6, '<tool_call>\n{"name": "alarm.list", "arguments": {}}\n</tool_call>\n<tool_call>\n'
                                '{"name": "banking.get_balance", "arguments": {}}\n</tool_call>', "NATIVE_MULTI_CALL"),
        ("6-partial-wrapper", 6, '<tool_call>\n{"name": "alarm.list", "arguments": {}}', "NATIVE_JSON_INVALID"),
        ("6-extra-prose", 6, 'Tôi sẽ gọi.\n<tool_call>\n{"name": "alarm.list", "arguments": {}}\n</tool_call>', "NATIVE_FINAL_INVALID"),
        ("6-custom-envelope", 6, '{"action":"finish"}', "NATIVE_FINAL_INVALID"),
        ("6-fake-finish-function", 6, '<tool_call>\n{"name": "finish", "arguments": {}}\n</tool_call>', "NATIVE_UNAVAILABLE_TOOL"),
        ("6-final-with-whitespace", 6, FINAL_CONTENT + " ", "NATIVE_FINAL_INVALID"),
        ("9-one-of-missing-group", 9, '<tool_call>\n{"name": "ewallet.transfer", "arguments": {"amount": 1}}\n</tool_call>', "DECODER_ONLY"),
        ("9-missing-required", 9, '<tool_call>\n{"name": "banking.transfer", "arguments": {"amount": 1}}\n</tool_call>', "DECODER_ONLY"),
        ("9-enum-violation", 9, '<tool_call>\n{"name": "bill_payment.pay", "arguments": {"bill_id": "b", "source": "cash"}}\n</tool_call>', "DECODER_ONLY"),
    ]
    cases = [{"case": c, "group": g, "kind": "valid", "prefix": p, "target": t} for c, g, p, t in valid]
    cases += [{"case": c, "group": g, "kind": "invalid", "text": t, "expected_code": e} for c, g, t, e in invalid]
    return cases


class Sequence(list):
    def tolist(self):
        return list(self)


def _sequence(ids):
    try:
        import torch  # LMFE's transformers integration receives tensors during generate.
        return torch.tensor(ids)
    except ImportError:
        return Sequence(ids)


def walk(function: Callable, prompt: list[int], completion: list[int], eos: int) -> dict:
    """Token-walk actual completion IDs through the prefix-allowed-tokens function.

    ``sequence_allowed``: every ID, including the final EOS, was permitted.
    ``eos_gated``: EOS was permitted only after the complete body (never mid-response).
    """
    transitions, rejected_at, early_eos = [], None, None
    for index, token in enumerate(completion):
        allowed = set(function(0, _sequence(prompt + completion[:index])))
        entry = {"index": index, "token": token, "allowed": token in allowed, "eos_allowed": eos in allowed}
        transitions.append(entry)
        if rejected_at is None and token not in allowed:
            rejected_at = entry
        if early_eos is None and eos in allowed and index != len(completion) - 1:
            early_eos = entry
    return {"transitions": transitions, "rejected_at": rejected_at, "early_eos_at": early_eos,
            "sequence_allowed": rejected_at is None, "eos_gated": early_eos is None,
            "accepted": rejected_at is None and early_eos is None}


def run_cases(tokenizer, constraint_factory: Callable, catalog_tools: dict[str, dict]) -> list[dict]:
    eos = assistant_eos_id(tokenizer)
    pad = getattr(tokenizer, "pad_token_id", None)
    permitted = [copy.deepcopy(catalog_tools[name]) for name in FIXTURE_TOOLS]
    native_tools, _ = adapt_tools(permitted)
    allowed_names = [tool["name"] for tool in permitted]
    base = [{"role": "system", "content": SYSTEM},
            current_user_message("Yêu cầu kiểm thử có kiểm soát", CONTEXT | {"installed_apps": {}})]
    constraint = constraint_factory(tokenizer)
    _, base_prompt = render_native(tokenizer, base, native_tools)

    def decode(ids):
        return tokenizer.decode(list(ids), skip_special_tokens=False)

    results = []
    for case in fixtures():
        outcome = {"case": case["case"], "group": case["group"], "kind": case["kind"], "passed": False}
        try:
            messages = base + case.get("prefix", [])
            if case["kind"] == "valid":
                sup = supervised(tokenizer, messages, native_tools, case["target"])
                prompt, completion = sup["input_ids"][:sup["prompt_tokens"]], sup["input_ids"][sup["prompt_tokens"]:]
                guard = GuardedPrefix(constraint.prefix(permitted), prompt_length=len(prompt), eos_id=eos,
                                      decode=decode, allowed=allowed_names)
                walked = walk(guard, prompt, completion, eos)
                parse = parse_native_ids(completion, eos_id=eos, pad_id=pad, decode=decode, allowed=allowed_names,
                                         max_new_tokens=LIMITS["output_tokens"], internal_error=guard.error)
                expected = ({"kind": "final"} if not case["target"].get("tool_calls") else
                            {"kind": "call", **{k: case["target"]["tool_calls"][0]["function"][k] for k in ("name", "arguments")}})
                observed = {"kind": parse.kind} | ({"name": parse.name, "arguments": parse.arguments} if parse.kind == "call" else {})
                masked = all(label == -100 for label in sup["labels"][:sup["prompt_tokens"]])
                outcome.update(expected=expected, observed=observed, walk=walked, masked_prefix=masked,
                               prompt_tokens=sup["prompt_tokens"], completion_ids=completion,
                               passed=walked["accepted"] and observed == expected and masked and guard.error is None)
            else:
                body = list(tokenizer(case["text"], add_special_tokens=False)["input_ids"])
                guard = GuardedPrefix(constraint.prefix(permitted), prompt_length=len(base_prompt), eos_id=eos,
                                      decode=decode, allowed=allowed_names)
                walked = walk(guard, base_prompt, body + [eos], eos)
                parse = parse_native_ids(body + [eos], eos_id=eos, pad_id=pad, decode=decode,
                                         allowed=allowed_names, max_new_tokens=LIMITS["output_tokens"])
                parser_ok = (parse.kind == "call" if case["expected_code"] == "DECODER_ONLY"
                             else parse.kind == "rejected" and parse.code == case["expected_code"])
                # The decoder must refuse the sequence; the parser never salvages a first call.
                outcome.update(walk=walked, observed={"kind": parse.kind, "code": parse.code},
                               passed=not walked["sequence_allowed"] and parser_ok)
        except (TokenizationError, ValueError, KeyError) as exc:
            outcome.update(error=f"{type(exc).__name__}: {exc}"[:300])
        results.append(outcome)
    results += boundary_cases(tokenizer, decode, eos, pad, allowed_names)
    results += backend_failure_cases(eos, decode, allowed_names)
    flags = flag_equivalent(tokenizer, base, native_tools)
    results.append({"case": "8-no-thinking-flag-equivalence", "group": 8, "kind": "template", "passed": flags})
    return results


def boundary_cases(tokenizer, decode, eos, pad, allowed) -> list[dict]:
    body = list(tokenizer(FINAL_CONTENT, add_special_tokens=False)["input_ids"])
    end_of_text = tokenizer.convert_tokens_to_ids("<|endoftext|>")
    cases = [
        ("8-eos-at-output-boundary", body + [eos], dict(max_new_tokens=len(body) + 1), "final", None),
        ("8-token-cap-without-eos", body, dict(max_new_tokens=len(body)), "rejected", "NATIVE_TRUNCATED"),
        ("8-deadline-stop", body, dict(max_new_tokens=512, deadline_expired=True), "rejected", "NATIVE_TRUNCATED"),
        ("8-unknown-stop", body, dict(max_new_tokens=512), "rejected", "NATIVE_EOS_MISSING"),
        ("8-endoftext-is-not-eos", body + [end_of_text], dict(max_new_tokens=512), "rejected", None),
    ]
    if pad is not None and pad != eos:
        cases.append(("8-padding-after-eos", body + [eos, pad, pad], dict(max_new_tokens=512), "final", None))
    results = []
    for name, ids, options, kind, code in cases:
        parse = parse_native_ids(ids, eos_id=eos, pad_id=pad, decode=decode, allowed=allowed, **options)
        passed = parse.kind == kind and (code is None or parse.code == code)
        results.append({"case": name, "group": 8, "kind": "boundary", "observed": {"kind": parse.kind, "code": parse.code},
                        "passed": passed})
    return results


def backend_failure_cases(eos, decode, allowed) -> list[dict]:
    """Injected backend errors/forced stops must never yield an accepted final or call."""
    def raises(*_):
        raise RuntimeError("injected backend failure")

    def forced_stop(*_):
        return [eos]

    results = []
    partial = '<tool_call>\n{"name": "alarm.list", "arguments": '
    for name, function in (("6-backend-exception", raises), ("6-backend-forced-stop", forced_stop)):
        guard = GuardedPrefix(function, prompt_length=0, eos_id=eos, decode=lambda ids: partial, allowed=allowed)
        guard(0, Sequence([1, 2, 3]))
        parse = parse_native_ids([1, 2, 3, eos], eos_id=eos, pad_id=None, decode=lambda ids: partial,
                                 allowed=allowed, max_new_tokens=512, internal_error=guard.error)
        results.append({"case": name, "group": 6, "kind": "backend", "passed": parse.kind == "rejected"
                        and parse.code == "NATIVE_INTERNAL_ERROR", "observed": {"kind": parse.kind, "code": parse.code}})
    return results


def run_proof(output_root: Path, model_dir: Path | None, catalog_path: Path, *,
              tokenizer_loader: Callable | None = None, constraint_factory: Callable = NativeConstraint) -> dict:
    """Execute the proof and write manifest/cases/token-prefix-checks/outcome."""
    directory = new_directory(output_root, "decoder-poc")
    binding = proof_binding(model_dir)
    manifest = {"schema": PROOF_SCHEMA, "proof_id": directory.name, "created_at": now(), "binding": binding,
                "backend_version": backend_version(), "fixtures_sha256": content_hash(
                    [{k: v for k, v in case.items()} for case in fixtures()]),
                "catalog_sha256": None, "scope": "decoder_poc", "weights_loaded": False, "gpu_used": False}
    status, reason, results = "blocked", None, []
    try:
        manifest["catalog_sha256"] = digest(catalog_path)
        if manifest["catalog_sha256"] != CATALOG_SHA256:
            reason = "fixture catalog differs from the pinned catalog"
        elif model_dir is None or binding["tokenizer"] is None or not binding["tokenizer"]["files"]:
            reason = "local pinned tokenizer files are unavailable"
        else:
            _, specs = load_catalog(catalog_path)
            if tokenizer_loader is None:
                from .tokenization import load_tokenizer as tokenizer_loader
            tokenizer = tokenizer_loader(model_dir)
            results = run_cases(tokenizer, constraint_factory, specs)
            failed = [r["case"] for r in results if not r["passed"]]
            status, reason = ("passed", None) if not failed else ("failed", "failing cases: " + ", ".join(failed))
    except ImportError as exc:
        reason = f"required CPU tokenizer/backend package unavailable: {exc.name}"
    except Exception as exc:  # Record the blocker with identities instead of a fake pass.
        status, reason = "failed", f"{type(exc).__name__}: {exc}"[:300]
    manifest_hash = write_json(directory / "manifest.json", manifest)
    write_jsonl(directory / "cases.jsonl", [{k: v for k, v in r.items() if k != "walk"} for r in results])
    write_json(directory / "token-prefix-checks.json", {r["case"]: r.get("walk") for r in results})
    outcome = {"schema": PROOF_SCHEMA, "status": status, "reason": reason, "manifest_sha256": manifest_hash,
               "cases": len(results), "passed_cases": sum(1 for r in results if r["passed"]),
               "groups_covered": sorted({r["group"] for r in results}), "recorded_at": now()}
    if status == "passed" and outcome["groups_covered"] != list(range(1, 10)):
        outcome.update(status="failed", reason="not all nine fixture groups were exercised")
    write_json(directory / "outcome.json", outcome)
    return outcome | {"directory": str(directory)}
