"""Merged local export with fresh-process round-trip; no implicit model download."""
from __future__ import annotations

from pathlib import Path

from asr.pretrained.data import audio_asset
from .storage import read, rows, seal, write, verify
from .workers import once, Session
from .orchestration import job, checked
from .config import binding
from .storage import code_identity, environment
from .checkpoints import load as validate_checkpoint


def export(suite: dict, config: dict, hardware: dict, checkpoint: Path,
           output: Path, reference_rows: list[dict]) -> dict:
    validate_checkpoint(checkpoint, binding(config, suite, hardware, code_identity(), environment()))
    result = checked(once(job(suite, config, mode="export", hardware=hardware,
                              checkpoint=str(checkpoint), export_path=str(output)), config["worker_timeout_seconds"]))
    write(output / "export-metadata.json", {"source": suite["model"]["provenance"]["source"],
          "revision": suite["model"]["provenance"]["revision"], "checkpoint": str(checkpoint),
          "logical_parameters": result["logical_parameters"], "dtype": config["inference_dtype"],
          "representation": "merged_nonquantized_base_plus_adapter"})
    seal(output)
    # New process + local_files_only. Model entrypoint never receives references.
    session = Session(job(suite, config, mode="inference", hardware=hardware, snapshot=str(output)))
    try:
        checked(session.receive(config["load_timeout_seconds"]), ready=True)
        for reference in reference_rows[:3]:
            response = checked(session.request(audio_asset(Path(suite["data_root"])/"train", reference["audio"]),
                                               config["timeout_seconds"]))
            if response["prediction"] != reference["prediction"]:
                raise ValueError("Export round-trip text differs from the same-dtype merged adapter evaluation")
    finally:
        session.close()
    write(output.parent / (output.name + "-roundtrip.json"), {"status": "passed", "utterances": min(3,len(reference_rows)),
                                                             "memory": result["memory"]})
    return {"path": str(output), "parameters": result["logical_parameters"], "roundtrip": "passed"}
