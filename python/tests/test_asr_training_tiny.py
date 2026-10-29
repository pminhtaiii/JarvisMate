"""Real tiny random Whisper + PEFT CPU checks; never download a checkpoint."""
import copy
import importlib.util
from pathlib import Path
import random
import socket
import tempfile
import unittest
from unittest.mock import patch

AVAILABLE = all(importlib.util.find_spec(name) for name in ('torch','peft','transformers','numpy'))


@unittest.skipUnless(AVAILABLE,'Install PEFT/Accelerate test dependencies to run tiny CPU smoke checks')
class TinyWhisperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        torch.set_num_threads(1)

    def setUp(self):
        import torch
        from transformers import WhisperConfig, WhisperForConditionalGeneration
        from lifemate.asr_training.config import DEFAULTS
        self.torch=torch
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.base=self.root/'base'
        torch.manual_seed(7)
        cfg=WhisperConfig(vocab_size=32,num_mel_bins=4,d_model=16,encoder_layers=1,decoder_layers=1,
             encoder_attention_heads=2,decoder_attention_heads=2,encoder_ffn_dim=32,decoder_ffn_dim=32,
             max_source_positions=8,max_target_positions=16,pad_token_id=0,bos_token_id=1,eos_token_id=2,
             decoder_start_token_id=1,suppress_tokens=[],begin_suppress_tokens=[],dropout=0.)
        WhisperForConditionalGeneration(cfg).save_pretrained(self.base)
        self.config=DEFAULTS|{'rank':2,'alpha':4,'dropout':0.,'scope':'decoder','experiment':'E1'}
        self.features=torch.randn(1,4,16)
        self.labels=torch.tensor([[3,4,2]])

    def model(self,scope='decoder'):
        from transformers import WhisperForConditionalGeneration
        from lifemate.asr_training.models import inject
        model=WhisperForConditionalGeneration.from_pretrained(self.base,local_files_only=True)
        model,targets=inject(model,self.config|{'scope':scope})
        model.train()
        return model,targets

    def update(self,model,optimizer):
        optimizer.zero_grad(set_to_none=True)
        loss=model(input_features=self.features,labels=self.labels).loss
        loss.backward()
        optimizer.step()
        return loss

    def test_real_decoder_scope_gradient_and_frozen_base(self):
        from lifemate.asr_training.models import gradient_report
        model,targets=self.model()
        self.assertEqual(len(targets),4)
        self.assertTrue(all('.decoder.' in n for n in targets))
        before={n:p.detach().clone() for n,p in model.named_parameters()}
        optimizer=self.torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],lr=.01)
        self.update(model,optimizer)
        report=gradient_report(model,'decoder')
        self.assertEqual(report['encoder'],0)
        self.assertGreater(report['decoder'],0)
        changed=[]
        for name,p in model.named_parameters():
            if not self.torch.equal(before[name],p): changed.append(name)
            if not p.requires_grad:
                self.assertTrue(self.torch.equal(before[name],p))
                self.assertIsNone(p.grad)
        self.assertTrue(changed)
        self.assertTrue(all('lora_' in name for name in changed))

    def test_real_encoder_decoder_checkpointed_backward(self):
        from lifemate.asr_training.models import gradient_report
        model,targets=self.model('encoder_decoder')
        self.assertEqual(len(targets),6)
        model.config.use_cache=False
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False})
        optimizer=self.torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],lr=.01)
        self.update(model,optimizer)
        report=gradient_report(model,'encoder_decoder')
        self.assertGreater(report['encoder'],0)
        self.assertGreater(report['decoder'],0)

    def test_checkpoint_optimizer_rng_resume_matches_next_update(self):
        import numpy as np
        from transformers import WhisperForConditionalGeneration
        from peft import PeftModel
        from lifemate.asr_training import checkpoints
        model,_=self.model()
        optimizer=self.torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],lr=.01)
        scheduler=self.torch.optim.lr_scheduler.LambdaLR(optimizer,lambda step:1.)
        scaler=self.torch.amp.GradScaler('cuda',enabled=False)
        self.update(model,optimizer)
        scheduler.step()
        binding={'config':'tiny-fixture','suite':'tiny-fixture'}
        checkpoint=checkpoints.save(self.root/'checkpoints',model,optimizer,scheduler,scaler,
                                   {'step':1,'epoch':0,'cursor':1},binding,self.torch,np)
        self.update(model,optimizer)
        expected={n:p.detach().clone() for n,p in model.named_parameters() if p.requires_grad}
        restored=PeftModel.from_pretrained(WhisperForConditionalGeneration.from_pretrained(self.base,local_files_only=True),
                                           checkpoint/'adapter',is_trainable=True,local_files_only=True)
        restored.train()
        other=self.torch.optim.AdamW([p for p in restored.parameters() if p.requires_grad],lr=.01)
        schedule=self.torch.optim.lr_scheduler.LambdaLR(other,lambda step:1.)
        state=checkpoints.restore(checkpoint,binding,other,schedule,scaler,self.torch,np)
        self.assertEqual(state['cursor'],1)
        self.update(restored,other)
        for n,p in restored.named_parameters():
            if p.requires_grad: self.torch.testing.assert_close(p,expected[n],rtol=0,atol=0)

    def test_merged_export_roundtrip_without_network(self):
        from transformers import WhisperForConditionalGeneration
        model,_=self.model()
        optimizer=self.torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],lr=.01)
        self.update(model,optimizer)
        model.eval()
        with self.torch.inference_mode():
            expected=model(input_features=self.features,decoder_input_ids=self.labels).logits
        merged=model.merge_and_unload(safe_merge=True)
        output=self.root/'export'
        merged.save_pretrained(output,safe_serialization=True)
        with patch.object(socket.socket,'connect',side_effect=AssertionError('No network in offline export')):
            restored=WhisperForConditionalGeneration.from_pretrained(output,local_files_only=True,trust_remote_code=False)
        restored.eval()
        with self.torch.inference_mode():
            actual=restored(input_features=self.features,decoder_input_ids=self.labels).logits
        self.torch.testing.assert_close(actual,expected,rtol=1e-5,atol=1e-6)
        self.assertFalse(any('lora_' in n for n,p in restored.named_parameters()))

    def test_nf4_is_not_claimed_supported_on_cpu(self):
        from lifemate.asr_training.models import load
        from lifemate.asr_training.resources import Unsupported
        with self.assertRaisesRegex(Unsupported,'target CUDA GPU'):
            load(str(self.base),self.config|{'experiment':'E3'},'float32',training=True,native=True,device='cpu')

    def test_real_peft_whisper_generate_accepts_audio_features(self):
        import numpy as np
        from lifemate.asr_training.models import generate
        from asr_training_support import make_audio
        model,_=self.model()
        model.eval()
        model.generation_config.lang_to_id={'<|vi|>':4}
        model.generation_config.task_to_id={'transcribe':3}
        model.generation_config.no_timestamps_token_id=5
        model.generation_config.is_multilingual=True
        model.generation_config.suppress_tokens=[i for i in range(32) if i!=2]
        model.generation_config.begin_suppress_tokens=[]
        torch=self.torch
        class Processor:
            def __call__(self,samples,**kwargs): return {'input_features':torch.zeros(1,4,16)}
            def batch_decode(self,output,**kwargs): return [str(output.tolist())]
        audio=self.root/'audio.wav'
        make_audio(audio,1)
        text=generate(model,Processor(),audio,np,self.torch,max_new_tokens=4)
        self.assertIsInstance(text,str)
        self.assertTrue(text)

    def test_shared_trainer_accumulation_and_last_partial_batch(self):
        import numpy as np
        from contextlib import nullcontext
        from types import SimpleNamespace
        from lifemate.asr_training.trainer import train_epoch
        from lifemate.asr_training.storage import write_rows, rows
        from asr_training_support import make_audio
        model,_=self.model()
        class Tokenizer:
            def __call__(self,text): return SimpleNamespace(input_ids=[1,3,4,2])
        torch=self.torch
        class Processor:
            tokenizer=Tokenizer()
            def __call__(self,samples,**kwargs):
                features=np.tile(samples[:16],(4,1)).astype(np.float32)
                return {'input_features':torch.tensor(features).unsqueeze(0)}
        class Memory:
            def phase(self,name): return nullcontext()
        fit=[]
        for i in range(5):
            path=f'audio/{i}.wav'
            make_audio(self.root/'data/train'/path,i+1)
            fit.append({'partition':'train','utterance_id':f's{i}/current','audio':path,
                        'reference':'synthetic text','duration_seconds':.01})
        write_rows(self.root/'fit.jsonl',fit)
        output=self.root/'run'
        output.mkdir()
        config=self.config|{'accumulation':2,'max_epochs':2,'checkpoint_updates':50}
        result=train_epoch(model,Processor(),{'config':config,'fit_path':str(self.root/'fit.jsonl'),
              'data_root':str(self.root/'data'),'output':str(output),'precision':'float32','binding':{'tiny':True}},
              self.torch,np,Memory())
        self.assertEqual(result['state'],{'step':3,'epoch':1,'cursor':0})
        logs=rows(output/'train-log.jsonl')
        self.assertEqual([r['effective_batch'] for r in logs],[2,2,1])
        self.assertTrue((Path(result['checkpoint'])/'files.json').is_file())

    def test_decoder_start_is_removed_once_and_overlong_labels_rejected(self):
        from types import SimpleNamespace
        from lifemate.asr_training.models import prepare_labels
        model,_=self.model()
        class Tokenizer:
            def __call__(self,text): return SimpleNamespace(input_ids=[1,3,4,2])
        self.assertEqual(prepare_labels(SimpleNamespace(tokenizer=Tokenizer()),model,'text'),[3,4,2])
        class Long:
            def __call__(self,text): return SimpleNamespace(input_ids=[3]*100)
        with self.assertRaises(ValueError):
            prepare_labels(SimpleNamespace(tokenizer=Long()),model,'text')


if __name__=='__main__': unittest.main()
