"""Load an explicitly trusted organizer package without editing its source."""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

from .contracts import JSON, PipelineError, PreparedDataset, RunConfig
from .dataset import require, validate_catalog
from .jsonio import digest, read_json, visible_path


class RuntimeFactory:
    def __init__(self, module, config: RunConfig, metadata: JSON, selected_ids: set[str]):
        self.module, self.config, self.metadata = module, config, metadata
        self.selected_ids = selected_ids
        self.opened: set[str] = set()

    def __call__(self, split: str, sample_id: str, root: Path):
        require(split == self.config.split and root.resolve() == self.config.data_root.resolve(),
                "Runtime invocation differs from preflight", "CATALOG_INVALID")
        require(sample_id in self.selected_ids, "Sample was not selected in preflight", "INPUT_INVALID")
        if sample_id in self.opened:
            raise PipelineError("EXECUTION_UNCERTAIN", "Environment cannot be reset/reopened", "environment")
        self.opened.add(sample_id)  # A failed open is not an invitation to retry.
        return self.module.ToolEnv(split, sample_id, root=root)


def load_runtime(config: RunConfig, dataset: PreparedDataset) -> RuntimeFactory:
    directory = config.runtime_dir.resolve()
    if directory.name == "zaic_tools" and directory.parent.name == config.split:
        reference = directory.parent / f"{config.split}_tools_catalog.json"
    elif directory.name == {"train": "train", "public_test": "test"}[config.split]:
        reference = directory.parent / f"{config.split}_tools_catalog.json"
    else:
        raise PipelineError("CATALOG_INVALID", "Runtime directory does not match the selected split")
    require((directory / "__init__.py").is_file(), "Runtime package is missing", "ASSET_MISSING")
    visible_path(directory / "__init__.py")
    reference_catalog = read_json(reference, "CATALOG_INVALID")
    validate_catalog(reference_catalog)
    require(reference_catalog == dataset.catalog, "Runtime and dataset catalogs differ", "CATALOG_INVALID")
    # Unique package names avoid importing a cached train package for public_test.
    name = "_lifemate_organizer_" + hashlib.sha256(str(directory).encode()).hexdigest()[:20]
    try:
        if name in sys.modules:
            module = sys.modules[name]
        else:
            spec = importlib.util.spec_from_file_location(
                name, directory / "__init__.py", submodule_search_locations=[str(directory)])
            require(spec is not None and spec.loader is not None, "Cannot load runtime", "CATALOG_INVALID")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            try:
                spec.loader.exec_module(module)
            except Exception:
                for key in list(sys.modules):
                    if key == name or key.startswith(name + "."):
                        sys.modules.pop(key, None)
                raise
        require(callable(getattr(module, "ToolEnv", None))
                and isinstance(getattr(module, "TOOLS", None), dict),
                "Invalid organizer runtime API", "CATALOG_INVALID")
        required = {t["name"] for sample in dataset.samples for t in sample.tools}
        require(required <= module.TOOLS.keys(), "Selected tool lacks a runtime implementation", "CATALOG_INVALID")
    except PipelineError:
        raise
    except Exception as exc:
        raise PipelineError("CATALOG_INVALID", "Trusted runtime could not be imported") from exc
    files = sorted(directory.rglob("*.py"))
    fingerprints = {str(p.relative_to(directory)).replace("\\", "/"): digest(p) for p in files}
    return RuntimeFactory(module, config, {"directory": str(directory), "source_sha256": fingerprints},
                          {sample.id for sample in dataset.samples})
