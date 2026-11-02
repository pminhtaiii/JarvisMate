"""Explicit user-requested L0-L3 workflow; each phase remains an isolated command."""
from __future__ import annotations

import argparse
from importlib.metadata import PackageNotFoundError, version
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from .config import content_hash, load_config
from .storage import file_hash, new_directory, read_json, source_provenance, write_json, write_jsonl

NVML_VERSION = '13.595.45'
STEPS = ['prepare/resume ASR caches if missing (approved E4, explicit job binding)', 'pinned environment', 'verify-resources', 'evaluation-inputs (no models)', 'prepare',
         'seal-selection-policy', 'token-audit', 'GPU kernels', 'early/full qualification',
         'L0 G/A diagnostics and closed loop', 'L0 audio pilot/operator review',
         'L1 independent train/export/verify/G/A', 'L2 independent train/export/verify/G/A',
         'RV018 weighting selection', 'approved Fit ASR views/token audit',
         'L3 length qualification/train/export/verify/G/A', 'eight-row final comparison']


class WorkflowError(ValueError):
    pass


def phase(root, directory, label, argv, accepted=None):
    """One subprocess, live output, bounded logs, recorded exit and exact source."""
    record = directory / label
    record.mkdir()
    write_json(record/'command.json', {'argv':argv, 'source':source_provenance(root), 'cwd':str(root)})
    print('\n>>> ' + label, flush=True)
    started = time.monotonic()
    from .progress import HEARTBEAT_SECONDS, duration, terminal_line
    last_display = [started]
    child = subprocess.Popen(argv, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    def tee(pipe, name, target):
        written = 0
        with (record/name).open('wb') as log:
            for line in iter(pipe.readline, b''):
                remaining = 8*1024*1024 - written
                if remaining > 0:
                    log.write(line[:remaining]); written += len(line[:remaining])
                text = line.decode('utf-8',errors='replace')
                if name == 'stderr.log' and terminal_line(text):
                    target.write(text[:2000]); target.flush()
                    last_display[0] = time.monotonic()
        pipe.close()
    threads = [threading.Thread(target=tee,args=(child.stdout,'stdout.log',sys.stdout)),
               threading.Thread(target=tee,args=(child.stderr,'stderr.log',sys.stderr))]
    for thread in threads:
        thread.start()
    try:
        while True:
            try:
                code = child.wait(timeout=1)
                break
            except subprocess.TimeoutExpired:
                if time.monotonic()-last_display[0] >= HEARTBEAT_SECONDS:
                    print(f'[LLM] {label} | running | elapsed={duration(time.monotonic()-started)}',flush=True)
                    last_display[0] = time.monotonic()
    except BaseException:
        if os.name == 'nt':
            # Kill this subprocess tree before its venv redirector can orphan the worker.
            subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],capture_output=True,check=False)
        else:
            child.terminate()
        try:
            child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            child.kill(); child.wait()
        raise
    finally:
        for thread in threads:
            thread.join()
    write_json(record/'outcome.json', {'exit_code':code,'elapsed_seconds':time.monotonic()-started,
        'logs':{name:file_hash(record/name) for name in ['stdout.log','stderr.log']}})
    result = {}
    if accepted is not None:
        try:
            result = read_json(record/'stdout.log')
        except (OSError,ValueError):
            if code == 0:
                raise WorkflowError(f'{label} produced no valid JSON outcome. Evidence: {record}')
    if code != 0:
        reason = str(result.get('reason') or result.get('error') or '')[:700]
        if not result:
            with (record/'stdout.log').open('rb') as log:
                log.seek(max(0,log.seek(0,2)-1500))
                tail = log.read().decode('utf-8',errors='replace').strip()
            if tail and not tail.startswith('{'):
                print(tail,file=sys.stderr,flush=True)
        message = f'{label} failed (exit {code}); stopped. {reason} Evidence: {record}'
        if (result.get('binding',{}).get('settings',{}).get('method')=='lora'
                and any(word in reason.lower() for word in ('out of memory','headroom','outofmemory'))):
            message += ' To explicitly select genuine NF4+LoRA for all L1-L3, rerun CHAY_TUNING_LLM.ps1 -Method nf4. No automatic method switch was made.'
        raise WorkflowError(message)
    if accepted and result.get('status') not in accepted:
        raise WorkflowError(f'{label}: unacceptable status {result.get("status")}; no next phase')
    counts = result.get('counts')
    detail = '' if not isinstance(counts,dict) else (
        f" | completed={counts.get('completed',0)} | failed={counts.get('failed',0)}"
        f" | not_attempted={counts.get('not_attempted',0)}")
    print(f'[LLM] {label} | {result.get("status","done")}{detail} | elapsed={duration(time.monotonic()-started)}',flush=True)
    return result


def bootstrap(root, directory, config, run_phase):
    """Add one explicitly pinned provider; never upgrade/downgrade existing packages."""
    if config.source['environment_profile'] != 'windows-py312-cu128':
        raise WorkflowError('This entrypoint requires the explicit receiving Windows/Python312/cu128 base profile')
    from .resources import validate_lock
    validate_lock(config)
    try:
        observed = version('nvidia-ml-py')
    except PackageNotFoundError:
        observed = None
    if observed not in {None, NVML_VERSION}:
        raise WorkflowError('Installed nvidia-ml-py differs from the pinned measurement profile; refusing to change it')
    if observed is None:
        run_phase(root,directory,'install-pinned-nvml',[sys.executable,'-m','pip','install','--no-deps',
            '--require-hashes','-r',str(root/'fine-tune-llm/requirements-nvml.lock')],None)
    run_phase(root,directory,'pip-check',[sys.executable,'-m','pip','check'],None)
    base = config.require('environment_lock')
    manifest = read_json(base.with_suffix('.manifest.json'))
    locks = directory/'locks'
    locks.mkdir()
    lock = locks/'windows-py312-cu128-nvml.lock'
    lock.write_text(base.read_text(encoding='utf-8')+'\n'+
                    (root/'fine-tune-llm/requirements-nvml.lock').read_text(encoding='utf-8'),encoding='utf-8')
    manifest.update(profile='windows-py312-cu128-nvml',lock_sha256=file_hash(lock),wheels=manifest['wheels']+1,
        parent_lock_sha256=file_hash(base),provider_lock_sha256=file_hash(root/'fine-tune-llm/requirements-nvml.lock'),
        resolution_scope='37-wheel parent resolution plus dependency-free NVIDIA provider; not a new resolver report',
        compatibility='derived pinned closure; this invocation must pass kernel and full model qualification')
    manifest['packages']['nvidia-ml-py'] = NVML_VERSION
    write_json(lock.with_suffix('.manifest.json'),manifest)
    return lock


def smoke_rows(config, suite, destination):
    from .acceptance import accepted_corpus
    corpus = accepted_corpus(config,suite)
    tokens = {r['row_id']:r for r in corpus['cache']}
    fit = [r for r in corpus['rows'] if r['provenance']['partition']=='fit']
    if not fit:
        raise WorkflowError('No accepted Fit rows for the declared early smoke')
    selected = [min(fit,key=lambda r:tokens[r['row_id']]['prompt_tokens']),
                max(fit,key=lambda r:tokens[r['row_id']]['prompt_tokens'])]
    write_jsonl(destination,[{k:r[k] for k in ('input','target','target_type')} for r in selected])


def check_inputs(config):
    """Fail before packages/data/model phases when required ASR inputs are absent."""
    missing = []
    export = config.paths.get('asr_model_dir')
    if export is None or not (export/'llm-handoff.json').is_file():
        missing.append('certified selected-ASR llm-handoff.json')
    for name in ('fit_asr_cache','validation_asr_cache'):
        path = config.paths.get(name)
        if path is None or not path.is_file() or not path.with_suffix('.manifest.json').is_file():
            missing.append(name + ' + matching turn-cache manifest')
    if missing:
        raise WorkflowError('Missing prerequisites for L0-L3: '+ '; '.join(missing)+
                            '. Prepare ASR explicitly once with CHAY_TUNING_LLM.ps1 -PrepareASR -AcceptProvisionalE4; '
                            'this selects provisional E4 and runs ASR cache inference only, never Qwen. '
                            'See fine-tune-llm/ASR_HANDOFF.md')


def review_pilot(pilot):
    if pilot.get('pilot_status') != 'locally_feasible':
        raise WorkflowError('L0 full-audio pilot is not locally_feasible; stop before training')
    print('Review the measured native audio pilot: '+pilot['evaluation_dir'])
    if input('After reviewing it, type TIEPTUC to authorize L1-L3 training: ').strip() != 'TIEPTUC':
        raise WorkflowError('Operator did not review/approve the pilot; stop before training')
    reason = input('Operator review note: ').strip()
    if not reason:
        raise WorkflowError('Operator review note is required')
    return reason


def ensure_asr(root, directory, config_path, orchestration_path, *, run_phase=phase):
    """Use ready caches, or prepare/resume only the explicitly approved E4 job."""
    config = load_config(config_path)
    try:
        check_inputs(config)
        return config
    except WorkflowError:
        pass
    if not orchestration_path.is_file():
        raise WorkflowError('ASR is missing and no approved orchestration.json exists; no implicit selection or arbitrary latest-job resume')
    record = read_json(orchestration_path)
    choice = record.get('selection',{})
    if (record.get('schema')!='lifemate-llm-orchestration-v1' or record.get('prepare_asr_if_missing') is not True
            or choice.get('experiment')!='E4' or choice.get('accept_provisional') is not True):
        raise WorkflowError('Explicit approved provisional E4 preparation is required')
    approval = (root/choice['approval_file']).resolve()
    if not approval.is_relative_to((root/'.agent-work').resolve()) or file_hash(approval)!=choice.get('approval_sha256'):
        raise WorkflowError('Recorded E4 operator approval is missing/changed')
    source = (root/choice['source_export']).resolve()
    if (source!=config.require('asr_model_dir')
            or content_hash(read_json(source/'files.json'))!=choice.get('source_export_files_sha256')):
        raise WorkflowError('Approved E4 export differs from the configured source')
    argv = [sys.executable,'-m','lifemate.llm_training.asr_handoff','--config',str(config_path),
            '--execute','--accept-provisional-e4','--operator',os.environ.get('USERNAME') or os.environ.get('USER') or 'approved-operator']
    resume = record.get('resume_asr_job')
    if resume:
        job = (root/resume).resolve()
        if (not job.is_relative_to((root/'.agent-work/llm-asr').resolve())
                or file_hash(job/'job.json')!=record.get('resume_job_sha256')):
            raise WorkflowError('Explicit ASR resume job is missing/changed/outside the ignored ASR workspace')
        argv += ['--resume',str(job)]
    lock = config.require('output_root')/'ASR-preparation.lock'
    if lock.exists():
        from ..asr_training.cli import process_alive
        owner = int(lock.read_text(encoding='utf-8').strip())
        if process_alive(owner):
            raise WorkflowError('ASR lock owner is still active; refusing a duplicate worker')
        write_json(directory/'recovered-ASR-lock.json',{'previous_pid':owner,'verified_not_alive':True})
        lock.unlink()
    write_json(directory/'ASR-preparation-plan.json',{'orchestration_sha256':file_hash(orchestration_path),
        'approved_source':str(source),'explicit_resume_job':None if not resume else str(job)})
    run_phase(root,directory,'prepare-ASR',argv,None)
    ready = load_config(config_path)
    check_inputs(ready)
    return ready


def workflow(root, directory, config, settings, operator, *, run_phase=phase, pilot_review=review_pilot,
             asr_reviews=None):
    """One full declared suite. Missing evidence never triggers another workflow."""
    check_inputs(config)
    lock = bootstrap(root,directory,config,run_phase)
    local = dict(config.source)
    local.update(project_root=str(config.project_root),environment_profile='windows-py312-cu128-nvml',
                 environment_lock=str(lock))
    local_path = directory/'local-config.json'
    write_json(local_path,local)
    active = load_config(local_path)
    suite = directory/'suite'
    common = ['--config',str(local_path)]
    selected = ['--suite-dir',str(suite),*common]
    cli = [sys.executable,'-m','lifemate.llm_training']
    def invoke(label,args,statuses):
        return run_phase(root,directory,label,[*cli,*args],statuses)
    invoke('verify-resources',['verify-resources',*common,'--phase','transfer'],{'ready'})
    invoke('evaluation-inputs',['evaluation-inputs',*common],{'ready'})
    invoke('prepare',['prepare',*selected],{'sealed'})
    invoke('seal-selection-policy',['seal-selection-policy',*selected,'--policy',
           str(root/'fine-tune-llm/configs/selection-policy.json')],{'sealed'})
    invoke('token-audit',['token-audit',*selected,'--scope','clean'],{'passed'})
    from .corpus import load_suite
    from .asr_views import CacheASR
    partition = load_suite(suite)['partition']
    for kind in ('fit','validation'):
        CacheASR(active.require(kind+'_asr_cache'),active,partition,kind=kind)
    write_json(directory/'ASR-readiness.json',{'status':'passed','scope':'actual export and both turn caches'})
    from .trainer import training_settings
    policy = training_settings(settings)
    gpu = ['gpu-preflight',*common,'--settings',str(settings)]
    if policy['method']=='nf4':
        gpu += ['--nf4']
    invoke('gpu-preflight',gpu,{'passed'})
    fixtures = directory/'short-long-fit.jsonl'
    smoke_rows(active,suite,fixtures)
    probe = ['probe',*selected,'--experiment','L1','--settings',str(settings)]
    invoke('early-probe',[*probe,'--scope','early','--smoke-fixtures',str(fixtures)],{'passed_early_smoke'})
    full = invoke('full-probe',[*probe,'--scope','full'],{'passed'})
    qualification = Path(full['directory'])/'outcome.json'
    evaluations = []
    def evaluate(experiment, export=None):
        for mode in ('G','A'):
            for protocol in ('teacher_forced','closed_loop'):
                args = ['evaluate',*selected,'--experiment',experiment,'--mode',mode,'--protocol',protocol,
                        '--continue-on-error']
                if export is not None:
                    args += ['--export',str(export)]
                result = invoke(experiment+'-'+mode+'-'+protocol,args,{'completed'})
                if protocol=='closed_loop':
                    evaluations.append({'experiment':experiment,'mode':mode,
                                        'evaluation':Path(result['evaluation_dir']).name})
    evaluate('L0')
    pilot = invoke('L0-audio-pilot',['latency-pilot',*selected,'--experiment','L0'],{'completed'})
    reason = pilot_review(pilot)
    decision = directory/'operator-audio-latency.json'
    write_json(decision,{'schema':'lifemate-audio-latency-decision-v1','suite_seal':read_json(suite/'SEAL.json')['identity'],
        'operator':operator,'decision':'pilot_reviewed','reason':reason,'pilot':pilot['evaluation_dir']})
    def treatment(experiment, qualified, policy_report=None):
        gates = ['--resource-qualification',str(qualified),'--latency-decision',str(decision)]
        if policy_report is not None:
            gates += ['--policy-report',str(policy_report)]
        invoke(experiment+'-preflight',['preflight',*selected,'--experiment',experiment,
               '--settings',str(settings),*gates],{'ready'})
        trained = invoke(experiment+'-train',['train',*selected,'--experiment',experiment,
                         '--settings',str(settings),*gates],{'completed_full_budget'})
        exported = invoke(experiment+'-export',['export',*selected,'--experiment',experiment,
                          '--run-dir',trained['directory'],'--checkpoint','best'],{'exported_pending_verification'})
        export = Path(exported['directory'])
        invoke(experiment+'-verify-export',['verify-export',*selected,'--experiment',experiment,
               '--export',str(export)],{'passed'})
        evaluate(experiment,export)
    treatment('L1',qualification)
    treatment('L2',qualification)
    def compare(label):
        selection = directory/(label+'-selection.json')
        write_json(selection,{'runs':evaluations})
        return invoke(label,['compare',*selected,'--runs',str(selection)],set())
    weighting = compare('RV018')
    choice = weighting.get('weighting_selection',{})
    if choice.get('status')!='decided' or choice.get('selected_policy') not in {'L1','L2'}:
        raise WorkflowError('RV018 cannot select a valid weighting policy; stop before L3')
    report = Path(weighting['comparison_dir'])/'comparison.json'
    args = ['build-asr-views',*selected,'--fit-cache',str(active.require('fit_asr_cache'))]
    if asr_reviews is not None:
        args += ['--manual-reviews',str(asr_reviews)]
    views = invoke('Fit-ASR-views',args,{'authored_views'})
    if views.get('approved',0) <= 0:
        raise WorkflowError('No approved full-prefix Fit ASR views; stop before L3')
    invoke('ASR-token-audit',['token-audit',*selected,'--scope','asr','--view-dir',views['directory']],{'passed'})
    noisy = invoke('L3-full-probe',['probe',*selected,'--experiment','L3','--settings',str(settings),
                   '--scope','full','--include-asr'],{'passed'})
    treatment('L3',Path(noisy['directory'])/'outcome.json',report)
    result = compare('final-L0-L3')
    if len(result.get('rows',[])) != 8 or not all(row.get('valid') for row in result['rows']):
        raise WorkflowError('Final comparison contains missing/incompatible evidence; no complete-suite claim')
    return result


def main(argv=None):
    root = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description='Explicit L0-L3 suite with prerequisite gates; stops on missing evidence')
    parser.add_argument('--config',type=Path,default=root/'.agent-work/llm-finetune/local-suite.json')
    parser.add_argument('--method',choices=['lora','nf4'],default='lora')
    parser.add_argument('--orchestration-config',type=Path,default=root/'.agent-work/llm-finetune/orchestration.json')
    parser.add_argument('--asr-reviews',type=Path,help='Existing certified Fit noisy-prefix reviews, separate from clean quality reviews')
    parser.add_argument('--check-inputs',action='store_true',help='Model-free check for required handoff/cache files only')
    parser.add_argument('--preview',action='store_true',help='Print phases; no writes, packages, data/model/device access')
    args = parser.parse_args(argv)
    if args.preview:
        print({'experiments':['L0','L1','L2','L3'],'method':args.method,'max_updates_per_trained_experiment':500,'phases':STEPS,
               'downloads':'one hash-pinned optional measurement wheel only; no model/data',
               'audio_latency':'actual pilot and explicit operator review required','automatic_fallback':False})
        return 0
    config = load_config(args.config)
    if args.check_inputs:
        try:
            check_inputs(config)
        except WorkflowError as exc:
            print(str(exc),file=sys.stderr)
            return 4
        print('Required handoff/cache files present; content verification still precedes model loading.')
        return 0
    print('Qwen3-4B: L0 evaluation, independent L1/L2/L3 training, G/A and final comparison.')
    from .trainer import training_settings
    settings = root/'fine-tune-llm/configs'/('training-nf4.json' if args.method=='nf4' else 'training.json')
    training_settings(settings)
    output = config.require('output_root')
    output.mkdir(parents=True,exist_ok=True)
    lock = output/'tuning-once.lock'
    try:
        fd = os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:
        print('Another invocation or stale tuning-once.lock exists; refusing to duplicate or resume a run.')
        return 4
    directory = None
    try:
        os.write(fd,str(os.getpid()).encode()); os.close(fd)
        directory = new_directory(output/'single-runs','L0-L3')
        config = ensure_asr(root,directory,args.config,args.orchestration_config)
        result = workflow(root,directory,config,settings,os.environ.get('USERNAME') or os.environ.get('USER') or 'interactive-operator',
                          asr_reviews=args.asr_reviews)
        write_json(directory/'workflow.json',{'status':'completed','comparison':result,'source':source_provenance(root)})
        print('\nCompleted L0-L3. Evidence/checkpoints: '+str(directory))
        return 0
    except BaseException as exc:
        if directory is not None:
            write_json(directory/'workflow.json',{'status':'interrupted' if isinstance(exc,KeyboardInterrupt) else 'failed',
                'reason':str(exc)[:1500],'source':source_provenance(root)})
        print(str(exc),file=sys.stderr)
        return 130 if isinstance(exc,KeyboardInterrupt) else 1
    finally:
        lock.unlink(missing_ok=True)


if __name__=='__main__':
    raise SystemExit(main())
