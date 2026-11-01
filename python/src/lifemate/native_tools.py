"""Pure catalog-to-native-function adapter (specs §4.3, N01).

Native Qwen ``tools=`` entries carry each permitted catalog tool's exact name,
description and complete parameters object. Non-function metadata (app, kind,
returns and any other keys) stays in a hash-bound binding used for audit and
validation; nothing is renamed, filtered, reordered or simplified.
"""
from __future__ import annotations

import copy
import hashlib
from typing import Any

from .jsonio import dumps

ADAPTER_VERSION = "lifemate-native-catalog-adapter-v1"
BINDING_SCHEMA = "lifemate-native-catalog-binding-v1"
SYSTEM_TOOL = "sys.ask_missing_info"
FUNCTION_KEYS = ("name", "description", "parameters")
# Organizer extensions whose meaning this project knows. x-ref is evidence metadata,
# not an ID resolver; x-match is scoring metadata; x-one-of needs >=1 complete group.
KNOWN_EXTENSIONS = frozenset({"x-ref", "x-match", "x-one-of"})


class CatalogAdapterError(ValueError):
    """The permitted tool list cannot be represented without losing semantics."""


def _hash(value: Any) -> str:
    return hashlib.sha256(dumps(value).encode("utf-8")).hexdigest()


def permitted_tool_names(installed_apps: dict, specs: dict[str, dict]) -> list[str]:
    """Exact per-sample installed-tool order, plus the system tool once if absent."""
    names: list[str] = []
    for app, info in installed_apps.items():
        for name in info["tools"]:
            if name not in specs or specs[name].get("app") != app or name in names:
                raise CatalogAdapterError("Installed tool is absent, misassigned or duplicated")
            names.append(name)
    if SYSTEM_TOOL not in names:
        names.append(SYSTEM_TOOL)
    return names


def extensions(schema: Any, path: str = "parameters") -> list[tuple[str, str]]:
    """Every x-* key with its schema path, recursively and in document order."""
    found: list[tuple[str, str]] = []
    if isinstance(schema, dict):
        for key, value in schema.items():
            if isinstance(key, str) and key.startswith("x-"):
                found.append((path, key))
            found.extend(extensions(value, f"{path}.{key}"))
    elif isinstance(schema, list):
        for index, value in enumerate(schema):
            found.extend(extensions(value, f"{path}[{index}]"))
    return found


def adapt_tools(permitted_tools: list[dict]) -> tuple[list[dict], dict]:
    """Return (native_tools, catalog_binding) for an exact ordered permitted tool list.

    The caller supplies tools in per-sample availability order; the system tool must
    already be present exactly once (``permitted_tool_names`` appends it if absent).
    Unknown x-* extensions are preserved and listed as unsupported for enforcement.
    """
    if not isinstance(permitted_tools, list) or not permitted_tools:
        raise CatalogAdapterError("Permitted tools must be a nonempty list")
    names = [tool.get("name") if isinstance(tool, dict) else None for tool in permitted_tools]
    if any(not isinstance(name, str) or not name for name in names) or len(set(names)) != len(names):
        raise CatalogAdapterError("Tool names must be unique nonempty strings")
    if names.count(SYSTEM_TOOL) != 1:
        raise CatalogAdapterError("The system tool must be available exactly once")
    native, entries, unsupported = [], [], []
    for tool in permitted_tools:
        if not isinstance(tool.get("description"), str) or not isinstance(tool.get("parameters"), dict):
            raise CatalogAdapterError("Tool requires a description and a parameters object")
        native.append({"type": "function", "function": {
            "name": tool["name"], "description": copy.deepcopy(tool["description"]),
            "parameters": copy.deepcopy(tool["parameters"])}})
        metadata = {key: copy.deepcopy(value) for key, value in tool.items() if key not in FUNCTION_KEYS}
        entries.append({"name": tool["name"], "key_order": list(tool), "metadata": metadata})
        unsupported += [{"tool": tool["name"], "path": path, "key": key}
                        for path, key in extensions(tool["parameters"]) if key not in KNOWN_EXTENSIONS]
    binding = {"schema": BINDING_SCHEMA, "adapter": ADAPTER_VERSION, "names": names,
               "tools": entries, "unsupported_extensions": unsupported,
               "native_tools_sha256": _hash(native), "catalog_tools_sha256": _hash(permitted_tools)}
    binding["identity"] = _hash(binding)
    return native, binding


def restore_catalog_tools(native_tools: list[dict], binding: dict) -> list[dict]:
    """Inverse of adapt_tools; used by round-trip audits (P02/N01)."""
    if binding.get("schema") != BINDING_SCHEMA or len(native_tools) != len(binding.get("tools", [])):
        raise CatalogAdapterError("Binding does not describe these native tools")
    if _hash(native_tools) != binding["native_tools_sha256"]:
        raise CatalogAdapterError("Native tools changed after binding")
    restored = []
    for native, entry in zip(native_tools, binding["tools"]):
        function = native.get("function", {})
        if native.get("type") != "function" or function.get("name") != entry["name"]:
            raise CatalogAdapterError("Native tool order/name differs from binding")
        values = {**{key: copy.deepcopy(function[key]) for key in FUNCTION_KEYS},
                  **copy.deepcopy(entry["metadata"])}
        restored.append({key: values[key] for key in entry["key_order"]})
    if _hash(restored) != binding["catalog_tools_sha256"]:
        raise CatalogAdapterError("Catalog round trip changed the original schemas")
    return restored

