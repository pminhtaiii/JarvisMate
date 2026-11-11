"""Shared IO and integrity boundaries. No model or simulator instances on import."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import sys
import uuid

sys.dont_write_bytecode = True
SOURCE_SHA = '047879eb0931e5fa85930d640fb4c0b71d9268bc'
SERVER_BASE = Path('/datastore/binhvp/BuiTrongTan/tmp')
ARMS = ('control', 'treatment')


class HarnessError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise HarnessError(message)


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def loads(text):
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, 'Duplicate JSON key: ' + k)
            result[k] = v
        return result
    def constant(value):
        raise HarnessError('Nonfinite JSON: ' + value)
    value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    dumps(value)
    return value


def read_json(path):
    return loads(Path(path).read_text(encoding='utf-8-sig'))


def read_jsonl(path):
    return [loads(s) for s in Path(path).read_text(encoding='utf-8-sig').splitlines() if s.strip()]


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as f:
        f.write(text)


def write_json(path, value):
    write_text(path, dumps(value) + '\n')


def write_jsonl(path, values):
    write_text(path, ''.join(dumps(v) + '\n' for v in values))


def digest(path):
    path = Path(path)
    require(not any(p.endswith('_environment') for p in path.parts) and path.name != 'state.json',
            'Harness may not read/hash environment files')
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def fingerprint(value):
    return hashlib.sha256(dumps(value).encode('utf-8')).hexdigest()


def equal(a, b):
    """Typed JSON equality; bool/int and int/float never silently compare equal."""
    return dumps(a) == dumps(b)


def inside(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    return path == root or path.is_relative_to(root)


def child(root, relative):
    path = (Path(root) / relative).resolve()
    require(inside(path, root), 'Path escapes experiment: ' + str(relative))
    return path


def train_id(value):
    require(isinstance(value, str) and re.fullmatch(r'train_[A-Za-z0-9_-]+', value),
            'Only safe Train IDs are allowed: ' + str(value))
    return value


def activate(source):
    source = Path(source).resolve() / 'python' / 'src'
    loaded = sys.modules.get('lifemate')
    if loaded and not inside(loaded.__file__, source):
        for name in list(sys.modules):
            if name == 'lifemate' or name.startswith('lifemate.'):
                del sys.modules[name]
    sys.path.insert(0, str(source)) if str(source) not in sys.path else None
    module = importlib.import_module('lifemate')
    require(inside(module.__file__, source), 'Wrong lifemate import path')


def code_files(root, suffixes=('.py', '.json', '.toml', '.sbatch', '.sh')):
    root = Path(root)
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(root.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts and p.suffix in suffixes}


def model_files(root):
    suffixes = {'.json', '.safetensors', '.bin', '.model', '.txt', '.tiktoken', '.jinja'}
    return {str(p.resolve()): digest(p) for p in sorted(Path(root).rglob('*'))
            if p.is_file() and '.cache' not in p.parts and p.suffix in suffixes}


def visible_rows(data_root):
    rows = read_jsonl(Path(data_root) / 'train/train.jsonl')
    ids = [train_id(r.get('id')) for r in rows]
    require(len(ids) == len(set(ids)) and bool(ids), 'Duplicate/empty Train IDs')
    for row in rows:
        require(isinstance(row.get('audio_text'), str) and row['audio_text'].strip(), 'Missing Train text')
        label = row.get('label')
        require(isinstance(label, dict) and isinstance(label.get('tool_calls'), list)
                and isinstance(label.get('tool_results'), list), 'Missing Train gold calls/results')
        require(len(label['tool_calls']) == len(label['tool_results']), 'Gold calls/results length mismatch')
    return rows


def base_inputs(data_root, rows):
    from lifemate.dataset import normalize_visible, prepare_request_once, validate_catalog
    from lifemate.contracts import Deadline
    catalog = read_json(Path(data_root) / 'train/train_tools_catalog.json')
    specs = validate_catalog(catalog)
    values = {}
    for row in rows:
        sample = normalize_visible(row, specs, (Path(data_root) / 'train').resolve(), 'transcript')
        value, stats = prepare_request_once(sample, None, Deadline(30))
        require(stats['asr_calls'] == 0, 'Transcript preparation unexpectedly used ASR')
        values[row['id']] = value
    return values, catalog, specs


def load_experiment(root, verify=True):
    root = Path(root).resolve()
    require(digest(root / 'experiment.json') == (root / 'experiment.sha256').read_text().strip(),
            'Experiment manifest checksum mismatch')
    record = read_json(root / 'experiment.json')
    require(record.get('schema_version') == 1 and record.get('source_sha') == SOURCE_SHA,
            'Wrong experiment/source version')
    require(Path(record['root']).resolve() == root, 'Experiment moved; absolute paths are frozen')
    if verify:
        verify_integrity(root, record)
    activate(root / 'src')
    return record


def verify_integrity(root, record=None, save=False):
    root = Path(root).resolve()
    record = record or read_json(root / 'experiment.json')
    expected = read_json(root / 'evidence/inputs-before.json')
    errors = []
    for path, sha in expected['files'].items():
        if not Path(path).is_file() or digest(path) != sha:
            errors.append('Changed/missing input: ' + path)
    for name in ('src', 'harness'):
        if code_files(root / name) != expected[name]:
            errors.append('Changed source/helper inventory: ' + name)
    if model_files(record['model']) != expected['model']:
        errors.append('Changed model inventory')
    if code_files(record['runtime_dir'],('.py',)) != expected['runtime']:
        errors.append('Changed runtime inventory')
    if code_files(Path(__file__).resolve().parent) != expected['harness']:
        errors.append('Executing harness version differs from frozen helpers; use experiment/harness')
    for path, sha in record['protocol_files'].items():
        if digest(child(root, path)) != sha:
            errors.append('Changed experiment protocol: ' + path)
    if save:
        write_json(root / 'evidence' / ('integrity-' + uuid.uuid4().hex + '.json'),
                   {'ok': not errors, 'errors': errors})
    require(not errors, '; '.join(errors))
    return {'ok': True, 'checked_inputs': len(expected['files'])}


def phase_runs(record, phase):
    require(phase in ('smoke', 'main'), 'Unknown phase')
    return record['phases'][phase]['runs']


def phase_ids(record, phase):
    return record['phases'][phase]['ids']


def config_for(root, run):
    from lifemate.configuration import load_config
    return load_config(child(root, run['config']))


def journal_for(root, run):
    from lifemate.diagnostics import read_journal
    from lifemate.contracts import PipelineError
    try:
        return read_journal(child(root, run['output']))
    except PipelineError as exc:
        raise HarnessError(str(exc)) from exc


def command_main(action):
    try:
        return action()
    except Exception as exc:
        print(dumps({'status': 'error', 'error_type': type(exc).__name__, 'message': str(exc)[:1000]}),
              file=sys.stderr)
        return 2


def add_experiment(parser):
    parser.add_argument('--experiment', type=Path, required=True)


def finite_time(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None
