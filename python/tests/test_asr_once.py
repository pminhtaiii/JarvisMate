"""Each distinct required clip is transcribed at most once per sample (FR-002)."""
import shutil
import unittest

from lifemate.contracts import Deadline, PipelineError
from lifemate.dataset import preflight, prepare_request_once
from support import ControlledASR, Fixture, wav


def tone(path, value):
    """Write a WAV whose content differs from the fixture's silent clips."""
    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(bytes([value, 0]) * 160)


class TranscribeOnceTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.close)
        row = self.fx.rows[0]
        base, sample_id = self.fx.split, row["id"]
        self.paths = {name: f"audio/{sample_id}/{sample_id}_{name}.wav" for name in ("u1", "u2", "copy")}
        tone(base / self.paths["u1"], 1)
        tone(base / self.paths["u2"], 2)
        # Identical content at a different path, plus a repeated reference to u1.
        shutil.copyfile(base / self.paths["u1"], base / self.paths["copy"])
        row["history"] = [
            {"role": "user", "audio": self.paths["u1"], "audio_text": "một"},
            {"role": "assistant", "text": "Dạ", "tool_calls": [{"name": "sms.send", "arguments": {"content": "x"}}],
             "tool_results": [{"ok": True}]},
            {"role": "user", "audio": self.paths["u2"], "audio_text": "hai"},
            {"role": "assistant", "text": "Vâng"},
            {"role": "user", "audio": self.paths["u1"], "audio_text": "một"},
            {"role": "assistant", "text": "Rồi"},
            {"role": "user", "audio": self.paths["copy"], "audio_text": "một"},
            {"role": "assistant", "text": "Ok"},
        ]
        self.fx.write()

    def prepare(self, mode="audio", asr=None):
        sample = preflight(self.fx.config(input_mode=mode)).samples[0]
        self.asr = asr if asr is not None else ControlledASR()
        return prepare_request_once(sample, self.asr, Deadline(30), asr_identity="whisper-test")

    def test_repeated_and_identical_clips_reuse_one_transcript(self):
        prepared, stats = self.prepare()
        # Distinct contents: u1 (also copy), u2, and the silent current clip.
        self.assertEqual(len(self.asr.paths), 3)
        self.assertEqual((stats["references"], stats["distinct_clips"], stats["asr_calls"], stats["reused_references"]),
                         (5, 3, 3, 2))
        users = [turn["text"] for turn in prepared["history"] if turn["role"] == "user"]
        self.assertEqual(users, ["ASR: train_0001_u1", "ASR: train_0001_u2", "ASR: train_0001_u1", "ASR: train_0001_u1"])
        self.assertEqual(prepared["request"], "ASR: train_0001")
        self.assertEqual([c["reused"] for c in stats["clips"]], [False, False, True, True, False])

    def test_history_order_and_supplied_calls_are_preserved_not_executed(self):
        prepared, _ = self.prepare()
        self.assertEqual([t["role"] for t in prepared["history"]], ["user", "assistant"] * 4)
        self.assertEqual(prepared["history"][1]["tool_calls"], [{"name": "sms.send", "arguments": {"content": "x"}}])
        self.assertNotIn("label", prepared)
        self.assertNotIn("GOLD_MUST_NOT_ENTER_PROMPT", repr(prepared))

    def test_transcript_mode_uses_supplied_text_without_asr(self):
        prepared, stats = self.prepare("transcript", asr=ControlledASR())
        self.assertEqual(self.asr.paths, [])
        self.assertEqual(stats["mode"], "transcript_diagnostic")
        self.assertEqual(stats["asr_calls"], 0)
        self.assertEqual([t["text"] for t in prepared["history"] if t["role"] == "user"], ["một", "hai", "một", "một"])
        self.assertEqual(prepared["request"], "Nhắn Lan tôi đến trễ")

    def test_empty_transcript_fails_visibly(self):
        class EmptyASR(ControlledASR):
            def transcribe(self, path, remaining_seconds):
                super().transcribe(path, remaining_seconds)
                return "   "

        with self.assertRaises(PipelineError) as caught:
            self.prepare(asr=EmptyASR())
        self.assertEqual((caught.exception.code, caught.exception.stage), ("INPUT_INVALID", "asr"))

    def test_audio_removed_after_preflight_fails_at_asr_stage(self):
        sample = preflight(self.fx.config(input_mode="audio")).samples[0]
        (self.fx.split / self.paths["u2"]).unlink()
        asr = ControlledASR()
        with self.assertRaises(PipelineError) as caught:
            prepare_request_once(sample, asr, Deadline(30))
        self.assertEqual((caught.exception.code, caught.exception.stage), ("ASSET_MISSING", "asr"))
        self.assertEqual(len(asr.paths), 1, "Only clips before the missing one were transcribed")

    def test_missing_asr_and_expired_deadline(self):
        sample = preflight(self.fx.config(input_mode="audio")).samples[0]
        with self.assertRaises(PipelineError):
            prepare_request_once(sample, None, Deadline(30))
        ticks = iter([0] + [100] * 20)
        asr = ControlledASR()
        with self.assertRaises(PipelineError) as caught:
            prepare_request_once(sample, asr, Deadline(30, lambda: next(ticks)))
        self.assertEqual(caught.exception.code, "TIME_LIMIT")
        self.assertEqual(asr.paths, [])


if __name__ == "__main__":
    unittest.main()
