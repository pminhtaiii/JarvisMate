"""RV003 opt-in random tiny Qwen, CPU only, no snapshot/download."""
import copy
import os
import random
import tempfile
import unittest
from pathlib import Path

@unittest.skipUnless(os.environ.get("LIFEMATE_LLM_TINY") == "1", "set LIFEMATE_LLM_TINY=1 for download-free RV003")
class TinyQwenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # PEFT's optional bitsandbytes import may initialize a visible CUDA device.
        # This explicit RV003 profile is CPU-only before any model library import.
        previous = os.environ.get("CUDA_VISIBLE_DEVICES")
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        def restore():
            if previous is None:
                os.environ.pop("CUDA_VISIBLE_DEVICES", None)
            else:
                os.environ["CUDA_VISIBLE_DEVICES"] = previous
        cls.addClassCleanup(restore)

    def setUp(self):
        import torch
        import numpy as np
        torch.set_num_threads(1)
        self.torch, self.np = torch, np
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def model(self):
        from transformers import Qwen3Config, Qwen3ForCausalLM
        from lifemate.llm_training.models import inject_lora
        self.torch.manual_seed(42)
        self.np.random.seed(42)
        random.seed(42)
        config = Qwen3Config(vocab_size=64, hidden_size=32, intermediate_size=48, num_hidden_layers=2,
                           num_attention_heads=4, num_key_value_heads=2, head_dim=8, tie_word_embeddings=True,
                           bos_token_id=1, eos_token_id=2, pad_token_id=0)
        config._attn_implementation = "eager"
        return inject_lora(Qwen3ForCausalLM(config))[0]

    def components(self, model):
        t = self.torch
        optimizer = t.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=.002)
        scheduler = t.optim.lr_scheduler.LambdaLR(optimizer, lambda _: 1.)
        scaler = t.amp.GradScaler("cpu", enabled=False)
        return optimizer, scheduler, scaler

    def test_pretrained_reload_enters_training_mode_and_uses_gradient_checkpointing(self):
        from transformers import AutoModelForCausalLM
        from unittest.mock import patch
        from lifemate.llm_training.models import inject_lora
        from lifemate.llm_training.losses import completion_loss
        base = self.model().merge_and_unload()
        base.save_pretrained(self.root/'base',safe_serialization=True)
        loaded = AutoModelForCausalLM.from_pretrained(self.root/'base',local_files_only=True)
        self.assertFalse(loaded.training, 'from_pretrained starts in eval mode')
        loaded.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False})
        loaded.enable_input_require_grads()
        layer = loaded.model.layers[0]
        with patch.object(layer,'_gradient_checkpointing_func',wraps=layer._gradient_checkpointing_func) as checkpoint:
            prepared,_ = inject_lora(loaded)
            tokens = {'input_ids':[1,4,10,11,2], 'labels':[-100,-100,10,11,2]}
            completion_loss(prepared,tokens,self.torch).backward()
            self.assertTrue(layer.training, 'base decoder must train, not only the PEFT wrapper')
            self.assertGreater(checkpoint.call_count,0,'checkpointing must actually execute on the loaded base')
        self.assertFalse(self.torch.cuda.is_initialized())

    def test_analytic_gradients_have_relative_weight_two_and_partial_window_scale(self):
        from lifemate.llm_training.losses import weighted_objective
        t = self.torch
        x = t.tensor(1., requires_grad=True)
        weighted_objective(x.square(), 1, 1.5, 3).backward()
        normal = x.grad.item()
        x.grad = None
        weighted_objective(x.square(), 2, 1.5, 3).backward()
        self.assertAlmostEqual(x.grad.item(), normal*2)
        x.grad = None
        weighted_objective(x.square(), 2, 1.5, 1).backward()
        self.assertAlmostEqual(x.grad.item(), normal*6, places=6)

    def test_native_planner_reuses_only_exact_prefix_inside_one_sample(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        import transformers
        from lifemate.adapters.planner import LocalPlanner
        from lifemate.contracts import Limits
        t=self.torch
        planner=LocalPlanner.__new__(LocalPlanner)
        planner.model=self.model().merge_and_unload().eval()
        planner.tokenizer=SimpleNamespace(decode=lambda ids,**kw:
            '<tool_call>\n{"name":"demo.read","arguments":{}}\n</tool_call>' if list(ids)==[10] else '')
        planner.torch,planner.hf,planner.device=t,transformers,'cpu'
        planner.limits=Limits(16,30.,16384,512,65536)
        planner.eos_id,planner.pad_id,planner.special_ids=2,0,frozenset({0,1})
        planner._selection_filters={}
        class Constraint:
            def prefix(self,tools):
                first=[None]
                def allowed(batch,sent):
                    if first[0] is None:first[0]=len(sent)
                    return [10] if len(sent)==first[0] else [2]
                return allowed
        planner.constraint=Constraint()
        seen=[]
        hook=planner.model.register_forward_pre_hook(
            lambda module,args,kwargs:seen.append(kwargs['input_ids'].shape[-1]),with_kwargs=True)
        self.addCleanup(hook.remove)
        first=([4,7,9,11,13,17]*16)
        second=first+[10,2,7,9]
        tools=[{'type':'function','function':{'name':'demo.read','parameters':{'type':'object','properties':{}}}}]
        with patch('lifemate.adapters.planner.render_native',side_effect=lambda tok,msg,tools:('',msg[0]['ids'])):
            planner.start_sample('one')
            self.assertEqual(planner.generate_native([{'ids':first}],tools,30.).kind,'call')
            split=len(seen)
            self.assertEqual(planner.generate_native([{'ids':second}],tools,30.).kind,'call')
            self.assertLessEqual(seen[split],len(second)-len(first)+1,
                                 'Repeated native decisions must not prefill the unchanged prompt again')
            self.assertEqual(planner.last_generation['prompt_tokens'],len(second))
            split=len(seen)
            planner.start_sample('two')
            planner.generate_native([{'ids':second}],tools,30.)
            self.assertEqual(seen[split],len(second),'Never reuse KV state across samples')
        self.assertFalse(t.cuda.is_initialized())

    def test_cropped_prefix_cache_matches_fresh_qwen_suffix_logits(self):
        from lifemate.adapters.prefix_cache import ExactPrefixCache
        t=self.torch
        model=self.model().merge_and_unload().eval()
        first=[4,7,9,11,13,17]*16
        changed=first[:-4]+[21,23,25,27]
        cache=ExactPrefixCache()
        with t.inference_mode():
            result=model(input_ids=t.tensor([first]),use_cache=True)
            cache.commit(first,result.past_key_values)
            kwargs,shared=cache.prepare(changed)
            self.assertEqual(shared,len(first)-4)
            fresh=model(input_ids=t.tensor([changed]),use_cache=False).logits[:,shared:]
            reused=model(input_ids=t.tensor([changed[shared:]]),
                attention_mask=t.ones(1,len(changed),dtype=t.long),
                past_key_values=kwargs['past_key_values'],use_cache=True).logits
        self.assertTrue(t.allclose(fresh,reused,atol=1e-6,rtol=1e-5))
        self.assertFalse(t.cuda.is_initialized())

    def test_offload_restores_cpu_master_storage_without_a_return_copy(self):
        from types import SimpleNamespace
        from unittest.mock import patch,Mock
        from lifemate.adapters.common import ModelResidency
        t=self.torch
        model=t.nn.Module()
        model.embed=t.nn.Embedding(8,4)
        model.head=t.nn.Linear(4,8,bias=False)
        model.head.weight=model.embed.weight
        model.register_buffer('position',t.tensor([1.]))
        model.eval()
        original_weight=model.embed.weight
        original_data=model.embed.weight.detach()
        original_buffer=model.position
        adapter=ModelResidency()
        adapter.cpu_offload,adapter.device,adapter.model=True,'cpu',model
        adapter.torch=SimpleNamespace(cuda=SimpleNamespace(empty_cache=Mock()))
        move=model.to
        # CPU dtype conversion exercises replacement/restoration without a GPU.
        with patch.object(model,'to',side_effect=lambda device:move(dtype=t.float64)) as transfer:
            with self.assertRaisesRegex(RuntimeError,'sample failure'):
                with adapter.inference_session():
                    self.assertEqual(model.embed.weight.dtype,t.float64)
                    raise RuntimeError('sample failure')
        self.assertEqual(transfer.call_count,1,'Unchanged weights must not be copied back to CPU')
        self.assertIs(model.embed.weight,original_weight)
        self.assertIs(model.head.weight,original_weight)
        self.assertEqual(model.embed.weight.data_ptr(),original_data.data_ptr())
        self.assertIs(model.position,original_buffer)
        self.assertTrue(t.equal(model.embed.weight,original_data))
        self.assertFalse(t.cuda.is_initialized())

    def test_forced_token_batching_matches_reference_greedy_and_reduces_forwards(self):
        from lifemate.adapters.fast_greedy import generate
        import time
        t=self.torch
        model=self.model().merge_and_unload().eval()
        prompt=[4,7,9,11]*8
        steps=[[10],[11],[12],[13,14],[15],[16],[2]]
        def prefix(batch,sent):return steps[len(sent)-len(prompt)]
        seen=[]
        hook=model.register_forward_pre_hook(lambda m,a,k:seen.append(k['input_ids'].shape[-1]),with_kwargs=True)
        self.addCleanup(hook.remove)
        with t.inference_mode():
            reference=model.generate(input_ids=t.tensor([prompt]),attention_mask=t.ones(1,len(prompt),dtype=t.long),
                do_sample=False,num_beams=1,max_new_tokens=16,prefix_allowed_tokens_fn=prefix,eos_token_id=2,pad_token_id=0)
            reference_calls=len(seen)
            optimized=generate(model,prompt,prefix,torch=t,device='cpu',eos_id=2,
                max_new_tokens=16,ends_at=time.monotonic()+30.)
        self.assertEqual(optimized.ids,reference[0].tolist())
        self.assertLess(optimized.forward_calls,reference_calls)
        self.assertEqual(optimized.forward_calls,2)
        self.assertEqual(optimized.forced_tokens,6)
        self.assertFalse(t.cuda.is_initialized())

    def test_forced_generation_still_obeys_deadline_and_output_budget(self):
        from lifemate.adapters.fast_greedy import generate
        import time
        t=self.torch
        model=self.model().merge_and_unload().eval()
        prompt=[4,7,9,11]
        with t.inference_mode():
            expired=generate(model,prompt,lambda b,s:[10],torch=t,device='cpu',eos_id=2,
                max_new_tokens=3,ends_at=time.monotonic()-1.)
            limited=generate(model,prompt,lambda b,s:[10],torch=t,device='cpu',eos_id=2,
                max_new_tokens=3,ends_at=time.monotonic()+30.)
        self.assertEqual((expired.ids,expired.forward_calls),(prompt,0))
        self.assertEqual(limited.ids,prompt+[10]*3)
        self.assertEqual(limited.forward_calls,1)

    def test_nf4_preparation_preserves_configured_embedding_precision_and_tying(self):
        from lifemate.llm_training.models import prepare_nf4_training, inject_lora, assert_adapter_only
        from lifemate.llm_training.losses import completion_loss
        t = self.torch
        base = self.model().merge_and_unload().to(t.bfloat16)
        # Exercise PEFT's real k-bit preparation/casts without a GPU or 4-bit kernels.
        base.is_loaded_in_4bit = True
        prepared = prepare_nf4_training(base, t.bfloat16)
        self.assertEqual(prepared.get_input_embeddings().weight.dtype, t.bfloat16)
        self.assertIs(prepared.get_input_embeddings().weight, prepared.get_output_embeddings().weight)
        norms = [p for n,p in prepared.named_parameters() if 'norm' in n]
        self.assertTrue(norms and all(p.dtype == t.bfloat16 for p in norms))
        from transformers.models.qwen3.modeling_qwen3 import Qwen3RMSNorm
        norm = next(m for m in prepared.modules() if isinstance(m,Qwen3RMSNorm))
        x = t.randn(1,3,norm.weight.numel(),dtype=t.bfloat16)
        expected = (x.float()*t.rsqrt(x.float().square().mean(-1,keepdim=True)+norm.variance_epsilon)).to(x.dtype)*norm.weight
        self.assertTrue(t.equal(norm(x),expected))
        # The tiny model has dense projections in place of CUDA Linear4bit; use
        # their real compute dtype to exercise the subsequent residual/loss path.
        for module in prepared.modules():
            if isinstance(module,t.nn.Linear):
                module.to(dtype=t.bfloat16)
        prepared, _ = inject_lora(prepared)
        assert_adapter_only(prepared)
        tokens = {'input_ids':[1,4,10,11,2], 'labels':[-100,-100,10,11,2]}
        loss = completion_loss(prepared,tokens,t)
        self.assertEqual(loss.dtype,t.float32)
        loss.backward()
        self.assertTrue(t.isfinite(loss))
        self.assertTrue(any(p.grad is not None and t.count_nonzero(p.grad) for n,p in prepared.named_parameters()
                            if '.lora_B.' in n))
        self.assertFalse(prepared.get_input_embeddings().weight.requires_grad)
        self.assertFalse(t.cuda.is_initialized())

    def test_real_qwen_update_checkpoint_reload_and_remaining_budget_resume(self):
        from lifemate.llm_training.trainer import loop, DEFAULTS
        from lifemate.llm_training import checkpoints
        from lifemate.llm_training.models import assert_adapter_only
        t, np = self.torch, self.np
        model = self.model()
        assert_adapter_only(model)
        before = {n: p.detach().clone() for n, p in model.named_parameters()}
        rows = [{"target_type": k, "provenance": {"base_row_id": str(i), "source_id": "fit"}}
                for i, k in enumerate(("normal_call", "ask_missing_info", "normal_call"))]
        cache = [{"input_ids": [1, 4, 10+i, 11, 2], "labels": [-100, -100, 10+i, 11, 2],
                  "prompt_tokens": 2, "completion_tokens": 3} for i in range(3)]
        settings = DEFAULTS | {"max_updates": 4, "accumulation": 2, "save_every": 2, "warmup_updates": 0}
        binding = {"experiment": "L2", "settings": settings, "controlled_random_tiny": True}
        weights = {"normal_call": 1, "ask_missing_info": 2}
        full = self.root/"full"
        full.mkdir()
        optimizer, scheduler, scaler = self.components(model)
        from unittest.mock import patch
        with patch("lifemate.llm_training.trainer.clean_nll", return_value=1.):
            finished = loop(model, optimizer, scheduler, scaler, rows, cache, cache, weights, settings,
                            full, binding, t, np)
        expected = {n: p.detach().clone() for n, p in model.named_parameters()}
        changed = [n for n, p in expected.items() if not t.equal(p, before[n])]
        self.assertTrue(changed)
        self.assertTrue(all("lora_" in n for n in changed))
        self.assertEqual((finished["step"], finished["remaining_updates"]), (4, 0))
        self.assertEqual([h["rows"] for h in finished["history"]], [2, 1, 2, 1])
        checkpoint = full/"checkpoints/step-000002"
        with self.assertRaises(ValueError):
            checkpoints.load(checkpoint, binding | {"experiment": "L1"})
        reloaded = self.model()
        optimizer, scheduler, scaler = self.components(reloaded)
        resumed = self.root/"resumed"
        resumed.mkdir()
        with patch("lifemate.llm_training.trainer.clean_nll", return_value=1.):
            end = loop(reloaded, optimizer, scheduler, scaler, rows, cache, cache, weights, settings,
                       resumed, binding, t, np, resume=checkpoint)
        self.assertEqual(end["best"]["step"], 2)
        from lifemate.llm_training.storage import read_json
        self.assertEqual(read_json(resumed/"best.json")["checkpoint"], "full/checkpoints/step-000002")
        self.assertEqual(end["visits"], finished["visits"])
        self.assertEqual(len(end["history"]), 4)
        for name, p in reloaded.named_parameters():
            self.assertTrue(t.equal(p, expected[name]), name)
        with self.assertRaises(ValueError):
            checkpoints.load(resumed/"checkpoints/step-000004", binding)
        # A byte mutation is detected before torch.load or optimizer restoration.
        target = checkpoint/"optimizer.pt"
        target.write_bytes(target.read_bytes()+b"corrupt")
        with self.assertRaises(Exception):
            checkpoints.load(checkpoint, binding)
        self.assertFalse(t.cuda.is_initialized(), "RV003 CPU check must not initialize CUDA for RNG capture")

    def test_tiny_safe_merge_and_offline_reload_preserve_logits_and_logical_count(self):
        from transformers import AutoModelForCausalLM
        from lifemate.llm_training.losses import optimizer_update
        from lifemate.llm_training.trainer import clean_nll
        t = self.torch
        model = self.model()
        logical = sum(p.numel() for n, p in model.named_parameters() if "lora_" not in n)
        tokens = {"input_ids":[1,4,10,11,2], "labels":[-100,-100,10,11,2], "prompt_tokens":2, "completion_tokens":3}
        optimizer,scheduler,scaler = self.components(model)
        optimizer_update(model,optimizer,scheduler,scaler,[(tokens,"normal_call")],{"normal_call":1},1.,t)
        self.assertTrue(__import__('math').isfinite(clean_nll(model,[tokens],t)))
        model.eval()
        ids = t.tensor([tokens["input_ids"]])
        with t.inference_mode():
            expected = model(input_ids=ids).logits
        merged = model.merge_and_unload(safe_merge=True)
        self.assertEqual(sum(p.numel() for p in merged.parameters()),logical)
        self.assertFalse(any("lora_" in name for name,_ in merged.named_parameters()))
        merged.save_pretrained(self.root/"merged",safe_serialization=True)
        reloaded = AutoModelForCausalLM.from_pretrained(self.root/"merged",local_files_only=True,trust_remote_code=False)
        reloaded.eval()
        with t.inference_mode():
            actual = reloaded(input_ids=ids).logits
        self.assertTrue(t.allclose(expected,actual,atol=1e-5,rtol=1e-5))
        self.assertFalse(t.cuda.is_initialized())


if __name__ == "__main__":
    unittest.main()
