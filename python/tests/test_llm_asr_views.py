"""Cache partition/turn/audio binding and identical A projection for generation/NLL."""
import copy
import hashlib
import json
import unittest
import wave
from pathlib import Path

from lifemate.llm_training.asr_views import ASR_HANDOFF, ASR_DECODING, CACHE_SCHEMA, CacheASR
from lifemate.llm_training.config import DEFAULT_SELECTION_POLICY, content_hash, load_config
from lifemate.llm_training.corpus import load_suite, prepare, seal_selection_policy
from lifemate.llm_training.evaluation import run_teacher_forced
from lifemate.llm_training.storage import file_hash, ordered_hash, read_json, write_json, write_jsonl
from lifemate.adapters.qwen_native import NativeParse
from llm_support import ROWS, SuiteFixture, accept_fixture


class CacheTests(unittest.TestCase):
    def setUp(self):
        rows = copy.deepcopy(ROWS)
        source = next(r for r in rows if r["id"] == "train_0009")
        source["history"] = [{"role": "user", "audio_text": "G_HISTORY", "audio": "audio/train_0009/history.wav"},
                             {"role": "assistant", "text": "UNCHANGED_ASSISTANT"}]
        self.fx = SuiteFixture(rows=rows)
        self.addCleanup(self.fx.close)
        export = self.fx.root/"resources/asr"
        export.mkdir()
        write_json(export/"config.json", {"model_type": "whisper", "architectures":["WhisperForConditionalGeneration"],
                   "d_model":1280,"encoder_layers":32,"decoder_layers":32})
        write_json(export/"preprocessor_config.json", {"sampling_rate": 16000})
        for name in ("tokenizer_config.json","vocab.json","merges.txt"):
            (export/name).write_text("controlled processor fixture",encoding="utf-8")
        (export/"model.safetensors").write_bytes(b"controlled ASR export, not model weights")
        files = {p.name: file_hash(p) for p in export.iterdir()}
        self.export = export
        self.cache = self.fx.root/"resources/validation-cache.jsonl"
        raw = read_json(self.fx.config_path)
        raw.update(asr_model_dir="resources/asr", validation_asr_cache="resources/validation-cache.jsonl")
        self.fx.config_path.write_text(json.dumps(raw), encoding="utf-8")
        self.config = load_config(self.fx.config_path)
        prepare(self.config, self.fx.suite, expected=self.fx.expected)
        accept_fixture(self.config, self.fx.suite)
        seal_selection_policy(self.fx.suite, DEFAULT_SELECTION_POLICY)
        self.partition = load_suite(self.fx.suite)["partition"]
        processor_hash=content_hash({n:h for n,h in files.items() if n in {"preprocessor_config.json","tokenizer_config.json","vocab.json","merges.txt"}})
        self.handoff = {"schema": ASR_HANDOFF, "base_model": "vinai/PhoWhisper-large", "base_revision":"e"*40,"selected_experiment": "E4",
            "checkpoint_sha256": "c"*64, "processor_sha256": processor_hash,
            "selection": {"experiment": "E4", "checkpoint_sha256": "c"*64},
            "training_source_ids": self.partition["fit_ids"], "split_identity": self.partition["split_identity"],
            "files": files, "logical_parameters": 1550000000, "decoding": ASR_DECODING}
        write_json(export/"selection-policy.json", {"controlled_frozen_policy":True})
        policy_hash=file_hash(export/"selection-policy.json")
        write_json(export/"selection-evidence.json", {"schema":"lifemate-asr-selection-evidence-v1", "status":"selected",
            "experiment":"E4", "checkpoint_sha256":"c"*64, "policy_sha256":policy_hash,
            "fit_membership_sha256":content_hash(sorted(self.partition["fit_ids"])), "export_files_sha256":content_hash(files)})
        self.handoff["selection"].update(policy_file="selection-policy.json",policy_sha256=policy_hash,
            evidence_file="selection-evidence.json",evidence_sha256=file_hash(export/"selection-evidence.json"))
        write_json(export/"llm-handoff.json", self.handoff)
        export_id = ordered_hash(self.handoff)
        turns = []
        for src in rows:
            if src["id"] not in self.partition["validation_ids"]:
                continue
            slots = [("current", src["audio"], "A_CURRENT")]
            slots += [(f"history:{i}", t["audio"], "A_HISTORY") for i, t in enumerate(src["history"]) if t["role"] == "user"]
            for turn, relative, text in slots:
                path = self.fx.data/"train"/relative
                path.parent.mkdir(parents=True, exist_ok=True)
                pcm = b"\0\0"*160
                with wave.open(str(path), "wb") as f:
                    f.setparams((1,2,16000,0,"NONE","not compressed"))
                    f.writeframes(pcm)
                turns.append({"source_id": src["id"], "group_id": self.partition["sources"][src["id"]]["group"],
                    "partition": "validation", "turn": turn, "audio": relative, "wav_sha256": file_hash(path),
                    "pcm_sha256": hashlib.sha256(pcm).hexdigest(), "export_identity": export_id,
                    "processor_sha256": self.handoff["processor_sha256"], "decoding_sha256": content_hash(self.handoff["decoding"]),
                    "status": "ok", "transcript": text, "elapsed": .1})
        self.turns = turns
        self.write_cache()

    def write_cache(self):
        write_jsonl(self.cache, self.turns, exclusive=False)
        write_json(self.cache.with_suffix(".manifest.json"), {"schema": CACHE_SCHEMA, "partition": "validation",
            "split_identity": self.partition["split_identity"], "export_identity": ordered_hash(self.handoff),
            "cache_sha256": file_hash(self.cache), "packages": {"controlled": "1"}}, exclusive=False)

    def test_real_producer_schema_is_consumed_by_the_strict_cache_adapter(self):
        from lifemate.llm_training.asr_handoff import cache_partition
        from lifemate.llm_training.asr_views import validate_export
        from types import SimpleNamespace
        requested=[{k:row[k] for k in ('source_id','group_id','partition','turn','audio','wav_sha256','pcm_sha256')}
                   for row in self.turns]
        output=self.fx.root/'resources/produced-validation.jsonl'
        fake=SimpleNamespace(transcribe=lambda audio,timeout:'ACTUAL_TEST_ADAPTER_PREDICTION')
        export=validate_export(self.export,self.partition)
        cache_partition(self.config,requested,export,output,fake,600.)
        loaded=CacheASR(output,self.config,self.partition)
        self.assertEqual(len(loaded.turns),len(self.turns))
        self.assertEqual({row['transcript'] for row in loaded.turns.values()},{'ACTUAL_TEST_ADAPTER_PREDICTION'})

    def test_teacher_forced_a_generation_and_nll_share_projected_history_and_request(self):
        asr = CacheASR(self.cache, self.config, self.partition)
        class Backend:
            def __init__(self):
                self.generation, self.loss = [], []
            def decide(self, messages, tools, allowed):
                self.generation.append(copy.deepcopy(messages))
                return NativeParse("final", metadata={"eos_observed": True})
            def nll(self, row):
                self.loss.append(copy.deepcopy(row["input"]["messages"]))
                return .5
        backend = Backend()
        result = run_teacher_forced(suite_dir=self.fx.suite, experiment="L0", mode="A", backend=backend,
                                   model_identity={"controlled": True}, transcripts=asr, config=self.config)
        self.assertEqual(backend.generation, backend.loss)
        rendered = json.dumps(backend.generation, ensure_ascii=False)
        self.assertIn("A_CURRENT", rendered)
        self.assertIn("A_HISTORY", rendered)
        self.assertNotIn("G_HISTORY", rendered)
        self.assertIn("UNCHANGED_ASSISTANT", rendered)

    def test_missing_history_failed_turn_partition_and_changed_audio_never_gold_fallback(self):
        original = copy.deepcopy(self.turns)
        self.turns = [r for r in original if not r["turn"].startswith("history")]
        self.write_cache()
        with self.assertRaises(ValueError):
            CacheASR(self.cache, self.config, self.partition)
        self.turns = original
        self.turns[0]["partition"] = "fit"
        self.write_cache()
        with self.assertRaises(ValueError):
            CacheASR(self.cache, self.config, self.partition)
        self.turns[0]["partition"] = "validation"
        self.write_cache()
        asr = CacheASR(self.cache, self.config, self.partition)
        path = self.fx.data/"train"/self.turns[0]["audio"]
        path.write_bytes(path.read_bytes()+b"mutated")
        with self.assertRaises(Exception):
            asr.transcribe(path, 10)

    def test_asr_fit_membership_cannot_include_validation(self):
        self.handoff["training_source_ids"] += [self.partition["validation_ids"][0]]
        write_json(self.export/"llm-handoff.json", self.handoff, exclusive=False)
        with self.assertRaises(ValueError):
            CacheASR(self.cache, self.config, self.partition)


if __name__ == "__main__":
    unittest.main()
