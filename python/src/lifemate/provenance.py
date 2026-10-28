"""Content identities for reproducible resume; no simulator-state access."""
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .jsonio import digest


def code_identity() -> dict:
    package = Path(__file__).resolve().parent
    files = sorted(package.rglob("*.py"))
    root = package.parents[1]
    files += [p for p in (root / "pyproject.toml", root / "run_train.py") if p.is_file()]
    return {str(p.relative_to(root)).replace("\\", "/"): digest(p) for p in files}


def execution_identity(config) -> dict:
    def model(path):
        if path is None:
            return None
        path = path.resolve()
        # Hash actual local weights/tokenizers, not just their directory name or mtime.
        files = sorted(p for p in path.rglob("*") if p.is_file() and
                       p.suffix in {".json", ".safetensors", ".bin", ".model", ".txt", ".tiktoken"})
        return {"path": str(path), "files": {str(p.relative_to(path)).replace("\\", "/"): digest(p)
                                            for p in files}}

    packages = {}
    for name in ("torch", "transformers", "numpy", "lm-format-enforcer", "pydantic", "interegular"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return {"code": code_identity(), "packages": packages,
            "planner": model(config.planner_model),
            "asr": model(config.asr_model) if config.input_mode == "audio" else None}
