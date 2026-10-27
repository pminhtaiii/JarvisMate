"""Local Qwen structured-action adapter; execution remains outside the model."""
from __future__ import annotations

import time

from ..contracts import JSON, Limits, PipelineError
from ..prompting import messages
from .common import dependencies, metadata, model_directory, parameter_count, stopping_criteria


class LocalPlanner:
    def __init__(self, path, device: str, limits: Limits, seed: int = 20261027):
        path = model_directory(path)
        torch, hf, _ = dependencies(device, seed)
        self.torch, self.hf, self.device, self.limits = torch, hf, device, limits
        dtype = torch.float32 if device == "cpu" else torch.float16
        try:
            config = hf.AutoConfig.from_pretrained(path, local_files_only=True, trust_remote_code=False)
            if config.model_type != "qwen3":
                raise PipelineError("MODEL_UNAVAILABLE", "Baseline planner requires a local Qwen3 checkpoint", "model_load")
            self.tokenizer = hf.AutoTokenizer.from_pretrained(path, local_files_only=True, trust_remote_code=False)
            self.model = hf.AutoModelForCausalLM.from_pretrained(
                path, config=config, local_files_only=True, trust_remote_code=False,
                torch_dtype=dtype, attn_implementation="eager", weights_only=True).to(device)
            self.model.eval()
            count = parameter_count(self.model, 5_000_000_000)
            self.metadata = metadata(path, count, device, dtype, seed) | {
                "context_limit": limits.context_tokens, "max_new_tokens": limits.output_tokens,
                "adapter": "qwen3-structured-react"}
        except PipelineError:
            raise
        except Exception as exc:
            raise PipelineError("MODEL_UNAVAILABLE", "Cannot load the local Qwen checkpoint/tokenizer", "model_load") from exc

    def next_action(self, planner_input: JSON, remaining_seconds: float) -> str:
        started = time.monotonic()
        try:
            rendered = self.tokenizer.apply_chat_template(
                messages(planner_input), tokenize=False, add_generation_prompt=True, enable_thinking=False)
            tokens = self.tokenizer(rendered, return_tensors="pt", add_special_tokens=False)
            length = tokens["input_ids"].shape[-1]
            if length + self.limits.output_tokens > self.limits.context_tokens:
                raise PipelineError("CONTEXT_LIMIT", "Prompt plus output reservation exceeds context", "planner")
            remaining = remaining_seconds - (time.monotonic() - started)
            stop = stopping_criteria(self.hf, remaining)
            tokens = {k: v.to(self.device) for k, v in tokens.items()}
            with self.torch.inference_mode():
                output = self.model.generate(
                    **tokens, do_sample=False, num_beams=1, max_new_tokens=self.limits.output_tokens,
                    stopping_criteria=stop, pad_token_id=self.tokenizer.eos_token_id)
            if time.monotonic() - started >= remaining_seconds:
                raise PipelineError("TIME_LIMIT", "Planner generation exceeded deadline", "planner")
            return self.tokenizer.decode(output[0][length:], skip_special_tokens=True)
        except PipelineError:
            raise
        except Exception as exc:
            raise PipelineError("PLANNER_ERROR", "Local planner generation failed", "planner") from exc
