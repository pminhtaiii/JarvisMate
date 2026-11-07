"""Faithful next-action export: controlled sources, plus real assets when explicitly enabled.

LIFEMATE_NATIVE_TOKENIZER points at Qwen3 tokenizer files for actual-tokenizer checks.
LIFEMATE_SFT_TRAIN points at a supplied split directory for actual-source accounting.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lifemate.adapters.qwen_native import FINISH_TEXT, completion_text, parse_completion
from lifemate.contracts import PipelineError
from lifemate.sft.data import (audit_overlap, convert_source, encode_row, load_ready_export, prepare, preflight,
                               read_role, reference_values, schema_errors)
from lifemate.sft.__main__ import main
from sft_support import (ASK, CATALOG, FOUND, SEARCH, SEND, SENT, SENTINEL, WAITING, CharTokenizer, make_config, source,
                         write_role)

LOOKUP = source("train_0001", calls=[SEARCH, SEND], results=[FOUND, SENT])
EMPTY = source("train_0002", request="Chào bạn")
CLARIFY = source("train_0003", request="Nhắn Lân", calls=[SEARCH, ASK], results=[FOUND, WAITING])
VALIDATION = source("dev_0001", request="Tìm Hoa", calls=[{"name": "contacts.search", "arguments": {"query": "Hoa"}}],
                    results=[{"ok": True, "contacts": []}])



class TemporaryRoot(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def role(self, *rows, name="train"):
        jsonl, catalog = write_role(self.root / "data" / name, name, rows)
        return read_role("train" if name == "train" else "validation", jsonl, catalog)

    def converted(self, row):
        return convert_source(row, self.role(row))



class PrepareTests(TemporaryRoot):
    def run_prepare(self, config):
        return prepare(config, tokenizer=CharTokenizer())

    def test_ready_export_accounts_every_source_and_keeps_roles_apart(self):
        config = make_config(self.root, [LOOKUP, EMPTY, CLARIFY], [VALIDATION])
        result = self.run_prepare(config)
        self.assertEqual(result["state"], "ready")
        counts = result["accounting"]["train"]
        self.assertEqual((counts["sources"], counts["sources_with_rows"], counts["rows"]), (3, 3, 6))
        self.assertEqual((counts["finish_rows"], counts["clarification_rows"]), (2, 1))
        ready = load_ready_export(config)
        self.assertEqual({r["provenance"]["source_id"] for r in ready.train}, {"train_0001", "train_0002", "train_0003"})
        self.assertEqual({r["provenance"]["source_id"] for r in ready.validation}, {"dev_0001"})
        self.assertEqual(ready.manifest["protocol"]["finish_text"], FINISH_TEXT)
        self.assertEqual((config.experiment_dir / "sft/audit.jsonl").read_text(encoding="utf-8"), "")
        self.assertTrue((config.experiment_dir / "effective_config.json").is_file())

    def test_persisted_rows_render_exactly_as_before_writing(self):
        # Key order shapes the prompt: sorted schemas or arguments would differ from inference.
        arguments = {"content": "Đỗ", "contact_id": "c_07"}
        trajectory = source("train_0030", calls=[SEARCH, {"name": "sms.send", "arguments": arguments}], results=[FOUND, SENT])
        config = make_config(self.root, [trajectory], [VALIDATION])
        self.run_prepare(config)
        fresh, _ = convert_source(trajectory, read_role("train", config.train_jsonl, config.train_catalog))
        tokenizer = CharTokenizer()
        ready = load_ready_export(config)
        self.assertEqual(list(ready.train[1]["target"]["arguments"]), ["content", "contact_id"])
        for row, original in zip(ready.train, fresh):
            with self.subTest(index=row["provenance"]["decision_index"]):
                self.assertEqual(json.dumps(row["input"], ensure_ascii=False), json.dumps(original["input"], ensure_ascii=False))
                encoded = encode_row(tokenizer, row, 16384, 512)
                self.assertEqual(encoded["input_ids"], encode_row(tokenizer, original, 16384, 512)["input_ids"])
                self.assertEqual(encoded["sha256"], row["tokens"]["sha256"])

    def test_no_environment_directory_is_needed_or_touched(self):
        config = make_config(self.root, [LOOKUP], [VALIDATION])
        self.assertFalse(list(self.root.rglob("*_environment")))
        with patch("lifemate.runtime.load_runtime", side_effect=AssertionError("no ToolEnv")):
            self.assertEqual(self.run_prepare(config)["state"], "ready")

    def test_overlap_blocks_before_expansion(self):
        config = make_config(self.root, [LOOKUP], [{**LOOKUP}])
        with self.assertRaises(PipelineError) as caught:
            self.run_prepare(config)
        self.assertEqual(caught.exception.code, "SFT_BLOCKED")
        manifest = json.loads((config.sft_dir / "export_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((manifest["state"], manifest["overlap"]["id_overlap"]), ("blocked", 1))
        self.assertEqual((config.sft_dir / "train.jsonl").read_text(encoding="utf-8"), "")
        with self.assertRaises(PipelineError):
            load_ready_export(config)

    def test_unresolved_training_exclusion_blocks_with_evidence(self):
        bad = source("train_0020", calls=[SEARCH], results=[])
        config = make_config(self.root, [LOOKUP, bad], [VALIDATION])
        with self.assertRaises(PipelineError) as caught:
            self.run_prepare(config)
        self.assertIn("1 unresolved", str(caught.exception))
        entries = [json.loads(l) for l in (config.sft_dir / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(e["source_id"], e["reason"], e["status"]) for e in entries],
                         [("train_0020", "UNEQUAL_PAIRS", "unresolved")])

    def test_overflow_blocks_a_whole_source_without_truncation(self):
        long = source("train_0021", request="x" * 2000, calls=[SEARCH], results=[FOUND])
        config = make_config(self.root, [EMPTY, long], [VALIDATION], context_tokens=6000, max_new_tokens=100)
        with self.assertRaises(PipelineError):
            self.run_prepare(config)
        manifest = json.loads((config.sft_dir / "export_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["accounting"]["train"]["audit_reasons"], {"CONTEXT_OVERFLOW": 2})
        self.assertEqual(manifest["accounting"]["train"]["sources_with_rows"], 1)

    def test_reviewed_resolutions_clear_the_block_and_stay_visible(self):
        flagged = source("train_0022", calls=[SEND], results=[SENT])
        malformed = source("train_0023", calls=[SEARCH], results=[])
        resolutions = [{"source_id": "train_0022", "reason": "UNGROUNDED_ID", "decision": "keep", "note": "reviewed"},
                       {"source_id": "train_0023", "reason": "UNEQUAL_PAIRS", "decision": "exclude", "note": "reviewed"}]
        config = make_config(self.root, [LOOKUP, flagged, malformed], [VALIDATION], resolutions=resolutions)
        counts = self.run_prepare(config)["accounting"]["train"]
        self.assertEqual((counts["sources_with_rows"], counts["sources_excluded"], counts["sources_unresolved"]), (2, 1, 0))
        statuses = [json.loads(l)["status"] for l in (config.sft_dir / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(statuses, ["kept", "excluded"])
        self.assertIn("train_0022", {r["provenance"]["source_id"] for r in load_ready_export(config).train})

    def test_invalid_or_stale_resolutions_are_rejected(self):
        base = [LOOKUP, source("train_0023", calls=[SEARCH], results=[])]
        keep_structural = [{"source_id": "train_0023", "reason": "UNEQUAL_PAIRS", "decision": "keep", "note": "x"}]
        with self.assertRaises(PipelineError):
            self.run_prepare(make_config(self.root, base, [VALIDATION], resolutions=keep_structural))
        stale = [{"source_id": "train_9999", "reason": "UNGROUNDED_ID", "decision": "exclude", "note": "x"}]
        with self.assertRaises(PipelineError):
            self.run_prepare(make_config(self.root, [LOOKUP], [VALIDATION], resolutions=stale))
        noteless = [{"source_id": "train_0023", "reason": "UNEQUAL_PAIRS", "decision": "exclude", "note": ""}]
        with self.assertRaises(PipelineError):
            self.run_prepare(make_config(self.root, base, [VALIDATION], resolutions=noteless))

    def test_validation_exclusion_is_audited_without_blocking(self):
        bad = source("dev_0003", request="Khác", calls=[SEARCH], results=[])
        config = make_config(self.root, [LOOKUP], [VALIDATION, bad])
        counts = self.run_prepare(config)["accounting"]["validation"]
        self.assertEqual((counts["sources_with_rows"], counts["sources_unresolved"]), (1, 1))

    def test_all_masked_role_is_blocked(self):
        bad = source("dev_0003", request="Khác", calls=[SEARCH], results=[])
        config = make_config(self.root, [LOOKUP], [bad])
        with self.assertRaises(PipelineError) as caught:
            self.run_prepare(config)
        self.assertIn("no usable rows", str(caught.exception))

    def test_changed_source_or_export_is_rejected_after_prepare(self):
        config = make_config(self.root, [LOOKUP], [VALIDATION])
        self.run_prepare(config)
        rows = config.sft_dir / "train.jsonl"
        original = rows.read_bytes()
        rows.write_bytes(original + b"\n")
        with self.assertRaises(PipelineError) as caught:
            load_ready_export(config)
        self.assertEqual(caught.exception.code, "SFT_IDENTITY")
        rows.write_bytes(original)
        config.train_jsonl.write_text(config.train_jsonl.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaises(PipelineError) as caught:
            load_ready_export(config)
        self.assertIn("changed", str(caught.exception))

    def test_prepare_refuses_to_replace_an_export_with_checkpoints(self):
        config = make_config(self.root, [LOOKUP], [VALIDATION])
        self.run_prepare(config)
        (config.experiment_dir / "checkpoints/step-0100").mkdir(parents=True)
        with self.assertRaises(PipelineError):
            self.run_prepare(config)

    def test_preflight_and_cli_report_without_loading_a_model(self):
        config = make_config(self.root, [LOOKUP], [VALIDATION])
        report = preflight(config)
        self.assertEqual((report["overlap"]["status"], report["base"]["parameter_count"]), ("disjoint", 10))
        self.assertNotIn("files_sha256", report["base"])
        with self.assertRaises(PipelineError) as caught:
            preflight(make_config(self.root, [LOOKUP], [{**LOOKUP}]))
        self.assertEqual(caught.exception.code, "SFT_BLOCKED")
        toml = self.root / "missing.toml"
        self.assertEqual(main(["preflight", "--config", str(toml)]), 1)


TOKENIZER = os.environ.get("LIFEMATE_NATIVE_TOKENIZER")
TRAIN_DIR = os.environ.get("LIFEMATE_SFT_TRAIN")


@unittest.skipUnless(TOKENIZER, "Set LIFEMATE_NATIVE_TOKENIZER to local Qwen3 tokenizer files")
class ActualTokenizerTests(TemporaryRoot):
    @classmethod
    def setUpClass(cls):
        from lifemate.sft.data import load_tokenizer

        cls.tokenizer = load_tokenizer(Path(TOKENIZER))

    def test_export_prompt_equals_the_inference_prompt_and_targets_parse(self):
        from lifemate.adapters.qwen_native import NativePlanner

        planner = NativePlanner.__new__(NativePlanner)
        planner.tokenizer = self.tokenizer
        rows, _ = self.converted(LOOKUP)
        for row in rows:
            encoded = encode_row(self.tokenizer, row, 16384, 512)
            prompt = planner.render(row["input"], row["input"]["observations"])
            self.assertEqual(self.tokenizer(prompt, add_special_tokens=False)["input_ids"],
                             encoded["input_ids"][:encoded["prompt_tokens"]])
            target = encoded["labels"][encoded["prompt_tokens"]:]
            self.assertEqual(target[-1], self.tokenizer.convert_tokens_to_ids("<|im_end|>"))
            self.assertEqual(self.tokenizer.decode(target[:-1]), completion_text(row["target"]))
            self.assertNotIn(SENTINEL, prompt if row["provenance"]["decision_index"] < 2 else "")

    def test_prior_calls_render_identically_to_a_supervised_target(self):
        rows, _ = self.converted(LOOKUP)
        prompt = self.tokenizer.decode(encode_row(self.tokenizer, rows[1], 16384, 512)["input_ids"])
        self.assertIn(completion_text(rows[0]["target"]) + "<|im_end|>", prompt)

    def test_pad_differs_from_eos_in_this_snapshot(self):
        self.assertNotEqual(self.tokenizer.pad_token_id, self.tokenizer.eos_token_id)

    @unittest.skipUnless(TRAIN_DIR, "Set LIFEMATE_SFT_TRAIN to a supplied split directory")
    def test_supplied_sources_are_fully_accounted(self):
        from lifemate.sft.data import export_role

        config = make_config(self.root, [LOOKUP], [VALIDATION])
        base = Path(TRAIN_DIR)
        data = read_role("train", base / "train.jsonl", base / "train_tools_catalog.json")
        rows, entries, counts = export_role(data, self.tokenizer, config, {})
        self.assertEqual(counts["sources"], len(data.rows))
        self.assertEqual(counts["sources_with_rows"] + counts["sources_unresolved"] + counts["sources_excluded"], counts["sources"])
        print(json.dumps({k: v for k, v in counts.items() if k != "targets"}, ensure_ascii=False))
        print(json.dumps([{k: e[k] for k in ("source_id", "decision_index", "reason")} for e in entries]))


if __name__ == "__main__":
    unittest.main()