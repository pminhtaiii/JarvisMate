"""Offline, deterministic skill metadata loading and branch retrieval."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
import hashlib
from importlib import resources
import json
import re
import unicodedata
from types import MappingProxyType
from typing import Any


_ASSET_NAME = "skill_library.json"
_MAX_LIBRARY_BYTES = 1_000_000
_MAX_REQUEST_CHARS = 8_192
_MAX_HISTORY_TURNS = 20
_MAX_HISTORY_CHARS = 16_384
_MAX_ELIGIBLE_TOOLS = 512
_TOOL_NAME = re.compile(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\Z")
_PARAMETER_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
_BRANCH_ID = re.compile(r"S[0-9]{2}\.B[0-9]{2}\Z")
_WORKFLOW_ID = re.compile(r"W[0-9]{2}\Z")
_TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)
_MISSING_INPUT_TOOL = "sys.ask_missing_info"
_PLACEHOLDER_VALUES = frozenset({
    "?", "n/a", "na", "missing", "none", "null", "tbd", "unknown", "undefined",
})
_BRANCH_KEYS = frozenset({
    "skill_id", "branch_id", "branch_key", "title", "domain_ids",
    "system_capabilities", "evidence", "workflow_ids", "intent_triggers",
    "required_object_cues", "required_cue_groups", "suppressor_branch_ids",
    "action_groups", "conditional_dependencies", "conditional_actions",
    "eligibility", "catalog_splits", "parameters", "dependency_flow",
    "constraints", "completion_criteria", "missing_information",
    "common_refs", "guidance",
})
_GATED_BRANCHES = frozenset({
    "S15.B01", "S15.B02", "S23.B01", "S23.B02",
})
_EXPECTED_BRANCH_COUNTS = (
    2, 3, 2, 3, 5, 6, 3, 2, 3, 1, 2, 6,
    5, 2, 2, 2, 3, 9, 8, 2, 2, 2, 2, 3,
)


class SkillLibraryError(ValueError):
    """The packaged skill library is malformed or incompatible."""


class SkillRetrievalInputError(ValueError):
    """A retrieval argument does not match the public input contract."""


@dataclass(frozen=True, slots=True)
class SkillParent:
    skill_id: str
    title: str

    def to_dict(self) -> dict[str, str]:
        return {"skill_id": self.skill_id, "title": self.title}


@dataclass(frozen=True, slots=True)
class SharedInstruction:
    instruction_id: str
    title: str
    guidance: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.instruction_id, "title": self.title, "guidance": self.guidance}


@dataclass(frozen=True, slots=True)
class CatalogFingerprint:
    schema_version: str
    sha256: str
    canonical_sha256: str

    def to_dict(self) -> dict[str, str]:
        return {"schema_version": self.schema_version, "sha256": self.sha256,
                "canonical_sha256": self.canonical_sha256}


@dataclass(frozen=True, slots=True)
class SkillDependencyGroup:
    tools: tuple[str, ...]
    guard: str
    input_alternatives: tuple[tuple[str, ...], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tools": list(self.tools),
            "guard": self.guard,
            "input_alternatives": [list(group) for group in self.input_alternatives],
        }


@dataclass(frozen=True, slots=True)
class SkillConditionalAction:
    tool: str
    guard: str

    def to_dict(self) -> dict[str, str]:
        return {"tool": self.tool, "guard": self.guard}


@dataclass(frozen=True, slots=True)
class SkillParameter:
    tool: str
    required: tuple[str, ...]
    x_one_of: tuple[tuple[str, ...], ...]
    optional: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "required": list(self.required),
            "x_one_of": [list(group) for group in self.x_one_of],
            "optional": list(self.optional),
        }


@dataclass(frozen=True, slots=True)
class SkillEligibility:
    rule: str
    conditional_reader_rule: str
    always_dependencies: tuple[tuple[str, ...], ...]
    conditional_action_rule: str
    tool_source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "conditional_reader_rule": self.conditional_reader_rule,
            "always_dependencies": [list(group) for group in self.always_dependencies],
            "conditional_action_rule": self.conditional_action_rule,
            "tool_source": self.tool_source,
        }


@dataclass(frozen=True, slots=True)
class SkillBranch:
    skill_id: str
    branch_id: str
    branch_key: str
    title: str
    domain_ids: tuple[str, ...]
    system_capabilities: tuple[str, ...]
    evidence: str
    workflow_ids: tuple[str, ...]
    intent_triggers: tuple[str, ...]
    required_object_cues: tuple[str, ...]
    required_cue_groups: tuple[tuple[str, ...], ...]
    suppressor_branch_ids: tuple[str, ...]
    action_groups: tuple[tuple[str, ...], ...]
    conditional_dependencies: tuple[SkillDependencyGroup, ...]
    conditional_actions: tuple[SkillConditionalAction, ...]
    eligibility: SkillEligibility
    catalog_splits: Mapping[str, tuple[str, ...]]
    parameters: tuple[SkillParameter, ...]
    dependency_flow: str
    constraints: tuple[str, ...]
    completion_criteria: str
    missing_information: str
    common_refs: tuple[str, ...]
    guidance: str


@dataclass(frozen=True, slots=True)
class SkillGuidance:
    """Immutable, sample-eligible guidance supplied to the planner."""

    branch_id: str
    parent_id: str
    title: str
    evidence: str
    action_groups: tuple[tuple[str, ...], ...]
    conditional_dependencies: tuple[SkillDependencyGroup, ...]
    conditional_actions: tuple[SkillConditionalAction, ...]
    eligibility: SkillEligibility
    constraints: tuple[str, ...]
    completion_criteria: str
    missing_information: str
    common_refs: tuple[str, ...]
    shared_instructions: tuple[SharedInstruction, ...]
    guidance: str
    dependency_flow: str

    def to_dict(self) -> dict[str, Any]:
        """Return a fresh JSON-compatible view without exposing mutable library state."""
        return {
            "branch_id": self.branch_id,
            "parent_id": self.parent_id,
            "title": self.title,
            "evidence": self.evidence,
            "action_groups": [list(group) for group in self.action_groups],
            "conditional_dependencies": [group.to_dict() for group in self.conditional_dependencies],
            "conditional_actions": [item.to_dict() for item in self.conditional_actions],
            "eligibility": self.eligibility.to_dict(),
            "constraints": list(self.constraints),
            "completion_criteria": self.completion_criteria,
            "missing_information": self.missing_information,
            "common_refs": list(self.common_refs),
            "shared_instructions": [item.to_dict() for item in self.shared_instructions],
            "guidance": self.guidance,
            "dependency_flow": self.dependency_flow,
        }


@dataclass(frozen=True, slots=True)
class SkillLibrary:
    version: str
    sha256: str
    parents: tuple[SkillParent, ...]
    branches: tuple[SkillBranch, ...]
    shared: Mapping[str, SharedInstruction]
    catalog_fingerprints: Mapping[str, CatalogFingerprint]
    runtime_evidence_policy: str

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "sha256": self.sha256,
            "catalog_fingerprints": {
                split: fingerprint.to_dict()
                for split, fingerprint in sorted(self.catalog_fingerprints.items())
            },
        }


def _json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SkillLibraryError("Duplicate skill library JSON key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise SkillLibraryError("Non-finite value in skill library")


def _exact_keys(value: Any, expected: set[str], where: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise SkillLibraryError(f"Invalid skill library fields at {where}")
    return value


def _text(value: Any, where: str, *, max_length: int = 4_000) -> str:
    if (not isinstance(value, str) or not value.strip()
            or len(value) > max_length or "\x00" in value):
        raise SkillLibraryError(f"Invalid text at {where}")
    return value.strip()


def _string_list(value: Any, where: str, *, pattern: re.Pattern[str] | None = None,
                 max_items: int = 100) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > max_items:
        raise SkillLibraryError(f"Invalid list at {where}")
    result: list[str] = []
    for index, item in enumerate(value):
        item = _text(item, f"{where}[{index}]", max_length=1_000)
        if pattern is not None and not pattern.fullmatch(item):
            raise SkillLibraryError(f"Invalid identifier at {where}[{index}]")
        if item in result:
            raise SkillLibraryError(f"Duplicate value at {where}[{index}]")
        result.append(item)
    return tuple(result)


def _tool(value: Any, where: str) -> str:
    value = _text(value, where, max_length=128)
    if not _TOOL_NAME.fullmatch(value):
        raise SkillLibraryError(f"Invalid tool name at {where}")
    return value


def _parse_library(raw: bytes) -> SkillLibrary:
    if not isinstance(raw, bytes) or not raw or len(raw) > _MAX_LIBRARY_BYTES:
        raise SkillLibraryError("Skill library is empty or exceeds its size limit")
    try:
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_json_pairs,
            parse_constant=_reject_constant,
        )
    except SkillLibraryError:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise SkillLibraryError("Skill library is not valid UTF-8 JSON") from exc
    root = _exact_keys(payload, {
        "schema_version", "version", "catalog_fingerprints",
        "runtime_evidence_policy", "tool_contracts", "parents",
        "shared_instructions", "branches",
    }, "root")
    if type(root["schema_version"]) is not int or root["schema_version"] != 1:
        raise SkillLibraryError("Unsupported skill library schema version")
    version = _text(root["version"], "version", max_length=80)
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\.[0-9]+", version):
        raise SkillLibraryError("Invalid skill library version")
    if root["runtime_evidence_policy"] != "E":
        raise SkillLibraryError("Only E evidence may be enabled for runtime retrieval")

    raw_fingerprints = root["catalog_fingerprints"]
    if not isinstance(raw_fingerprints, dict) or set(raw_fingerprints) != {"train", "public_test"}:
        raise SkillLibraryError("Catalog fingerprints must cover train and public_test")
    fingerprints: dict[str, CatalogFingerprint] = {}
    for split, value in raw_fingerprints.items():
        value = _exact_keys(value, {"schema_version", "sha256", "canonical_sha256"},
                            f"catalog_fingerprints.{split}")
        schema_version = _text(value["schema_version"], f"{split}.schema_version", max_length=32)
        sha256 = _text(value["sha256"], f"{split}.sha256", max_length=64).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise SkillLibraryError(f"Invalid {split} catalog fingerprint")
        canonical = _text(value["canonical_sha256"], f"{split}.canonical_sha256", max_length=64)
        if not re.fullmatch(r"[0-9a-f]{64}", canonical):
            raise SkillLibraryError(f"Invalid {split} canonical catalog fingerprint")
        fingerprints[split] = CatalogFingerprint(schema_version, sha256, canonical)

    raw_contracts = root["tool_contracts"]
    if not isinstance(raw_contracts, dict) or set(raw_contracts) != {"train", "public_test"}:
        raise SkillLibraryError("Tool contracts must cover train and public_test")
    tool_contracts: dict[str, dict[str, dict[str, Any]]] = {}
    for split, raw_tools in raw_contracts.items():
        if not isinstance(raw_tools, dict):
            raise SkillLibraryError(f"Invalid {split} tool contracts")
        parsed_tools: dict[str, dict[str, Any]] = {}
        for name, raw_contract in raw_tools.items():
            name = _tool(name, f"tool_contracts.{split} key")
            contract = _exact_keys(raw_contract, {"properties", "required", "x_one_of"},
                                   f"tool_contracts.{split}.{name}")
            properties = _string_list(contract["properties"],
                                      f"tool_contracts.{split}.{name}.properties",
                                      pattern=_PARAMETER_NAME, max_items=128)
            required = _string_list(contract["required"],
                                    f"tool_contracts.{split}.{name}.required",
                                    pattern=_PARAMETER_NAME, max_items=128)
            raw_groups = contract["x_one_of"]
            if not isinstance(raw_groups, list) or len(raw_groups) > 32:
                raise SkillLibraryError(f"Invalid x-one-of contract for {name}")
            groups = tuple(
                _string_list(group, f"tool_contracts.{split}.{name}.x_one_of[{index}]",
                             pattern=_PARAMETER_NAME, max_items=64)
                for index, group in enumerate(raw_groups)
            )
            if (len(properties) != len(set(properties))
                    or not set(required) <= set(properties)
                    or any(not group or not set(group) <= set(properties) for group in groups)):
                raise SkillLibraryError(f"Inconsistent tool contract for {name}")
            parsed_tools[name] = {
                "properties": properties, "required": required, "x_one_of": groups,
            }
        tool_contracts[split] = parsed_tools

    raw_parents = root["parents"]
    if not isinstance(raw_parents, list) or len(raw_parents) != 24:
        raise SkillLibraryError("Skill library must contain exactly 24 parents")
    parents: list[SkillParent] = []
    parent_ids: set[str] = set()
    for index, raw_parent in enumerate(raw_parents):
        value = _exact_keys(raw_parent, {"skill_id", "title"}, f"parents[{index}]")
        skill_id = _text(value["skill_id"], f"parents[{index}].skill_id", max_length=8)
        title = _text(value["title"], f"parents[{index}].title", max_length=200)
        expected_id = f"S{index + 1:02d}"
        if skill_id != expected_id or skill_id in parent_ids:
            raise SkillLibraryError("Parent IDs must be unique and ordered S01-S24")
        parent_ids.add(skill_id)
        parents.append(SkillParent(skill_id, title))

    raw_shared = root["shared_instructions"]
    if not isinstance(raw_shared, list) or len(raw_shared) != 6:
        raise SkillLibraryError("Skill library must contain C01-C06")
    shared: dict[str, SharedInstruction] = {}
    for index, raw_instruction in enumerate(raw_shared):
        value = _exact_keys(raw_instruction, {"id", "title", "guidance"},
                            f"shared_instructions[{index}]")
        instruction_id = _text(value["id"], f"shared_instructions[{index}].id", max_length=4)
        if instruction_id != f"C{index + 1:02d}" or instruction_id in shared:
            raise SkillLibraryError("Shared instructions must be unique and ordered C01-C06")
        shared[instruction_id] = SharedInstruction(
            instruction_id,
            _text(value["title"], f"{instruction_id}.title", max_length=200),
            _text(value["guidance"], f"{instruction_id}.guidance"),
        )

    raw_branches = root["branches"]
    if not isinstance(raw_branches, list) or len(raw_branches) != 80:
        raise SkillLibraryError("Skill library must contain exactly 80 branches")
    branches: list[SkillBranch] = []
    branch_ids: set[str] = set()
    evidence_counts = {"E": 0, "S": 0, "H": 0}
    for index, raw_branch in enumerate(raw_branches):
        where = f"branches[{index}]"
        value = _exact_keys(raw_branch, _BRANCH_KEYS, where)
        skill_id = _text(value["skill_id"], f"{where}.skill_id", max_length=8)
        branch_id = _text(value["branch_id"], f"{where}.branch_id", max_length=16)
        if (not _BRANCH_ID.fullmatch(branch_id) or branch_id in branch_ids
                or branch_id.split(".", 1)[0] != skill_id or skill_id not in parent_ids):
            raise SkillLibraryError(f"Invalid or duplicate branch ID at {where}")
        branch_ids.add(branch_id)
        evidence = value["evidence"]
        if evidence not in evidence_counts:
            raise SkillLibraryError(f"Invalid evidence level at {where}")
        evidence_counts[evidence] += 1
        if (branch_id in _GATED_BRANCHES) != (evidence == "H"):
            raise SkillLibraryError("H evidence is reserved for the four reviewed gated branches")

        domains = _string_list(value["domain_ids"], f"{where}.domain_ids", max_items=16)
        if not domains or any(not re.fullmatch(r"D(?:0[1-9]|1[0-6])", item) for item in domains):
            raise SkillLibraryError(f"Invalid business domains at {where}")
        capabilities = _string_list(value["system_capabilities"],
                                    f"{where}.system_capabilities", max_items=4)
        if any(item != "SC01" for item in capabilities):
            raise SkillLibraryError(f"Unknown system capability at {where}")
        workflows = _string_list(value["workflow_ids"], f"{where}.workflow_ids",
                                 pattern=_WORKFLOW_ID, max_items=8)
        if not workflows:
            raise SkillLibraryError(f"Missing workflow evidence at {where}")
        triggers = _string_list(value["intent_triggers"], f"{where}.intent_triggers",
                                max_items=32)
        if not triggers:
            raise SkillLibraryError(f"Missing intent triggers at {where}")
        required_object_cues = _string_list(
            value["required_object_cues"], f"{where}.required_object_cues", max_items=16
        )
        raw_cue_groups = value["required_cue_groups"]
        if not isinstance(raw_cue_groups, list) or len(raw_cue_groups) > 8:
            raise SkillLibraryError(f"Invalid required cue groups at {where}")
        cue_groups = tuple(
            _string_list(group, f"{where}.required_cue_groups[{index}]", max_items=16)
            for index, group in enumerate(raw_cue_groups)
        )
        if any(not group for group in cue_groups):
            raise SkillLibraryError(f"Empty required cue group at {where}")
        suppressor_branch_ids = _string_list(
            value["suppressor_branch_ids"], f"{where}.suppressor_branch_ids",
            pattern=_BRANCH_ID, max_items=16,
        )
        if branch_id in suppressor_branch_ids:
            raise SkillLibraryError(f"Self-suppression is invalid at {where}")

        raw_action_groups = value["action_groups"]
        if not isinstance(raw_action_groups, list) or not raw_action_groups:
            raise SkillLibraryError(f"Missing action groups at {where}")
        action_groups: list[tuple[str, ...]] = []
        action_names: set[str] = set()
        for group_index, raw_group in enumerate(raw_action_groups):
            group = tuple(_tool(item, f"{where}.action_groups[{group_index}]")
                          for item in raw_group) if isinstance(raw_group, list) else ()
            if not group or len(set(group)) != len(group) or action_names.intersection(group):
                raise SkillLibraryError(f"Invalid action group at {where}")
            action_groups.append(group)
            action_names.update(group)

        raw_dependencies = value["conditional_dependencies"]
        if not isinstance(raw_dependencies, list) or len(raw_dependencies) > 20:
            raise SkillLibraryError(f"Invalid conditional dependencies at {where}")
        dependencies: list[SkillDependencyGroup] = []
        dependency_names: set[str] = set()
        for group_index, raw_group in enumerate(raw_dependencies):
            dep = _exact_keys(raw_group, {"tools", "guard", "input_alternatives"},
                              f"{where}.conditional_dependencies[{group_index}]")
            tools = tuple(_tool(item, f"{where}.conditional_dependencies[{group_index}].tools")
                          for item in dep["tools"]) if isinstance(dep["tools"], list) else ()
            guard = _text(dep["guard"], f"{where}.conditional_dependencies[{group_index}].guard",
                          max_length=64)
            raw_input_alternatives = dep["input_alternatives"]
            if not isinstance(raw_input_alternatives, list) or len(raw_input_alternatives) > 8:
                raise SkillLibraryError(f"Invalid dependency input alternatives at {where}")
            input_alternatives = tuple(
                _string_list(group,
                             f"{where}.conditional_dependencies[{group_index}].input_alternatives[{index}]",
                             pattern=_PARAMETER_NAME, max_items=64)
                for index, group in enumerate(raw_input_alternatives)
            )
            if (not tools or len(set(tools)) != len(tools)
                    or guard not in {"required_data_missing", "optional_detail_missing",
                                     "always_before_action"}
                    or dependency_names.intersection(tools)
                    or any(not alternative for alternative in input_alternatives)):
                raise SkillLibraryError(f"Invalid dependency group at {where}")
            dependencies.append(SkillDependencyGroup(tools, guard, input_alternatives))
            dependency_names.update(tools)

        raw_conditional_actions = value["conditional_actions"]
        if not isinstance(raw_conditional_actions, list) or len(raw_conditional_actions) > 8:
            raise SkillLibraryError(f"Invalid conditional actions at {where}")
        conditional_actions: list[SkillConditionalAction] = []
        conditional_action_names: set[str] = set()
        for action_index, raw_action in enumerate(raw_conditional_actions):
            action = _exact_keys(raw_action, {"tool", "guard"},
                                 f"{where}.conditional_actions[{action_index}]")
            tool = _tool(action["tool"], f"{where}.conditional_actions[{action_index}].tool")
            guard = _text(action["guard"], f"{where}.conditional_actions[{action_index}].guard",
                          max_length=64)
            if tool in action_names or tool in dependency_names or tool in conditional_action_names:
                raise SkillLibraryError(f"Duplicate conditional action at {where}")
            if guard != "user_explicitly_requests_order":
                raise SkillLibraryError(f"Unsupported conditional action guard at {where}")
            conditional_actions.append(SkillConditionalAction(tool, guard))
            conditional_action_names.add(tool)

        raw_eligibility = _exact_keys(value["eligibility"], {
            "rule", "conditional_reader_rule", "always_dependencies",
            "conditional_action_rule", "tool_source",
        }, f"{where}.eligibility")
        rule = _text(raw_eligibility["rule"], f"{where}.eligibility.rule", max_length=1_000)
        reader_rule = _text(raw_eligibility["conditional_reader_rule"],
                            f"{where}.eligibility.conditional_reader_rule", max_length=1_000)
        action_rule = _text(raw_eligibility["conditional_action_rule"],
                            f"{where}.eligibility.conditional_action_rule", max_length=1_000)
        tool_source = _text(raw_eligibility["tool_source"],
                            f"{where}.eligibility.tool_source", max_length=100)
        if tool_source != "eligible_tools":
            raise SkillLibraryError(f"Unsupported eligibility source at {where}")
        raw_always = raw_eligibility["always_dependencies"]
        if not isinstance(raw_always, list):
            raise SkillLibraryError(f"Invalid always dependencies at {where}")
        always = tuple(
            tuple(_tool(item, f"{where}.eligibility.always_dependencies")
                  for item in group) if isinstance(group, list) else ()
            for group in raw_always
        )
        expected_always = tuple(dep.tools for dep in dependencies
                                if dep.guard == "always_before_action")
        if always != expected_always:
            raise SkillLibraryError(f"Always-dependency declaration disagrees at {where}")
        eligibility = SkillEligibility(rule, reader_rule, always, action_rule, tool_source)

        raw_catalog_splits = value["catalog_splits"]
        if not isinstance(raw_catalog_splits, dict):
            raise SkillLibraryError(f"Invalid catalog splits at {where}")
        referenced_tools = action_names | dependency_names | conditional_action_names
        if set(raw_catalog_splits) != referenced_tools:
            raise SkillLibraryError(f"Catalog coverage disagrees with referenced tools at {where}")
        catalog_splits: dict[str, tuple[str, ...]] = {}
        for tool_name, raw_splits in raw_catalog_splits.items():
            _tool(tool_name, f"{where}.catalog_splits key")
            splits = _string_list(raw_splits, f"{where}.catalog_splits.{tool_name}", max_items=2)
            if not splits or any(split not in fingerprints for split in splits):
                raise SkillLibraryError(f"Invalid split list at {where}")
            catalog_splits[tool_name] = splits
            for split in splits:
                if tool_name not in tool_contracts[split]:
                    raise SkillLibraryError(f"Tool {tool_name} is absent from the {split} contract")
        referenced_fields = {
            field
            for tool_name, splits in catalog_splits.items()
            for split in splits
            for field in tool_contracts[split][tool_name]["properties"]
        }
        if any(not set(alternative) <= referenced_fields
               for dependency in dependencies
               for alternative in dependency.input_alternatives):
            raise SkillLibraryError(f"Unknown dependency input field at {where}")

        raw_parameters = value["parameters"]
        if not isinstance(raw_parameters, list) or len(raw_parameters) > 20:
            raise SkillLibraryError(f"Invalid parameters at {where}")
        parameters: list[SkillParameter] = []
        parameter_tools: set[str] = set()
        for param_index, raw_param in enumerate(raw_parameters):
            param = _exact_keys(raw_param, {"tool", "required", "x_one_of", "optional"},
                                f"{where}.parameters[{param_index}]")
            tool_name = _tool(param["tool"], f"{where}.parameters[{param_index}].tool")
            required = _string_list(param["required"], f"{where}.parameters[{param_index}].required",
                                    pattern=_PARAMETER_NAME, max_items=64)
            raw_one_of = param["x_one_of"]
            if not isinstance(raw_one_of, list) or len(raw_one_of) > 32:
                raise SkillLibraryError(f"Invalid action x-one-of groups at {where}")
            x_one_of = tuple(
                _string_list(group, f"{where}.parameters[{param_index}].x_one_of[{group_index}]",
                             pattern=_PARAMETER_NAME, max_items=64)
                for group_index, group in enumerate(raw_one_of)
            )
            optional = _string_list(param["optional"], f"{where}.parameters[{param_index}].optional",
                                    pattern=_PARAMETER_NAME, max_items=64)
            if (tool_name not in action_names or tool_name in parameter_tools
                    or set(required).intersection(optional)
                    or any(not group or not set(group) <= set(optional) | set(required)
                           for group in x_one_of)):
                raise SkillLibraryError(f"Invalid action parameter reference at {where}")
            for split in catalog_splits[tool_name]:
                contract = tool_contracts[split][tool_name]
                if (required != contract["required"] or x_one_of != contract["x_one_of"]
                        or not set(optional) <= set(contract["properties"]) - set(contract["required"])):
                    raise SkillLibraryError(f"Action parameters disagree with {split} catalog for {tool_name}")
            parameter_tools.add(tool_name)
            parameters.append(SkillParameter(tool_name, required, x_one_of, optional))
        if parameter_tools != action_names:
            raise SkillLibraryError(f"Action parameter coverage disagrees at {where}")

        common_refs = _string_list(value["common_refs"], f"{where}.common_refs",
                                   pattern=re.compile(r"C0[1-6]\Z"), max_items=6)
        if not common_refs:
            raise SkillLibraryError(f"Missing shared instruction references at {where}")
        flow = _text(value["dependency_flow"], f"{where}.dependency_flow", max_length=2_000)
        constraints = _string_list(value["constraints"], f"{where}.constraints", max_items=16)
        if not constraints:
            raise SkillLibraryError(f"Missing constraints at {where}")
        completion = _text(value["completion_criteria"], f"{where}.completion_criteria")
        missing = _text(value["missing_information"], f"{where}.missing_information", max_length=1_000)
        guidance = _text(value["guidance"], f"{where}.guidance", max_length=2_000)
        branches.append(SkillBranch(
            skill_id=skill_id,
            branch_id=branch_id,
            branch_key=_text(value["branch_key"], f"{where}.branch_key", max_length=100),
            title=_text(value["title"], f"{where}.title", max_length=200),
            domain_ids=domains,
            system_capabilities=capabilities,
            evidence=evidence,
            workflow_ids=workflows,
            intent_triggers=triggers,
            required_object_cues=required_object_cues,
            required_cue_groups=cue_groups,
            suppressor_branch_ids=suppressor_branch_ids,
            action_groups=tuple(action_groups),
            conditional_dependencies=tuple(dependencies),
            conditional_actions=tuple(conditional_actions),
            eligibility=eligibility,
            catalog_splits=MappingProxyType(catalog_splits),
            parameters=tuple(parameters),
            dependency_flow=flow,
            constraints=constraints,
            completion_criteria=completion,
            missing_information=missing,
            common_refs=common_refs,
            guidance=guidance,
        ))

    if evidence_counts != {"E": 63, "S": 13, "H": 4}:
        raise SkillLibraryError("Evidence counts must remain E=63, S=13, H=4")
    actual_counts = tuple(
        sum(branch.skill_id == f"S{parent:02d}" for branch in branches)
        for parent in range(1, 25)
    )
    if actual_counts != _EXPECTED_BRANCH_COUNTS:
        raise SkillLibraryError("Branch distribution must preserve the reviewed S01-S24 inventory")
    if {branch.skill_id for branch in branches} != parent_ids:
        raise SkillLibraryError("Every parent must own at least one branch")
    for branch in branches:
        if any(ref not in shared for ref in branch.common_refs):
            raise SkillLibraryError(f"Unknown shared instruction reference in {branch.branch_id}")
        if any(ref not in branch_ids for ref in branch.suppressor_branch_ids):
            raise SkillLibraryError(f"Unknown suppression branch in {branch.branch_id}")
        if any(next(item for item in branches if item.branch_id == ref).evidence == "E"
               for ref in branch.suppressor_branch_ids):
            raise SkillLibraryError(f"Suppression targets must remain evidence-gated in {branch.branch_id}")
    return SkillLibrary(
        version=version,
        sha256=hashlib.sha256(raw).hexdigest(),
        parents=tuple(parents),
        branches=tuple(branches),
        shared=MappingProxyType(shared),
        catalog_fingerprints=MappingProxyType(fingerprints),
        runtime_evidence_policy=root["runtime_evidence_policy"],
    )


def load_library() -> SkillLibrary:
    """Load and validate the packaged library; never reads repository/docs/tool paths."""
    try:
        resource = resources.files("lifemate").joinpath(_ASSET_NAME)
        raw = resource.read_bytes()
    except (ModuleNotFoundError, OSError, TypeError) as exc:
        raise SkillLibraryError("Packaged skill library is unavailable") from exc
    return _parse_library(raw)


_STOPWORDS = frozenset({
    "a", "ai", "anh", "ban", "bang", "bi", "boi", "cac", "cai", "can", "cho",
    "chua", "co", "cua", "da", "de", "duoc", "em", "gi", "hay", "hoac",
    "la", "len", "luc", "ma", "minh", "mot", "nay", "neu", "nguoi", "nhu",
    "o", "qua", "sau", "se", "toi", "theo", "thi", "tu", "va", "voi", "vua",
    "y", "do", "ay", "roi", "nua", "giup", "cho", "toi", "dang", "chi",
})
_TOKEN_ALIASES = {
    "huy": "huy", "huỷ": "huy", "hủy": "huy",
    "xoa": "xoa", "xoá": "xoa", "xóa": "xoa",
    "khoa": "khoa", "khoá": "khoa", "khóa": "khoa",
    "hoa": "hoa", "hoà": "hoa", "hòa": "hoa",
}
_ACTION_CATEGORIES: Mapping[str, frozenset[str]] = MappingProxyType({
    "activate": frozenset({"bat", "mo", "chay", "khoi", "start", "run", "play",
                           "phat", "nghe", "hut", "tune", "turn"}),
    "deactivate": frozenset({"tat", "dung", "ngung", "stop", "off"}),
    "modify": frozenset({"chinh", "sua", "doi", "capnhat", "update", "move",
                         "reschedule", "edit", "set", "chuyen", "dichoi", "them", "append"}),
    "cancel": frozenset({"huy", "xoa", "delete", "remove", "cancel", "bo"}),
    "send": frozenset({"gui", "nhan", "send", "text", "message", "nhan_tin"}),
    "call": frozenset({"goi", "call", "dial"}),
    "reply": frozenset({"reply", "respond", "answer"}),
    "create": frozenset({"tao", "dat", "cap", "book", "reserve", "add", "them", "mua",
                         "order", "pay", "transfer", "redeem", "subscribe", "queue",
                         "record", "create", "open", "nap", "nhac", "hen", "dangky",
                         "soan"}),
    "complete": frozenset({"complete", "done", "log", "ghi", "uong", "mark"}),
    "lookup": frozenset({"tim", "xem", "read", "check", "find", "list", "search",
                         "look", "liet", "kiem", "tra"}),
    "translate": frozenset({"dich", "translate"}),
    "archive": frozenset({"luutru", "archive"}),
    "return": frozenset({"return"}),
    "trade": frozenset({"mua", "ban", "trade"}),
})
_TOOL_CATEGORY: Mapping[str, frozenset[str]] = MappingProxyType({
    "translate": frozenset({"translate"}),
    "send": frozenset({"send"}),
    "send_message": frozenset({"send"}),
    "send_location": frozenset({"send"}),
    "call": frozenset({"call"}),
    "reply": frozenset({"reply"}),
    "cancel": frozenset({"cancel"}),
    "delete": frozenset({"cancel"}),
    "remove": frozenset({"cancel"}),
    "archive": frozenset({"archive", "cancel"}),
    "update": frozenset({"modify"}),
    "set": frozenset({"modify", "activate", "deactivate"}),
    "add": frozenset({"create"}),
    "add_to_cart": frozenset({"create"}),
    "add_to_playlist": frozenset({"create"}),
    "create": frozenset({"create"}),
    "reserve": frozenset({"create"}),
    "book": frozenset({"create"}),
    "checkout": frozenset({"create"}),
    "transfer": frozenset({"create"}),
    "pay": frozenset({"create"}),
    "pay_qr": frozenset({"create"}),
    "redeem": frozenset({"create"}),
    "subscribe": frozenset({"create"}),
    "queue": frozenset({"create"}),
    "open_savings": frozenset({"create"}),
    "topup_mobile": frozenset({"create"}),
    "place_order": frozenset({"create"}),
    "request_return": frozenset({"return"}),
    "start": frozenset({"activate"}),
    "start_cycle": frozenset({"activate", "modify"}),
    "play": frozenset({"activate"}),
    "tune": frozenset({"activate", "modify"}),
    "complete": frozenset({"complete"}),
    "log": frozenset({"complete"}),
    "log_taken": frozenset({"complete"}),
    "append": frozenset({"modify"}),
    "end_session": frozenset({"complete"}),
    "acknowledge_alert": frozenset({"complete"}),
    "record": frozenset({"create"}),
    "schedule_lesson": frozenset({"create"}),
    "enroll": frozenset({"create"}),
    "grant_guest_code": frozenset({"create"}),
    "arm": frozenset({"activate", "modify"}),
    "check_in": frozenset({"checkin"}),
    "next_departures": frozenset({"lookup"}),
    "get_quotes": frozenset({"lookup"}),
    "find_routes": frozenset({"lookup"}),
    "control": frozenset({"modify", "activate", "deactivate"}),
    "join": frozenset({"activate"}),
})
_NEGATIONS = frozenset({"khong", "dung", "chua", "khoi", "chong", "not", "dont"})
_ACTION_PHRASES: Mapping[tuple[str, ...], frozenset[str]] = MappingProxyType({
    ("tra", "loi"): frozenset({"reply"}),
    ("luu", "tru"): frozenset({"archive"}),
    ("nhan", "tin"): frozenset({"send"}),
    ("ket", "thuc"): frozenset({"complete"}),
    ("hoan", "thanh"): frozenset({"complete"}),
    ("danh", "dau"): frozenset({"complete"}),
    ("dang", "ky"): frozenset({"create"}),
    ("lam", "thu", "tuc"): frozenset({"checkin"}),
    ("check", "in"): frozenset({"checkin"}),
    ("thanh", "toan"): frozenset({"create"}),
    ("chuyen", "tien"): frozenset({"create"}),
    ("chuyen", "khoan"): frozenset({"create"}),
    ("tra", "qr"): frozenset({"create"}),
    ("tra", "hoa", "don"): frozenset({"create"}),
    ("goi", "xe"): frozenset({"create"}),
    ("giu", "sach"): frozenset({"create"}),
    ("doi", "diem"): frozenset({"create"}),
    ("doi", "voucher"): frozenset({"create"}),
    ("gui", "tiet", "kiem"): frozenset({"create"}),
    ("ghi", "tiep"): frozenset({"modify"}),
    ("viet", "tiep"): frozenset({"modify"}),
    ("them", "vao"): frozenset({"modify"}),
    ("tra", "hang"): frozenset({"return"}),
    ("tra", "don"): frozenset({"return"}),
    ("hoan", "tra"): frozenset({"return"}),
    ("yeu", "cau", "hoan", "tra"): frozenset({"return"}),
    ("len", "lich"): frozenset({"create"}),
    ("hen", "lich"): frozenset({"create"}),
})
_ACTION_WORDS = frozenset(
    word for words in _ACTION_CATEGORIES.values() for word in words
) | frozenset(word for phrase in _ACTION_PHRASES for word in phrase)


@lru_cache(maxsize=4096)
def _has_marks(token: str) -> bool:
    return any(unicodedata.category(char) == "Mn"
               for char in unicodedata.normalize("NFD", token))


@lru_cache(maxsize=8192)
def _fold(token: str) -> str:
    value = unicodedata.normalize("NFD", token.lower())
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    return value.replace("đ", "d")


@lru_cache(maxsize=4096)
def _tokens(value: str) -> tuple[str, ...]:
    return tuple(match.group(0).lower() for match in _TOKEN.finditer(value))


@lru_cache(maxsize=16384)
def _token_matches(left: str, right: str) -> bool:
    left_alias = _TOKEN_ALIASES.get(left, left)
    right_alias = _TOKEN_ALIASES.get(right, right)
    if left_alias == right_alias:
        return True
    if _has_marks(left) and _has_marks(right):
        return False
    return _fold(left) == _fold(right)


@lru_cache(maxsize=8192)
def _token_categories(token: str) -> frozenset[str]:
    folded = _fold(token)
    categories = {
        category for category, words in _ACTION_CATEGORIES.items()
        if folded in words
    }
    # Keep frequent accentless homonyms from becoming write intents.
    if _has_marks(token):
        if folded == "dat" and token != "đặt":
            categories.discard("create")
        if folded == "ban" and token != "bán":
            categories.discard("trade")
        if folded == "mua" and token != "mua":
            categories.discard("create")
            categories.discard("trade")
        if folded == "nhac" and token == "nhắc":
            categories.discard("create")
        if folded == "goi" and token == "gói":
            categories.discard("call")
    return frozenset(categories)


@lru_cache(maxsize=4096)
def _action_signals(tokens: tuple[str, ...]) -> tuple[tuple[int, int, frozenset[str]], ...]:
    signals: list[tuple[int, int, frozenset[str]]] = []
    for index, token in enumerate(tokens):
        categories = _token_categories(token)
        folded = _fold(token)
        if (folded == "phat" and index >= 2
                and tuple(_fold(item) for item in tokens[index - 2:index]) == ("danh", "sach")):
            categories = frozenset()
        if (folded == "uong" and index >= 1
                and _fold(tokens[index - 1]) == "nhac"):
            categories = frozenset()
        if (folded == "nghe" and index >= 1
                and _fold(tokens[index - 1]) == "cong"):
            # "công nghệ" is a noun phrase, including accentless ASR text;
            # it must not turn directional "den" into an instruction for đèn.
            categories = frozenset()
        if categories:
            signals.append((index, index + 1, categories))
    for phrase, categories in _ACTION_PHRASES.items():
        width = len(phrase)
        for start in range(len(tokens) - width + 1):
            if all(_token_matches(tokens[start + offset], phrase[offset])
                   for offset in range(width)):
                signals.append((start, start + width, categories))
    return tuple(signals)


@lru_cache(maxsize=4096)
def _action_categories(tokens: tuple[str, ...]) -> frozenset[str]:
    materialized = tokens
    return frozenset(category
                     for _, _, categories in _action_signals(materialized)
                     for category in categories)


def _tool_categories(tool: str) -> frozenset[str]:
    suffix = tool.rsplit(".", 1)[-1]
    if suffix in _TOOL_CATEGORY:
        return _TOOL_CATEGORY[suffix]
    if suffix.endswith("_set"):
        return _TOOL_CATEGORY["set"]
    if suffix.endswith("_run"):
        return frozenset({"activate"})
    if suffix == "stop":
        return frozenset({"deactivate"})
    if suffix.startswith(("update_", "reschedule_")):
        return frozenset({"modify"})
    for prefix in ("cancel_", "delete_", "remove_", "send_", "add_", "create_",
                   "book_", "reserve_", "set_", "update_", "complete_", "log_",
                   "search_", "list_", "get_", "read_", "find_", "track_"):
        if suffix.startswith(prefix):
            return _TOOL_CATEGORY.get(prefix[:-1], frozenset())
    if suffix.startswith(("list_", "get_", "search", "read_", "find_", "track")):
        return frozenset({"lookup"})
    return frozenset()


@lru_cache(maxsize=8192)
def _content_tokens(tokens: tuple[str, ...],
                    action_categories: frozenset[str] = frozenset()) -> tuple[str, ...]:
    return tuple(token for token in tokens
                 if _fold(token) not in _STOPWORDS
                 and not (_token_categories(token) & action_categories)
                 and len(token) > 1)


def _is_negated_at(tokens: tuple[str, ...], start: int) -> bool:
    preceding = tuple(_fold(token) for token in tokens[max(0, start - 4):start])
    if "quen" in preceding and any(token in _NEGATIONS for token in preceding):
        return False
    if any(preceding[index:index + 2] == ("khong", "chi")
           for index in range(max(0, len(preceding) - 2), len(preceding) - 1)):
        return False
    for token in reversed(preceding):
        if token in {"roi", "nhung", "con", "but", "chi", "and", "va", "thi", "then"}:
            break
        if token in _NEGATIONS:
            return True
    return False


def _is_completed_at(tokens: tuple[str, ...], start: int) -> bool:
    """Exclude actions explicitly described as already completed."""
    return "da" in tuple(_fold(token) for token in tokens[max(0, start - 2):start])


@lru_cache(maxsize=1024)
def _active_categories(tokens: tuple[str, ...],
                       ignore_completed_actions: bool) -> frozenset[str]:
    return frozenset(
        category
        for start, _, categories in _action_signals(tokens)
        if not _is_negated_at(tokens, start)
        and (not ignore_completed_actions or not _is_completed_at(tokens, start))
        for category in categories
    )


@lru_cache(maxsize=512)
def _clause_tokens(clauses: tuple[tuple[str, ...], ...]) -> tuple[str, ...]:
    return tuple(token for clause in clauses for token in clause)


@lru_cache(maxsize=4096)
def _content_overlap_count(request_content: tuple[str, ...],
                           trigger_content: tuple[str, ...]) -> int:
    trigger_aliases = {_TOKEN_ALIASES.get(token, token) for token in trigger_content}
    trigger_folds = {_fold(token) for token in trigger_content}
    trigger_unmarked_folds = {
        _fold(token) for token in trigger_content if not _has_marks(token)
    }
    return len({
        token for token in request_content
        if (_TOKEN_ALIASES.get(token, token) in trigger_aliases
            or (_fold(token) in trigger_folds
                and (not _has_marks(token) or _fold(token) in trigger_unmarked_folds)))
    })


def _request_clauses(text: str) -> tuple[tuple[str, ...], ...]:
    parts = re.split(r"[,;.!?\n]|\b(?:rồi|roi|sau\s+(?:đó|do)|nhưng|nhung|but|và|va|and|then)\b",
                     text, flags=re.IGNORECASE)
    return tuple(tokens for part in parts if (tokens := _tokens(part)))


def _active_phrase(tokens: tuple[str, ...], phrases: tuple[str, ...]) -> bool:
    """Require a current action, retaining the existing negation/completion policy."""
    for phrase in phrases:
        words = _tokens(phrase)
        for start in range(len(tokens) - len(words) + 1):
            if (all(_token_matches(tokens[start + offset], word)
                    for offset, word in enumerate(words))
                    and not _is_negated_at(tokens, start)
                    and not _is_completed_at(tokens, start)):
                return True
    return False


def _workflow_clauses(branch: SkillBranch, clauses: tuple[tuple[str, ...], ...],
                      context_tokens: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    """Narrow ambiguous write workflows before the generic action-category match.

    A shared category such as create/modify is insufficient for these workflows.
    Keep action, object and payment channel in the same clause; history supplies
    an object only for an explicit reference in that clause. Other branches keep
    their existing composite matching and eligibility/evidence gates.
    """
    key = branch.branch_key
    if key not in {"bank-transfer", "bank-savings", "wallet-transfer",
                   "alarm-change", "note-append"}:
        return clauses
    result = []
    for clause in clauses:
        target = (*clause, *context_tokens) if _has_reference(" ".join(clause)) else clause
        has = lambda phrases: any(_phrase_present(phrase, target) for phrase in phrases)
        active = lambda phrases: _active_phrase(clause, phrases)
        if not has(branch.required_object_cues):
            continue
        if key == "bank-savings":
            # Mentioning a bank, or looking up savings, is not an opening intent.
            matched = active(("gửi tiết kiệm", "mở tiết kiệm", "mở sổ tiết kiệm",
                              "mở tài khoản tiết kiệm", "tạo khoản tiết kiệm",
                              "open savings", "create savings"))
        elif key in {"bank-transfer", "wallet-transfer"}:
            if not active(("chuyển", "transfer", "gửi tiền", "send money")):
                continue
            if has(("hóa đơn", "bill", "qr")):
                continue  # A payment is not a transfer to a beneficiary/contact.
            bank = has(("ngân hàng", "tài khoản ngân hàng", "bank", "banking"))
            wallet = has(("ví", "ewallet", "wallet"))
            # Both channels in one clause may describe a cross-app operation that
            # neither branch establishes. Leave that ambiguity to the planner.
            if key == "wallet-transfer":
                matched = wallet and not bank
            else:
                matched = (bank or has(("chuyển khoản",))) and not wallet
        elif key == "alarm-change":
            # A new alarm may contain words such as "sửa xe" or "chuyển tiền".
            # Require an actual alarm-change phrase, not any modify action nearby.
            verbs = (
                "đổi", "dời", "sửa", "chỉnh", "cập nhật", "tắt", "xóa", "hủy",
                "update", "edit", "delete", "cancel", "reschedule")
            matched = (active(tuple(f"{verb} {obj}" for verb in verbs
                                    for obj in ("báo thức", "giờ báo thức", "alarm")))
                       or (_has_reference(" ".join(clause)) and active(verbs)))
        else:  # note-append
            matched = (not has(("ghi chú mới", "note mới", "new note"))
                       and (active(("ghi tiếp", "viết tiếp", "bổ sung", "append"))
                            or (active(("thêm", "add"))
                                and has(("vào ghi chú", "vào note", "ghi chú đã có",
                                         "note đã có", "ghi chú cũ", "existing note")))))
        if matched:
            result.append(clause)
    return tuple(result)


def _branch_request_candidate(
    branch: SkillBranch,
    clauses: tuple[tuple[str, ...], ...],
    context_tokens: tuple[str, ...],
    *,
    ignore_completed_actions: bool,
) -> bool:
    requirements = _branch_action_requirements(branch)
    if not requirements:
        return False
    cue_source = (*_clause_tokens(clauses), *context_tokens)
    if branch.required_object_cues and not any(
        _phrase_present(cue, cue_source) for cue in branch.required_object_cues
    ):
        return False
    if any(not any(_phrase_present(cue, cue_source) for cue in group)
           for group in branch.required_cue_groups):
        return False
    relevant_clauses = (
        (_clause_tokens(clauses),)
        if len(branch.domain_ids) > 1 or len(branch.action_groups) > 1
        else clauses
    )
    return any(
        all(_active_categories(clause, ignore_completed_actions) & group
            for group in requirements)
        for clause in relevant_clauses
    )


def _trigger_match(
    clauses: tuple[tuple[str, ...], ...],
    context_tokens: tuple[str, ...],
    trigger: str,
    required_categories: tuple[frozenset[str], ...],
    required_object_cues: tuple[str, ...] = (),
    required_cue_groups: tuple[tuple[str, ...], ...] = (),
    *,
    composite: bool,
    ignore_completed_actions: bool = True,
    cues_prechecked: bool = False,
) -> tuple[bool, float]:
    trigger_tokens = _tokens(trigger)
    if not trigger_tokens:
        return False, 0.0
    trigger_signals = _action_signals(trigger_tokens)
    if not required_categories or any(
        not any(signal_categories & group for _, _, signal_categories in trigger_signals)
        for group in required_categories
    ):
        return False, 0.0
    action_categories = frozenset(category for group in required_categories for category in group)
    all_request_tokens = _clause_tokens(clauses)
    cue_source = (*all_request_tokens, *context_tokens)
    if not cues_prechecked:
        if required_object_cues and not any(
            _phrase_present(cue, cue_source) for cue in required_object_cues
        ):
            return False, 0.0
        if any(not any(_phrase_present(cue, cue_source) for cue in group)
               for group in required_cue_groups):
            return False, 0.0
    trigger_content = _content_tokens(trigger_tokens, action_categories)
    relevant_clauses = (_clause_tokens(clauses),) if composite else clauses
    for clause in relevant_clauses:
        active_categories = _active_categories(clause, ignore_completed_actions)
        if any(not (active_categories & group) for group in required_categories):
            continue
        request_content = _content_tokens((*clause, *context_tokens), action_categories)
        object_hits = _content_overlap_count(request_content, trigger_content)
        if object_hits:
            return True, min(0.99, 0.62 + min(object_hits, 3) * 0.08)
    return False, 0.0


@lru_cache(maxsize=4096)
def _phrase_present(phrase: str, tokens: tuple[str, ...]) -> bool:
    phrase_tokens = _tokens(phrase)
    if not phrase_tokens:
        return False
    width = len(phrase_tokens)
    return any(
        all(_token_matches(tokens[start + offset], phrase_tokens[offset])
            for offset in range(width))
        for start in range(len(tokens) - width + 1)
    )


def _branch_action_requirements(branch: SkillBranch) -> tuple[frozenset[str], ...]:
    # The scoped gates above establish the business action. Accept its actual
    # surface verbs (e.g. "mở sổ", "chuyển ví", "tắt báo thức") as well as create.
    if branch.branch_key == "bank-savings":
        return (frozenset({"create", "activate", "send"}),)
    if branch.branch_key in {"bank-transfer", "wallet-transfer"}:
        return (frozenset({"create", "modify", "send"}),)
    if branch.branch_key == "alarm-change":
        return (frozenset({"modify", "cancel", "deactivate"}),)
    return _action_requirements(branch.action_groups)


@lru_cache(maxsize=256)
def _action_requirements(action_groups: tuple[tuple[str, ...], ...]
                        ) -> tuple[frozenset[str], ...]:
    groups: list[frozenset[str]] = []
    for action_group in action_groups:
        categories = frozenset(
            category for tool in action_group for category in _tool_categories(tool)
        )
        if not categories:
            return ()
        groups.append(categories)
    return tuple(groups)


def _is_logging_branch(branch: SkillBranch) -> bool:
    return all(
        tool.rsplit(".", 1)[-1] in {"log", "log_taken", "log_progress"}
        for group in branch.action_groups for tool in group
    )


def _history_text(history: Sequence[str | Mapping[str, Any]]) -> tuple[str, ...]:
    if isinstance(history, (str, bytes)) or not isinstance(history, Sequence):
        raise SkillRetrievalInputError("history must be a sequence of user text or turns")
    if len(history) > _MAX_HISTORY_TURNS:
        raise SkillRetrievalInputError("history exceeds its turn limit")
    result: list[str] = []
    total = 0
    for index, turn in enumerate(history):
        if isinstance(turn, str):
            value = turn
        elif isinstance(turn, Mapping):
            role = turn.get("role")
            if role not in {"user", "assistant"}:
                raise SkillRetrievalInputError(f"history[{index}] has an invalid role")
            if role != "user":
                continue
            value = turn.get("text")
            if not isinstance(value, str):
                raise SkillRetrievalInputError(f"history[{index}] has no user text")
        else:
            raise SkillRetrievalInputError(f"history[{index}] is not text or a turn")
        if not isinstance(value, str) or len(value) > _MAX_REQUEST_CHARS:
            raise SkillRetrievalInputError(f"history[{index}] text is invalid or too long")
        total += len(value)
        if total > _MAX_HISTORY_CHARS:
            raise SkillRetrievalInputError("history text exceeds its size limit")
        if value.strip():
            result.append(value.strip())
    return tuple(result)


def _eligible_tool_set(eligible_tools: Iterable[str]) -> frozenset[str]:
    if isinstance(eligible_tools, (str, bytes)) or not isinstance(eligible_tools, Iterable):
        raise SkillRetrievalInputError("eligible_tools must be an iterable of exact tool names")
    result: set[str] = set()
    for index, value in enumerate(eligible_tools):
        if index >= _MAX_ELIGIBLE_TOOLS:
            raise SkillRetrievalInputError("eligible_tools exceeds its size limit")
        value = _tool(value, f"eligible_tools[{index}]")
        result.add(value)
    return frozenset(result)


@lru_cache(maxsize=512)
def _parameter_value_pattern(field_name: str) -> re.Pattern[str]:
    label = r"[\s_-]+".join(re.escape(part) for part in field_name.split("_"))
    return re.compile(
        rf"(?<![\w])(?:[\"'])?{label}(?:[\"'])?\s*(?:=|:|\bis\b)\s*"
        r"[\"']?([A-Za-z0-9+][A-Za-z0-9.+:/_@-]*)[\"']?(?![\w])",
        re.IGNORECASE,
    )


def _explicit_parameter_present(field_name: str, evidence: tuple[str, ...]) -> bool:
    pattern = _parameter_value_pattern(field_name)
    return any(
        (match := pattern.search(text)) is not None
        and match.group(1).casefold() not in _PLACEHOLDER_VALUES
        for text in evidence
    )


def _parameter_values_present(parameter: SkillParameter,
                              evidence: tuple[str, ...]) -> bool:
    return (
        all(_explicit_parameter_present(field, evidence) for field in parameter.required)
        and (not parameter.x_one_of or any(
            all(_explicit_parameter_present(field, evidence) for field in group)
            for group in parameter.x_one_of
        ))
    )


def _dependency_input_present(dependency: SkillDependencyGroup,
                              evidence: tuple[str, ...]) -> bool:
    return any(
        all(_explicit_parameter_present(field, evidence) for field in alternative)
        for alternative in dependency.input_alternatives
    )


def _ready_action_groups(branch: SkillBranch, eligible: frozenset[str],
                         evidence: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    parameters = {item.tool: item for item in branch.parameters}
    return tuple(
        tuple(tool for tool in group
              if tool in eligible and _parameter_values_present(parameters[tool], evidence))
        for group in branch.action_groups
    )


def _has_reference(text: str) -> bool:
    folded = " ".join(_fold(token) for token in _tokens(text))
    if re.search(r"\b(?:cai do|cai nay|nguoi ay|nguoi do|nguoi nay|nhu cu)\b", folded):
        return True
    return re.search(r"\bno\b", folded) is not None


def _guidance_for(branch: SkillBranch, eligible: frozenset[str],
                  library: SkillLibrary, shared_refs: tuple[str, ...], *,
                  action_inputs_available: bool,
                  ready_action_groups: tuple[tuple[str, ...], ...]) -> SkillGuidance:
    action_groups = (ready_action_groups if action_inputs_available else
                     tuple(tuple(tool for tool in group if tool in eligible)
                           for group in branch.action_groups))
    dependencies = tuple(
        SkillDependencyGroup(
            tuple(tool for tool in group.tools if tool in eligible),
            group.guard,
            group.input_alternatives,
        )
        for group in branch.conditional_dependencies
        if any(tool in eligible for tool in group.tools)
        and not (action_inputs_available and group.guard in {
            "required_data_missing", "optional_detail_missing",
        })
    )
    conditional_actions = tuple(action for action in branch.conditional_actions
                                if action.tool in eligible)
    always = tuple(tuple(tool for tool in group if tool in eligible)
                   for group in branch.eligibility.always_dependencies
                   if any(tool in eligible for tool in group))
    eligibility = SkillEligibility(
        rule=branch.eligibility.rule,
        conditional_reader_rule=branch.eligibility.conditional_reader_rule,
        always_dependencies=always,
        conditional_action_rule=branch.eligibility.conditional_action_rule,
        tool_source=branch.eligibility.tool_source,
    )
    # The guidance object intentionally carries only currently callable names.
    if not action_groups or any(not group for group in action_groups):
        raise SkillLibraryError(f"Internal eligibility error for {branch.branch_id}")
    shared = tuple(library.shared[ref] for ref in shared_refs)
    return SkillGuidance(
        branch_id=branch.branch_id,
        parent_id=branch.skill_id,
        title=branch.title,
        evidence=branch.evidence,
        action_groups=action_groups,
        conditional_dependencies=dependencies,
        conditional_actions=conditional_actions,
        eligibility=eligibility,
        constraints=branch.constraints,
        completion_criteria=branch.completion_criteria,
        missing_information=branch.missing_information,
        common_refs=shared_refs,
        shared_instructions=shared,
        guidance=branch.guidance,
        dependency_flow=branch.dependency_flow,
    )


def retrieve(
    request: str,
    history: Sequence[str | Mapping[str, Any]],
    eligible_tools: Iterable[str],
    library: SkillLibrary | None = None,
) -> tuple[SkillGuidance, ...]:
    """Select E branches from current request; history only resolves explicit references.

    Retrieval never executes tools, reads labels/state, mutates request arguments, or
    broadens the caller's exact eligible tool set.
    """
    if not isinstance(request, str) or not request.strip() or len(request) > _MAX_REQUEST_CHARS:
        raise SkillRetrievalInputError("request must be nonempty bounded text")
    library = load_library() if library is None else library
    if not isinstance(library, SkillLibrary):
        raise SkillRetrievalInputError("library must be a validated SkillLibrary")
    user_history = _history_text(history)
    eligible = _eligible_tool_set(eligible_tools)
    text = request.strip()
    request_tokens = _tokens(text)
    # Past user text can supply target words for an explicit reference, but it never
    # contributes action verbs; prior intents cannot be replayed from history.
    context_tokens: tuple[str, ...] = ()
    if (_has_reference(text) and _action_categories(request_tokens) and user_history):
        context_tokens = _tokens(" ".join(user_history[-4:]))
    relevant_history = user_history[-4:] if context_tokens else ()
    parameter_evidence = (text, *relevant_history)
    clauses = _request_clauses(text)
    gated_matches: set[str] = set()
    for branch in library.branches:
        if branch.evidence == "E":
            continue
        requirements = _branch_action_requirements(branch)
        ignore_completed = not _is_logging_branch(branch)
        if not _branch_request_candidate(
            branch, clauses, context_tokens,
            ignore_completed_actions=ignore_completed,
        ):
            continue
        if any(_trigger_match(
            clauses, context_tokens, trigger, requirements,
            branch.required_object_cues,
            branch.required_cue_groups,
            composite=len(branch.domain_ids) > 1 or len(branch.action_groups) > 1,
            ignore_completed_actions=ignore_completed,
            cues_prechecked=True,
        )[0] for trigger in branch.intent_triggers):
            gated_matches.add(branch.branch_id)

    selected: list[tuple[float, SkillBranch, bool, tuple[tuple[str, ...], ...]]] = []
    for branch in library.branches:
        if branch.evidence != "E":
            continue
        if any(branch_id in gated_matches for branch_id in branch.suppressor_branch_ids):
            continue
        if any(not any(tool in eligible for tool in group) for group in branch.action_groups):
            continue
        if any(not any(tool in eligible for tool in group)
               for group in branch.eligibility.always_dependencies):
            continue
        requirements = _branch_action_requirements(branch)
        ignore_completed = not _is_logging_branch(branch)
        branch_clauses = _workflow_clauses(branch, clauses, context_tokens)
        if not _branch_request_candidate(
            branch, branch_clauses, context_tokens,
            ignore_completed_actions=ignore_completed,
        ):
            continue
        ready_action_groups = _ready_action_groups(branch, eligible, parameter_evidence)
        action_inputs_available = all(ready_action_groups)
        missing_required_reader = any(
            dependency.guard == "required_data_missing"
            and not any(tool in eligible for tool in dependency.tools)
            and not _dependency_input_present(dependency, parameter_evidence)
            for dependency in branch.conditional_dependencies
        )
        if (missing_required_reader and not action_inputs_available
                and _MISSING_INPUT_TOOL not in eligible):
            continue
        best = 0.0
        for trigger in branch.intent_triggers:
            matched, score = _trigger_match(
                branch_clauses, context_tokens, trigger, requirements,
                branch.required_object_cues,
                branch.required_cue_groups,
                composite=len(branch.domain_ids) > 1 or len(branch.action_groups) > 1,
                ignore_completed_actions=ignore_completed,
                cues_prechecked=True,
            )
            if matched:
                best = max(best, score)
        if best:
            selected.append((best, branch, action_inputs_available, ready_action_groups))
    selected.sort(key=lambda item: (-item[0], item[1].skill_id, item[1].branch_id))
    # Shared references are attached once across the complete result, while distinct
    # branch/action goals remain separate even when they happen to use one tool.
    result: list[SkillGuidance] = []
    seen_shared: set[str] = set()
    for _, branch, action_inputs_available, ready_action_groups in selected:
        fresh_refs = tuple(ref for ref in branch.common_refs if ref not in seen_shared)
        seen_shared.update(branch.common_refs)
        result.append(_guidance_for(
            branch, eligible, library, fresh_refs,
            action_inputs_available=action_inputs_available,
            ready_action_groups=ready_action_groups,
        ))
    return tuple(result)
