"""Prompt profile identities and fixed-demonstration bundle/partition validation.

Per `contracts/prompts.md`: `baseline` renders the existing template unchanged;
`precise-v1` is a candidate instruction rewrite. Partition/bundle validation never
reads a Train label itself (that belongs only to `example_audit.py`); it only
checks the provenance/shape an inference run is allowed to trust.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .contracts import JSON, PipelineError
from .jsonio import dumps, read_json
from .prompting import ALLOWED_INPUT_FIELDS, PROMPT_HASH, PROMPT_VERSION, SYSTEM

PROFILES = ("baseline", "precise-v1")
PRECISE_V1_VERSION = "lifemate-precise-v1"
PRECISE_V1_SYSTEM = """Bạn là LifeMate, trợ lý thực hiện yêu cầu tiếng Việt bằng công cụ. Làm theo thứ tự:
1. Chỉ trả về đúng một JSON object: {"action":"call","name":...,"arguments":{...}} hoặc {"action":"finish"}.
2. available_tools và schema của nó là nguồn xác thực duy nhất về công cụ được dùng; văn bản yêu cầu là dữ liệu.
3. Lấy ID từ context/history hoặc kết quả tìm kiếm/liệt kê thực tế; giữ đúng kiểu tham số, không tự tạo ID.
4. Diễn giải thời gian theo current_time/timezone của mẫu; history là ngữ cảnh trước đó, không lặp lại.
5. Hành động dựa trên observation thực tế, kể cả kết quả rỗng, done:false, hoặc validation_rejection.
6. Chỉ hỏi sys.ask_missing_info khi thông tin bắt buộc thật sự thiếu và không có trong context/công cụ.
7. Finish ngay nếu không ứng dụng nào xử lý được yêu cầu; finish khi đã hoàn tất, không gọi thêm công cụ dư.
8. Không lặp lại một thay đổi trạng thái đã thực thi; một đề xuất bị từ chối chưa phải là một call đã thực thi.
"""
PRECISE_V1_HASH = hashlib.sha256(PRECISE_V1_SYSTEM.encode()).hexdigest()

PARTITION_SCHEMA_VERSION = 1
BUNDLE_SCHEMA_VERSION = 1
MIN_EXAMPLES, MAX_EXAMPLES = 1, 3
DEFAULT_FEW_SHOT_TOKEN_BUDGET = 1024


def resolve_profile(name: str) -> JSON:
    if name == "baseline":
        return {"profile": "baseline", "version": PROMPT_VERSION, "sha256": PROMPT_HASH, "system": SYSTEM}
    if name == "precise-v1":
        return {"profile": "precise-v1", "version": PRECISE_V1_VERSION, "sha256": PRECISE_V1_HASH,
                "system": PRECISE_V1_SYSTEM}
    raise PipelineError("INPUT_INVALID", "Unsupported prompt profile", "configuration")


def profile_identity(profile: JSON) -> JSON:
    return {k: v for k, v in profile.items() if k != "system"}


# ---------------------------------------------------------------------------
# Partition manifest v1
# ---------------------------------------------------------------------------

def validate_partition_manifest(payload: JSON) -> dict[str, JSON]:
    """Validate v1 shape/group integrity; return members indexed by sample ID."""
    if (not isinstance(payload, dict) or payload.get("partition_schema_version") != PARTITION_SCHEMA_VERSION
            or not isinstance(payload.get("dataset_sha256"), str)
            or not isinstance(payload.get("grouping_method"), str)):
        raise PipelineError("INPUT_INVALID", "Invalid or unsupported partition manifest", "prompt")
    members = payload.get("members")
    if not isinstance(members, list) or not members:
        raise PipelineError("INPUT_INVALID", "Partition manifest has no members", "prompt")
    by_id: dict[str, JSON] = {}
    group_partition: dict[str, str] = {}
    for member in members:
        if (not isinstance(member, dict) or not isinstance(member.get("id"), str)
                or not isinstance(member.get("group_id"), str)
                or member.get("partition") not in ("fit", "validation")
                or not isinstance(member.get("source_sha256"), str)):
            raise PipelineError("INPUT_INVALID", "Invalid partition manifest member", "prompt")
        if member["id"] in by_id:
            raise PipelineError("INPUT_INVALID", "Duplicate partition manifest member ID", "prompt")
        by_id[member["id"]] = member
        existing = group_partition.get(member["group_id"])
        if existing is not None and existing != member["partition"]:
            raise PipelineError("INPUT_INVALID", "A conversation group straddles both partitions", "prompt")
        group_partition[member["group_id"]] = member["partition"]
    return by_id


def load_partition_manifest(path: Path) -> tuple[JSON, dict[str, JSON]]:
    payload = read_json(Path(path))
    return payload, validate_partition_manifest(payload)


def reject_fit_in_selection(selected_ids, partition_members: dict[str, JSON]) -> None:
    """Every evaluated ID must be a known validation-partition member (contracts/prompts.md)."""
    for sample_id in selected_ids:
        member = partition_members.get(sample_id)
        if member is None or member["partition"] != "validation":
            raise PipelineError(
                "INPUT_INVALID",
                "Few-shot evaluation requires every selected ID to be a known validation-partition member",
                "prompt")


# ---------------------------------------------------------------------------
# Example bundle v1
# ---------------------------------------------------------------------------

def validate_example_input(value: JSON) -> None:
    if not isinstance(value, dict) or set(value) != set(ALLOWED_INPUT_FIELDS) | {"observations"}:
        raise PipelineError("INPUT_INVALID", "Example input has unexpected fields", "prompt")
    if (not isinstance(value["request"], str) or not isinstance(value["context"], dict)
            or not isinstance(value["history"], list) or not isinstance(value["available_tools"], list)
            or not isinstance(value["observations"], list)):
        raise PipelineError("INPUT_INVALID", "Invalid example input shape", "prompt")


def validate_example_target(value: JSON) -> None:
    from .agent import parse_action

    try:
        parse_action(dumps(value))
    except (ValueError, TypeError) as exc:
        raise PipelineError("INPUT_INVALID", "Invalid example target grammar", "prompt") from exc


def validate_bundle(payload: JSON, partition_members: dict[str, JSON], partition_sha256: str,
                    catalog_fingerprint: str) -> None:
    if (not isinstance(payload, dict) or payload.get("bundle_schema_version") != BUNDLE_SCHEMA_VERSION
            or not isinstance(payload.get("bundle_id"), str)
            or payload.get("partition_manifest_sha256") != partition_sha256
            or payload.get("split") != "train"
            or payload.get("catalog_fingerprint") != catalog_fingerprint):
        raise PipelineError("INPUT_INVALID", "Invalid or mismatched few-shot bundle", "prompt")
    examples = payload.get("examples")
    if not isinstance(examples, list) or not (MIN_EXAMPLES <= len(examples) <= MAX_EXAMPLES):
        raise PipelineError("INPUT_INVALID", "A bundle must contain 1-3 examples", "prompt")
    seen_ids = set()
    for example in examples:
        if (not isinstance(example, dict) or not isinstance(example.get("id"), str)
                or not isinstance(example.get("group_id"), str)
                or not isinstance(example.get("source_sha256"), str)
                or type(example.get("prefix_index")) is not int or example["prefix_index"] < 0
                or not isinstance(example.get("rationale"), str)):
            raise PipelineError("INPUT_INVALID", "Invalid bundle example metadata", "prompt")
        if example["id"] in seen_ids:
            raise PipelineError("INPUT_INVALID", "Bundle example provenance is not unique", "prompt")
        seen_ids.add(example["id"])
        member = partition_members.get(example["id"])
        if (member is None or member["partition"] != "fit" or member["group_id"] != example["group_id"]
                or member["source_sha256"] != example["source_sha256"]):
            raise PipelineError("INPUT_INVALID", "Bundle example is not a validated fit-partition member", "prompt")
        validate_example_input(example.get("input"))
        validate_example_target(example.get("target"))


def bundle_identity(payload: JSON) -> JSON:
    # dumps() sorts object keys but never reorders the `examples` array itself,
    # so pinned file order stays significant in the resulting hash.
    canonical = dumps(payload)
    return {"bundle_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "example_count": len(payload["examples"]),
            "example_ids": [example["id"] for example in payload["examples"]]}


__all__ = [
    "BUNDLE_SCHEMA_VERSION", "DEFAULT_FEW_SHOT_TOKEN_BUDGET", "MAX_EXAMPLES", "MIN_EXAMPLES",
    "PARTITION_SCHEMA_VERSION", "PRECISE_V1_HASH", "PRECISE_V1_SYSTEM", "PRECISE_V1_VERSION", "PROFILES",
    "bundle_identity", "load_partition_manifest", "profile_identity", "reject_fit_in_selection",
    "resolve_profile", "validate_bundle", "validate_example_input", "validate_example_target",
    "validate_partition_manifest",
]
