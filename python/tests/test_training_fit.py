"""Controlled adapter fitting and deployment merge (spec 003 T027-T030).

Controlled tests use exported rows and the character-level tokenizer double, so they
need no training library. `RealStackSmoke` runs only in the isolated training
environment: it builds a tiny random Qwen3 checkpoint with a character-level fast
tokenizer, then exports, fits on CPU, saves/reloads, merges and loads the merged
export through the native planner. It proves the code path, not Qwen3-4B memory,
GPU behavior or model quality.
"""
import contextlib
import copy
import hashlib
import importlib.metadata
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lifemate.contracts import Limits, PipelineError
from lifemate.dataset import validate_catalog
from lifemate.jsonio import digest, dumps
from lifemate.prompting import NATIVE_FINISH_TEXT, NATIVE_SYSTEM
from lifemate.provenance import model_identity
from lifemate.training import data as training_data
from lifemate.training import export as merging
from lifemate.training import fit
from lifemate.training.__main__ import main
from test_training_data import (EXPORT_CATALOG, FOUND, SEARCH, SEND, SENT, ExportCase, MergingTokenizer,
                                QwenLikeTokenizer, sample)

TRAINING_STACK = all(importlib.util.find_spec(m) for m in ("torch", "transformers", "peft", "tokenizers"))
LMFE = importlib.util.find_spec("lmformatenforcer") is not None
CUDA = TRAINING_STACK and __import__("torch").cuda.is_available()
ROWS = [sample("train_0001", calls=[SEARCH, SEND], results=[FOUND, SENT]),
        sample("train_0002", request="Kể chuyện cười"),
        sample("train_0003", request="Mở nhạc", calls=[SEARCH], results=[FOUND])]


def settings(**overrides):
    value = {"schema_version": 1, "base_model": "../models/qwen", "export_manifest": "../exports/sft-1/export_manifest.json",
             "fit_rows": "../exports/sft-1/fit.jsonl", "output_dir": "../runs/fit-1", "method": "lora",
             "device": "cpu", "seed": 20261027, "context_limit": 16384, "max_target_tokens": 512, "microbatch": 1,
             "gradient_accumulation": 16, "gradient_checkpointing": True, "learning_rate": 1e-4, "epochs": 3,
             "adapter": {"rank": 32, "alpha": 64, "dropout": 0.05, "targets": "all-linear"},
             "optimizer": "adamw_torch", "schedule": "linear", "warmup_ratio": 0.03, "checkpoint_cadence": "epoch",
             "package_lock": {"path": "../requirements-training.txt", "sha256": "0" * 64}}
    value.update(overrides)
    return value


class ConfigTests(unittest.TestCase):
    def test_paths_resolve_against_the_config_directory(self):
        base = Path(tempfile.gettempdir()) / "lifemate" / "configs"
        config = fit.validate_config(settings(), base)
        self.assertEqual(config["paths"]["output_dir"], (base.parent / "runs" / "fit-1").resolve())
        self.assertEqual(config["paths"]["package_lock"], (base.parent / "requirements-training.txt").resolve())

    def test_invalid_settings_are_rejected(self):
        extra = settings()
        extra["notes"] = "x"
        missing = settings()
        del missing["epochs"]
        cases = {"unknown field": extra, "missing field": missing, "method": settings(method="full"),
                 "qlora on cpu": settings(method="qlora"), "device": settings(device="mps"),
                 "context over cap": settings(context_limit=20_000),
                 "target not below context": settings(context_limit=512),
                 "zero microbatch": settings(microbatch=0), "boolean epochs": settings(epochs=True),
                 "zero learning rate": settings(learning_rate=0), "warmup of one": settings(warmup_ratio=1),
                 "negative seed": settings(seed=-1), "optimizer": settings(optimizer="sgd"),
                 "cadence": settings(checkpoint_cadence="steps"),
                 "empty targets": settings(adapter={"rank": 8, "alpha": 16, "dropout": 0, "targets": []}),
                 "duplicate targets": settings(adapter={"rank": 8, "alpha": 16, "dropout": 0,
                                                        "targets": ["q_proj", "q_proj"]}),
                 "adapter field": settings(adapter={"rank": 8, "alpha": 16, "dropout": 0}),
                 "lock digest": settings(package_lock={"path": "lock.txt", "sha256": "ABC"}),
                 "output inside base": settings(output_dir="../models/qwen/fit"),
                 "output inside export": settings(output_dir="../exports/sft-1/fit"),
                 "not an object": ["fit"]}
        for label, value in cases.items():
            with self.subTest(label):
                with self.assertRaises(PipelineError) as caught:
                    fit.validate_config(value, Path(tempfile.gettempdir()) / "configs")
                self.assertEqual(caught.exception.code, "INPUT_INVALID")

    def test_unreadable_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fit.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaises(PipelineError) as caught:
                fit.load_config(path)
            self.assertEqual(caught.exception.code, "INPUT_INVALID")


class PackageLockTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.lock = Path(directory.name) / "requirements-training.txt"
        self.pins = {name: "1.0" for name in fit.REQUIRED_PINS}

    def check(self, text, method="lora", installed=None):
        self.lock.write_text(text, encoding="utf-8")
        sha = hashlib.sha256(self.lock.read_bytes()).hexdigest()
        versions = installed if installed is not None else self.pins

        def version(name):
            if versions.get(name) is None:
                raise importlib.metadata.PackageNotFoundError(name)
            return versions[name]

        return fit.locked_packages(self.lock, sha, method, version)

    def lines(self, **extra):
        return "# provisional lock\n" + "".join(f"{n}=={v}\n" for n, v in (self.pins | extra).items())

    def test_matching_installed_versions_are_recorded(self):
        result = self.check(self.lines())
        self.assertEqual(result["pins"], self.pins)

    def test_mismatched_or_missing_packages_block_the_run(self):
        for label, installed in {"different": self.pins | {"peft": "2.0"}, "missing": self.pins | {"torch": None}}.items():
            with self.subTest(label):
                with self.assertRaises(PipelineError) as caught:
                    self.check(self.lines(), installed=installed)
                self.assertEqual(caught.exception.code, "MODEL_UNAVAILABLE")

    def test_repository_lock_is_exact_and_keeps_the_inference_pins(self):
        root = Path(fit.__file__).resolve().parents[3]
        pins = {}
        for line in (root / "requirements-training.txt").read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                match = fit.PIN.fullmatch(line)
                self.assertIsNotNone(match, line)
                pins[match[1].lower().replace("_", "-")] = match[2]
        self.assertTrue(set(fit.REQUIRED_PINS) | {"bitsandbytes"} <= set(pins))
        project = (root / "pyproject.toml").read_text(encoding="utf-8")
        for name in ("torch", "transformers", "numpy", "lm-format-enforcer"):
            self.assertIn(f'"{name}=={pins[name]}"', project)

    def test_lock_shape_and_identity_are_enforced(self):
        cases = {"range pin": self.lines() + "pydantic>=2\n", "missing pin": "torch==1.0\n"}
        for label, text in cases.items():
            with self.subTest(label):
                with self.assertRaises(PipelineError) as caught:
                    self.check(text)
                self.assertEqual(caught.exception.code, "INPUT_INVALID")
        with self.assertRaises(PipelineError) as caught:
            self.check(self.lines(), method="qlora")
        self.assertIn("bitsandbytes", str(caught.exception))
        self.lock.write_text(self.lines(), encoding="utf-8")
        with self.assertRaises(PipelineError) as caught:
            fit.locked_packages(self.lock, "0" * 64, "lora", lambda name: "1.0")
        self.assertEqual(caught.exception.code, "INPUT_INVALID")


class AuditedExportCase(ExportCase):
    """One export with fit rows from two samples and validation diagnostics from a third."""

    def setUp(self):
        super().setUp()
        _, files = self.export(copy.deepcopy(ROWS), validation=("train_0003",), validation_diagnostics=True)
        self.directory = self.fx.root / "exports" / "sft-1"
        self.fit_rows = files["fit.jsonl"]
        self.paths = {"export_manifest": self.directory / "export_manifest.json",
                      "fit_rows": self.directory / "fit.jsonl"}

    def subset(self, rows, name="subset.jsonl"):
        path = self.fx.root / name
        path.write_text("".join(dumps(row) + "\n" for row in rows), encoding="utf-8")
        return self.paths | {"fit_rows": path}

    def manifest_variant(self, change):
        manifest = json.loads(self.paths["export_manifest"].read_text(encoding="utf-8"))
        change(manifest)
        path = self.directory / "variant_manifest.json"
        path.write_text(dumps(manifest), encoding="utf-8")
        return self.paths | {"export_manifest": path}

    def rejected(self, paths, text=None):
        with self.assertRaises(PipelineError) as caught:
            fit.audited_rows(paths)
        self.assertEqual(caught.exception.code, "INPUT_INVALID")
        if text:
            self.assertIn(text, str(caught.exception))


class InputGateTests(AuditedExportCase):
    def test_the_full_fit_side_and_unmodified_subsets_are_accepted(self):
        rows, _, identity = fit.audited_rows(self.paths)
        self.assertEqual(rows, self.fit_rows)
        self.assertEqual((identity["fit_rows"]["rows"], identity["fit_rows"]["subset"]), (4, False))
        rows, _, identity = fit.audited_rows(self.subset(self.fit_rows[:1]))
        self.assertEqual((len(rows), identity["fit_rows"]["subset"]), (1, True))

    def test_validation_rows_never_enter_optimizer_input(self):
        self.rejected(self.paths | {"fit_rows": self.directory / "validation.next_action.jsonl"}, "validation")
        relabelled = json.loads((self.directory / "validation.next_action.jsonl").read_text("utf-8").splitlines()[0])
        relabelled["use"] = "fit"
        relabelled["provenance"]["partition"] = "fit"
        self.rejected(self.subset([relabelled]), "unmodified")

    def test_edited_duplicated_or_empty_rows_are_rejected(self):
        edited = copy.deepcopy(self.fit_rows[0])
        edited["completion"] = edited["completion"].replace("Lan", "Mai")
        self.rejected(self.subset([edited]), "unmodified")
        self.rejected(self.subset([self.fit_rows[0], self.fit_rows[0]]), "unique")
        self.rejected(self.subset([]), "no rows")

    def test_a_stale_or_unaudited_export_is_rejected(self):
        changes = {"leakage failure": lambda m: m["audits"]["leakage"].update(failures=1),
                   "shared groups": lambda m: m["audits"]["partition"].update(shared_groups=1),
                   "prompt drift": lambda m: m["protocol"]["prompt"].update(sha256="0" * 64),
                   "exporter": lambda m: m["exporter"].update(version="other-v1"),
                   "packing": lambda m: m["supervision"].update(packing=True),
                   "missing audits": lambda m: m.pop("audits")}
        for label, change in changes.items():
            with self.subTest(label):
                self.rejected(self.manifest_variant(change))
        with (self.directory / "fit.jsonl").open("a", encoding="utf-8") as stream:
            stream.write("\n")
        self.rejected(self.paths, "differs from its manifest")


class MaskAuditTests(AuditedExportCase):
    def test_labels_are_rederived_and_train_only_the_completion(self):
        rows, _, _ = fit.audited_rows(self.paths)
        examples, audit = fit.mask_audit(rows, self.tokenizer, settings())
        for row, example in zip(rows, examples):
            prompt = row["prompt_tokens"]
            self.assertEqual(example["labels"][:prompt], [training_data.IGNORE_INDEX] * prompt)
            self.assertEqual(example["labels"][prompt:], example["input_ids"][prompt:])
            self.assertEqual(example["input_ids"][-1], self.tokenizer.eos_token_id)
        self.assertEqual(audit["rows_checked"], 4)
        self.assertEqual(audit["target_tokens"], sum(r["completion_tokens"] for r in rows))
        self.assertEqual(audit["max_total_tokens"], max(r["prompt_tokens"] + r["completion_tokens"] for r in rows))

    def test_a_tokenizer_that_disagrees_with_the_export_fails_the_audit(self):
        rows, _, _ = fit.audited_rows(self.paths)
        with self.assertRaises(PipelineError) as caught:
            fit.mask_audit(rows, MergingTokenizer(), settings())
        self.assertIn("Mask audit failed", str(caught.exception))

    def test_rows_over_the_fit_budgets_stop_the_run_instead_of_being_dropped(self):
        rows, _, _ = fit.audited_rows(self.paths)
        longest = max(r["prompt_tokens"] + r["completion_tokens"] for r in rows)
        widest = max(r["completion_tokens"] for r in rows)
        for overrides in ({"context_limit": longest - 1}, {"max_target_tokens": widest - 1}):
            with self.subTest(overrides):
                with self.assertRaises(PipelineError) as caught:
                    fit.mask_audit(rows, self.tokenizer, settings(**overrides))
                self.assertEqual(caught.exception.code, "CONTEXT_LIMIT")


class BaseIdentityTests(AuditedExportCase):
    def test_the_export_base_is_verified_and_its_full_identity_recorded(self):
        _, manifest, _ = fit.audited_rows(self.paths)
        base = fit.verify_base(self.model, manifest, self.tokenizer)
        self.assertEqual(base["identity"]["files"], model_identity(self.model)["files"])

    def test_changed_base_files_or_template_are_rejected(self):
        _, manifest, _ = fit.audited_rows(self.paths)
        other = QwenLikeTokenizer()
        other.chat_template = "another template"
        with self.assertRaises(PipelineError):
            fit.verify_base(self.model, manifest, other)
        (self.model / "tokenizer_config.json").write_text('{"changed": true}', encoding="utf-8")
        with self.assertRaises(PipelineError) as caught:
            fit.verify_base(self.model, manifest, self.tokenizer)
        self.assertIn("differ from the export's base", str(caught.exception))


class FitCommandTests(AuditedExportCase):
    def setUp(self):
        super().setUp()
        self.lock = self.fx.root / "requirements-training.txt"
        self.lock.write_text("".join(f"{n}==0.0.0.not-installed\n" for n in fit.REQUIRED_PINS), encoding="utf-8")
        self.configs = self.fx.root / "configs"
        self.configs.mkdir()

    def config(self, **overrides):
        lock = {"path": "../requirements-training.txt", "sha256": hashlib.sha256(self.lock.read_bytes()).hexdigest()}
        path = self.configs / "fit.json"
        path.write_text(dumps(settings(package_lock=lock, **overrides)), encoding="utf-8")
        return path

    def run_fit(self, config):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["fit", "--config", str(config)])
        return code, json.loads(stdout.getvalue())

    def manifest(self, name="fit-1"):
        return json.loads((self.fx.root / "runs" / name / fit.RUN_MANIFEST).read_text(encoding="utf-8"))

    def test_a_failure_after_claiming_the_output_preserves_a_failed_manifest(self):
        code, summary = self.run_fit(self.config())
        self.assertEqual((code, summary["error"]["code"]), (1, "MODEL_UNAVAILABLE"))
        manifest = self.manifest()
        self.assertEqual((manifest["status"], manifest["stage"], manifest["check"]), ("failed", "preflight", "packages"))
        self.assertEqual(manifest["inputs"]["fit_rows"]["rows"], 4)
        self.assertEqual(manifest["error"]["code"], "MODEL_UNAVAILABLE")
        self.assertEqual(manifest["checkpoints"], [])

    def test_rejected_inputs_fail_before_packages_or_models_are_touched(self):
        code, summary = self.run_fit(self.config(fit_rows="../exports/sft-1/validation.next_action.jsonl"))
        self.assertEqual((code, summary["error"]["code"]), (2, "INPUT_INVALID"))
        manifest = self.manifest()
        self.assertEqual((manifest["status"], manifest["check"]), ("failed", "inputs"))
        self.assertNotIn("packages", manifest)

    def test_a_failed_first_manifest_write_is_still_recorded_as_a_failure(self):
        real, calls = fit.atomic_json, []

        def flaky(path, value):
            calls.append(value["status"])
            if len(calls) == 1:
                raise PipelineError("OUTPUT_IO", "Cannot persist run manifest", "output")
            real(path, value)

        with patch.object(fit, "atomic_json", side_effect=flaky):
            code, summary = self.run_fit(self.config())
        self.assertEqual((code, summary["error"]["code"]), (1, "OUTPUT_IO"))
        self.assertEqual(calls, ["running", "failed"])
        manifest = self.manifest()
        self.assertEqual((manifest["status"], manifest["check"], manifest["error"]["code"]),
                         ("failed", "inputs", "OUTPUT_IO"))

    def test_an_existing_output_is_never_reused(self):
        existing = self.fx.root / "runs" / "fit-1"
        existing.mkdir(parents=True)
        code, summary = self.run_fit(self.config())
        self.assertEqual((code, summary["error"]["code"]), (2, "INPUT_INVALID"))
        self.assertEqual(list(existing.iterdir()), [])


class MergeRejectionTests(ExportCase):
    """Every merge refusal happens before training libraries load or the output exists."""

    def setUp(self):
        super().setUp()
        self.adapter = self.fx.root / "runs" / "fit-1" / "checkpoint-epoch-1"
        self.adapter.mkdir(parents=True)
        (self.adapter / fit.ADAPTER_CONFIG).write_text('{"r": 8, "lora_alpha": 16}', encoding="utf-8")
        (self.adapter / fit.ADAPTER_WEIGHTS).write_bytes(b"weights")
        self.provenance = {"trainer": fit.TRAINER_VERSION,
                           "protocol": {"protocol": "qwen-native-v1", "prompt": fit.native_prompt_identity(),
                                        "final_text": NATIVE_FINISH_TEXT},
                           "base_model": {"files": model_identity(self.model)["files"],
                                          "chat_template_sha256": "0" * 64},
                           "adapter_sha256": digest(self.adapter / fit.ADAPTER_WEIGHTS),
                           "adapter_config_sha256": digest(self.adapter / fit.ADAPTER_CONFIG)}
        self.write_provenance()
        self.output = self.fx.root / "deployment"

    def write_provenance(self, **changes):
        (self.adapter / fit.ADAPTER_PROVENANCE).write_text(dumps(self.provenance | changes), encoding="utf-8")

    def run_merge(self, output=None):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["merge", "--base-model", str(self.model), "--adapter", str(self.adapter),
                         "--output", str(output or self.output)])
        return code, json.loads(stdout.getvalue())

    def refused(self, text, output=None):
        with patch.object(fit, "libraries", side_effect=AssertionError("libraries loaded")):
            code, summary = self.run_merge(output)
        self.assertEqual((code, summary["error"]["code"]), (2, "INPUT_INVALID"))
        self.assertIn(text, summary["error"]["message"])
        self.assertFalse(self.output.exists())

    def test_an_adapter_trained_on_a_different_base_is_refused(self):
        (self.model / "config.json").write_text('{"num_hidden_layers": 3}', encoding="utf-8")
        self.refused("different base")

    def test_incomplete_tampered_or_foreign_adapters_are_refused(self):
        (self.adapter / fit.ADAPTER_WEIGHTS).write_bytes(b"other weights")
        self.refused("differ from their recorded provenance")
        (self.adapter / fit.ADAPTER_WEIGHTS).write_bytes(b"weights")
        self.write_provenance(protocol=self.provenance["protocol"] | {"protocol": "structured-v1"})
        self.refused("native protocol")
        self.write_provenance(trainer="other-trainer")
        self.refused("native protocol")
        (self.adapter / fit.ADAPTER_PROVENANCE).unlink()
        self.refused("complete checkpoint")

    def test_a_changed_adapter_config_is_refused(self):
        # r and lora_alpha set the scaling the merge applies.
        (self.adapter / fit.ADAPTER_CONFIG).write_text('{"r": 8, "lora_alpha": 64}', encoding="utf-8")
        self.refused("configuration differs")

    def test_an_adapter_trained_with_another_prompt_or_final_text_is_refused(self):
        native = self.provenance["protocol"]
        for label, protocol in {"prompt": native | {"prompt": native["prompt"] | {"sha256": "0" * 64}},
                                "final text": native | {"final_text": "Xong."}}.items():
            with self.subTest(label):
                self.write_provenance(protocol=protocol)
                self.refused("different native prompt or final text")

    def test_the_output_appears_only_after_a_completed_merge(self):
        seen = {}

        def merged(torch, hf, peft, base, adapter, staging, provenance, identity):
            # A process killed here would leave only the hidden staging directory.
            (staging / "config.json").write_text("{}", encoding="utf-8")
            seen["output_during_merge"] = self.output.exists()
            seen["staging"] = staging
            return {"status": "completed"}

        with patch.object(fit, "libraries", return_value=(None, None, None)), \
                patch.object(merging, "_merge", side_effect=merged):
            self.assertEqual(merging.merge(self.model, self.adapter, self.output), {"status": "completed"})
        self.assertFalse(seen["output_during_merge"])
        self.assertEqual(seen["staging"].parent, self.output.parent)
        self.assertTrue(seen["staging"].name.startswith("."))
        self.assertEqual([p.name for p in self.output.iterdir()], ["config.json"])
        self.assertFalse(seen["staging"].exists())

    def test_a_failed_merge_leaves_neither_output_nor_staging(self):
        def broken(torch, hf, peft, base, adapter, staging, provenance, identity):
            (staging / "model.safetensors").write_bytes(b"partial")
            raise RuntimeError("disk full")

        with patch.object(fit, "libraries", return_value=(None, None, None)), \
                patch.object(merging, "_merge", side_effect=broken):
            with self.assertRaises(PipelineError) as caught:
                merging.merge(self.model, self.adapter, self.output)
        self.assertEqual(caught.exception.code, "MODEL_UNAVAILABLE")
        self.assertEqual(list(self.output.parent.glob("*deployment*")), [])

    def test_existing_or_nested_outputs_are_refused(self):
        self.refused("outside", output=self.model / "merged")
        self.refused("outside", output=self.adapter / "merged")
        self.output.mkdir()
        with patch.object(fit, "libraries", side_effect=AssertionError("libraries loaded")):
            code, summary = self.run_merge()
        self.assertEqual((code, summary["error"]["code"]), (2, "INPUT_INVALID"))
        self.assertEqual(list(self.output.iterdir()), [])

    @unittest.skipIf(TRAINING_STACK, "Checks the missing-library path only outside the training environment")
    def test_missing_training_libraries_fail_before_the_output_is_claimed(self):
        code, summary = self.run_merge()
        self.assertEqual((code, summary["error"]["code"]), (1, "MODEL_UNAVAILABLE"))
        self.assertFalse(self.output.exists())


# ---------------------------------------------------------------------------
# Real training stack on a tiny random Qwen3 checkpoint (isolated environment only)
# ---------------------------------------------------------------------------

TEMPLATE = (
    "{%- for message in messages %}"
    "{%- if message.role == 'system' %}"
    "{{- '<|im_start|>system\\n' + message.content }}"
    "{%- if tools %}{{- '\\n\\n# Tools\\n<tools>' }}{%- for tool in tools %}{{- '\\n' + (tool | tojson) }}"
    "{%- endfor %}{{- '\\n</tools>' }}{%- endif %}{{- '<|im_end|>\\n' }}"
    "{%- elif message.role == 'assistant' %}{{- '<|im_start|>assistant\\n' + message.content }}"
    "{%- for call in message.tool_calls or [] %}{%- if not loop.first or message.content %}{{- '\\n' }}{%- endif %}"
    "{{- '<tool_call>\\n{\"name\": \"' + call.function.name + '\", \"arguments\": ' + (call.function.arguments | tojson)"
    " + '}\\n</tool_call>' }}{%- endfor %}{{- '<|im_end|>\\n' }}"
    "{%- elif message.role == 'tool' %}"
    "{{- '<|im_start|>user\\n<tool_response>\\n' + message.content + '\\n</tool_response><|im_end|>\\n' }}"
    "{%- else %}{{- '<|im_start|>' + message.role + '\\n' + message.content + '<|im_end|>\\n' }}{%- endif %}"
    "{%- endfor %}{%- if add_generation_prompt %}{{- '<|im_start|>assistant\\n' }}{%- endif %}")


def tiny_qwen3(directory: Path, seed: int) -> None:
    """A random two-layer Qwen3 with a character-level fast tokenizer and a Qwen3-style tool template."""
    import torch
    from tokenizers import Regex, Tokenizer, decoders, models, pre_tokenizers
    from transformers import PreTrainedTokenizerFast, Qwen3Config, Qwen3ForCausalLM

    ranges = [(32, 127), (0xC0, 0x250), (0x1EA0, 0x1F00), (0x2010, 0x2030)]
    characters = ["\n"] + [chr(c) for low, high in ranges for c in range(low, high)]
    characters += sorted(set(NATIVE_SYSTEM) - set(characters))
    vocabulary = {token: index for index, token in
                  enumerate(["<unk>", "<|im_start|>", "<|im_end|>", "<|endoftext|>"] + characters)}
    backend = Tokenizer(models.WordLevel(vocabulary, unk_token="<unk>"))
    backend.pre_tokenizer = pre_tokenizers.Split(Regex(r"[\s\S]"), behavior="isolated")
    backend.decoder = decoders.Fuse()
    tokenizer = PreTrainedTokenizerFast(tokenizer_object=backend, unk_token="<unk>", eos_token="<|im_end|>",
                                        pad_token="<|endoftext|>", additional_special_tokens=["<|im_start|>"],
                                        clean_up_tokenization_spaces=False,
                                        model_input_names=["input_ids", "attention_mask"])
    tokenizer.chat_template = TEMPLATE
    tokenizer.save_pretrained(directory)
    torch.manual_seed(seed)
    config = Qwen3Config(vocab_size=len(vocabulary), hidden_size=32, intermediate_size=64, num_hidden_layers=2,
                         num_attention_heads=4, num_key_value_heads=2, head_dim=8, max_position_embeddings=32768,
                         tie_word_embeddings=True, eos_token_id=2, pad_token_id=3, bos_token_id=None)
    Qwen3ForCausalLM(config).save_pretrained(directory)


@unittest.skipUnless(TRAINING_STACK, "Needs the isolated training environment (python/requirements-training.txt)")
class RealStackSmoke(AuditedExportCase):
    def setUp(self):
        from transformers import AutoTokenizer

        ExportCase.setUp(self)
        for path in self.model.iterdir():
            path.unlink()
        tiny_qwen3(self.model, seed=0)
        self.tokenizer = AutoTokenizer.from_pretrained(self.model, local_files_only=True)
        _, files = self.export(copy.deepcopy(ROWS), validation=("train_0003",), validation_diagnostics=True)
        self.directory = self.fx.root / "exports" / "sft-1"
        self.fit_rows = files["fit.jsonl"]
        self.paths = {"export_manifest": self.directory / "export_manifest.json",
                      "fit_rows": self.directory / "fit.jsonl"}
        self.lock = self.fx.root / "requirements-training.txt"
        self.lock.write_text("".join(f"{n}=={importlib.metadata.version(n)}\n" for n in fit.REQUIRED_PINS),
                             encoding="utf-8")
        self.configs = self.fx.root / "configs"
        self.configs.mkdir()

    def invoke(self, command, *arguments):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main([command, *arguments])
        return code, json.loads(stdout.getvalue())

    def fit_run(self, name, *flags, **overrides):
        lock = {"path": "../requirements-training.txt", "sha256": hashlib.sha256(self.lock.read_bytes()).hexdigest()}
        values = settings(package_lock=lock, output_dir=f"../runs/{name}", epochs=2, microbatch=2,
                          gradient_accumulation=1, learning_rate=1e-3,
                          adapter={"rank": 4, "alpha": 8, "dropout": 0.05, "targets": "all-linear"}) | overrides
        path = self.configs / f"{name}.json"
        path.write_text(dumps(values), encoding="utf-8")
        code, summary = self.invoke("fit", "--config", str(path), *flags)
        self.assertEqual(code, 0, summary)
        return json.loads((self.fx.root / "runs" / name / fit.RUN_MANIFEST).read_text(encoding="utf-8"))

    def test_fit_trains_saves_and_reloads_adapters_deterministically(self):
        first = self.fit_run("fit-a")
        self.assertEqual((first["status"], first["stage"]), ("completed", "adapter-saved"))
        self.assertEqual((first["mask_audit"]["rows_checked"], first["mask_audit"]["failures"]), (4, 0))
        self.assertEqual(first["memory"]["probe_tokens"], first["mask_audit"]["max_total_tokens"])
        self.assertEqual(first["training"]["optimizer_steps"], 4)
        self.assertTrue(first["model"]["trainable_parameters"] > 0)
        self.assertEqual([c["epoch"] for c in first["checkpoints"]], [1, 2])
        for checkpoint in first["checkpoints"]:
            path = Path(checkpoint["path"])
            self.assertTrue(checkpoint["reload_verified"])
            provenance = json.loads((path / fit.ADAPTER_PROVENANCE).read_text(encoding="utf-8"))
            self.assertEqual(provenance["base_model"]["files"], model_identity(self.model)["files"])
            self.assertEqual(provenance["adapter_sha256"], digest(path / fit.ADAPTER_WEIGHTS))
        second = self.fit_run("fit-b")
        self.assertEqual([c["adapter_sha256"] for c in first["checkpoints"]],
                         [c["adapter_sha256"] for c in second["checkpoints"]])

    def test_preflight_only_measures_without_updating_weights(self):
        manifest = self.fit_run("preflight", "--preflight-only")
        self.assertEqual((manifest["status"], manifest["checkpoints"]), ("preflight-passed", []))
        self.assertIn("optimizer_state_bytes_estimate", manifest["memory"])
        # The probe bounds every microbatch: the longest rows with the longest completion's logits.
        self.assertEqual((manifest["memory"]["probe_tokens"], manifest["memory"]["probe_completion_tokens"]),
                         (manifest["mask_audit"]["max_total_tokens"], manifest["mask_audit"]["max_completion_tokens"]))
        self.assertEqual(sorted(p.name for p in (self.fx.root / "runs" / "preflight").iterdir()), [fit.RUN_MANIFEST])

    def test_the_probe_batch_keeps_logits_for_the_longest_completion(self):
        import torch

        short = {"input_ids": [5, 6, 7, 8, 2], "labels": [-100, -100, -100, 8, 2], "completion_tokens": 2}
        ids, _, _, targets, keep = fit._batch(torch, [short], 3, "cpu", keep=5)
        self.assertEqual((keep, tuple(targets.shape)), (5, (1, 4)))
        self.assertEqual(targets.tolist(), [[-100, -100, 8, 2]])
        self.assertEqual(fit._batch(torch, [short], 3, "cpu")[4], 3)

    @unittest.skipUnless(CUDA, "QLoRA needs CUDA and bitsandbytes")
    def test_qlora_preflight_on_cuda(self):
        # QLoRA requires a bitsandbytes pin in the lock.
        with self.lock.open("a", encoding="utf-8") as stream:
            stream.write(f"bitsandbytes=={importlib.metadata.version('bitsandbytes')}\n")
        manifest = self.fit_run("qlora", "--preflight-only", method="qlora", device="cuda")
        self.assertEqual(manifest["model"]["qlora"]["quant_type"], "nf4")
        self.assertGreater(manifest["memory"]["peak_allocated_bytes"], 0)

    def test_merged_export_is_self_contained_and_runs_the_native_protocol(self):
        finish = [row for row in self.fit_rows if row["canonical_target"] == {"action": "finish"}]
        subset = self.fx.root / "finish.jsonl"
        subset.write_text("".join(dumps(row) + "\n" for row in finish), encoding="utf-8")
        manifest = self.fit_run("fit-finish", fit_rows="../finish.jsonl", epochs=12, learning_rate=0.05,
                                adapter={"rank": 8, "alpha": 16, "dropout": 0.0, "targets": "all-linear"})
        adapter = manifest["checkpoints"][-1]["path"]
        output = self.fx.root / "deployment"
        code, summary = self.invoke("merge", "--base-model", str(self.model), "--adapter", adapter,
                                 "--output", str(output))
        self.assertEqual(code, 0, summary)
        marker = json.loads((output / merging.EXPORT_MARKER).read_text(encoding="utf-8"))
        self.assertTrue(marker["reload_verified"])
        self.assertEqual(marker["parameters"]["deployed"], marker["parameters"]["base"])
        for name in merging.tokenizer_files(self.model):
            self.assertEqual(digest(output / name), digest(self.model / name))
        self.assertFalse((output / fit.ADAPTER_WEIGHTS).exists())

        other = self.fx.root / "models" / "other"
        other.mkdir()
        tiny_qwen3(other, seed=1)
        code, summary = self.invoke("merge", "--base-model", str(other), "--adapter", adapter,
                                 "--output", str(self.fx.root / "other-deployment"))
        self.assertEqual((code, summary["error"]["code"]), (2, "INPUT_INVALID"))
        self.assertFalse((self.fx.root / "other-deployment").exists())

        if not LMFE:
            self.skipTest("Native planner load needs lm-format-enforcer")
        from lifemate.adapters.planner import LocalPlanner

        member = {"id": "train_0002", "group_id": "g-train_0002", "partition": "fit", "source_sha256": "0" * 64}
        rows, _ = training_data.gold_rows(self.fx.rows[1], member, validate_catalog(EXPORT_CATALOG), self.fx.data)
        planner = LocalPlanner(output, "cpu", Limits(), protocol="qwen-native-v1")
        self.assertEqual(json.loads(planner.next_action(rows[-1]["input"], 120)), {"action": "finish"})
        self.assertEqual(planner.last_native_outputs[-1]["stop_reason"], "eos")


if __name__ == "__main__":
    unittest.main()
