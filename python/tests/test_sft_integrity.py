"""Finite LoRA weights are required even with finite loss/gradients and matching digests."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lifemate.contracts import PipelineError
from lifemate.sft.data import load_ready_export, prepare
from lifemate.sft.training import (Coverage, RowStream, TrainPlan, checkpoint_path, finalize_selection,
                                   read_checkpoint, require_finite_weights, run_training, save_checkpoint,
                                   tree_digests, tree_sha256)
from sft_support import CharTokenizer, make_config, train_only_config
from test_sft_training import HAS_MODEL_LIBRARIES, PLAN, VALIDATION, many_sources, tiny_loader

NONFINITE = (float("nan"), float("inf"), -float("inf"))


@unittest.skipUnless(HAS_MODEL_LIBRARIES, "Needs torch, transformers, peft and safetensors")
class AdapterIntegrityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def config(self, mode, name):
        if mode == "none":
            config = train_only_config(self.root, many_sources(), experiment=name)
        else:
            config = make_config(self.root, many_sources(), VALIDATION, experiment=name)
        prepare(config, tokenizer=CharTokenizer())
        return config

    def test_finite_weights_are_accepted_without_gradients(self):
        runtime = tiny_loader()(None)
        weights = [(n, p) for n, p in runtime.model.named_parameters() if p.requires_grad]
        self.assertTrue(weights)
        self.assertTrue(all(p.grad is None for _, p in weights))
        require_finite_weights(runtime.torch, weights)

    def test_nan_and_both_infinities_are_rejected_in_either_lora_matrix(self):
        runtime = tiny_loader()(None)
        for side in ("lora_A", "lora_B"):
            name, weight = next((n, p) for n, p in runtime.model.named_parameters() if side in n)
            original = weight.detach().clone()
            for value in NONFINITE:
                with self.subTest(side=side, value=value), runtime.torch.no_grad():
                    weight.copy_(original)
                    weight.view(-1)[-1] = value
                    with self.assertRaises(PipelineError) as caught:
                        require_finite_weights(runtime.torch, [(name, weight)])
                    self.assertEqual(caught.exception.code, "SFT_TRAINING")
                    self.assertIn("Nonfinite adapter weight", str(caught.exception))
                    self.assertIn(side, str(caught.exception))
            with runtime.torch.no_grad():
                weight.copy_(original)

    def test_optimizer_corruption_stops_before_progress_or_checkpoint_commit(self):
        import torch

        original_step = torch.optim.AdamW.step
        for mode in ("none", "separate"):
            for bad_update in (1, PLAN.updates):
                for index, value in enumerate(NONFINITE):
                    with self.subTest(mode=mode, update=bad_update, value=value):
                        config = self.config(mode, f"{mode}-{bad_update}-{index}")
                        steps = 0

                        def corrupt(optimizer, *args, **kwargs):
                            nonlocal steps
                            result = original_step(optimizer, *args, **kwargs)
                            steps += 1
                            if steps == bad_update:
                                with torch.no_grad():
                                    optimizer.param_groups[0]["params"][-1].view(-1)[-1] = value
                            return result

                        with patch.object(torch.optim.AdamW, "step", corrupt):
                            with self.assertRaises(PipelineError) as caught:
                                run_training(config, loader=tiny_loader(), plan=PLAN)
                        self.assertEqual(caught.exception.code, "SFT_TRAINING")
                        self.assertIn("Nonfinite adapter weight", str(caught.exception))
                        self.assertEqual(steps, bad_update)
                        metrics = [json.loads(line) for line in
                                   (config.experiment_dir / "training_metrics.jsonl").read_text().splitlines()]
                        self.assertEqual([m["update"] for m in metrics if "loss" in m], list(range(1, bad_update)))
                        checkpoints = list((config.experiment_dir / "checkpoints").glob("step-*"))
                        self.assertEqual(sorted(p.name for p in checkpoints),
                                         [] if bad_update == 1 else ["step-0002"])
                        self.assertFalse((config.experiment_dir / "selection.json").exists())
                        self.assertFalse((config.experiment_dir / "adapter").exists())

    def test_checkpoint_writer_rejects_nonfinite_weights_before_staging(self):
        import torch

        runtime = tiny_loader()(None)
        optimizer = torch.optim.AdamW([p for p in runtime.model.parameters() if p.requires_grad])
        scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda _: 1)
        for index, value in enumerate(NONFINITE):
            with self.subTest(value=value), torch.no_grad():
                weight = next(p for n, p in runtime.model.named_parameters() if "lora_B" in n)
                weight.view(-1)[-1] = value
                root = self.root / str(index)
                with patch.object(runtime.model, "save_pretrained") as save:
                    with self.assertRaises(PipelineError) as caught:
                        save_checkpoint(root, 2, runtime, optimizer, scheduler, RowStream(1), Coverage(["s"]), {}, None)
                    self.assertEqual(caught.exception.code, "SFT_TRAINING")
                    save.assert_not_called()
                self.assertFalse(root.exists(), "Invalid weights must not create even a staging directory")

    def test_matching_digests_cannot_make_a_nonfinite_final_checkpoint_selectable(self):
        from safetensors.torch import load_file, save_file

        for mode in ("none", "separate"):
            for index, value in enumerate(NONFINITE):
                with self.subTest(mode=mode, value=value):
                    config = self.config(mode, f"{mode}-{index}")
                    with self.assertRaisesRegex(PipelineError, "Stopped by test hook"):
                        run_training(config, loader=tiny_loader(), plan=TrainPlan(4, 2, 2, stop_after=4))
                    final = checkpoint_path(config.experiment_dir, 4)
                    sources = [row["provenance"]["source_id"] for row in load_ready_export(config).train]
                    state = read_checkpoint(final, sources)
                    self.assertTrue(state["coverage"]["complete"])
                    weights = final / "adapter" / "adapter_model.safetensors"
                    tensors = load_file(weights)
                    name = next(n for n in tensors if "lora_B" in n)
                    tensors[name].view(-1)[-1] = value
                    save_file(tensors, weights)
                    # Simulate an older/corrupt producer that committed NaN/Inf with valid hashes.
                    state["files"] = tree_digests(final)
                    state["adapter_sha256"] = tree_sha256({n: v for n, v in state["files"].items()
                                                           if n.startswith("adapter/")})
                    (final / "checkpoint.json").write_text(json.dumps(state), encoding="utf-8")
                    self.assertEqual(tree_digests(final), state["files"])
                    before = {p.relative_to(final): p.read_bytes() for p in final.rglob("*") if p.is_file()}
                    for action in (
                        lambda: read_checkpoint(final, sources, identity=state["identity"]),
                        lambda: finalize_selection(config.experiment_dir, PLAN, sources, state["identity"],
                                                   validation_mode=mode),
                        lambda: run_training(config, resume=final, loader=tiny_loader(), plan=PLAN),
                    ):
                        with self.assertRaises(PipelineError) as caught:
                            action()
                        self.assertEqual(caught.exception.code, "SFT_IDENTITY")
                        self.assertIn("Nonfinite adapter weight", str(caught.exception))
                    self.assertFalse((config.experiment_dir / "selection.json").exists())
                    self.assertFalse((config.experiment_dir / "adapter").exists())
                    after = {p.relative_to(final): p.read_bytes() for p in final.rglob("*") if p.is_file()}
                    self.assertEqual(before, after, "Rejected committed checkpoints stay unchanged")


if __name__ == "__main__":
    unittest.main()
