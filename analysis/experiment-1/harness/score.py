"""Read-only paired scoring. No model loading, prediction replay or ToolEnv creation."""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import csv
import importlib.util
import math
from pathlib import Path
import re
import statistics
import unicodedata

from _common import (ARMS, HarnessError, add_experiment, base_inputs, child, command_main,
                     config_for, digest, dumps, equal, finite_time, fingerprint, journal_for,
                     load_experiment, model_files, phase_ids, phase_runs, read_json,
                     read_jsonl, require, visible_rows, write_json, write_jsonl, write_text)


def token_f1(left, right):
    if not isinstance(left, str) or not isinstance(right, str):
        return 0.0
    a, b = [Counter(re.findall(r'\w+', unicodedata.normalize('NFC', s).lower())) for s in (left, right)]
    na, nb = sum(a.values()), sum(b.values())
    if not na or not nb:
        return float(na == nb)
    return 2 * sum((a & b).values()) / (na + nb)


def compatible_call(predicted, gold, specs):
    if predicted.get('name') != gold.get('name') or predicted.get('name') not in specs:
        return False
    a, b = predicted.get('arguments'), gold.get('arguments')
    if not isinstance(a, dict) or not isinstance(b, dict) or set(a) != set(b):
        return False
    properties = specs[predicted['name']]['parameters']['properties']
    return all(token_f1(a[k], b[k]) > 0.6 if properties.get(k, {}).get('x-match') == 'fuzzy'
               else equal(a[k], b[k]) for k in b)


def match_calls(predicted, gold, specs, invalid=()):
    """Maximum cardinality, plus greedy diagnostic under the same typed edge rule."""
    invalid = set(invalid)
    edges = [[j for j, g in enumerate(gold) if compatible_call(p, g, specs)] if i not in invalid else []
             for i, p in enumerate(predicted)]
    owner = {}
    def augment(i, seen):
        for j in edges[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in owner or augment(owner[j], seen):
                owner[j] = i
                return True
        return False
    for i in range(len(predicted)):
        augment(i, set())
    used = set()
    for choices in edges:
        free = next((j for j in choices if j not in used), None)
        if free is not None:
            used.add(free)
    m, mg = len(owner), len(used)
    n, g = len(predicted), len(gold)
    return {'matched': m, 'unmatched': n - m, 'gold_count': g, 'predicted_count': n,
            'precision': m / n if n else 0.0, 'recall': m / g if g else None,
            'call_f1': 2*m/(n+g) if g else None,
            'greedy_matched': mg, 'greedy_f1': 2*mg/(n+g) if g else None,
            'matching_ambiguous': m != mg,
            'matched_pairs': sorted([[i, j] for j, i in owner.items()]), 'schema_rejected_count': len(invalid)}


def score_sample(gold, prediction, accepted, reference, specs, invalid=()):
    oracle_valid = reference is not None and reference.get('status') == 'valid'
    valid = accepted and isinstance(prediction, dict)
    p = prediction['tool_calls'] if valid else None
    hash_match = (prediction['state_hash'] == reference['gold_reference_state_hash']) if valid and oracle_valid else None
    match = match_calls(p, gold, specs, invalid) if valid else None
    if not gold:
        score = float(not p) if valid else 0.0
    elif not oracle_valid:
        score = None
    elif not valid:
        score = 0.0
    else:
        score = match['call_f1'] if hash_match else 0.0
    return {'oracle_status': reference.get('status') if reference else 'oracle_missing',
            'inference_status': 'accepted' if valid else 'missing_or_failed_prediction',
            'hash_match': hash_match, 'hash_status': ('match' if hash_match else 'mismatch')
                if hash_match is not None else 'unknown',
            'score': score, 'call_f1_operational': match['call_f1'] if match else (0.0 if gold else None),
            'match': match, 'call_count': len(p) if p is not None else None}


def transition(a, b):
    if a is None and b is None:
        return 'unknown_both'
    if a is None:
        return 'unknown_control'
    if b is None:
        return 'unknown_treatment'
    return { (True, True): 'n11', (True, False): 'n10',
             (False, True): 'n01', (False, False): 'n00'}[(a, b)]


def quantile(values, q):
    if not values:
        return None
    s = sorted(values); x = (len(s) - 1) * q; low = math.floor(x); high = math.ceil(x)
    return s[low] + (s[high] - s[low]) * (x - low)


def timing_summary(values, signed=False):
    valid = [v for v in values if type(v) in (int,float) and math.isfinite(v) and (signed or v >= 0)]
    return {'known': len(valid), 'unknown': len(values) - len(valid),
            'mean': statistics.mean(valid) if valid else None,
            'p50': quantile(valid, .5), 'p95': quantile(valid, .95), 'max': max(valid) if valid else None}


def load_validator(path):
    spec = importlib.util.spec_from_file_location('_exp1_train_validator_' + digest(path)[:12], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.schema_error


def audit_manifest(root, record, run, manifest, state):
    cfg = config_for(root, run)
    expected_ids = run['ids']
    require(equal(manifest['effective_config'], cfg.record()), 'Manifest/config mismatch')
    identity = manifest['identity']
    require(state.header['run_sha256'] == manifest['run_sha256'], 'Journal/manifest run identity mismatch')
    require(state.header['config_sha256'] == identity['config_sha256'] == cfg.fingerprint(), 'Config digest mismatch')
    require(equal(state.header['selected_ids'], expected_ids) and equal(identity['dataset']['selected_ids'], expected_ids),
            'Run IDs/order differ from frozen selection')
    require(set(state.by_sample) <= set(expected_ids), 'Unexpected journal sample IDs')
    require(equal(identity['code'], record['code_identity']), 'Inference source differs from 047879e')
    require(equal(identity['packages'], record['packages']), 'Runtime packages changed')
    require(identity['asr'] is None and identity['protocol'] == 'qwen-native-v1', 'Wrong input protocol/ASR')
    require(identity['dataset']['dataset_sha256'] == digest(Path(record['data_root']) / 'train/train.jsonl'), 'Dataset changed')
    require(identity['dataset']['catalog_sha256'] == digest(Path(record['data_root']) / 'train/train_tools_catalog.json'), 'Catalog changed')
    require(identity['dataset']['selection_sha256'] == digest(cfg.sample_ids_file), 'Selection digest changed')
    runtime = Path(record['runtime_dir'])
    require(identity['runtime_source_sha256'] == {p.relative_to(runtime).as_posix(): digest(p) for p in runtime.rglob('*.py')},
            'Runtime source mismatch')
    expected_weights = {Path(p).relative_to(record['model']).as_posix(): h for p, h in model_files(record['model']).items()}
    require(identity['planner']['files'] == expected_weights, 'Planner weight/tokenizer identity mismatch')
    if run['arm'] == 'treatment':
        require(identity.get('skill_library') == record['library'], 'Wrong ON Library')
        require(identity['dataset']['catalog_canonical_sha256'] == record['catalog_canonical_sha256'], 'Wrong canonical catalog')
    else:
        require(identity.get('skill_library') is None, 'OFF loaded skill identity')
    require(cfg.reuse_kv_cache and cfg.mode == 'transcript' and cfg.split == 'train' and cfg.debug_payloads,
            'Pair protocol flags changed')
    require(cfg.enable_skill_retrieval == (run['arm'] == 'treatment'), 'Wrong treatment flag')
    publication = manifest['publication']
    name = 'predictions.jsonl' if publication['complete'] else 'predictions.partial.jsonl'
    published = read_jsonl(child(root, run['output']) / name)
    expected = [state.terminal[state.by_sample[sid]]['prediction'] for sid in expected_ids
                if sid in state.by_sample and state.by_sample[sid] in state.terminal
                and state.terminal[state.by_sample[sid]]['type']=='accept']
    require(equal(published,expected), 'Published predictions differ from accepted journal')
    require(Path(publication['path']).resolve()==child(root,run['output'])/name, 'Publication path differs')


def audit_trace(path, sid, terminal, base, arm, known_branches):
    from lifemate.artifacts import sanitize
    events = read_jsonl(path)
    require([e['sequence'] for e in events] == list(range(1, len(events)+1)), 'Broken trace sequence')
    require(all(e['sample_id'] == sid and e['run_id'] == terminal['attempt_id'] for e in events), 'Trace attempt mismatch')
    prepared = [e for e in events if e['kind'] == 'request_prepared']
    require(len(prepared) == 1, 'Request trace missing/duplicated')
    require(equal(prepared[0].get('payload'), sanitize({'request': base['request'], 'history': base['history']})),
            'Actual request/history differs from frozen input or is truncated')
    require(prepared[0]['available_tools'] == [t['name'] for t in base['available_tools']], 'Available tools changed')
    worker = terminal['metrics']['worker']; metrics = worker['metrics']
    decisions = metrics['decisions']
    require(all(d.get('kv_cache_enabled') is True for d in decisions), 'KV not enabled in actual decision')
    require(equal([e['canonical_action'] for e in events if e['kind'] == 'planner_decision'],
                  [d['canonical_action'] for d in decisions]), 'Trace/metadata decisions mismatch')
    require(worker['stop_reason'] == events[-1].get('stop_reason') and events[-1]['kind'] == 'sample_finished',
            'Trace stop reason mismatch')
    calls = terminal['prediction']['tool_calls']
    action_calls = [{'name': d['canonical_action']['name'], 'arguments': d['canonical_action']['arguments']}
                    for d in decisions if d['canonical_action']['action'] == 'call']
    require(equal(calls, action_calls), 'Authoritative calls differ from decisions')
    results = [e for e in events if e['kind'] == 'tool_call_result']
    starts = [e for e in events if e['kind'] == 'tool_call_started']
    require(len(results) == len(calls) == len(starts), 'Missing tool result/start')
    require([e['name'] for e in results] == [c['name'] for c in calls], 'Wrong result tool names')
    require(equal(events[-1].get('payload'), sanitize(terminal['prediction'])), 'Final trace differs from accepted prediction')
    for start, result, call in zip(starts, results, calls):
        require(start['step'] == result['step'] and start['name'] == call['name']
                and equal(start.get('payload'), sanitize(call['arguments'])), 'Wrong call/result binding')
    retrieval = metrics.get('skill_retrieval')
    if arm == 'control':
        require(retrieval is None, 'OFF unexpectedly retrieved skills')
        ids = []
    else:
        require(isinstance(retrieval, dict) and retrieval.get('enabled') is True, 'ON retrieval metric missing')
        ids = retrieval['selected_branch_ids']
        require(len(ids) == len(set(ids)) and all(known_branches.get(b) == 'E' for b in ids), 'Invalid/gated branch IDs')
        rt = [e for e in events if e['kind'] == 'skill_retrieval']
        require(len(rt) == 1 and rt[0]['selected_branch_ids'] == ids, 'Retrieval trace mismatch')
    payloads = [e for e in events if e['kind'] in ('request_prepared', 'tool_call_started', 'tool_call_result', 'sample_finished')]
    complete = all(e.get('payload_omitted') is False and not e.get('payload_truncated')
                   and not e.get('payload_redacted') and 'payload' in e for e in payloads)
    return {'valid': True, 'payload_complete': complete, 'selected_branch_ids': ids,
            'trace': str(path), 'decision_count': len(decisions), 'result_count': len(results)}


def read_run(root, record, run, bases, branches):
    output = child(root, run['output'])
    errors, samples = [], {}
    manifest = None
    try:
        manifest = read_json(output / 'manifest.json')
        state = journal_for(root, run)
        audit_manifest(root, record, run, manifest, state)
    except Exception as exc:
        return {}, None, [run['output'] + ': ' + str(exc)]
    for sid in run['ids']:
        terminal = state.terminal.get(state.by_sample.get(sid))
        value = {'status': 'not_attempted' if sid not in state.by_sample else 'uncertain',
                 'accepted': False, 'prediction': None, 'attempt_seconds': None, 'stop_reason': None,
                 'attempt_id': state.by_sample.get(sid), 'trace_audit': None, 'selected_branch_ids': [], 'decisions': []}
        if terminal:
            value.update(status=terminal['status'], accepted=terminal['type'] == 'accept',
                         prediction=terminal.get('prediction'), attempt_id=terminal['attempt_id'],
                         attempt_seconds=finite_time(terminal.get('metrics', {}).get('attempt_seconds')),
                         stop_reason=terminal.get('metrics', {}).get('worker', {}).get('stop_reason'))
            if value['accepted']:
                try:
                    require(value['attempt_seconds'] is not None and value['attempt_seconds'] < 30,
                            'Accepted timing invalid/outside hard budget')
                    path = child(output, 'staging/' + terminal['attempt_id'] + '/trace.jsonl')
                    value['trace_audit'] = audit_trace(path, sid, terminal, bases[sid], run['arm'], branches)
                    value['selected_branch_ids'] = value['trace_audit']['selected_branch_ids']
                    value['decisions'] = terminal['metrics']['worker']['metrics']['decisions']
                    if not value['trace_audit']['payload_complete']:
                        errors.append(sid + ': redacted/omitted/truncated payload')
                except Exception as exc:
                    errors.append(sid + ': trace/protocol error: ' + str(exc))
                    if value['attempt_seconds'] is None or value['attempt_seconds'] >= 30:
                        # Never award score to a claimed acceptance outside the hard deadline.
                        value.update(accepted=False,prediction=None,status='invalid_accepted_timing')
        samples[sid] = value
    if set(state.by_sample) != set(run['ids']) or state.unresolved():
        errors.append(run['output'] + ': incomplete terminal accounting')
    return samples, manifest, errors


def aggregate(samples):
    summary = {'samples': len(samples), 'arms': {}, 'transitions': {}}
    nonempty = [r for r in samples if r['gold_count'] > 0]
    for arm in ARMS:
        values = [r[arm] for r in samples]
        nv = [r[arm] for r in nonempty]
        scores = [r['score'] for r in values]
        matches = [v['match'] for v in nv if v['match'] is not None]
        known_calls = [v['call_count'] for v in values if v['call_count'] is not None]
        total_m = sum(m['matched'] for m in matches)
        denominator = sum(m['gold_count']+m['predicted_count'] for m in matches)
        summary['arms'][arm] = {'gold_nonempty_denominator': len(nv),
            'verified_hash_success_rate': sum(v['hash_match'] is True for v in nv)/len(nv) if nv and all(v['oracle_status']=='valid' for v in nv) else None,
            'hash_matches': sum(v['hash_match'] is True for v in nv), 'hash_unknown': sum(v['hash_match'] is None for v in nv),
            'observed_hash_match_rate': (sum(v['hash_match'] is True for v in nv)/sum(v['hash_match'] is not None for v in nv))
                if any(v['hash_match'] is not None for v in nv) else None,
            'hash_mismatches_observed': sum(v['hash_match'] is False for v in nv),
            'oracle_invalid': sum(v['oracle_status'] != 'valid' for v in values),
            'local_macro_score_100': 100*sum(scores)/len(values) if values and all(s is not None for s in scores) else None,
            'macro_call_f1_nonempty_operational': statistics.mean(v['call_f1_operational'] for v in nv) if nv else None,
            'micro_call_f1_observed': 2*total_m/denominator if denominator else None,
            'micro_observed_samples': len(matches), 'inference_failures_or_missing': sum(not v['accepted'] for v in values),
            'statuses': dict(Counter(v['status'] for v in values)),
            'soft_deadline_rate': sum(v['stop_reason']=='soft_deadline' for v in values)/len(values) if values else None,
            'soft_deadline_count': sum(v['stop_reason']=='soft_deadline' for v in values),
            'latency_seconds': timing_summary([v['attempt_seconds'] for v in values]),
            'known_total_tool_calls': sum(known_calls), 'tool_calls_unknown': len(values)-len(known_calls),
            'mean_calls_observed': statistics.mean(known_calls) if known_calls else None,
            'empty_gold_accuracy': statistics.mean(v['score'] for r,v in zip(samples,values) if r['gold_count']==0) if len(samples)>len(nv) else None,
            'ambiguous_matching_samples': sum(v['match'] is not None and v['match']['matching_ambiguous'] for v in values)}
    summary['transitions'] = {name: [r['id'] for r in nonempty if r['transition']==name]
                               for name in ('n11','n10','n01','n00','unknown_control','unknown_treatment','unknown_both')}
    a, b = [summary['arms'][arm]['local_macro_score_100'] for arm in ARMS]
    summary['delta_local_score_100_on_minus_off'] = b-a if a is not None and b is not None else None
    ha,hb=[summary['arms'][arm]['verified_hash_success_rate'] for arm in ARMS]
    summary['delta_verified_hash_success_rate']=hb-ha if ha is not None and hb is not None else None
    summary['transition_counts']={k:len(v) for k,v in summary['transitions'].items()}
    summary['paired_latency_delta_seconds'] = timing_summary([
        r['treatment']['attempt_seconds']-r['control']['attempt_seconds'] for r in samples
        if r['treatment']['attempt_seconds'] is not None and r['control']['attempt_seconds'] is not None], signed=True)
    normal=[r for r in samples if all(r[a]['status'] in ('completed','needs_info') and r[a]['accepted']
            and r[a]['attempt_seconds'] is not None for a in ARMS)]
    summary['paired_normal_terminal_latency_delta_seconds']=timing_summary([
        r['treatment']['attempt_seconds']-r['control']['attempt_seconds'] for r in normal],signed=True)
    summary['paired_call_count_delta']=timing_summary([r['treatment']['call_count']-r['control']['call_count']
        for r in samples if all(r[a]['call_count'] is not None for a in ARMS)],signed=True)
    return summary


def write_csv(path, rows):
    if not rows:
        write_text(path, 'id\n'); return
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader()
        writer.writerows({k: dumps(v) if isinstance(v, (dict,list)) else v for k,v in r.items()} for r in rows)


def score_experiment(root, phase):
    root = Path(root).resolve(); record = load_experiment(root)
    destination = root / 'reports' / phase
    require(not destination.exists(), 'Report exists; refusing overwrite')
    rows = {r['id']: r for r in visible_rows(record['data_root'])}
    bases = {r['id']: r['prepared'] for r in read_jsonl(root / 'inputs/base_inputs.jsonl')}
    from lifemate.dataset import validate_catalog
    specs = validate_catalog(read_json(Path(record['data_root']) / 'train/train_tools_catalog.json'))
    validator = load_validator(Path(record['runtime_dir']) / 'validate.py')
    branches = {b['branch_id']: b['evidence'] for b in read_json(root / 'src/python/src/lifemate/skill_library.json')['branches']}
    errors = []; refs = {}; ref_audit = None
    try:
        folder = root / 'gold' / phase
        ref_audit = read_json(folder / 'reference_audit.json')
        require(ref_audit['cpu_check_only'] is False and ref_audit['experiment_sha256']==digest(root/'experiment.json'), 'Wrong oracle identity/CPU check reference')
        require(ref_audit['factory'] == 'pinned_Train_runtime', 'Scoring requires real Train runtime oracle')
        require(ref_audit['source_sha']==record['source_sha'] and ref_audit['phase']==phase, 'Oracle source/phase differs')
        require(ref_audit['catalog_sha256']==digest(Path(record['data_root'])/'train/train_tools_catalog.json')
                and ref_audit['dataset_sha256']==digest(Path(record['data_root'])/'train/train.jsonl'), 'Oracle input identity differs')
        require(ref_audit['reference_hashes_sha256']==digest(folder/'reference_hashes.jsonl')
                and ref_audit['reference_results_sha256']==digest(folder/'reference_results.jsonl'), 'Oracle output digest mismatch')
        raw = read_jsonl(folder / 'reference_hashes.jsonl'); refs = {v['id']:v for v in raw}
        require(len(raw)==len(refs) and set(refs)==set(phase_ids(record, phase)), 'Oracle ID coverage mismatch')
        results_raw=read_jsonl(folder/'reference_results.jsonl');results={v['id']:v for v in results_raw}
        require(len(results_raw)==len(results) and set(results)==set(refs), 'Oracle result coverage mismatch')
        for sid, ref in refs.items():
            require(ref.get('calls_digest') == fingerprint(rows[sid]['label']['tool_calls']) or ref['status']=='oracle_error', 'Oracle calls changed')
            require(equal(ref,{k:v for k,v in results[sid].items() if k not in ('results','authoritative_calls')}),
                    'Oracle hash/result records disagree')
            if ref['status']=='valid':
                require(ref['results_match'] is True and ref['calls_match'] is True
                        and equal(results[sid]['results'],rows[sid]['label']['tool_results'])
                        and equal(results[sid]['authoritative_calls'],rows[sid]['label']['tool_calls']),
                        'Valid oracle does not match supplied Gold results/calls')
    except Exception as exc:
        errors.append('Oracle error: ' + str(exc)); refs = {}
    try:
        index=read_json(root/'evidence'/f'{phase}-run-index.json')
        require(index['finished'] is True and index['experiment_sha256']==digest(root/'experiment.json'), 'Driver identity differs')
        if index['returncode'] or index['failure']:
            errors.append('Paired driver failed/incomplete; see run index')
    except Exception as exc:
        errors.append('Paired driver provenance unavailable: '+str(exc))
    arms = {arm:{} for arm in ARMS}; manifests = {}
    for run in phase_runs(record, phase):
        values, manifest, issues = read_run(root, record, run, bases, branches)
        require(not (set(values) & set(arms[run['arm']])), 'Duplicate sample across blocks')
        arms[run['arm']].update(values); errors.extend(issues)
        manifests[(run['block'],run['arm'])] = manifest
    for block in {r['block'] for r in phase_runs(record,phase)}:
        a,b = [manifests.get((block,arm)) for arm in ARMS]
        if not a or not b:
            continue
        try:
            for key in ('planner','asr','code','packages','runtime_source_sha256'):
                require(equal(a['identity'][key],b['identity'][key]), 'Paired identity differs: '+key)
            for key in ('visible_devices','nvidia_smi'):
                require(equal(a['host'].get(key),b['host'].get(key)) and a['host'].get(key) is not None, 'GPU identity unavailable/different')
            ast,bst=[m['timings']['startup'][0] for m in (a,b)]
            require(equal(ast['hardware'],bst['hardware']) and equal(ast['models']['planner'],bst['models']['planner']), 'Startup hardware/model metadata differ')
        except Exception as exc:
            errors.append(block+': '+str(exc))
    output = []
    for sid in phase_ids(record,phase):
        row = rows[sid]; gold = row['label']['tool_calls']; reference = refs.get(sid)
        item = {'id':sid,'gold_count':len(gold),'request':bases[sid]['request'],
                'base_input_digest':fingerprint(bases[sid]), 'gold_hash':reference.get('gold_reference_state_hash') if reference else None}
        allowed = {t['name'] for t in bases[sid]['available_tools']}
        for arm in ARMS:
            run = arms[arm].get(sid, {'accepted':False,'prediction':None,'status':'not_attempted',
                  'stop_reason':None,'attempt_seconds':None,'selected_branch_ids':[],'decisions':[],'attempt_id':None,'trace_audit':None})
            pred = run['prediction']
            invalid = [i for i,c in enumerate(pred['tool_calls']) if validator(c['name'],c['arguments'],specs,allowed) is not None] if pred else []
            item[arm] = run | score_sample(gold,pred,run['accepted'],reference,specs,invalid)
        item['transition'] = transition(item['control']['hash_match'],item['treatment']['hash_match']) if gold else 'gold_empty'
        aa,bb=[item[a]['decisions'] for a in ARMS]
        acts=[[d['canonical_action'] for d in ds] for ds in (aa,bb)]
        item['first_divergence'] = next((i+1 for i in range(max(map(len,acts)))
            if i>=len(acts[0]) or i>=len(acts[1]) or not equal(acts[0][i],acts[1][i])),None)
        output.append(item)
    summary = aggregate(output)
    if any(v.get('status')!='valid' for v in refs.values()) or not refs:
        errors.append('One or more Gold references unavailable/inconsistent')
    if any(not r[a]['accepted'] for r in output for a in ARMS):
        errors.append('Inference failure/missing prediction: fixed denominator retained')
    exposure = Counter(b for r in output for b in r['treatment']['selected_branch_ids'])
    if phase=='smoke' and not exposure:
        errors.append('Smoke has no actual retrieved branch exposure')
    summary.update(phase=phase, source_sha=record['source_sha'], evidence_valid=not errors,
                   errors=errors, official_scorer_compatibility_verified=False, policy=record['scorer_policy'],
                   generalization='Train diagnostic; held-out provenance unavailable',
                   experiment_sha256=digest(root/'experiment.json'),execution_profile=record['profile'])
    destination.mkdir(parents=True)
    write_json(destination/'summary.json',summary)
    write_jsonl(destination/'per_sample.jsonl',output)
    flat=[]
    for r in output:
        f={k:v for k,v in r.items() if k not in ARMS}
        for arm in ARMS:
            for k,v in r[arm].items():
                f[arm+'_'+k]=v
        flat.append(f)
    write_csv(destination/'per_sample.csv',flat)
    write_csv(destination/'hash_transitions.csv',[{'id':r['id'],'transition':r['transition'],
              'control_match':r['control']['hash_match'],'treatment_match':r['treatment']['hash_match']}
              for r in output if r['gold_count']])
    write_csv(destination/'branch_exposure.csv',[{'branch_id':b,'selected_samples':n,
              'hash_regressions':sum(b in r['treatment']['selected_branch_ids'] and r['transition']=='n10' for r in output),
              'hash_recoveries':sum(b in r['treatment']['selected_branch_ids'] and r['transition']=='n01' for r in output),
              'interpretation':'association_only'} for b,n in exposure.most_common()])
    write_json(destination/'trace_audit.json',{r['id']:{a:r[a]['trace_audit'] for a in ARMS} for r in output})
    lines=['# Experiment 1 '+phase, '', 'Local benchmark-formula score; official scorer compatibility unverified.',
           '', 'Evidence valid: '+str(not errors), '', '| Metric | Control | Treatment |','| --- | ---: | ---: |']
    for key in ('verified_hash_success_rate','local_macro_score_100','macro_call_f1_nonempty_operational',
                'inference_failures_or_missing','soft_deadline_rate','known_total_tool_calls'):
        lines.append('| '+key+' | '+str(summary['arms']['control'][key])+' | '+str(summary['arms']['treatment'][key])+' |')
    lines += ['', 'Transitions: '+dumps({k:len(v) for k,v in summary['transitions'].items()}),
              '', 'Delta local score ON-OFF: '+str(summary['delta_local_score_100_on_minus_off']), '',
              'No deployment decision is made automatically. Train results do not establish unseen generalization.',
              '', '## Evidence issues', '', *['- '+str(e) for e in errors]]
    write_text(destination/'summary.md','\n'.join(lines)+'\n')
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__);add_experiment(p)
    p.add_argument('--phase',choices=('smoke','main'),required=True)
    a=p.parse_args();result=score_experiment(a.experiment,a.phase)
    print(dumps({'phase':a.phase,'evidence_valid':result['evidence_valid'],'errors':result['errors']}))
    return 0 if result['evidence_valid'] else 1


if __name__=='__main__':
    raise SystemExit(command_main(main))
