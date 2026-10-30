"""Whisper/PhoWhisper short-form Vietnamese ASR from local PCM WAVs."""
from __future__ import annotations

import time
import wave

from ..contracts import Limits, PipelineError
from ..dataset import wav_info
from ..metrics import Generation
from .common import ModelResidency, dependencies, metadata, model_directory, parameter_count, stopping_criteria

MAX_NEW_TOKENS = 440


class LocalASR(ModelResidency):
    def __init__(self, path, device: str, limits: Limits, seed: int = 20261027, *, cpu_offload=False):
        path = model_directory(path)
        torch, hf, np = dependencies(device, seed)
        self.torch, self.hf, self.np, self.device = torch, hf, np, device
        self.cpu_offload = cpu_offload and device == "cuda"
        self.dtype = torch.float32 if device == "cpu" else torch.float16
        self._clip_index = 0
        try:
            self.processor = hf.WhisperProcessor.from_pretrained(path, local_files_only=True, trust_remote_code=False)
            self.model = hf.WhisperForConditionalGeneration.from_pretrained(
                path, local_files_only=True, trust_remote_code=False,
                dtype=self.dtype, attn_implementation="eager", weights_only=True).to("cpu" if self.cpu_offload else device)
            self.model.eval()
            # Only the combined deployed-system budget is specified by the brief.
            # CLI checks ASR + planner together before executing any sample.
            count = parameter_count(self.model, 6_000_000_000)
            self.metadata = metadata(path, count, device, self.dtype, seed) | {
                "adapter": "whisper-vietnamese", "language": "vi", "task": "transcribe",
                "cpu_offload": self.cpu_offload}
        except PipelineError:
            raise
        except Exception as exc:
            raise PipelineError("MODEL_UNAVAILABLE", "Cannot load the local Whisper checkpoint/processor", "model_load") from exc

    def set_metrics_recorder(self, recorder) -> None:
        super().set_metrics_recorder(recorder)
        self._clip_index = 0

    def transcribe(self, audio_path, remaining_seconds: float) -> str:
        started = time.monotonic()
        index = self._clip_index
        self._clip_index += 1
        try:
            info = wav_info(audio_path)
            with wave.open(str(audio_path), "rb") as stream:
                raw = stream.readframes(info["frames"])
            if len(raw) != info["frames"] * 2:
                raise PipelineError("INPUT_INVALID", "Truncated WAV payload", "asr")
            samples = self.np.frombuffer(raw, dtype="<i2").astype(self.np.float32) / 32768.0
            batch = self.processor(samples, sampling_rate=16000, return_tensors="pt", return_attention_mask=True)
            features = batch["input_features"].to(self.device, dtype=self.dtype)
            remaining = remaining_seconds - (time.monotonic() - started)
            stop = stopping_criteria(self.hf, remaining)
            kwargs = {"attention_mask": batch["attention_mask"].to(self.device)} if "attention_mask" in batch else {}
            generation_start = self._recorder.clock.offset() if self._recorder else None
            try:
                with self.torch.inference_mode():
                    output = self.model.generate(
                        features, **kwargs, language="vi", task="transcribe", forced_decoder_ids=None,
                        do_sample=False, num_beams=1, max_new_tokens=MAX_NEW_TOKENS,
                        return_timestamps=False, stopping_criteria=stop)
            except Exception:
                if self._recorder:
                    self._recorder.unfinished("generation", generation_start, index=index, parent_stage="asr_clip")
                raise
            timed_out = time.monotonic() - started >= remaining_seconds
            if self._recorder:
                span = self._recorder.mark("generation", generation_start, index=index, parent_stage="asr_clip")
                output_length = int(output.shape[-1]) if hasattr(output, "shape") else None
                stop_reason = ("deadline" if timed_out
                              else "max_tokens" if output_length is not None and output_length >= MAX_NEW_TOKENS
                              else "eos")
                self._recorder.record_generation(Generation("asr", index, seconds=span.duration,
                                                             output_tokens=output_length, stop_reason=stop_reason))
            if timed_out:
                raise PipelineError("TIME_LIMIT", "ASR exceeded sample deadline", "asr")
            result = self.processor.batch_decode(output, skip_special_tokens=True)[0].strip()
            if not result:
                raise PipelineError("PLANNER_ERROR", "ASR returned an empty transcript", "asr")
            return result
        except PipelineError:
            raise
        except Exception as exc:
            raise PipelineError("PLANNER_ERROR", "Local ASR failed", "asr") from exc
