"""Merged export: selection evidence, interruption, offline reload and native protocol.

Tiny-model cases merge a real adapter into a saved random CPU Qwen3. Because that snapshot
needs a real template, they also need LIFEMATE_NATIVE_TOKENIZER (Qwen3 tokenizer files).
They do not establish adapter-versus-merged drift on the real model.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path

from lifemate.contracts import PipelineError
from lifemate.sft import load_config
from lifemate.sft.__main__ import main
from lifemate.sft.data import load_ready_export, prepare
from lifemate.sft.export import protocol_cases, run_diagnostics, run_export, verify_reload, verify_selection
from lifemate.sft.training import TrainPlan, checkpoint_path, run_training
from sft_support import CharTokenizer, make_config
from test_sft_training import PLAN, VALIDATION, HAS_MODEL_LIBRARIES, many_sources, tiny_loader

TOKENIZER = os.environ.get("LIFEMATE_NATIVE_TOKENIZER")


def fake_merge(_, adapter, target):
    (target / "config.json").write_text(json.dumps({"model_type": "qwen3", "max_position_embeddings": 32768}), encoding="utf-8")
    header = json.dumps({"weight": {"dtype": "F16", "shape": [10], "data_offsets": [0, 20]}}).encode("utf-8")
    (target / "model.safetensors").write_bytes(len(header).to_bytes(8, "little") + header + bytes(20))
    return {"parameter_count": 10, "dtype": "float16"}


@unittest.skipUnless(HAS_MODEL_LIBRARIES, "Needs torch, transformers, peft and safetensors")
class SelectionEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        # Update 1 covers only 16 rows, so it can never be eligible.
        cls.plan = TrainPlan(updates=4, evaluate_every=1, warmup=1)
        cls.config = make_config(cls.root, many_sources(30), VALIDATION)
        prepare(cls.config, tokenizer=CharTokenizer())
        run_training(cls.config, loader=tiny_loader(), plan=cls.plan)
        cls.selection = cls.config.experiment_dir / "selection.json"
        cls.original = cls.selection.read_text(encoding="utf-8")

    def setUp(self):
        self.selection.write_text(self.original, encoding="utf-8")
        target = self.config.experiment_dir / "merged_fp16"
        if target.exists():
            shutil.rmtree(target)
        self.addCleanup(lambda: self.selection.write_text(self.original, encoding="utf-8"))

    def forged(self, **changes):
        record = json.loads(self.original)
        record.update(changes)
        self.selection.write_text(json.dumps(record), encoding="utf-8")

    def verify(self):
        return verify_selection(self.config, load_ready_export(self.config), self.selection, plan=self.plan)

    def code(self, call):
        with self.assertRaises(PipelineError) as caught:
            call()
        return caught.exception.code, str(caught.exception)

    def test_recorded_selection_verifies_against_committed_checkpoints(self):
        state, adapter = self.verify()
        self.assertEqual(state["update"], json.loads(self.original)["selected_update"])
        self.assertTrue(state["coverage"]["complete"])
        self.assertTrue((adapter / "adapter_config.json").is_file())

    def test_forged_uncovered_selection_is_rejected(self):
        record = json.loads(self.original)
        first = record["candidates"][0]
        self.assertFalse(first["eligible"])
        self.forged(selected_update=1, adapter_sha256=first["adapter_sha256"])
        self.assertEqual(self.code(self.verify)[0], "SFT_SELECTION")

    def test_forged_eligibility_assertion_is_not_trusted(self):
        record = json.loads(self.original)
        record["candidates"][0].update(eligible=True, unique_rows=record["candidates"][0]["expected_rows"], validation_nll=0.0)
        self.selection.write_text(json.dumps(record | {"selected_update": 1,
                                                       "adapter_sha256": record["candidates"][0]["adapter_sha256"]}), encoding="utf-8")
        self.assertEqual(self.code(self.verify)[0], "SFT_SELECTION")

    def test_failed_selection_cannot_export(self):
        self.forged(status="failed", selected_update=None)
        self.assertEqual(self.code(self.verify)[0], "SFT_SELECTION")

    def test_foreign_run_identity_is_rejected(self):
        record = json.loads(self.original)
        record["identity"]["export_manifest_sha256"] = "0" * 64
        self.selection.write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(self.code(self.verify)[0], "SFT_IDENTITY")

    def test_changed_adapter_file_is_rejected(self):
        state, adapter = self.verify()
        weights = adapter / "adapter_model.safetensors"
        original = weights.read_bytes()
        self.addCleanup(weights.write_bytes, original)
        weights.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        self.assertEqual(self.code(self.verify)[0], "SFT_IDENTITY")

    def test_interrupted_merge_leaves_no_export_and_can_be_repeated(self):
        def crash(_, __, target):
            (target / "partial").write_text("x", encoding="utf-8")
            raise PipelineError("SFT_EXPORT", "Simulated crash", "sft_export")

        self.assertEqual(self.code(lambda: run_export(self.config, self.selection, plan=self.plan, merge=crash))[0], "SFT_EXPORT")
        self.assertFalse((self.config.experiment_dir / "merged_fp16").exists())
        self.assertFalse(list(self.config.experiment_dir.glob(".merged-*")))
        result = run_export(self.config, self.selection, plan=self.plan, merge=fake_merge, verifier=lambda path: {"verified": True})
        self.assertEqual(result["state"], "reload_verified")

    def test_failed_reload_keeps_the_merged_state_explicit(self):
        def broken(_):
            raise PipelineError("SFT_EXPORT", "Reload failed", "sft_export")

        self.assertEqual(self.code(lambda: run_export(self.config, self.selection, plan=self.plan, merge=fake_merge, verifier=broken))[0],
                         "SFT_EXPORT")
        manifest = json.loads((self.config.experiment_dir / "export_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["state"], "merged")
        self.assertIn("not a competition score", manifest["note"])

    def test_existing_export_is_not_overwritten(self):
        (self.config.experiment_dir / "merged_fp16").mkdir()
        self.assertIn("already exists", self.code(lambda: run_export(self.config, self.selection, plan=self.plan, merge=fake_merge))[1])


class ReloadCaseTests(unittest.TestCase):
    def test_protocol_cases_cover_call_dependent_call_clarification_and_finish(self):
        actions = [action for *_, action in protocol_cases()]
        self.assertEqual([a.get("name") for a in actions], ["contacts.search", "sms.send", "sys.ask_missing_info", None])
        self.assertEqual([len(observations) for _, observations, _ in protocol_cases()], [0, 1, 1, 1])


@unittest.skipUnless(HAS_MODEL_LIBRARIES and TOKENIZER, "Needs model libraries and LIFEMATE_NATIVE_TOKENIZER")
class TinyMergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        from transformers import AutoModelForCausalLM, Qwen3Config

        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        torch.manual_seed(1)
        config = Qwen3Config(vocab_size=160000, hidden_size=16, intermediate_size=32, num_hidden_layers=2, num_attention_heads=2,
                             num_key_value_heads=2, max_position_embeddings=32768, head_dim=8,
                             layer_types=["full_attention"] * 2, attn_implementation="eager")
        cls.base = cls.root / "real_base"
        AutoModelForCausalLM.from_config(config, dtype=torch.bfloat16).save_pretrained(cls.base)
        for name in ("tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt", "generation_config.json"):
            shutil.copyfile(Path(TOKENIZER) / name, cls.base / name)

    def test_export_merges_reloads_without_training_libraries_and_reports_drift(self):
        import torch

        from lifemate.sft.data import load_tokenizer
        from lifemate.sft.training import TrainingRuntime, attach_lora
        from transformers import AutoModelForCausalLM

        root = self.root / "run"
        config = make_config(root, many_sources(), VALIDATION)
        # Point the configuration at the real tiny snapshot rather than the metadata-only one.
        raw = config.record()
        toml = root / "config.toml"
        toml.write_text(
            'schema_version = 1\n[data]\n'
            + "".join(f'{key} = {json.dumps(raw["data"][key])}\n' for key in
                      ("train_jsonl", "train_catalog", "validation_jsonl", "validation_catalog", "permitted_use"))
            + 'train_role = "train"\nvalidation_role = "validation"\n[model]\n'
            + f'base_path = {json.dumps(self.base.as_posix())}\n'
            + '[training]\nrecipe = "qlora-baseline-v1"\ndevice = "cuda:0"\nseed = 20261027\nmicrobatch = 4\naccumulation = 4\n'
            + '[limits]\ncontext_tokens = 16384\nmax_new_tokens = 512\n'
            + f'[output]\nexperiment_dir = {json.dumps(raw["output"]["experiment_dir"])}\n', encoding="utf-8")
        config = load_config(toml)
        self.assertEqual(main(["prepare", "--config", str(toml)]), 0)

        def loader(config):
            torch.manual_seed(7)
            base = AutoModelForCausalLM.from_pretrained(self.base, dtype=torch.float32, attn_implementation="eager")
            base.config.use_cache = False
            model, trainable = attach_lora(base)
            model.train()
            tokenizer = load_tokenizer(config.base_path)
            return TrainingRuntime(torch, model, tokenizer, "cpu", tokenizer.pad_token_id,
                                   environment={"packages": {}, "gpu": "none"}, trainable=trainable)

        run_training(config, loader=loader, plan=PLAN)
        selection = config.experiment_dir / "selection.json"
        result = run_export(config, selection, plan=PLAN)
        self.assertEqual(result["state"], "reload_verified")
        merged = config.experiment_dir / "merged_fp16"
        manifest = json.loads((config.experiment_dir / "export_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["reload"]["protocol_cases"], 4)
        self.assertEqual(manifest["reload"]["training_modules_blocked"], ["peft", "bitsandbytes", "accelerate"])
        self.assertEqual(manifest["parameter_count"], manifest["reload"]["parameter_count"])

        # A trained adapter must change the merged weights relative to the frozen base.
        state = json.loads((checkpoint_path(config.experiment_dir, result["selected_update"]) / "checkpoint.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["adapter_sha256"], state["adapter_sha256"])
        fresh = AutoModelForCausalLM.from_pretrained(self.base, dtype=torch.float32)
        reloaded = AutoModelForCausalLM.from_pretrained(merged, dtype=torch.float16)
        self.assertFalse(any("lora" in name for name, _ in reloaded.named_parameters()))
        projection = "model.layers.0.self_attn.q_proj.weight"
        self.assertFalse(torch.equal(dict(fresh.named_parameters())[projection].half(), dict(reloaded.named_parameters())[projection]))
        untouched = "model.layers.0.mlp.up_proj.weight"
        self.assertTrue(torch.equal(dict(fresh.named_parameters())[untouched].half(), dict(reloaded.named_parameters())[untouched]))
        self.assertEqual(verify_reload(merged)["protocol_cases"], 4)

        # The inference path needs no training package at all.
        code = ("import sys\nfor n in ('peft','bitsandbytes','accelerate'):\n    sys.modules[n]=None\n"
                "import torch\nfrom transformers import AutoModelForCausalLM as M\n"
                f"m=M.from_pretrained({merged.as_posix()!r},dtype=torch.float16,local_files_only=True)\nprint(next(m.parameters()).dtype)")
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
        self.assertEqual((done.returncode, done.stdout.strip().splitlines()[-1]), (0, "torch.float16"), done.stderr[-300:])

        def merged_model(_, path):
            return AutoModelForCausalLM.from_pretrained(path, dtype=torch.float16).eval()

        def adapter_model(_, adapter):
            from peft import PeftModel

            base = AutoModelForCausalLM.from_pretrained(self.base, dtype=torch.float32)
            return PeftModel.from_pretrained(base, adapter).eval()

        report = run_diagnostics(config, selection, count=1, plan=PLAN, adapter_loader=adapter_model,
                                 merged_loader=merged_model, device="cpu")
        self.assertEqual((report["stage"], report["prompts"]), ("diagnose", 1))
        self.assertIn(report["identical"], (0, 1), "Drift is recorded, not assumed away")
        self.assertTrue((config.experiment_dir / "export_diagnostics.json").is_file())


if __name__ == "__main__":
    unittest.main()
