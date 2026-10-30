"""Model-free behavioral tests. All audio and records below are synthetic."""
from __future__ import annotations

import copy
from pathlib import Path
import struct
import tempfile
import time
import unittest
import wave

from lifemate.contracts import PipelineError
from lifemate.jsonio import digest, dumps, loads

from asr.pretrained.cli import main
from asr.pretrained.data import group_samples, load_selection, make_split, project_train
from asr.pretrained.metrics import normalize, percentile95, score, summarize
from asr.pretrained.models import local_spec, require_paired_source
from asr.pretrained.runner import result_row, run_configuration


class Dataset:
    def __init__(self, root: Path):
        self.root = root
        self.base = root / "train"
        self.base.mkdir()
        self.rows = []
        texts = ["Gửi thư cho Mai", "Tắt đèn phòng ngủ", "Mở bản đồ Hà Nội",
                 "Tìm quán bún bò", "Đọc tin thể thao", "Đặt báo thức sáng mai",
                 "Kiểm tra tài khoản ngân hàng", "Phát nhạc Trịnh Công Sơn"]
        for index, text in enumerate(texts):
            relative = f"audio/s{index}/current.wav"
            self.wav(relative, index + 1)
            self.rows.append({"id": f"s{index}", "audio": relative, "audio_text": text,
                              "history": [], "context": {"do_not_use": "CONTEXT_SENTINEL"},
                              "label": {"do_not_use": "LABEL_SENTINEL"}})
        self.save()

    def wav(self, relative, value):
        path = self.base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(struct.pack("<h", value) * 160)

    def save(self):
        (self.base / "train.jsonl").write_text("".join(dumps(r) + "\n" for r in self.rows), encoding="utf-8")


def controlled_worker(connection, spec, settings):
    """Tests the real supervisor without loading optional inference packages."""
    if settings.get("test_behavior") == "load_error":
        connection.send({"status": "error", "error": "controlled load failure"})
        connection.close()
        return
    connection.send({"status": "ready", "load_seconds": .001, "model": {"test_only": True}})
    while True:
        request = connection.recv()
        if request is None:
            break
        if not isinstance(request, str) or not request.endswith(".wav"):
            raise AssertionError("Worker must receive only a WAV path")
        if settings.get("test_behavior") == "timeout":
            time.sleep(2)
        connection.send({"status": "ok", "prediction": "", "latency_seconds": .01})
    connection.close()


class MetricsTests(unittest.TestCase):
    def test_normalization_preserves_accents_numbers_and_symbols(self):
        self.assertEqual(normalize("  HẸN,  12:30; giá 50.000₫! "), "hẹn 12 30 giá 50 000₫")
        self.assertEqual(normalize("Đa\u0300 Nă\u0303ng"), "đà nẵng")

    def test_corpus_wer_uses_total_reference_units(self):
        rows = [result_row({"reference": "một", "duration_seconds": 1},
                           {"status": "ok", "prediction": "hai", "latency_seconds": 1}),
                result_row({"reference": "a b c d e f g h i", "duration_seconds": 9},
                           {"status": "ok", "prediction": "a b c d e f g h i", "latency_seconds": 2})]
        report = summarize(rows)
        self.assertEqual(report["normalized_wer"], .1)
        self.assertEqual(report["rtf"], .3)
        self.assertEqual(report["p95_latency_seconds"], 2)

    def test_empty_reference_insertions_and_undefined_denominator(self):
        self.assertEqual(score("", "xin chào")["raw"]["wer"]["insertions"], 2)
        row = result_row({"reference": "", "duration_seconds": 1},
                         {"status": "ok", "prediction": "xin", "latency_seconds": .1})
        self.assertIsNone(summarize([row])["raw_wer"])

    def test_failure_is_not_removed_from_wer_denominator(self):
        rows = [result_row({"reference": "xin chào", "duration_seconds": 2},
                           {"status": "timeout", "error": "deadline", "latency_seconds": 1}),
                result_row({"reference": "đặt báo thức", "duration_seconds": 1}, {"status": "not_run"})]
        report = summarize(rows)
        self.assertEqual(report["normalized_wer"], 1)
        self.assertEqual(report["coverage"], 0)
        self.assertEqual(report["timeouts"], 1)
        self.assertEqual(report["not_run"], 1)
        self.assertEqual(report["rtf"], .5)
        self.assertEqual(report["measured_utterances"], 1)

    def test_edit_counts_and_p95(self):
        counts = score("a b c", "a d c e")["raw"]["wer"]
        self.assertEqual((counts["substitutions"], counts["insertions"], counts["errors"]), (1, 1, 2))
        self.assertEqual(percentile95(list(range(1, 101))), 95)


class DataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = Dataset(self.root)

    def manifest(self):
        manifest = make_split(self.root)
        path = self.root / "split.json"
        path.write_text(dumps(manifest), encoding="utf-8")
        return path, manifest

    def test_projection_aligns_history_and_drops_context_labels_assistant(self):
        self.data.wav("audio/s0/user.wav", 99)
        self.data.rows[0]["history"] = [
            {"role": "assistant", "text": "ASSISTANT_SENTINEL"},
            {"role": "user", "audio": "audio/s0/user.wav", "audio_text": "Chào buổi chiều"}]
        self.data.save()
        samples, _ = project_train(self.root)
        utterances = samples[0]["utterances"]
        self.assertEqual([u["turn_id"] for u in utterances], ["history_001", "current"])
        self.assertEqual(utterances[0]["reference"], "Chào buổi chiều")
        for forbidden in ("CONTEXT_SENTINEL", "LABEL_SENTINEL", "ASSISTANT_SENTINEL"):
            self.assertNotIn(forbidden, dumps(samples))

    def test_grouping_is_transitive_across_audio_and_history(self):
        # s0 and s1 share PCM, s1 and s2 share a user-history transcript.
        self.data.wav(self.data.rows[1]["audio"], 1)
        for index in (1, 2):
            relative = f"audio/s{index}/history.wav"
            self.data.wav(relative, 50 + index)
            self.data.rows[index]["history"] = [{"role": "user", "audio": relative,
                                                  "audio_text": "Hội thoại chung trước đó"}]
        self.data.save()
        path, manifest = self.manifest()
        memberships = {s["id"]: (s["group"], s["partition"]) for s in manifest["samples"]}
        self.assertEqual(memberships["s0"], memberships["s1"])
        self.assertEqual(memberships["s1"], memberships["s2"])
        self.assertEqual(manifest["seed"], 42)
        self.assertEqual(make_split(self.root), manifest)
        _, current = load_selection(path, self.root, "current")
        self.assertTrue(all(u["turn_id"] == "current" for u in current))

    def test_numeric_templates_and_near_text_stay_together(self):
        samples, _ = project_train(self.root)
        samples[0]["utterances"][0]["reference"] = "Hẹn gặp bạn vào lúc 12 giờ"
        samples[1]["utterances"][0]["reference"] = "Hẹn gặp bạn vào lúc 15 giờ"
        text = "Nhờ bạn gửi giúp cho tôi một lời nhắc mang theo đầy đủ giấy tờ trước khi đi họp vào buổi sáng hôm nay"
        samples[2]["utterances"][0]["reference"] = text
        samples[3]["utterances"][0]["reference"] = text.replace("sáng", "chiều")
        groups, reasons = group_samples(samples)
        self.assertTrue(any({"s0", "s1"} <= set(g) for g in groups))
        self.assertTrue(any({"s2", "s3"} <= set(g) for g in groups))
        self.assertGreater(reasons.get("near_text", 0), 0)

    def test_history_scope_expands_the_same_frozen_validation(self):
        for index, record in enumerate(self.data.rows):
            relative = f"audio/s{index}/user.wav"
            self.data.wav(relative, 100 + index)
            record["history"] = [{"role": "user", "audio": relative,
                                   "audio_text": record["audio_text"] + " giúp tôi"}]
        self.data.save()
        path, _ = self.manifest()
        frozen, current = load_selection(path, self.root, "current")
        expanded, history = load_selection(path, self.root, "with-history")
        self.assertEqual(frozen["identity"], expanded["identity"])
        self.assertEqual({u["sample_id"] for u in current}, {u["sample_id"] for u in history})
        self.assertEqual(len(history), 2 * len(current))

    def test_single_connected_group_is_rejected(self):
        for row in self.data.rows:
            row["audio_text"] = "Cùng một yêu cầu"
        self.data.save()
        with self.assertRaisesRegex(ValueError, "fewer than two groups"):
            make_split(self.root)

    def test_missing_or_changed_selected_wav_is_rejected(self):
        path, _ = self.manifest()
        _, selected = load_selection(path, self.root, "current")
        self.data.wav(selected[0]["audio"], 1234)
        with self.assertRaisesRegex(ValueError, "Changed audio"):
            load_selection(path, self.root, "current")
        (self.data.base / selected[0]["audio"]).unlink()
        with self.assertRaises(PipelineError):
            load_selection(path, self.root, "current")

    def test_changed_source_and_tampered_manifest_are_rejected(self):
        path, manifest = self.manifest()
        manifest["seed"] = 43
        path.write_text(dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            load_selection(path, self.root, "current")
        path, _ = self.manifest()
        self.data.rows[0]["audio_text"] = "Thay đổi transcript"
        self.data.save()
        with self.assertRaisesRegex(ValueError, "Source JSONL changed"):
            load_selection(path, self.root, "current")

    def test_missing_reference_fails_instead_of_skipping(self):
        del self.data.rows[0]["audio_text"]
        self.data.save()
        with self.assertRaisesRegex(ValueError, "Missing audio_text"):
            project_train(self.root)

    def test_hidden_or_traversal_paths_are_rejected(self):
        for relative in ("train_environment/s0/state.json", "audio/../../state.wav"):
            self.data.rows[0]["audio"] = relative
            self.data.save()
            with self.assertRaises((ValueError, PipelineError)):
                project_train(self.root)


class ModelProvenanceTests(unittest.TestCase):
    def test_missing_ct2_tokenizer_is_rejected_before_backend_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            models = Path(temporary)
            path = models / "whisper-small-ct2"
            path.mkdir()
            for name in ("config.json", "preprocessor_config.json", "model.bin"):
                (path / name).write_text("{}", encoding="utf-8")
            provenance = {"source": "openai/whisper-small", "engine": "faster-whisper",
                          "revision": "a" * 40, "parameter_count": 1, "generation_defaults": {},
                          "assets": {p.name: digest(p) for p in path.iterdir()}}
            (path / "provenance.json").write_text(dumps(provenance), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no tokenizer/preprocessor fallback"):
                local_spec("whisper-small-ct2", models)

    def test_ct2_comparison_rejects_different_checkpoint_assets(self):
        hf = {"name": "whisper-small", "provenance": {"revision": "a" * 40, "assets": {"weights": "sha"}}}
        ct2 = {"name": "whisper-small-ct2", "provenance": {"revision": "a" * 40,
                                                               "source_assets": {"weights": "sha"}}}
        require_paired_source([hf, ct2])
        changed = copy.deepcopy(ct2)
        changed["provenance"]["source_assets"]["weights"] = "different"
        with self.assertRaisesRegex(ValueError, "same source"):
            require_paired_source([hf, changed])

    def test_cli_rejects_unsupported_cpu_dtype_before_loading_models(self):
        with self.assertRaises(SystemExit) as exit_code:
            main(["run", "--dtype", "float16"])
        self.assertEqual(exit_code.exception.code, 2)


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = Dataset(self.root)
        samples, _ = project_train(self.root)
        self.utterances = [s["utterances"][0] for s in samples[:2]]
        self.settings = {"warmup": 1, "timeout_seconds": 10, "load_timeout_seconds": 20}

    def run_worker(self):
        return run_configuration({"name": "controlled-test"}, self.settings, self.utterances,
                                 self.data.base, self.root / "run", worker_target=controlled_worker)

    def test_success_keeps_empty_transcript_and_full_artifacts(self):
        manifest, rows = self.run_worker()
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(len(rows), 2)
        self.assertEqual(manifest["summary"]["coverage"], 1)
        self.assertEqual(rows[0]["prediction"], "")
        self.assertEqual(rows[0]["scores"]["raw"]["wer"]["deletions"], 4)
        lines = (self.root / "run/transcripts.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(loads(lines[0])["utterance_id"], self.utterances[0]["utterance_id"])

    def test_hard_timeout_preserves_remaining_denominator(self):
        self.settings.update(test_behavior="timeout", warmup=0, timeout_seconds=.05)
        manifest, rows = self.run_worker()
        self.assertEqual([r["status"] for r in rows], ["timeout", "not_run"])
        self.assertEqual(manifest["status"], "incomplete")
        self.assertEqual(manifest["summary"]["normalized_wer"], 1)

    def test_load_failure_marks_entire_selection_not_run(self):
        self.settings["test_behavior"] = "load_error"
        manifest, rows = self.run_worker()
        self.assertEqual([r["status"] for r in rows], ["not_run", "not_run"])
        self.assertEqual(manifest["summary"]["coverage"], 0)


if __name__ == "__main__":
    unittest.main()
