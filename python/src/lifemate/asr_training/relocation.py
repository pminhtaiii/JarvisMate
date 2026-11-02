"""Resolve imported asset paths without rewriting historical evidence or identities."""
from __future__ import annotations

import json
from pathlib import Path

from lifemate.jsonio import digest, visible_path


def resolve_path(value, suite: Path | None = None) -> Path:
    """Apply only the explicitly registered source-root mapping for this suite."""
    if suite is None:
        suite = Path(__file__).resolve().parents[4] / '.agent-work/asr-finetune/suite-01'
    mapping = suite / 'relocation.json'
    path = Path(value)
    visible_path(path)
    if not mapping.is_file():
        return path
    record = json.loads(mapping.read_text(encoding='utf-8'))
    if (record.get('schema') != 'lifemate-asr-relocation-v1'
            or record.get('suite_sha256') != digest(suite / 'suite.json')
            or not isinstance(record.get('source_roots'), list) or not record['source_roots']):
        raise ValueError('ASR relocation mapping/schema/suite hash mismatch')
    destination = (suite / record['project_root']).resolve()
    normalized = str(value).replace('\\', '/').rstrip('/')
    for original in record['source_roots']:
        prefix = original.replace('\\', '/').rstrip('/')
        if normalized.casefold() == prefix.casefold() or normalized.casefold().startswith(prefix.casefold() + '/'):
            relative = normalized[len(prefix):].lstrip('/')
            path = (destination / relative).resolve()
            if not path.is_relative_to(destination):
                raise ValueError('ASR relocated path escapes the destination project')
            visible_path(path)
            return path
    return path


def operational_view(value, suite: Path):
    """Presentation only; never use this projection to recompute original identities."""
    if isinstance(value, dict):
        return {k: operational_view(v, suite) for k, v in value.items()}
    if isinstance(value, list):
        return [operational_view(v, suite) for v in value]
    if isinstance(value, str) and (Path(value).is_absolute() or ':/' in value.replace('\\', '/')):
        return str(resolve_path(value, suite))
    return value
