"""Train-only reference replay through public ToolEnv APIs; never model inference."""
from __future__ import annotations

import argparse
import copy
from pathlib import Path
import re

from _common import (add_experiment, child, command_main, config_for, digest, dumps, equal,
                     fingerprint, journal_for, load_experiment, phase_ids, phase_runs, require,
                     train_id, visible_rows, write_json, write_jsonl)


def replay_reference(row, factory, data_root):
    sid = train_id(row['id'])
    env = factory('train', sid, Path(data_root))
    initial = env.get_state_hash()
    require(isinstance(initial,str) and re.fullmatch('[0-9a-f]{64}',initial), 'Invalid initial ToolEnv hash')
    gold = copy.deepcopy(row['label']['tool_calls'])
    results = [env.call(c['name'], copy.deepcopy(c['arguments'])) for c in gold]
    log = env.get_tool_calls()
    final = env.get_state_hash()
    require(isinstance(final,str) and re.fullmatch('[0-9a-f]{64}',final), 'Invalid final ToolEnv hash')
    consistent = equal(log, gold) and equal(results, row['label']['tool_results'])
    return {'id': sid, 'initial_state_hash': initial, 'gold_reference_state_hash': final,
            'status': 'valid' if consistent else 'reference_inconsistent',
            'calls_match': equal(log, gold), 'results_match': equal(results, row['label']['tool_results']),
            'gold_call_count': len(gold), 'calls_digest': fingerprint(gold),
            'results': results, 'authoritative_calls': log}


def oracle(root, phase, cpu_check=False, factory=None):
    root = Path(root).resolve()
    record = load_experiment(root)
    ids = phase_ids(record, phase)
    # A CPU check is explicitly separate and never becomes a scoring oracle.
    destination = root / 'gold' / ('cpu-check-' + phase if cpu_check else phase)
    require(not destination.exists(), 'Oracle output exists; no replay/resume')
    if not cpu_check:
        for run in phase_runs(record, phase):
            state = journal_for(root, run)
            require(all(sid in state.by_sample and state.by_sample[sid] in state.terminal for sid in run['ids']),
                    'Oracle evaluation requires completed terminal accounting in both arms')
    rows = {r['id']: r for r in visible_rows(record['data_root'])}
    injected = factory is not None
    if factory is None:
        from lifemate.configuration import run_config
        from lifemate.dataset import preflight
        from lifemate.runtime import load_runtime
        cfg = run_config(config_for(root, phase_runs(record, phase)[0]))
        from dataclasses import replace
        cfg = replace(cfg, selected_ids=tuple(ids), select_all=False)
        dataset = preflight(cfg)
        factory = load_runtime(cfg, dataset)
    destination.mkdir(parents=True)
    records, errors = [], []
    for sid in ids:
        try:
            value = replay_reference(rows[sid], factory, record['data_root'])
        except Exception as exc:
            # A failed environment is never reopened. Keep all expected IDs.
            value = {'id': sid, 'status': 'oracle_error', 'error_type': type(exc).__name__,
                     'error': str(exc)[:500], 'gold_reference_state_hash': None,
                     'gold_call_count': len(rows[sid]['label']['tool_calls'])}
        if value['status'] != 'valid':
            errors.append(sid)
        records.append(value)
    load_experiment(root)  # Do not publish valid references if visible inputs/code changed during replay.
    write_jsonl(destination / 'reference_results.jsonl', records)
    hashes = [{k: v for k, v in r.items() if k not in ('results', 'authoritative_calls')} for r in records]
    write_jsonl(destination / 'reference_hashes.jsonl', hashes)
    audit = {'schema_version': 1, 'phase': phase, 'cpu_check_only': cpu_check,
             'experiment_sha256': digest(root / 'experiment.json'), 'source_sha': record['source_sha'],
             'catalog_sha256': digest(Path(record['data_root']) / 'train/train_tools_catalog.json'),
             'dataset_sha256': digest(Path(record['data_root']) / 'train/train.jsonl'),
             'reference_results_sha256': digest(destination / 'reference_results.jsonl'),
             'reference_hashes_sha256': digest(destination / 'reference_hashes.jsonl'),
             'expected': len(ids), 'valid': len(ids) - len(errors), 'errors': errors,
             'reference_kind': 'local_gold_toolenv_replay_not_organizer_hash',
             'factory': 'injected_test_double' if injected else 'pinned_Train_runtime'}
    write_json(destination / 'reference_audit.json', audit)
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__); add_experiment(parser)
    parser.add_argument('--phase', choices=('smoke', 'main'), required=True)
    parser.add_argument('--cpu-check', action='store_true', help='No inference required; output cannot be used to score an arm')
    args = parser.parse_args()
    result = oracle(args.experiment, args.phase, args.cpu_check)
    print(dumps(result))
    return 0 if not result['errors'] else 1


if __name__ == '__main__':
    raise SystemExit(command_main(main))
