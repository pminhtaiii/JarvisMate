"""Metadata-only catalog/dataset check: no models, ASR, runtime or ToolEnv."""
from __future__ import annotations

import argparse
from pathlib import Path

from .configuration import validate_skill_catalog
from .contracts import RunConfig
from .dataset import preflight
from .jsonio import canonical_sha256, digest, dumps, read_json
from .skills import load_library


def check(data_root: Path, repository_catalogs: Path) -> dict:
    library = load_library()
    results = []
    for split in ("train", "public_test"):
        dataset = preflight(RunConfig(data_root=data_root, runtime_dir=data_root / split / "zaic_tools",
                                      split=split, input_mode="audio", select_all=True))
        validate_skill_catalog(library, split, dataset.metadata)
        repository_path = repository_catalogs / f"{split}_tools_catalog.json"
        repository = read_json(repository_path, "CATALOG_INVALID")
        repository_metadata = {"catalog_version": repository["schema_version"],
                               "catalog_sha256": digest(repository_path),
                               "catalog_canonical_sha256": canonical_sha256(repository)}
        validate_skill_catalog(library, split, repository_metadata)
        results.append({"split": split, "selected_count": len(dataset.samples),
                        "dataset_sha256": dataset.metadata["dataset_sha256"],
                        "dataset_catalog_raw_sha256": dataset.metadata["catalog_sha256"],
                        "repository_catalog_raw_sha256": repository_metadata["catalog_sha256"],
                        "catalog_canonical_sha256": repository_metadata["catalog_canonical_sha256"],
                        "schema_version": repository["schema_version"], "status": "passed"})
    return {"kind": "skill_metadata_preflight", "models_loaded": False,
            "environments_created": 0, "skill_library": library.identity, "splits": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--repository-catalogs", required=True, type=Path)
    args = parser.parse_args()
    print(dumps(check(args.data_root.resolve(), args.repository_catalogs.resolve())))


if __name__ == "__main__":
    main()
