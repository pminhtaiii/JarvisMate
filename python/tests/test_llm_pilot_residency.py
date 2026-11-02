"""Both audio adapters must yield the limited GPU between speech and planning."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from lifemate.llm_training.pilot import load_audio_adapters


class Adapter:
    def __init__(self,path,device,limits,*,cpu_offload):
        self.metadata={}
        self.cpu_offload=cpu_offload


class PilotResidencyTests(unittest.TestCase):
    def test_cuda_full_audio_offloads_both_models_and_declares_transfers_in_budget(self):
        config=SimpleNamespace(require=lambda key:Path(key))
        with patch('lifemate.adapters.asr.LocalASR',Adapter),patch('lifemate.adapters.planner.LocalPlanner',Adapter):
            asr,planner,policy=load_audio_adapters(config,'cuda')
        self.assertTrue(asr.cpu_offload)
        self.assertTrue(planner.cpu_offload)
        self.assertTrue(policy['offload'])
        self.assertTrue(policy['transfers_in_sample_elapsed'])
        self.assertEqual(asr.metadata['residency_policy'],planner.metadata['residency_policy'])

    def test_cpu_has_no_fake_gpu_offload(self):
        config=SimpleNamespace(require=lambda key:Path(key))
        with patch('lifemate.adapters.asr.LocalASR',Adapter),patch('lifemate.adapters.planner.LocalPlanner',Adapter):
            asr,planner,policy=load_audio_adapters(config,'cpu')
        self.assertFalse(asr.cpu_offload)
        self.assertFalse(planner.cpu_offload)
        self.assertFalse(policy['offload'])
