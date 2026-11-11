"""Freeze 011 source and Train transcript inputs without loading models or ToolEnv."""
from __future__ import annotations

import argparse
import copy
import io
from pathlib import Path
import shutil
import subprocess
import tarfile

from _common import (SOURCE_SHA, SERVER_BASE, activate, add_experiment, base_inputs, child,
                     code_files, command_main, digest, dumps, equal, fingerprint, inside,
                     load_experiment, model_files, read_json, require, visible_rows,
                     write_json, write_jsonl, write_text)


def snapshot(repo, destination):
    def git(*args):
        return subprocess.check_output(['git', '-c', 'safe.directory=' + Path(repo).resolve().as_posix(),
                                        '-C', str(repo), *args], stderr=subprocess.PIPE)
    require(git('rev-parse', SOURCE_SHA + '^{commit}').decode().strip() == SOURCE_SHA, 'Missing source commit')
    raw = git('archive', '--format=tar', SOURCE_SHA)
    archive_path = destination.parent / 'evidence/source-047879e.tar'
    with archive_path.open('xb') as f:
        f.write(raw)
    destination.mkdir()
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive:
            require(member.isdir() or member.isfile(), 'Source archive contains link/special entry')
            target = child(destination, member.name)
            require(not any(p.endswith('_environment') for p in target.parts)
                    and target.name != 'state.json', 'Environment files cannot be source assets')
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as src, target.open('xb') as dst:
                    shutil.copyfileobj(src, dst)


def grouped_blocks(rows, seed, size):
    require(type(size) is int and size > 0, 'Invalid block size')
    groups = {}
    for row in rows:
        declared = next(((k, row[k]) for k in ('conversation_id', 'dialogue_id', 'group_id')
                         if row.get(k) is not None), None)
        key = fingerprint(declared) if declared else (
            fingerprint(row['history']) if row.get('history') else row['id'])
        groups.setdefault(key, []).append(row['id'])
    ordered = sorted(groups, key=lambda g: fingerprint([seed, g]))
    blocks, pending = [], []
    for group in ordered:
        require(len(groups[group]) <= size, 'Conversation group exceeds block size; choose larger size before freeze')
        if pending and len(pending) + len(groups[group]) > size:
            blocks.append(pending)
            pending = []
        pending.extend(groups[group])
    if pending:
        blocks.append(pending)
    # Runtime retains JSONL order within each selected set.
    order = {row['id']: i for i, row in enumerate(rows)}
    return [sorted(block, key=order.get) for block in blocks], groups


def toml_record(value):
    def scalar(v):
        if isinstance(v, bool):
            return str(v).lower()
        return dumps(v)
    return 'schema_version = 1\n' + ''.join(
        '\n[' + section + ']\n' + ''.join(k + ' = ' + scalar(v) + '\n' for k, v in table.items())
        for section, table in value.items() if section != 'schema_version')


def validate_model_reference(reference, files, metadata, code, library):
    identity=reference['identity']
    require(equal(identity['code'],code) and identity.get('skill_library')==library,
            'Reference manifest is not the pinned 011 code/Library')
    require(equal(identity['planner']['files'],files), 'Checkpoint/tokenizer differs from original 011 reference')
    require(metadata is not None and identity['planner']['parameter_count']==metadata['parameter_count']
            and identity['planner']['template_sha256']==metadata['template_sha256'], 'Model metadata differs from 011 reference')


def prepare(root, repo, data, model, *, seed=42, block_size=256, local=False, skip_model=False,
            protect=(), model_reference=None):
    root, repo, data, model = [Path(p).resolve() for p in (root, repo, data, model)]
    require(not root.exists(), 'Experiment root exists; refusing overwrite/resume')
    require(type(seed) is int and 0 <= seed < 2**32, 'Invalid seed')
    for source in (repo, data, model):
        require(not inside(root, source) and not inside(source, root), 'Experiment overlaps input')
    if not local:
        require(all(inside(p, SERVER_BASE) for p in (root, repo, data, model, *map(Path, protect))),
                'All server paths must resolve under ' + str(SERVER_BASE))
        require(all(inside(data / p, SERVER_BASE) for p in ('train/train.jsonl','train/train_tools_catalog.json','train/zaic_tools')),
                'Dataset/runtime symlink resolves outside UIT tmp')
    require(not skip_model or local, 'Skipping model checks is CPU-local only')
    require(local or model_reference is not None, 'UIT preparation requires --model-reference-manifest for checkpoint 011')
    if model_reference is not None and not local:
        require(inside(model_reference,SERVER_BASE),'Model reference manifest must be under UIT tmp')
    rows = visible_rows(data)
    root.mkdir(parents=True)
    (root / 'evidence').mkdir()
    snapshot(repo, root / 'src')
    # Copy the complete standalone harness; no package code is edited.
    shutil.copytree(Path(__file__).resolve().parent, root / 'harness',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    activate(root / 'src')
    from lifemate.configuration import ModelSettings, inspect_snapshot, load_config
    from lifemate.provenance import code_identity, package_versions
    from lifemate.skills import SkillRetrievalInputError, load_library, retrieve
    prepared, catalog, specs = base_inputs(data, rows)
    library = load_library()
    require(library.catalog_fingerprints['train'].canonical_sha256 == fingerprint(catalog),
            'Train catalog does not match pinned Library')
    settings = ModelSettings('qwen3', model, 'cuda:0', 'float16', False, 'qwen-native-v1', 16384, 512)
    model_metadata = None if skip_model else inspect_snapshot(settings, planner=True)
    if model_metadata:
        require(model_metadata['parameter_count'] is not None and model_metadata['parameter_count'] < 5_000_000_000,
                'Need checked <5B parameter safetensors snapshot')
    reference_record=None
    if model_reference is not None:
        model_reference=Path(model_reference).resolve()
        files={Path(p).relative_to(model).as_posix():h for p,h in model_files(model).items()}
        validate_model_reference(read_json(model_reference),files,model_metadata,code_identity(),
                                 {'sha256':library.sha256,'version':library.version})
        reference_record={'path':str(model_reference),'sha256':digest(model_reference),'verified':True}
    candidates = {}; retrieval_fallbacks = []
    for sid, p in prepared.items():
        try:
            candidates[sid] = [b.branch_id for b in retrieve(p['request'], p['history'],
                              [t['name'] for t in p['available_tools']], library=library)]
        except SkillRetrievalInputError:
            candidates[sid] = []
            retrieval_fallbacks.append(sid)
    smoke = sorted(prepared, key=lambda sid: fingerprint([seed, sid]))[:min(16, len(rows))]
    matched = [i for i in prepared if candidates[i]]
    require(bool(matched), 'No eligible Train retrieval candidate: cannot validate ON smoke exposure')
    if not any(candidates[i] for i in smoke):
        smoke[-1] = sorted(matched, key=lambda i: fingerprint([seed, i]))[0]
    ids = [r['id'] for r in rows]
    smoke = [sid for sid in ids if sid in set(smoke)]
    blocks, groups = grouped_blocks(rows, seed, block_size)
    record = {'schema_version': 1, 'source_sha': SOURCE_SHA, 'root': str(root),
              'profile': 'local_cpu_only' if local else 'uit', 'model_checked': not skip_model,
              'data_root': str(data), 'runtime_dir': str(data / 'train/zaic_tools'), 'model': str(model),
              'model_metadata': model_metadata, 'seed': seed, 'library': {'sha256': library.sha256, 'version': library.version},
              'model_reference':reference_record,
              'code_identity': code_identity(), 'packages': package_versions(),
              'catalog_canonical_sha256': fingerprint(catalog),
              'scorer_policy': 'maximum_bipartite_regex_NFC_v1_official_compatibility_unverified',
              'training_holdout_provenance': 'unavailable; Train diagnostic, not unseen validation',
              'groups': groups, 'grouping_rule': 'declared conversation/dialogue/group id else exact nonempty history else id',
              'phases': {}, 'protocol_files': {}}
    for phase, sets in [('smoke', [smoke]), ('main', blocks)]:
        runs = []
        for index, selected in enumerate(sets):
            key = 'block-' + f'{index:03d}'
            selection = f'inputs/{phase}/{key}.txt'
            write_text(root / selection, '\n'.join(selected) + '\n')
            for arm in (('control', 'treatment') if index % 2 == 0 else ('treatment', 'control')):
                cfg = {'schema_version': 1, 'planner': {'backend': 'qwen3', 'protocol': 'qwen-native-v1',
                    'model_path': str(model), 'device': 'cuda:0', 'dtype': 'float16', 'offload': False,
                    'context_tokens': 16384, 'max_new_tokens': 512},
                    'execution': {'timeout_seconds': 30, 'soft_timeout_seconds': 28, 'reuse_kv_cache': True,
                    'enable_skill_retrieval': arm == 'treatment', 'max_steps': 16,
                    'startup_timeout_seconds': 900, 'recovery_attempts': 1, 'seed': seed},
                    'data': {'root': str(data), 'runtime_dir': str(data / 'train/zaic_tools'), 'split': 'train',
                    'mode': 'transcript', 'sample_ids_file': str(root / selection)},
                    'output': {'root': str(root / f'runs/{phase}/{key}/{arm}'), 'debug_payloads': True}}
                path = f'configs/{phase}/{key}/{arm}.toml'
                write_text(root / path, toml_record(cfg))
                load_config(root / path)  # No preflight/model loading/environment.
                runs.append({'block': key, 'arm': arm, 'ids': selected, 'config': path,
                             'output': f'runs/{phase}/{key}/{arm}'})
        record['phases'][phase] = {'ids': smoke if phase == 'smoke' else ids, 'runs': runs}
    write_jsonl(root / 'inputs/base_inputs.jsonl', [{'id': sid, 'digest': fingerprint(p), 'prepared': p}
                                                  for sid, p in prepared.items()])
    write_json(root / 'inputs/cohorts.json', {'ids': ids, 'smoke': smoke,
               'gold_nonempty': sum(bool(r['label']['tool_calls']) for r in rows),
               'gold_empty': sum(not r['label']['tool_calls'] for r in rows),
               'pre_fit_retrieval_candidates': candidates, 'unsupported_input_fallbacks': retrieval_fallbacks})
    protected = {str(data / 'train/train.jsonl'): digest(data / 'train/train.jsonl'),
                 str(data / 'train/train_tools_catalog.json'): digest(data / 'train/train_tools_catalog.json')}
    runtime = data / 'train/zaic_tools'
    require((runtime / '__init__.py').is_file(), 'Missing Train runtime')
    protected.update({str(p): digest(p) for p in runtime.rglob('*.py')})
    protected.update(model_files(model))
    protected.update({str(Path(p).resolve()): digest(p) for p in protect})
    if model_reference is not None:
        protected[str(model_reference)]=digest(model_reference)
    if not local:
        require(all(inside(p, SERVER_BASE) for p in protected), 'Material input resolves outside UIT tmp')
    protocol_files = [p for folder in ('inputs', 'configs') for p in (root / folder).rglob('*') if p.is_file()]
    record['protocol_files'] = {p.relative_to(root).as_posix(): digest(p) for p in protocol_files}
    write_json(root / 'evidence/inputs-before.json', {'files': protected, 'src': code_files(root / 'src'),
                                                    'harness': code_files(root / 'harness'),
                                                    'model':model_files(model), 'runtime':code_files(runtime,('.py',))})
    record['protocol_files']['evidence/inputs-before.json'] = digest(root / 'evidence/inputs-before.json')
    write_json(root / 'experiment.json', record)
    write_text(root / 'experiment.sha256', digest(root / 'experiment.json') + '\n')
    return {'status': 'prepared', 'root': str(root), 'main_samples': len(rows), 'smoke_samples': len(smoke),
            'model_checked': not skip_model, 'gpu_execution_allowed': not local}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare'); add_experiment(p)
    p.add_argument('--source-repo', type=Path, required=True)
    p.add_argument('--data-root', type=Path, required=True)
    p.add_argument('--planner-model', type=Path, required=True)
    p.add_argument('--model-reference-manifest', type=Path,
                   help='Original 011 run manifest; mandatory for UIT, compare model/tokenizer/code/Library hashes')
    p.add_argument('--seed', type=int, default=42); p.add_argument('--block-size', type=int, default=256)
    p.add_argument('--local', action='store_true', help='CPU-only profile; paired GPU runner will refuse it')
    p.add_argument('--skip-model-check', action='store_true')
    p.add_argument('--protect-file', action='append', default=[], type=Path)
    p = sub.add_parser('verify'); add_experiment(p)
    args = parser.parse_args()
    if args.command == 'prepare':
        result = prepare(args.experiment, args.source_repo, args.data_root, args.planner_model,
                         seed=args.seed, block_size=args.block_size, local=args.local,
                         skip_model=args.skip_model_check, protect=args.protect_file,
                         model_reference=args.model_reference_manifest)
    else:
        from _common import verify_integrity
        record = load_experiment(args.experiment)
        result = verify_integrity(args.experiment, record, save=True)
    print(dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(command_main(main))
