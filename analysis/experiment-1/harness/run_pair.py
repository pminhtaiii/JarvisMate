"""Sequential paired integration runner. CLI GPU execution requires an UIT allocation."""
from __future__ import annotations

import argparse
import copy
import os
from pathlib import Path
import subprocess
import uuid

from _common import (SERVER_BASE, add_experiment, child, command_main, config_for, digest,
                     dumps, equal, inside, load_experiment, phase_runs, read_json, require,
                     write_json, write_text)


def child_environment(root):
    env = os.environ.copy()
    env.update(PYTHONPATH=str(Path(root)/'src/python/src'), PYTHONNOUSERSITE='1',
               PYTHONDONTWRITEBYTECODE='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               TOKENIZERS_PARALLELISM='false', HF_HOME=str(Path(root)/'cache/huggingface'),
               XDG_CACHE_HOME=str(Path(root)/'cache'))
    return env


def invoke(command, stdout, stderr, root, executor=None):
    executor = executor or subprocess.run
    with Path(stdout).open('x',encoding='utf-8') as out, Path(stderr).open('x',encoding='utf-8') as err:
        result = executor(command, stdout=out, stderr=err, cwd=str(root), env=child_environment(root))
    return result.returncode


def check_preflight(value, root, record, run):
    require(value.get('status')=='validated', 'Preflight did not validate')
    cfg=config_for(root,run); identity=value['identity']
    require(equal(value['effective_config'],cfg.record()), 'Preflight effective config differs')
    require(equal(identity['code'],record['code_identity']), 'Preflight imported wrong source')
    require(equal(identity['packages'],record['packages']), 'Preflight package environment differs')
    require(identity['asr'] is None, 'ASR unexpectedly present in transcript mode')
    require(identity['dataset']['selected_ids']==run['ids'], 'Preflight selected IDs/order differ')
    if run['arm']=='treatment':
        require(identity.get('skill_library')==record['library'], 'Preflight ON Library differs')
    else:
        require(identity.get('skill_library') is None, 'Preflight OFF loaded Library')


def run_phase(root, phase, python, check_only=False, executor=None):
    root=Path(root).resolve();record=load_experiment(root)
    require(Path(python).is_file(), 'Python executable is missing')
    runs=phase_runs(record,phase)
    if not check_only and executor is None:
        require(record['profile']=='uit' and record['model_checked'], 'GPU runner refuses CPU-local/unverified model profile')
        require((record.get('model_reference') or {}).get('verified') is True,'Original 011 checkpoint identity not verified')
        require(inside(root,SERVER_BASE), 'GPU experiment must be under UIT tmp root')
        require(Path(python).absolute().is_relative_to(SERVER_BASE), 'Use the UIT tmp venv executable path')
        require(os.environ.get('SLURM_JOB_ID') and os.environ.get('CUDA_VISIBLE_DEVICES') not in (None,'','-1'),
                'GPU inference requires explicit Slurm allocation; no job is submitted by this helper')
    if phase=='main' and not check_only:
        smoke=read_json(root/'reports/smoke/summary.json')
        require(smoke['evidence_valid'] is True and smoke['experiment_sha256']==digest(root/'experiment.json'),
                'Main requires a passing smoke evidence audit from this experiment')
    if not check_only:
        require(not (root/'evidence'/f'{phase}-driver-started.json').exists(), 'Phase already attempted; no resume/retry')
        for run in runs:
            require(not child(root,run['output']).exists(), 'Run output exists; refusing overwrite')
        write_json(root/'evidence'/f'{phase}-driver-started.json',
                   {'experiment_sha256':digest(root/'experiment.json'),'phase':phase,
                    'slurm_job_id':os.environ.get('SLURM_JOB_ID'),'cuda_visible_devices':os.environ.get('CUDA_VISIBLE_DEVICES')})
    folder=root/'evidence'/('preflight-'+phase+'-'+uuid.uuid4().hex)
    folder.mkdir(parents=True)
    preflights={};commands=[];overall=0;failure=None
    try:
        for run in runs:
            stem=run['block']+'-'+run['arm']
            cmd=[str(python),'-m','lifemate.integration','--config',str(child(root,run['config'])),'--check-config']
            out=folder/(stem+'.stdout.json');err=folder/(stem+'.stderr.log')
            rc=invoke(cmd,out,err,root,executor)
            commands.append({'stage':'preflight','block':run['block'],'arm':run['arm'],'argv':cmd,'returncode':rc,
                             'stdout':str(out),'stderr':str(err)})
            require(rc==0,'Preflight failed; see '+str(err))
            value=read_json(out);check_preflight(value,root,record,run)
            preflights[(run['block'],run['arm'])]=value
        for block in {run['block'] for run in runs}:
            a,b=[preflights[(block,arm)]['identity'] for arm in ('control','treatment')]
            for key in ('planner','asr','code','packages','runtime_source_sha256'):
                require(equal(a[key],b[key]),'Paired preflight differs: '+key)
            ad,bd=copy.deepcopy(a['dataset']),copy.deepcopy(b['dataset'])
            ad.pop('catalog_canonical_sha256',None);bd.pop('catalog_canonical_sha256',None)
            require(equal(ad,bd),'Paired dataset/selection identities differ')
        if not check_only:
            for run in runs:
                load_experiment(root)  # Fail closed if anything drifted between arms.
                require(not child(root,run['output']).exists(),'Output appeared before dispatch')
                stem=run['block']+'-'+run['arm']
                cmd=[str(python),'-m','lifemate.integration','--config',str(child(root,run['config']))]
                out=folder/(stem+'.run.stdout.log');err=folder/(stem+'.run.stderr.log')
                rc=invoke(cmd,out,err,root,executor)
                commands.append({'stage':'inference','block':run['block'],'arm':run['arm'],'argv':cmd,
                                 'returncode':rc,'stdout':str(out),'stderr':str(err)})
                # A sample failure/incomplete publication must not suppress its partner.
                if rc:
                    overall=1
    except Exception as exc:
        overall=2;failure={'type':type(exc).__name__,'message':str(exc)}
    report={'schema_version':1,'phase':phase,'check_only':check_only,
            'experiment_sha256':digest(root/'experiment.json'),'commands':commands,
            'returncode':overall,'failure':failure,'finished':True}
    write_json(folder/'driver.json',report)
    if not check_only:
        write_json(root/'evidence'/f'{phase}-run-index.json',report)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);add_experiment(p)
    p.add_argument('--phase',choices=('smoke','main'),required=True)
    p.add_argument('--python',required=True,type=Path)
    p.add_argument('--check-only',action='store_true',help='Metadata/header preflight only; no model load or ToolEnv instances')
    a=p.parse_args();r=run_phase(a.experiment,a.phase,a.python,a.check_only)
    print(dumps({'phase':a.phase,'returncode':r['returncode'],'failure':r['failure']}))
    return r['returncode']


if __name__=='__main__':
    raise SystemExit(command_main(main))
