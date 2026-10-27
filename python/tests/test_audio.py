import unittest

from lifemate.agent import run_sample
from lifemate.contracts import Deadline, Limits, PipelineError
from lifemate.dataset import preflight, prepare_request
from support import FINISH, ControlledASR, ControlledEnvironment, ControlledPlanner, Fixture, MemoryTrace, wav


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.close)

    def history(self):
        path = "audio/train_0001/train_0001_u1.wav"
        wav(self.fx.split / path)
        self.fx.rows[0]["history"] = [
            {"role": "user", "audio": path, "audio_text": "DO_NOT_USE_SUPPLIED_HISTORY"},
            {"role": "assistant", "text": "Đã xem", "tool_calls": [{"name": "contacts.search", "arguments": {}}],
             "tool_results": [{"ok": True, "contacts": []}]}]
        self.fx.rows[0]["audio_text"] = "DO_NOT_USE_SUPPLIED_CURRENT"
        self.fx.write()

    def test_audio_transcribes_user_turns_chronologically_and_preserves_assistant(self):
        self.history()
        sample = preflight(self.fx.config(input_mode="audio")).samples[0]
        asr = ControlledASR()
        prepared = prepare_request(sample, asr, Deadline(30))
        self.assertEqual([p.stem for p in asr.paths], ["train_0001_u1", "train_0001"])
        self.assertEqual(prepared["history"][1]["text"], "Đã xem")
        self.assertNotIn("DO_NOT_USE_SUPPLIED", repr(prepared))
        self.assertEqual(len(prepared["history"][1]["tool_calls"]), 1)

    def test_history_calls_are_context_only(self):
        self.history()
        sample = preflight(self.fx.config(input_mode="audio")).samples[0]
        env = ControlledEnvironment()
        outcome = run_sample(sample, ControlledPlanner([FINISH]), ControlledASR(),
                             lambda *_: env, MemoryTrace(), Limits(), split="train", data_root=self.fx.data)
        self.assertEqual(outcome.result["tool_calls"], [])

    def test_bad_rate_or_stereo_and_missing_audio_fail(self):
        target = self.fx.split / self.fx.rows[0]["audio"]
        for kwargs in ({"rate": 8000}, {"channels": 2}):
            wav(target, **kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(PipelineError):
                preflight(self.fx.config(input_mode="audio"))
        target.unlink()
        with self.assertRaises(PipelineError):
            preflight(self.fx.config(input_mode="audio"))

    def test_asr_failure_has_no_transcript_fallback_or_environment(self):
        self.history()
        sample = preflight(self.fx.config(input_mode="audio")).samples[0]
        opened = []

        class FailingASR(ControlledASR):
            def transcribe(self, *args):
                raise PipelineError("MODEL_UNAVAILABLE", "no ASR", "asr")

        outcome = run_sample(sample, ControlledPlanner([FINISH]), FailingASR(),
                             lambda *args: opened.append(args), MemoryTrace(), Limits(),
                             split="train", data_root=self.fx.data)
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(opened, [])

    def test_asr_time_consumes_sample_budget(self):
        sample = preflight(self.fx.config(input_mode="audio")).samples[0]
        now, opened = [0.0], []

        class SlowASR(ControlledASR):
            def transcribe(self, path, remaining_seconds):
                now[0] += 31
                return "text"

        outcome = run_sample(sample, ControlledPlanner([FINISH]), SlowASR(),
                             lambda *args: opened.append(args), MemoryTrace(), Limits(),
                             split="train", data_root=self.fx.data, clock=lambda: now[0])
        self.assertEqual(outcome.error["code"], "TIME_LIMIT")
        self.assertEqual(opened, [])
