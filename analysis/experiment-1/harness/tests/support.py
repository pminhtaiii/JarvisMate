import copy
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace

from _common import (base_inputs, config_for, digest, dumps, fingerprint, phase_runs, read_json,
                     read_jsonl, write_json, write_jsonl)
from prepare import prepare

WORKSPACE = Path(__file__).resolve().parents[4]
REPO = Path(os.environ.get('EXPERIMENT1_TEST_SOURCE_REPO', str(WORKSPACE / 'JarvisMate')))
DATA = Path(os.environ.get('EXPERIMENT1_TEST_DATA_ROOT', str(WORKSPACE / 'train+public_test/train+public_test')))


class Fixture:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='lifemate-exp1-cpu-')
        self.base = Path(self.tmp.name)
        self.data = self.base / 'assets/data'
        split = self.data / 'train'
        split.mkdir(parents=True)
        shutil.copyfile(DATA / 'train/train_tools_catalog.json', split / 'train_tools_catalog.json')
        raw = read_jsonl(DATA / 'train/train.jsonl')
        row = next(r for r in raw if 'ewallet.transfer' in r['context']['installed_apps'].get('ewallet', {}).get('tools', []))
        row = copy.deepcopy(row)
        row.update(id='train_fixture_a', audio='audio/train_fixture_a/train_fixture_a.wav', history=[],
                   audio_text='chuyển tiền ví cho Minh')
        row['label'] = {'tool_calls': [], 'tool_results': [], 'final_state': {}}
        other = copy.deepcopy(row)
        other.update(id='train_fixture_b', audio='audio/train_fixture_b/train_fixture_b.wav')
        self.rows = [row, other]
        write_jsonl(split / 'train.jsonl', self.rows)
        runtime = split / 'zaic_tools'
        runtime.mkdir()
        (runtime / '__init__.py').write_text('# CPU fixture; not a real runtime\n')
        shutil.copyfile(DATA / 'train/zaic_tools/validate.py', runtime / 'validate.py')
        self.root = self.base / 'experiment'

    def prepare(self):
        return prepare(self.root, REPO, self.data, self.base / 'no-model', local=True, skip_model=True, block_size=1)

    def close(self):
        self.tmp.cleanup()


class FakeIntegration:
    """CPU artifact producer, never imports a model or creates an environment."""
    def __init__(self, root, fail_first=False, predicted_calls=()):
        self.root=Path(root)
        self.record=read_json(self.root/'experiment.json')
        self.calls=[];self.fail_first=fail_first;self.inferences=0
        self.predicted_calls=list(predicted_calls)

    def __call__(self, argv, stdout, stderr, cwd, env):
        self.calls.append(argv)
        path=Path(argv[argv.index('--config')+1])
        run=next(r for phase in self.record['phases'].values() for r in phase['runs'] if self.root/r['config']==path)
        cfg=config_for(self.root,run)
        from lifemate.provenance import package_versions
        data=Path(self.record['data_root']);runtime=Path(self.record['runtime_dir'])
        identity={'config_sha256':cfg.fingerprint(),'protocol':'qwen-native-v1',
                  'code':self.record['code_identity'],'packages':self.record['packages'], 'asr':None,
                  'planner':{'files':{},'model_type':'qwen3','parameter_count':1},
                  'dataset':{'selected_ids':run['ids'],'selection_sha256':digest(cfg.sample_ids_file),
                    'dataset_sha256':digest(data/'train/train.jsonl'),
                    'catalog_sha256':digest(data/'train/train_tools_catalog.json'),'catalog_version':'2.7.0'},
                  'runtime_source_sha256':{p.relative_to(runtime).as_posix():digest(p) for p in runtime.rglob('*.py')}}
        if run['arm']=='treatment':
            identity['skill_library']=self.record['library']
            identity['dataset']['catalog_canonical_sha256']=self.record['catalog_canonical_sha256']
        value={'status':'validated','identity':identity,'effective_config':cfg.record(),'run_sha256':fingerprint(identity)}
        if '--check-config' in argv:
            stdout.write(dumps(value)+'\n')
            return SimpleNamespace(returncode=0)
        self.inferences+=1
        if self.fail_first and self.inferences==1:
            return SimpleNamespace(returncode=1)
        self.artifacts(run,cfg,value)
        return SimpleNamespace(returncode=0)

    def artifacts(self,run,cfg,value):
        from lifemate.artifacts import Trace,_check
        root=self.root/run['output'];root.mkdir(parents=True)
        frozen={r['id']:r['prepared'] for r in read_jsonl(self.root/'inputs/base_inputs.jsonl')}
        records=[];predictions=[]
        def emit(kind,**fields):
            r={'type':kind,'seq':len(records)+1,**fields};r['check']=_check(r);records.append(r)
        emit('run',run_sha256=value['run_sha256'],config_sha256=cfg.fingerprint(),selected_ids=run['ids'])
        emit('worker_started',generation=1,pid=1)
        for index,sid in enumerate(run['ids']):
            attempt=f'{index+1:032x}'
            emit('reserve',sample_id=sid,attempt_id=attempt,generation=1,config_sha256=cfg.fingerprint())
            folder=root/'staging'/attempt;folder.mkdir(parents=True)
            prediction={'id':sid,'tool_calls':copy.deepcopy(self.predicted_calls),'state_hash':'a'*64};predictions.append(prediction)
            actions=[{'action':'call',**copy.deepcopy(c)} for c in self.predicted_calls]+[{'action':'finish'}]
            decisions=[{'step':n+1,'action':a['action'],'canonical_action':a,'seconds':.1,
                       'kv_cache_enabled':True,'prompt_tokens':10,'generated_tokens':1} for n,a in enumerate(actions)]
            metrics={'decisions':decisions,'tools':[{'name':c['name'],'step':n+1,'seconds':.001}
                                                  for n,c in enumerate(self.predicted_calls)]}
            if run['arm']=='treatment':
                metrics['skill_retrieval']={'enabled':True,'selected_branch_ids':['S09.B01'],
                                            'dropped_for_context':0,'seconds':.001,'budget_seconds':.001}
                for d in decisions:d.update(skill_guidance_count=1,skill_guidance_dropped=0)
            tr=Trace(folder/'trace.jsonl',attempt,sid,payloads=True)
            tr.emit('sample_started',input_mode='transcript')
            if run['arm']=='treatment':tr.emit('skill_retrieval',**metrics['skill_retrieval'])
            tr.emit('request_prepared',payload={'request':frozen[sid]['request'],'history':frozen[sid]['history']},
                    available_tools=[t['name'] for t in frozen[sid]['available_tools']])
            for d in decisions:
                tr.emit('planner_decision',step=d['step'],canonical_action=d['canonical_action'])
                if d['action']=='call':
                    a=d['canonical_action']
                    tr.emit('tool_call_started',step=d['step'],name=a['name'],payload=a['arguments'])
                    tr.emit('tool_call_result',step=d['step'],name=a['name'],payload={'ok':True,'balance':0})
            tr.emit('sample_finished',step=len(decisions),stop_reason='finish',payload=prediction);tr.close()
            emit('accept',sample_id=sid,attempt_id=attempt,status='completed',prediction=prediction,
                 metrics={'attempt_seconds':1.0,'worker':{'stop_reason':'finish','metrics':metrics}})
        emit('worker_stopped',generation=1,confirmed=True,reason='normal')
        write_jsonl(root/'journal.jsonl',records)
        write_jsonl(root/'predictions.jsonl',predictions)
        write_json(root/'effective-config.json',cfg.record())
        write_json(root/'manifest.json',{'effective_config':cfg.record(),'identity':value['identity'],
           'run_sha256':value['run_sha256'],'status':'completed',
           'host':{'visible_devices':'cpu-fixture','nvidia_smi':['CPU test double']},
           'publication':{'complete':True,'path':str(root/'predictions.jsonl')},
           'timings':{'startup':[{'hardware':{'test_double':True},'models':{'planner':{'reuse_kv_cache':True}}}]}})
