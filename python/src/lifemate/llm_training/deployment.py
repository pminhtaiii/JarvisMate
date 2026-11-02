"""Read-only A30 acceptance interface; cooperative deadlines never imply supervision."""
from pathlib import Path

from ..model_budget import check_budget
from .storage import file_hash, read_json, read_jsonl
from .metrics import coverage


def deployment_check(evidence_path: Path, expected_ids: list[str]):
    evidence = read_json(evidence_path)
    required = {"schema", "host", "offline_network_disabled", "container_digest", "assets", "logical_parameters",
                "context_tokens", "supervisor", "outcomes", "repeatability"}
    issues = []
    if set(evidence) != required or evidence["schema"] != "lifemate-a30-acceptance-v1":
        raise ValueError("A30 acceptance evidence schema mismatch")
    if (evidence["host"].get("gpu") != "NVIDIA A30" or evidence["host"].get("cpu_cores", 0) < 16
            or evidence["host"].get("ram_bytes", 0) < 64_000_000_000):
        issues.append("actual_A30_profile_required")
    if evidence["offline_network_disabled"] is not True or not evidence["container_digest"]:
        issues.append("offline_container_evidence_missing")
    if not {"container_manifest", "supervisor_record", "repeatability_record", "submission", "outcomes"} <= evidence["assets"].keys():
        issues.append("acceptance_artifact_evidence_missing")
    size = evidence["logical_parameters"]
    check_budget(size["asr"], size["planner"], extra=size.get("other", 0), context_tokens=evidence["context_tokens"])
    supervisor = evidence["supervisor"]
    if (supervisor.get("hard_deadline_seconds") != 30 or supervisor.get("kills_process_tree") is not True
            or supervisor.get("cleanup_verified") is not True or not supervisor.get("implementation_sha256")):
        issues.append("hard_deadline_supervisor_unverified")
    for name, asset in evidence["assets"].items():
        path = Path(asset["path"])
        if not path.is_absolute():
            path = evidence_path.parent / path
        if file_hash(path) != asset["sha256"]:
            issues.append("asset_hash:" + name)
    out_path = Path(evidence["outcomes"])
    if not out_path.is_absolute():
        out_path = evidence_path.parent / out_path
    outcome_asset = evidence["assets"].get("outcomes", {})
    if file_hash(out_path) != outcome_asset.get("sha256"):
        issues.append("outcomes_not_bound_to_acceptance_asset")
    outcomes = read_jsonl(out_path)
    counts = coverage(outcomes, expected_ids)
    if not counts["full_coverage"] or counts["failed"] or any(o.get("elapsed") is None or o["elapsed"] > 30 for o in outcomes):
        issues.append("coverage_or_30_second_failure")
    repeat = evidence["repeatability"]
    if repeat.get("matched_authoritative_outputs") is not True or repeat.get("independent_runs", 0) < 2:
        issues.append("repeatability_unverified")
    return {"status": "passed" if not issues else "blocked_dependency", "issues": issues,
            "submission_ready": not issues, "evidence_sha256": file_hash(evidence_path), "counts": counts}
