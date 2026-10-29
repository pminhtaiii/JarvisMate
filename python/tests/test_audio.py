import unittest
import wave
from unittest.mock import MagicMock

from lifemate.adapters.common import ModelResidency
from lifemate.agent import run_sample
from lifemate.contracts import Deadline, Limits, PipelineError
from lifemate.dataset import preflight, prepare_request, wav_info
from lifemate.metrics import Clock, SpanRecorder
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

    def test_truncated_wav_payload_fails_preflight_for_current_and_history_audio(self):
        self.history()
        for value in (self.fx.rows[0]["audio"], self.fx.rows[0]["history"][0]["audio"]):
            target = self.fx.split / value
            original = target.read_bytes()
            self.assertEqual(wav_info(target), {"frames": 160, "seconds": 0.01})
            for missing in (1, 2, 320):
                with self.subTest(audio=value, missing=missing):
                    target.write_bytes(original[:-missing])
                    with self.assertRaises(PipelineError) as caught:
                        preflight(self.fx.config(input_mode="audio"))
                    self.assertEqual(caught.exception.code, "INPUT_INVALID")
            target.write_bytes(original)

    def test_wav_duration_boundaries(self):
        target = self.fx.split / self.fx.rows[0]["audio"]
        for frames in (0, 1, 480000, 480001):
            with self.subTest(frames=frames):
                with wave.open(str(target), "wb") as stream:
                    stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                    stream.writeframes(b"\0\0" * frames)
                if 0 < frames <= 480000:
                    self.assertEqual(wav_info(target), {"frames": frames, "seconds": frames / 16000})
                else:
                    with self.assertRaises(PipelineError):
                        wav_info(target)

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

    def test_clip_spans_are_recorded_historical_first_then_current(self):
        self.history()
        sample = preflight(self.fx.config(input_mode="audio")).samples[0]
        recorder = SpanRecorder()
        prepare_request(sample, ControlledASR(), Deadline(30), recorder)
        clips = [s for s in recorder.spans if s.stage == "asr_clip"]
        self.assertEqual([c.index for c in clips], [0, 1])
        self.assertTrue(all(c.parent_stage == "request" and c.status == "completed" for c in clips))

    def test_transcript_mode_records_no_clip_spans(self):
        sample = preflight(self.fx.config(input_mode="transcript")).samples[0]
        recorder = SpanRecorder()
        prepare_request(sample, None, Deadline(30), recorder)
        self.assertEqual([s for s in recorder.spans if s.stage == "asr_clip"], [])

    def test_a_failing_clip_is_recorded_unfinished_then_reraises(self):
        sample = preflight(self.fx.config(input_mode="audio")).samples[0]
        recorder = SpanRecorder()

        class FailingASR(ControlledASR):
            def transcribe(self, *args):
                raise PipelineError("MODEL_UNAVAILABLE", "no ASR", "asr")

        with self.assertRaises(PipelineError):
            prepare_request(sample, FailingASR(), Deadline(30), recorder)
        clips = [s for s in recorder.spans if s.stage == "asr_clip"]
        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0].status, "unfinished")
        self.assertIsNone(clips[0].end_offset)

    def test_no_recorder_behaves_exactly_as_before(self):
        self.history()
        sample = preflight(self.fx.config(input_mode="audio")).samples[0]
        prepared = prepare_request(sample, ControlledASR(), Deadline(30))
        self.assertEqual(prepared["history"][1]["text"], "Đã xem")

    def test_request_span_includes_asr_offload_transfer_time(self):
        sample = preflight(self.fx.config(input_mode="audio")).samples[0]
        now = [0.0]

        class OffloadedASR(ModelResidency):
            metadata = {"parameter_count": 10}

            def transcribe(self, path, remaining_seconds):
                return "text"

        asr = OffloadedASR()
        asr.cpu_offload, asr.device = True, "cuda"
        asr.model, asr.torch = MagicMock(), MagicMock()

        def slow_transfer(device):
            now[0] += 2.0  # onload/offload is not free; it belongs to sample time.

        asr.model.to.side_effect = slow_transfer
        recorder = SpanRecorder(clock=Clock(lambda: now[0]))
        outcome = run_sample(sample, ControlledPlanner([FINISH]), asr,
                             lambda *_: ControlledEnvironment(), MemoryTrace(), Limits(),
                             split="train", data_root=self.fx.data, clock=lambda: now[0], recorder=recorder)
        self.assertEqual(outcome.status, "completed")
        request_span = next(s for s in recorder.spans if s.stage == "request")
        # Two transfers (onto cuda, back to cpu) at 2.0s each must be inside
        # the request span, not lost between it and the next span.
        self.assertGreaterEqual(request_span.duration, 4.0)

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
