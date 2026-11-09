"""Worker-side doubles loaded via ``--factory integration_doubles:factory``.

Behaviors are chosen per sample through LIFEMATE_TEST_BEHAVIORS (JSON id -> name).
Markers written to LIFEMATE_TEST_MARKERS let the parent observe environment opens
and mutations across worker generations and supervisor restarts.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from lifemate.contracts import PipelineError

FOREVER = 3600


def behaviors() -> dict:
    return json.loads(os.environ.get("LIFEMATE_TEST_BEHAVIORS", "{}"))


def marker(name: str) -> None:
    directory = Path(os.environ["LIFEMATE_TEST_MARKERS"])
    with (directory / f"{name}-{os.getpid()}-{uuid.uuid4().hex}").open("x"):
        pass


class ASR:
    metadata = {"parameter_count": 50, "controlled_test_only": True}

    def __init__(self):
        self.current = None

    def transcribe(self, path, remaining_seconds):
        if behaviors().get(self.current) == "block_asr":
            time.sleep(FOREVER)
        return "Nhắn Lan"


class Planner:
    metadata = {"parameter_count": 100, "controlled_test_only": True}

    def __init__(self, asr):
        self.asr = asr

    def decide(self, prepared, observations, remaining_seconds):
        sample_id = self.asr.current
        behavior = behaviors().get(sample_id, "finish")
        details = {"prompt_tokens": 1, "generated_tokens": 1, "terminated": "eos"}
        if behavior == "block_planner":
            time.sleep(FOREVER)
        if behavior == "soft_planner":
            time.sleep(0.3)  # Test config sets soft=0.25, hard=2; return control safely.
        if behavior == "fail_planner":
            raise PipelineError("PLANNER_FORMAT", "Injected malformed completion", "planner")
        if behavior in {"lookup", "block_tool", "crash_tool"} and not observations:
            return {"action": "call", "name": "contacts.search", "arguments": {"query": "Lan"}}, details
        if behavior == "lookup" and len(observations) == 1:
            contact = observations[0]["result"]["contacts"][0]["id"]
            return {"action": "call", "name": "sms.send",
                    "arguments": {"contact_id": contact, "content": "Đến trễ"}}, details
        return {"action": "finish"}, details


class Environment:
    def __init__(self, sample_id):
        self.sample_id, self.calls = sample_id, []

    def call(self, name, arguments):
        self.calls.append({"name": name, "arguments": arguments})
        marker(f"mutated-{self.sample_id}")
        behavior = behaviors().get(self.sample_id)
        if behavior == "block_tool":
            time.sleep(FOREVER)
        if behavior == "crash_tool":
            os._exit(17)
        if name == "contacts.search":
            return {"ok": True, "contacts": [{"id": "c77", "name": "Lan"}]}
        return {"ok": True}

    def get_tool_calls(self):
        return list(self.calls)

    def get_state_hash(self):
        return "b" * 64


def factory(config) -> dict:
    """Controlled components; startup may be slowed to exercise recovery limits."""
    starts = len([p for p in Path(os.environ["LIFEMATE_TEST_MARKERS"]).iterdir() if p.name.startswith("startup-")])
    marker("startup")
    if os.environ.get("LIFEMATE_TEST_STARTUP") == "block" or (
            os.environ.get("LIFEMATE_TEST_STARTUP") == "block_recovery" and starts >= 1):
        time.sleep(FOREVER)
    asr = ASR()
    opened = set()

    def environments(split, sample_id, root):
        if sample_id in opened:
            raise PipelineError("EXECUTION_UNCERTAIN", "Environment cannot be reopened", "environment")
        opened.add(sample_id)
        asr.current = sample_id
        marker(f"opened-{sample_id}")
        return Environment(sample_id)

    if any(b == "block_output" for b in behaviors().values()):
        import lifemate.artifacts as artifacts

        original = artifacts.write_durable

        def blocking_write(path, content):
            if path.name == "prediction.json" and any(
                    f'"id":"{i}"' in content for i, b in behaviors().items() if b == "block_output"):
                time.sleep(FOREVER)
            original(path, content)

        artifacts.write_durable = blocking_write

    # Sample ASR occurs before the environment opens; bind the current ID earlier.
    original_prepare = __import__("lifemate.dataset", fromlist=["prepare_request_once"]).prepare_request_once

    def prepare(sample, *args, **kwargs):
        asr.current = sample.id
        return original_prepare(sample, *args, **kwargs)

    import lifemate.dataset as dataset
    dataset.prepare_request_once = prepare
    return {"asr": asr, "planner": Planner(asr), "asr_identity": "controlled", "environment_factory": environments,
            "metadata": {"asr": ASR.metadata, "planner": Planner.metadata, "total_parameters": 150}}
