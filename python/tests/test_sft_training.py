"""The fixed recipe's rules. Pure cases need nothing; tiny-model cases need torch, transformers and peft.

Tiny-model cases run real LoRA, backward, checkpointing and resume on an unquantized CPU
Qwen3 with random weights. They establish loop behaviour, never GPU feasibility or model
quality. LIFEMATE_SFT_GPU_BASE names a local base snapshot for the separately enabled
real NF4 smoke, which needs a GPU and the complete training extra.
"""
import json
import math
import os
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path

from lifemate.contracts import PipelineError
from lifemate.sft import RECIPE
from lifemate.sft.data import prepare
from lifemate.sft.training import (Coverage, RowStream, TrainingRuntime, TrainPlan, attach_lora, checkpoint_path, evaluate,
                                   finalize_selection, lr_multiplier, read_checkpoint, replay, require_coverage_budget,
                                   run_training, select_checkpoint, validate_trainable)
from sft_support import ASK, FOUND, SEARCH, SEND, SENT, WAITING, CharTokenizer, make_config, source

HAS_MODEL_LIBRARIES = all(find_spec(name) for name in ("torch", "transformers", "peft", "safetensors"))


def candidate(update, nll, rows, expected=2120, sources=None, expected_sources=800):
    return {"update": update, "validation_nll": nll, "adapter_sha256": f"digest-{update}",
            "coverage": {"unique_rows": rows, "expected_rows": expected,
                         "unique_sources": expected_sources if sources is None else sources,
                         "expected_sources": expected_sources}}


class RowStreamTests(unittest.TestCase):
    def test_every_row_is_visited_before_any_repeats(self):
        stream, seen = RowStream(50), []
        for _ in range(3):
            seen += stream.next_window()
        self.assertEqual(len(set(seen)), 48)
        window = stream.next_window()
        self.assertEqual(set(seen + window[:2]), set(range(50)), "Final rows complete the epoch first")
        self.assertEqual(len(window), 16, "The partial tail continues into the next epoch")
        self.assertEqual(stream.state(), {"epoch": 1, "position": 14})

    def test_order_is_deterministic_and_reshuffled_each_epoch(self):
        one, two = RowStream(40), RowStream(40)
        self.assertEqual(one.next_window(40), two.next_window(40))
        self.assertNotEqual(one.next_window(40), list(range(40)))
        self.assertNotEqual(RowStream(40, seed=1).next_window(40), RowStream(40, seed=2).next_window(40))

    def test_state_restores_without_replay(self):
        original = RowStream(23)
        for _ in range(5):
            original.next_window()
        restored = RowStream(23, original.seed, **original.state())
        self.assertEqual(original.next_window(), restored.next_window())

    def test_invalid_state_is_rejected(self):
        with self.assertRaises(PipelineError):
            RowStream(10, position=11)


class CoverageTests(unittest.TestCase):
    def sources(self, rows, per_source=3):
        return [f"s{index // per_source}" for index in range(rows)]

    def test_unique_rows_and_sources_accumulate_only_when_added(self):
        coverage = Coverage(["a", "a", "b"])
        coverage.add([0])
        self.assertEqual((len(coverage.rows), len(coverage.sources), coverage.complete), (1, 1, False))
        coverage.add([0, 1, 2])
        self.assertTrue(coverage.complete)

    def test_coverage_is_never_inflated_by_repeats(self):
        _, coverage = replay(self.sources(2120), 100)
        self.assertEqual(len(coverage.rows), 1600)
        self.assertFalse(coverage.complete)
        self.assertTrue(replay(self.sources(2120), 133)[1].complete)
        self.assertFalse(replay(self.sources(2120), 132)[1].complete)

    def test_coverage_budget_requires_the_recipe_to_reach_every_row(self):
        require_coverage_budget(8000, TrainPlan())
        with self.assertRaises(PipelineError):
            require_coverage_budget(8001, TrainPlan())


class ScheduleTests(unittest.TestCase):
    def test_linear_warmup_then_constant(self):
        self.assertEqual(lr_multiplier(0), 1 / 25)
        self.assertEqual(lr_multiplier(11), 12 / 25)
        self.assertEqual(lr_multiplier(24), 1.0)
        self.assertEqual(lr_multiplier(499), 1.0)


class SelectionTests(unittest.TestCase):
    def test_lowest_nll_update_100_with_2120_rows_is_rejected(self):
        record = select_checkpoint([candidate(100, 0.1, 1600), candidate(200, 0.5, 2120), candidate(300, 0.4, 2120),
                                    candidate(400, 0.45, 2120), candidate(500, 0.6, 2120)])
        self.assertEqual((record["status"], record["selected_update"], record["adapter_sha256"]), ("selected", 300, "digest-300"))
        first = record["candidates"][0]
        self.assertEqual((first["update"], first["finite"], first["eligible"], first["unique_rows"]), (100, True, False, 1600))

    def test_exact_tie_takes_the_earlier_update(self):
        record = select_checkpoint([candidate(400, 0.3, 2120), candidate(300, 0.3, 2120)])
        self.assertEqual(record["selected_update"], 300)

    def test_uncovered_sources_alone_make_a_candidate_ineligible(self):
        record = select_checkpoint([candidate(100, 0.1, 2120, sources=799), candidate(200, 0.2, 2120)])
        self.assertEqual(record["selected_update"], 200)

    def test_no_eligible_finite_candidate_fails(self):
        for candidates in ([candidate(100, 0.1, 1600)],
                           [candidate(200, None, 2120), candidate(300, math.inf, 2120), candidate(400, math.nan, 2120)],
                           []):
            with self.subTest(candidates=len(candidates)):
                record = select_checkpoint(candidates)
                self.assertEqual((record["status"], record["selected_update"]), ("failed", None))


# --- Tiny real model ------------------------------------------------------------

def tiny_loader(*, dropout=RECIPE["lora_dropout"], layers=2):
    def load(config):
        import torch
        from transformers import AutoModelForCausalLM, Qwen3Config

        torch.manual_seed(20261027)
        torch.set_num_threads(1)
        model_config = Qwen3Config(vocab_size=9000, hidden_size=16, intermediate_size=32, num_hidden_layers=layers,
                                   num_attention_heads=2, num_key_value_heads=2, max_position_embeddings=4096,
                                   head_dim=8, layer_types=["full_attention"] * layers, attn_implementation="eager")
        base = AutoModelForCausalLM.from_config(model_config)
        base.config.use_cache = False
        model, trainable = attach_lora(base, dropout=dropout)
        model.train()
        tokenizer = CharTokenizer()
        return TrainingRuntime(torch, model, tokenizer, "cpu", tokenizer.pad_token_id,
                               environment={"packages": {"test": "1"}, "gpu": "none"}, trainable=trainable)

    return load


def many_sources(count=9):
    rows = []
    for index in range(count):
        calls = [SEARCH, SEND][:index % 3]
        rows.append(source(f"train_{index + 1:04d}", request=f"Yêu cầu {index}", calls=calls, results=[FOUND, SENT][:index % 3]))
    return rows


VALIDATION = [source("dev_0001", request="Tìm Hoa", calls=[ASK], results=[WAITING])]
PLAN = TrainPlan(updates=4, evaluate_every=2, warmup=2)


@unittest.skipUnless(HAS_MODEL_LIBRARIES, "Needs torch, transformers, peft and safetensors")
class TinyModelTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def ready_config(self, sources=None, name="experiment", **options):
        config = make_config(self.root, sources or many_sources(), VALIDATION, experiment=name, **options)
        prepare(config, tokenizer=CharTokenizer())
        return config

    def adapter(self, path):
        from safetensors.torch import load_file

        return load_file(path / "adapter" / "adapter_model.safetensors")

    def test_collate_masks_padding_by_position_even_when_pad_equals_eos(self):
        import torch

        from lifemate.sft.training import collate

        long, short = {"input_ids": [5, 6, 2, 7, 2], "labels": [-100, -100, -100, 7, 2]}, {"input_ids": [5, 2], "labels": [-100, 2]}
        batch = collate(torch, [long, short], pad_id=2, device="cpu")
        self.assertEqual(batch["input_ids"][1].tolist(), [5, 2, 2, 2, 2])
        self.assertEqual(batch["attention_mask"][1].tolist(), [1, 1, 0, 0, 0])
        self.assertEqual(batch["labels"][1].tolist(), [-100, 2, -100, -100, -100], "Terminal kept, padding masked")
        self.assertEqual(batch["labels"][0].tolist(), [-100, -100, -100, 7, 2], "Earlier EOS in the prompt stays masked")

    def test_only_all_lora_weights_train(self):
        runtime = tiny_loader()(None)
        self.assertEqual(runtime.trainable["lora_weights"], 2 * 4 * 2)
        for name, parameter in runtime.model.named_parameters():
            self.assertEqual(parameter.requires_grad, ".lora_" in name, name)
        names = [name for name, _ in runtime.model.named_parameters()]
        self.assertFalse(any(("mlp" in n or "embed" in n or "lm_head" in n) and ".lora_" in n for n in names))

    def test_a_trainable_base_weight_or_missing_layer_is_rejected(self):
        runtime = tiny_loader()(None)
        next(p for n, p in runtime.model.named_parameters() if "lm_head" in n or "embed" in n).requires_grad = True
        with self.assertRaises(PipelineError):
            validate_trainable(runtime.model, 2)
        with self.assertRaises(PipelineError):
            validate_trainable(tiny_loader()(None).model, 3)

    def test_factorizations_of_a_window_have_equal_gradients_with_unequal_targets(self):
        from lifemate.sft.training import accumulate_window, target_loss_sum

        examples = []
        for index in range(16):
            length = 3 + index * 2  # Unequal completions make naive mean-of-means differ.
            examples.append({"input_ids": list(range(20, 30 + index)) + list(range(40, 40 + length)),
                             "labels": [-100] * (10 + index) + list(range(40, 40 + length))})

        def gradients(microbatch):
            runtime = tiny_loader(dropout=0.0)(None)
            runtime.model.train()
            loss = accumulate_window(runtime, examples, microbatch)
            return loss, {n: p.grad.clone() for n, p in runtime.model.named_parameters() if p.requires_grad and p.grad is not None}

        import torch

        (loss_one, one), (loss_four, four) = gradients(1), gradients(4)
        self.assertAlmostEqual(loss_one, loss_four, places=4)
        self.assertEqual(one.keys(), four.keys())
        self.assertTrue(any(bool(g.abs().sum() > 0) for g in one.values()))
        for name in one:
            self.assertTrue(torch.allclose(one[name], four[name], rtol=1e-3, atol=1e-6), name)

        # The rejected alternative really differs here, so this check has power.
        runtime = tiny_loader(dropout=0.0)(None)
        runtime.model.train()
        from lifemate.sft.training import collate

        for start in range(0, 16, 4):
            batch = collate(torch, examples[start:start + 4], runtime.pad_id, "cpu")
            total, count = target_loss_sum(torch, runtime.model, batch)
            (total / count / 4).backward()
        naive = {n: p.grad for n, p in runtime.model.named_parameters() if p.requires_grad and p.grad is not None}
        self.assertFalse(all(torch.allclose(one[n], naive[n], rtol=1e-3, atol=1e-6) for n in one))

    def test_loss_uses_only_target_positions(self):
        import torch

        from lifemate.sft.training import collate, target_loss_sum

        runtime = tiny_loader(dropout=0.0)(None)
        runtime.model.eval()
        example = {"input_ids": list(range(30, 50)), "labels": [-100] * 15 + list(range(45, 50))}
        batch = collate(torch, [example], runtime.pad_id, "cpu")
        with torch.no_grad():
            total, count = target_loss_sum(torch, runtime.model, batch)
            logits = runtime.model(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"], use_cache=False).logits
            expected = torch.nn.functional.cross_entropy(logits[0, 14:19], batch["input_ids"][0, 15:20], reduction="sum")
        self.assertEqual(count, 5)
        self.assertAlmostEqual(float(total), float(expected), places=4)

    def test_validation_has_no_gradient_or_training_side_effects(self):
        import torch

        config = self.ready_config()
        runtime = tiny_loader()(config)
        runtime.model.train()
        example = {"input_ids": list(range(30, 50)), "labels": [-100] * 15 + list(range(45, 50))}
        state = torch.get_rng_state()
        first = evaluate(runtime, [example])
        self.assertTrue(runtime.model.training)
        self.assertTrue(torch.equal(state, torch.get_rng_state()))
        self.assertTrue(all(p.grad is None for p in runtime.model.parameters()))
        self.assertEqual(first, evaluate(runtime, [example]), "LoRA dropout is off during validation")

    def test_full_short_run_persists_diagnostics_coverage_and_selection(self):
        config = self.ready_config()
        result = run_training(config, loader=tiny_loader(), plan=PLAN)
        rows = config.experiment_dir / "sft/train.jsonl"
        count = len(rows.read_text(encoding="utf-8").splitlines())
        self.assertEqual(result["mode"], "full")
        selection = json.loads((config.experiment_dir / "selection.json").read_text(encoding="utf-8"))
        self.assertEqual(selection["status"], "selected")
        self.assertEqual([c["update"] for c in selection["candidates"]], [2, 4])
        for item in selection["candidates"]:
            self.assertTrue(item["finite"])
            self.assertEqual(item["expected_rows"], count)
        chosen = checkpoint_path(config.experiment_dir, selection["selected_update"])
        for item in ("adapter/adapter_model.safetensors", "trainer_state.pt", "checkpoint.json"):
            self.assertTrue((chosen / item).is_file(), item)
        self.assertEqual(sorted(p.name for p in (config.experiment_dir / "adapter").iterdir()),
                         sorted(p.name for p in (chosen / "adapter").iterdir()))
        metrics = [json.loads(line) for line in (config.experiment_dir / "training_metrics.jsonl").read_text(encoding="utf-8").splitlines()]
        losses = [m for m in metrics if "loss" in m]
        self.assertEqual([m["update"] for m in losses], [1, 2, 3, 4])
        self.assertTrue(all(math.isfinite(m["loss"]) and m["gradient_norm"] > 0 for m in losses))
        self.assertEqual([m["learning_rate"] for m in losses][:2], [5e-5, 1e-4])
        environment = json.loads((config.experiment_dir / "environment.json").read_text(encoding="utf-8"))
        self.assertGreater(environment["feasibility"]["longest_row_tokens"], 0)
        self.assertEqual(environment["effective_settings"]["training"]["microbatch"], 1)

    def test_uncovered_candidates_are_recorded_but_not_selected(self):
        # 18+ rows with 2 updates of 16: update 2 can cover at most 32 rows, so use more rows.
        config = self.ready_config(many_sources(30))
        plan = TrainPlan(updates=4, evaluate_every=1, warmup=1)
        run_training(config, loader=tiny_loader(), plan=plan)
        selection = json.loads((config.experiment_dir / "selection.json").read_text(encoding="utf-8"))
        first = selection["candidates"][0]
        self.assertFalse(first["eligible"])
        self.assertLess(first["unique_rows"], first["expected_rows"])
        self.assertGreater(selection["selected_update"], 1)

    def test_budget_shortfall_stops_before_the_model_loads(self):
        config = self.ready_config(many_sources(30))
        def forbidden(_):
            raise AssertionError("Model must not load")
        with self.assertRaises(PipelineError) as caught:
            run_training(config, loader=forbidden, plan=TrainPlan(updates=1, evaluate_every=1, warmup=1))
        self.assertIn("cannot cover", str(caught.exception))

    def test_resume_matches_an_uninterrupted_run_exactly(self):
        import torch

        straight = self.ready_config(name="straight")
        run_training(straight, loader=tiny_loader(), plan=PLAN)

        interrupted = self.ready_config(name="interrupted")
        with self.assertRaises(PipelineError):
            run_training(interrupted, loader=tiny_loader(), plan=TrainPlan(4, 2, 2, stop_after=3))
        with self.assertRaises(PipelineError) as caught:
            run_training(interrupted, loader=tiny_loader(), plan=PLAN)
        self.assertIn("resume explicitly", str(caught.exception))
        resumed = run_training(interrupted, resume=checkpoint_path(interrupted.experiment_dir, 2),
                               loader=tiny_loader(), plan=PLAN)
        self.assertEqual(resumed["mode"], "full")

        one = self.adapter(checkpoint_path(straight.experiment_dir, 4))
        two = self.adapter(checkpoint_path(interrupted.experiment_dir, 4))
        self.assertEqual(one.keys(), two.keys())
        for key in one:
            self.assertTrue(torch.equal(one[key], two[key]), key)

        def progress(config):
            state = json.loads((checkpoint_path(config.experiment_dir, 4) / "checkpoint.json").read_text(encoding="utf-8"))
            return state["coverage"], state["stream"], state["validation_nll"]

        self.assertEqual(progress(straight), progress(interrupted))
        metrics = [json.loads(l) for l in (interrupted.experiment_dir / "training_metrics.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([m["update"] for m in metrics if "loss" in m], [1, 2, 3, 4], "Metrics past the checkpoint are rewritten")

    def run_to_checkpoint(self):
        config = self.ready_config()
        with self.assertRaises(PipelineError):
            run_training(config, loader=tiny_loader(), plan=TrainPlan(4, 2, 2, stop_after=2))
        return config, checkpoint_path(config.experiment_dir, 2)

    def row_sources(self, config):
        rows = (config.sft_dir / "train.jsonl").read_text(encoding="utf-8").splitlines()
        return [json.loads(line)["provenance"]["source_id"] for line in rows]

    def test_mismatched_or_incomplete_checkpoints_are_rejected(self):
        config, path = self.run_to_checkpoint()
        sources = self.row_sources(config)
        identity = json.loads((path / "checkpoint.json").read_text(encoding="utf-8"))["identity"]
        self.assertEqual(read_checkpoint(path, sources, identity=identity)["update"], 2)
        with self.assertRaises(PipelineError) as caught:
            read_checkpoint(path, sources, identity=identity | {"plan": {}})
        self.assertEqual(caught.exception.code, "SFT_IDENTITY")
        self.assertIn("identity", str(caught.exception))

        other = TrainPlan(updates=6, evaluate_every=2, warmup=2)
        with self.assertRaises(PipelineError) as caught:
            run_training(config, resume=path, loader=tiny_loader(), plan=other)
        self.assertIn("identity", str(caught.exception))

        (path / "trainer_state.pt").write_bytes(b"changed")
        with self.assertRaises(PipelineError) as caught:
            read_checkpoint(path, sources, identity=identity)
        self.assertIn("digests", str(caught.exception))

        (path / "checkpoint.json").unlink()
        with self.assertRaises(PipelineError) as caught:
            run_training(config, resume=path, loader=tiny_loader(), plan=PLAN)
        self.assertIn("incomplete", str(caught.exception))

    def test_overstated_persisted_coverage_is_rejected(self):
        config, path = self.run_to_checkpoint()
        sources = self.row_sources(config)
        state = json.loads((path / "checkpoint.json").read_text(encoding="utf-8"))
        state["coverage"].update(unique_rows=len(sources), rows=list(range(len(sources))), complete=True)
        state["stream"]["position"] += 1
        (path / "checkpoint.json").write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaises(PipelineError) as caught:
            read_checkpoint(path, sources)
        self.assertIn("deterministic stream", str(caught.exception))

    def test_resume_must_be_the_latest_committed_checkpoint(self):
        config = self.ready_config()
        run_training(config, loader=tiny_loader(), plan=PLAN)
        with self.assertRaises(PipelineError) as caught:
            run_training(config, resume=checkpoint_path(config.experiment_dir, 2), loader=tiny_loader(), plan=PLAN)
        self.assertIn("latest", str(caught.exception))

    def test_interrupted_stage_is_ignored_and_cleaned(self):
        config, path = self.run_to_checkpoint()
        stage = path.with_name(".stage-step-0004-abc")
        stage.mkdir()
        run_training(config, resume=path, loader=tiny_loader(), plan=PLAN)
        self.assertFalse(stage.exists())

    def test_no_eligible_candidate_fails_selection_visibly(self):
        config, path = self.run_to_checkpoint()
        sources = self.row_sources(config)
        state = json.loads((path / "checkpoint.json").read_text(encoding="utf-8"))
        state.update(validation_nll=None, finite=False)
        (path / "checkpoint.json").write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaises(PipelineError) as caught:
            finalize_selection(config.experiment_dir, TrainPlan(updates=2, evaluate_every=2), sources, state["identity"])
        self.assertEqual(caught.exception.code, "SFT_SELECTION")
        record = json.loads((config.experiment_dir / "selection.json").read_text(encoding="utf-8"))
        self.assertEqual((record["status"], record["selected_update"]), ("failed", None))
        self.assertFalse((config.experiment_dir / "adapter").exists())

    def test_nonfinite_training_loss_stops_without_a_checkpoint(self):
        config = self.ready_config()

        def poisoned(config):
            runtime = tiny_loader()(config)
            import torch

            with torch.no_grad():
                for name, parameter in runtime.model.named_parameters():
                    if "lora_A" in name:
                        parameter.fill_(float("nan"))
                    if "lora_B" in name:
                        parameter.fill_(1.0)
            return runtime

        with self.assertRaises(PipelineError) as caught:
            run_training(config, loader=poisoned, plan=PLAN)
        self.assertEqual(caught.exception.code, "SFT_TRAINING")
        self.assertIn("Nonfinite", str(caught.exception))
        self.assertFalse(list(config.experiment_dir.glob("checkpoints/step-*")))

    def test_smoke_is_explicit_and_isolated_from_the_full_run(self):
        config = self.ready_config()
        report = run_training(config, smoke=True, loader=tiny_loader())
        self.assertEqual((report["mode"], report["updates"], report["frozen_unchanged"]), ("smoke", 2, True))
        self.assertFalse((config.experiment_dir / "checkpoints").exists())
        self.assertFalse((config.experiment_dir / "selection.json").exists())
        self.assertTrue((config.experiment_dir / "smoke/smoke_report.json").is_file())
        self.assertEqual(run_training(config, loader=tiny_loader(), plan=PLAN)["mode"], "full")

    def test_export_changes_after_training_are_rejected(self):
        config, path = self.run_to_checkpoint()
        config.train_jsonl.write_text(config.train_jsonl.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaises(PipelineError) as caught:
            run_training(config, resume=path, loader=tiny_loader(), plan=PLAN)
        self.assertEqual(caught.exception.code, "SFT_IDENTITY")


GPU_BASE = os.environ.get("LIFEMATE_SFT_GPU_BASE")


@unittest.skipUnless(GPU_BASE, "Set LIFEMATE_SFT_GPU_BASE to a local Qwen3 snapshot on a GPU host")
class RealGpuTests(unittest.TestCase):
    def test_nf4_recipe_trains_adapter_weights_only(self):
        from lifemate.sft import parse_config
        from lifemate.sft.data import load_tokenizer

        with tempfile.TemporaryDirectory() as root:
            config = make_config(Path(root), many_sources(), VALIDATION)
            raw = config.record()
            real = parse_config({"schema_version": 1, "data": {
                **{k: raw["data"][k] for k in ("train_jsonl", "train_catalog", "validation_jsonl", "validation_catalog", "permitted_use")},
                "train_role": "train", "validation_role": "validation"},
                "model": {"base_path": GPU_BASE},
                "training": {"recipe": RECIPE["name"], "device": "cuda:0", "seed": RECIPE["seed"], "microbatch": 1, "accumulation": 16},
                "limits": raw["limits"], "output": raw["output"]}, Path(root))
            prepare(real, tokenizer=load_tokenizer(real.base_path))
            report = run_training(real, smoke=True)
            self.assertTrue(report["frozen_unchanged"])
            self.assertGreater(report["feasibility"]["peak_allocated_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
