"""Producer cache contracts without downloading/loading ASR or Qwen weights."""
import hashlib
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace

from lifemate.llm_training.asr_handoff import cache_partition, request_rows, import_export
from lifemate.llm_training.asr_views import ASR_DECODING
from lifemate.llm_training.storage import file_hash,read_json,read_jsonl,write_json,write_jsonl
from lifemate.llm_training.config import content_hash


class ASRProducerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.data=self.root/'data'
        self.config=SimpleNamespace(require=lambda key:self.data)
        self.requests=[]
        for i in range(2):
            path=self.data/'train/audio'/f'{i}.wav'
            path.parent.mkdir(parents=True,exist_ok=True)
            pcm=(i+1).to_bytes(2,'little')*160
            with wave.open(str(path),'wb') as wav:
                wav.setparams((1,2,16000,0,'NONE','not compressed'));wav.writeframes(pcm)
            self.requests.append({'source_id':f's{i}','group_id':f'g{i}','partition':'fit','turn':'current',
                'audio':f'audio/{i}.wav','wav_sha256':file_hash(path),'pcm_sha256':hashlib.sha256(pcm).hexdigest()})
        self.export={'identity':'e'*64,'processor_sha256':'p'*64,'decoding':ASR_DECODING,'split_identity':'frozen-test'}
        self.output=self.root/'fit-cache.jsonl'

    def adapter(self, text='HEARD_FROM_AUDIO'):
        calls=[]
        def transcribe(audio,timeout):
            self.assertIsInstance(audio,Path)
            calls.append(audio)
            return text
        return SimpleNamespace(transcribe=transcribe,calls=calls)

    def test_projection_keeps_original_history_indices_and_never_gold_text(self):
        source=SimpleNamespace(id='s0',record={'audio':'audio/0.wav','audio_text':'GOLD_MUST_NOT_BE_AN_ASR_REQUEST',
            'label':{'tool_calls':['FUTURE_SENTINEL']},'history':[{'role':'assistant','text':'ASSISTANT'},
                {'role':'user','audio':'audio/1.wav','audio_text':'GOLD_HISTORY'}]})
        split={'samples':[{'id':'s0','group':'g0','partition':'train','utterances':[
            {'audio':r['audio'],'wav_sha256':r['wav_sha256'],'pcm_sha256':r['pcm_sha256']} for r in self.requests]}]}
        result=request_rows([source],split)
        self.assertEqual([r['turn'] for r in result['fit']],['history:1','current'])
        self.assertNotIn('GOLD',str(result))
        self.assertNotIn('FUTURE_SENTINEL',str(result))

    def test_predictions_are_produced_from_audio_and_manifest_binds_cache(self):
        adapter=self.adapter()
        cache_partition(self.config,self.requests,self.export,self.output,adapter,600)
        rows=read_jsonl(self.output)
        self.assertEqual([r['transcript'] for r in rows],['HEARD_FROM_AUDIO']*2)
        self.assertEqual(len(adapter.calls),2)
        metadata=read_json(self.output.with_suffix('.manifest.json'))
        self.assertEqual(metadata['cache_sha256'],file_hash(self.output))
        self.assertEqual(metadata['request_sha256'],content_hash(self.requests))
        self.assertFalse(self.output.with_suffix('.partial.jsonl').exists())

    def test_changed_audio_is_rejected_before_any_model_call(self):
        (self.data/'train/audio/0.wav').write_bytes(b'changed')
        adapter=self.adapter()
        with self.assertRaisesRegex(ValueError,'Audio changed'):
            cache_partition(self.config,self.requests,self.export,self.output,adapter,600)
        self.assertEqual(adapter.calls,[])
        self.assertFalse(self.output.exists())

    def test_empty_output_is_an_explicit_failed_partial_never_gold_fallback(self):
        with self.assertRaisesRegex(ValueError,'no gold fallback'):
            cache_partition(self.config,self.requests,self.export,self.output,self.adapter(''),600)
        failed=read_jsonl(self.output.with_suffix('.partial.jsonl'))
        self.assertEqual(failed[0]['status'],'failed')
        self.assertIsNone(failed[0]['transcript'])
        self.assertFalse(self.output.exists())
        with self.assertRaisesRegex(ValueError,'failed rows'):
            cache_partition(self.config,self.requests,self.export,self.output,self.adapter(),600,resume=True)

    def test_explicit_resume_does_not_repeat_successful_audio(self):
        first=self.requests[0]|{'export_identity':self.export['identity'],
            'processor_sha256':self.export['processor_sha256'],'decoding_sha256':content_hash(ASR_DECODING),
            'status':'ok','transcript':'ALREADY_HEARD','elapsed':.1}
        write_jsonl(self.output.with_suffix('.partial.jsonl'),[first])
        adapter=self.adapter()
        cache_partition(self.config,self.requests,self.export,self.output,adapter,600,resume=True)
        self.assertEqual(len(adapter.calls),1)
        self.assertEqual(read_jsonl(self.output)[0]['transcript'],'ALREADY_HEARD')

    def test_manifest_commit_interruption_is_recoverable_without_model_rerun(self):
        from unittest.mock import patch
        adapter=self.adapter()
        original_replace=Path.replace
        def stop_before_final(path,target):
            if path.name.endswith('.partial.jsonl'):
                raise InterruptedError('controlled commit interruption')
            return original_replace(path,target)
        with patch.object(Path,'replace',stop_before_final):
            with self.assertRaises(InterruptedError):
                cache_partition(self.config,self.requests,self.export,self.output,adapter,600)
        self.assertTrue(self.output.with_suffix('.manifest.json').exists())
        resumed=self.adapter()
        cache_partition(self.config,self.requests,self.export,self.output,resumed,600,resume=True)
        self.assertEqual(resumed.calls,[])
        self.assertEqual(len(read_jsonl(self.output)),2)

    def test_import_cannot_infer_an_operator_selection(self):
        with self.assertRaisesRegex(ValueError,'operator'):
            import_export({},self.root/'must-not-exist','')
        self.assertFalse((self.root/'must-not-exist').exists())


if __name__=='__main__':
    unittest.main()
