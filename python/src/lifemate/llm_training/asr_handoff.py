"""Explicit E4 import and real current/history ASR caches; never a gold-text fallback."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import sys
import time
import wave

from .asr_views import ASR_DECODING, ASR_HANDOFF, CACHE_SCHEMA, CacheASR, expected_turns, validate_export
from .config import CATALOG_SHA256, DATASET_SHA256, SEEDS, SPLIT_IDENTITY, content_hash, load_config
from .data import read_train
from .resources import packages, validate_lock
from .storage import (file_hash, new_directory, read_json, read_jsonl, source_provenance,
                      write_json, write_jsonl)


def partition_of(split):
    if split.get('identity') != SPLIT_IDENTITY or content_hash({k:v for k,v in split.items() if k!='identity'}) != SPLIT_IDENTITY:
        raise ValueError('Frozen split identity mismatch')
    return {'split_identity':split['identity'],
        'fit_ids':[s['id'] for s in split['samples'] if s['partition']=='train'],
        'validation_ids':[s['id'] for s in split['samples'] if s['partition']=='validation'],
        'sources':{s['id']:{'group':s['group']} for s in split['samples']}}


def request_rows(sources, split):
    """Project only source/turn/audio identities. Gold text/results are never requests."""
    records = {s.id:s.record for s in sources}
    requests = {'fit':[], 'validation':[]}
    for sample in split['samples']:
        source = records[sample['id']]
        manifest = {u['audio']:u for u in sample['utterances']}
        turns = expected_turns(source)
        if set(turns.values()) != set(manifest):
            raise ValueError('Frozen source/history/audio alignment differs')
        kind = 'fit' if sample['partition']=='train' else 'validation'
        for turn,audio in turns.items():
            row = manifest[audio]
            requests[kind].append({'source_id':sample['id'],'group_id':sample['group'],'partition':kind,
                'turn':turn,'audio':audio,'wav_sha256':row['wav_sha256'],'pcm_sha256':row['pcm_sha256']})
    return requests


def source_plan(config):
    """Validate original E4 evidence without loading tensors or inventing selection."""
    from ..asr_training.comparison_artifacts import suite_inputs, validate_primary
    from ..asr_training.relocation import resolve_path
    from ..asr_training.storage import identity, verify
    root = config.project_root
    suite = root/'.agent-work/asr-finetune/suite-01'
    metadata,validation,slots = suite_inputs(suite)
    export = config.require('asr_model_dir')
    run = export.parent.parent
    if not run.resolve().is_relative_to(suite.resolve()):
        raise ValueError('Select the original imported E4 export for this preparation')
    manifest = read_json(run/'manifest.json')
    if manifest.get('experiment')!='E4' or manifest.get('status')!='completed':
        raise ValueError('A completed original E4 run is required')
    _,_,_,evaluation_hashes = validate_primary(suite,metadata,validation,slots,run,manifest)
    checkpoint = resolve_path(manifest['best_checkpoint'],suite)
    verify(checkpoint)
    state = read_json(checkpoint/'state.json')
    if state['training']['step'] != manifest['best_step'] or state['binding']['suite'] != metadata['identity']:
        raise ValueError('E4 best checkpoint does not match its frozen training suite')
    verify(export)
    exported = read_json(export/'export-metadata.json')
    if (resolve_path(exported['checkpoint'],suite)!=checkpoint
            or resolve_path(manifest['export']['path'],suite)!=export
            or exported['revision']!=metadata['model']['provenance']['revision']
            or exported['logical_parameters']!=manifest['export']['parameters']):
        raise ValueError('E4 merged export/checkpoint/base binding mismatch')
    policy = root/'python/src/lifemate/asr_training/selection.py'
    saved = {k.replace('\\','/'):v for k,v in manifest['code']['files'].items()}
    if file_hash(policy)!=saved.get(policy.relative_to(root).as_posix()):
        raise ValueError('Original frozen ASR selection source is unavailable; cannot fabricate a policy')
    fit = read_jsonl(suite/'data/fit.jsonl')
    if identity(fit)!=manifest['fit_identity']:
        raise ValueError('Original ASR Fit membership changed')
    train = config.require('data_root')/'train'
    if file_hash(train/'train.jsonl')!=DATASET_SHA256 or file_hash(train/'train_tools_catalog.json')!=CATALOG_SHA256:
        raise ValueError('Visible Train/catalog hash mismatch')
    split = read_json(config.require('split_manifest'))
    partition = partition_of(split)
    trained = sorted({r['sample_id'] for r in fit})
    if (not set(trained)<=set(partition['fit_ids']) or set(trained)&set(partition['validation_ids'])
            or metadata['split_identity']!=split['identity']):
        raise ValueError('ASR training provenance is not Fit-only')
    requests = request_rows(read_train(train/'train.jsonl'),split)
    return {'export':export,'run':run,'checkpoint':checkpoint,'policy':policy,'metadata':metadata,
        'trained':trained,'partition':partition,'requests':requests,'evaluation_hashes':evaluation_hashes,
        'manifest':manifest,'files':read_json(export/'files.json')}


def import_export(plan, destination, operator):
    """Called only after an explicit provisional E4 selection by the operator."""
    if not operator.strip():
        raise ValueError('Explicit selecting operator is required')
    destination.mkdir()
    for name,expected in plan['files'].items():
        from ..jsonio import contained
        source = contained(plan['export'],name)
        target = destination/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,target)
        if file_hash(target)!=expected:
            raise ValueError('Derived ASR asset copy hash mismatch')
    policy = destination/'original-selection-policy.py'
    shutil.copy2(plan['policy'],policy)
    policy_hash = file_hash(policy)
    checkpoint_hash = file_hash(plan['checkpoint']/'files.json')
    evidence = {'schema':'lifemate-asr-selection-evidence-v1','status':'selected','experiment':'E4',
        'checkpoint_sha256':checkpoint_hash,'policy_sha256':policy_hash,
        'fit_membership_sha256':content_hash(plan['trained']),'export_files_sha256':content_hash(plan['files']),
        'operator':operator,'decision':'explicit_provisional_E4_for_LLM_development',
        'semantic_slot_acceptance':'unverified','deployment_acceptance':'unverified',
        'original_run_manifest_sha256':file_hash(plan['run']/'manifest.json'),
        'original_suite_identity':plan['metadata']['identity'],'original_evaluation_hashes':plan['evaluation_hashes']}
    write_json(destination/'selection-evidence.json',evidence)
    body = {'schema':ASR_HANDOFF,'base_model':'vinai/PhoWhisper-large',
        'base_revision':plan['metadata']['model']['provenance']['revision'],'selected_experiment':'E4',
        'checkpoint_sha256':checkpoint_hash,'processor_sha256':'',
        'selection':{'experiment':'E4','checkpoint_sha256':checkpoint_hash,
                     'policy_file':policy.name,'policy_sha256':policy_hash,'evidence_file':'selection-evidence.json',
                     'evidence_sha256':file_hash(destination/'selection-evidence.json')},
        'training_source_ids':plan['trained'],'split_identity':plan['partition']['split_identity'],
        'files':plan['files'],'logical_parameters':plan['manifest']['export']['parameters'],'decoding':ASR_DECODING}
    names = {'preprocessor_config.json','tokenizer_config.json','vocab.json','merges.txt','tokenizer.json',
             'special_tokens_map.json','added_tokens.json','normalizer.json'}
    body['processor_sha256'] = content_hash({n:h for n,h in plan['files'].items() if n in names})
    write_json(destination/'llm-handoff.json',body)
    return validate_export(destination,plan['partition'])


def cache_partition(config, requests, export, path, adapter, timeout, *, resume=False):
    """Append real predictions only. Interrupted prefixes can be resumed explicitly."""
    from ..jsonio import contained
    partial = path.with_suffix('.partial.jsonl')
    prior = read_jsonl(partial) if resume and partial.exists() else []
    if path.exists() or (partial.exists() and not resume):
        raise ValueError('Cache output exists; no implicit overwrite')
    if len(prior)>len(requests):
        raise ValueError('Partial cache is longer than its frozen request list')
    constants = {'export_identity':export['identity'],'processor_sha256':export['processor_sha256'],
                 'decoding_sha256':content_hash(export['decoding'])}
    for old,request in zip(prior,requests):
        if any(old.get(k)!=v for k,v in (request|constants).items()) or old.get('status')!='ok':
            raise ValueError('Partial cache has incompatible/failed rows; inspect it, do not silently retry')
    partial.parent.mkdir(parents=True,exist_ok=True)
    with partial.open('a' if resume else 'x',encoding='utf-8') as stream:
        for index,request in enumerate(requests[len(prior):],len(prior)+1):
            audio = contained(config.require('data_root')/'train',request['audio'])
            if file_hash(audio)!=request['wav_sha256']:
                raise ValueError('Audio changed before ASR')
            with wave.open(str(audio),'rb') as wav:
                pcm = hashlib.sha256(wav.readframes(wav.getnframes())).hexdigest()
            if pcm!=request['pcm_sha256']:
                raise ValueError('PCM changed before ASR')
            started = time.monotonic()
            try:
                transcript = adapter.transcribe(audio,timeout)
                if not isinstance(transcript,str) or not transcript.strip():
                    raise ValueError('Empty ASR output; no gold fallback')
                if file_hash(audio)!=request['wav_sha256']:
                    raise ValueError('Audio changed during ASR')
                row = request|constants|{'status':'ok','transcript':transcript,'elapsed':time.monotonic()-started}
            except Exception:
                row = request|constants|{'status':'failed','transcript':None,'elapsed':time.monotonic()-started}
                from ..jsonio import dumps
                stream.write(dumps(row)+'\n');stream.flush();os.fsync(stream.fileno())
                raise
            from ..jsonio import dumps
            stream.write(dumps(row)+'\n');stream.flush();os.fsync(stream.fileno())
            print(f"ASR cache {request['partition']}: {index}/{len(requests)} {request['source_id']} {request['turn']}",
                  file=sys.stderr,flush=True)
    kind = requests[0]['partition']
    manifest = {'schema':CACHE_SCHEMA,'partition':kind,
        'split_identity':export['split_identity'],'export_identity':export['identity'],
        'cache_sha256':file_hash(partial),'packages':packages(),'inference_seed':SEEDS['inference'],
        'adapter_code_sha256':file_hash(Path(__file__).parents[1]/'adapters/asr.py'),
        'request_sha256':content_hash(requests),'turns':len(requests),'creator':'actual LocalASR; no gold fallback'}
    published = path.with_suffix('.manifest.json')
    if published.exists():
        if read_json(published)!=manifest:
            raise ValueError('Existing cache manifest differs during explicit resume')
    else:
        write_json(published,manifest)
    partial.replace(path)


def execute(config, directory, operator, *, resume=False, adapter_factory=None):
    validate_lock(config)
    plan = source_plan(config)
    binding = {'source_export_files':plan['files'],'split':plan['partition']['split_identity'],
        'requests':{k:content_hash(v) for k,v in plan['requests'].items()},'packages':packages(),
        'code':file_hash(Path(__file__)),'adapter':file_hash(Path(__file__).parents[1]/'adapters/asr.py')}
    job = directory/'job.json'
    if resume:
        old = read_json(job)
        if old['binding']!=binding:
            raise ValueError('Resume ASR cache binding changed')
        export = validate_export(directory/'export',plan['partition'])
    else:
        write_json(job,{'binding':binding,'original_config_identity':config.identity(),
                        'operator':operator,'source':source_provenance(config.project_root)})
        export = import_export(plan,directory/'export',operator)
    # Factory receives only the verified model path/device/limits, never texts or labels.
    if adapter_factory is None:
        from ..adapters.asr import LocalASR
        adapter_factory = LocalASR
    from ..contracts import Limits
    adapter = adapter_factory(directory/'export','cuda',Limits(),seed=SEEDS['inference'])
    if adapter.metadata['parameter_count']!=export['logical_parameters']:
        raise ValueError('Actual loaded ASR logical count mismatch')
    for kind,requests in plan['requests'].items():
        path = directory/(kind+'-cache.jsonl')
        if resume and path.is_file():
            manifest = read_json(path.with_suffix('.manifest.json'))
            if manifest.get('cache_sha256')!=file_hash(path) or manifest.get('request_sha256')!=content_hash(requests):
                raise ValueError('Completed cache changed before resume')
            continue
        cache_partition(config,requests,export,path,adapter,600.,resume=resume)
    raw = dict(config.source)
    raw.update(asr_model_dir=str(directory/'export'),fit_asr_cache=str(directory/'fit-cache.jsonl'),
               validation_asr_cache=str(directory/'validation-cache.jsonl'))
    temporary = directory/'prepared-config.json'
    if not temporary.exists():
        write_json(temporary,raw)
    ready = load_config(temporary)
    for kind in ('fit','validation'):
        CacheASR(ready.require(kind+'_asr_cache'),ready,plan['partition'],kind=kind)
    write_json(directory/'outcome.json',{'status':'ready','directory':str(directory),
        'fit_turns':len(plan['requests']['fit']),'validation_turns':len(plan['requests']['validation']),
        'ASR_training':False,'Qwen_loaded':False,'prepared_config':str(temporary)},exclusive=False)
    return raw


def main(argv=None):
    root = Path(__file__).resolve().parents[4]
    sys.path.insert(0,str(root))
    parser = argparse.ArgumentParser(description='Explicit provisional E4 selection + genuine ASR turn caches; no Qwen run')
    parser.add_argument('--config',type=Path,default=root/'.agent-work/llm-finetune/local-suite.json')
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--accept-provisional-e4',action='store_true')
    parser.add_argument('--operator')
    parser.add_argument('--resume',type=Path)
    args = parser.parse_args(argv)
    config = load_config(args.config)
    if not args.execute:
        plan = source_plan(config)
        print({'status':'planned','export':str(plan['export']),'source_training_completed':True,
               'selection_status':'provisional; explicit operator selection required',
               'turn_counts':{k:len(v) for k,v in plan['requests'].items()},'model_loaded':False})
        return 0
    if not args.accept_provisional_e4 or not args.operator or not args.operator.strip():
        parser.error('--execute requires --accept-provisional-e4 and --operator; no inferred selection')
    lock = config.require('output_root')/'ASR-preparation.lock'
    lock.parent.mkdir(parents=True,exist_ok=True)
    fd = os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    os.write(fd,str(os.getpid()).encode());os.close(fd)
    before = file_hash(args.config)
    directory = None
    try:
        directory = args.resume.resolve() if args.resume else new_directory(root/'.agent-work/llm-asr','E4')
        if not directory.is_relative_to((root/'.agent-work').resolve()):
            raise ValueError('Preparation output must remain inside ignored .agent-work')
        raw = execute(config,directory,args.operator,resume=bool(args.resume))
        if file_hash(args.config)!=before:
            raise ValueError('Local config changed during cache creation; ready assets retained, not auto-bound')
        backup = directory/'config-before.json'
        if not backup.exists():
            shutil.copy2(args.config,backup)
        write_json(args.config,raw,exclusive=False)
        print({'status':'ready','directory':str(directory),'config_updated':str(args.config),'Qwen_run':False})
        return 0
    except BaseException as exc:
        if directory is not None:
            write_json(directory/'failure.json',{'status':'interrupted' if isinstance(exc,KeyboardInterrupt) else 'failed',
                                                'reason':type(exc).__name__},exclusive=False)
            print('ASR preparation stopped; evidence: '+str(directory),file=sys.stderr)
        raise
    finally:
        lock.unlink(missing_ok=True)


if __name__=='__main__':
    raise SystemExit(main())
