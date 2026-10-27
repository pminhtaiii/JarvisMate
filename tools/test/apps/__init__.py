"""One module per app, one method per tool: `smart_home.get_status` is `smart_home.SmartHome.get_status(...)`.
APPS and TOOLS are collected automatically from every App subclass defined in this package."""
from __future__ import annotations

import importlib
import pkgutil

from .base import App, read, write, meta  # noqa: F401

APPS: dict[str, type] = {}
for _m in pkgutil.iter_modules(__path__):
    if _m.name == "base":
        continue
    _mod = importlib.import_module(f"{__name__}.{_m.name}")
    for _obj in vars(_mod).values():
        if isinstance(_obj, type) and issubclass(_obj, App) and _obj is not App and _obj.name:
            APPS[_obj.name] = _obj
# "app.tool" -> kind, for every implemented tool
TOOLS: dict[str, str] = {f"{cls.name}.{m}": getattr(getattr(cls, m), "kind") for cls in APPS.values()
                         for m in dir(cls) if not m.startswith("_") and callable(getattr(cls, m)) and hasattr(getattr(cls, m), "kind")}
__all__ = ["App", "read", "write", "meta", "APPS", "TOOLS"]
