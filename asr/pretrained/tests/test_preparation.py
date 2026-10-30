"""Preparation regression tests; no network, real checkpoints or model loading."""
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from lifemate.jsonio import loads

from asr.pretrained.prepare import source_snapshot


class CardDataLike:
    """CardData supports get(), but dict(card_data) tries __getitem__(0)."""
    def __getitem__(self, key):
        if key == "license":
            return "apache-2.0"
        raise KeyError(key)

    def get(self, key, default=None):
        return "apache-2.0" if key == "license" else default


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.target = self.root / "whisper-small"
        self.revision = "a" * 40
        self.info = SimpleNamespace(sha=self.revision, card_data=CardDataLike(),
                                    siblings=[SimpleNamespace(rfilename="model.safetensors")])
        self.api = Mock()
        self.api.model_info.return_value = self.info
        self.api.list_repo_commits.return_value = [
            SimpleNamespace(commit_id=self.revision, created_at=datetime(2025, 1, 1, tzinfo=timezone.utc))]
        self.download = Mock(side_effect=self.cached_download)
        hub = ModuleType("huggingface_hub")
        hub.HfApi = Mock(return_value=self.api)
        hub.snapshot_download = self.download
        self.hub = hub
        self.modules = patch.dict(sys.modules, {"huggingface_hub": hub})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.details = patch("asr.pretrained.prepare.model_details", return_value=(123, {"suppress_tokens": [1]}))
        self.model_details = self.details.start()
        self.addCleanup(self.details.stop)

    def cached_download(self, source, *, revision, local_dir, **kwargs):
        self.assertEqual(source, "openai/whisper-small")
        self.assertEqual(revision, self.revision)
        local_dir.mkdir(parents=True, exist_ok=True)
        # Emulate reuse of a completed Hub-managed file: never replace its bytes.
        for name in ("config.json", "preprocessor_config.json", "model.safetensors"):
            path = local_dir / name
            if not path.exists():
                path.write_bytes(b"synthetic asset")
        metadata = local_dir / ".cache/huggingface/download/config.json.metadata"
        metadata.parent.mkdir(parents=True, exist_ok=True)
        metadata.write_text(revision + "\nsynthetic-etag\n0\n", encoding="utf-8")
        return str(local_dir)

    def prepare(self, revision="main"):
        return source_snapshot("whisper-small", self.root, revision)

    def test_carddata_mapping_and_missing_card_are_supported(self):
        for card, expected in ((CardDataLike(), "apache-2.0"), ({"license": "mit"}, "mit"), (None, None)):
            with self.subTest(card=type(card).__name__):
                self.info.card_data = card
                provenance = self.target / "provenance.json"
                if provenance.exists():
                    provenance.unlink()
                self.prepare()
                self.assertEqual(loads(provenance.read_text(encoding="utf-8"))["license_from_model_card"], expected)
                self.assertFalse((self.target / ".provenance.json.tmp").exists())

    def test_resume_after_postdownload_failure_preserves_weights_and_revision(self):
        self.model_details.side_effect = RuntimeError("interrupted metadata inspection")
        with self.assertRaisesRegex(RuntimeError, "interrupted metadata"):
            self.prepare()
        weights = self.target / "model.safetensors"
        weights.write_bytes(b"previously downloaded complete weights")
        self.assertFalse((self.target / "provenance.json").exists())
        self.model_details.side_effect = None
        self.prepare()
        self.assertEqual(weights.read_bytes(), b"previously downloaded complete weights")
        self.api.model_info.assert_called_with("openai/whisper-small", revision=self.revision)
        self.assertEqual(loads((self.target / "provenance.json").read_text(encoding="utf-8"))["revision"], self.revision)

    def test_complete_snapshot_is_reused_without_network(self):
        self.prepare()
        self.api.reset_mock()
        self.download.reset_mock()
        self.prepare()
        self.api.model_info.assert_not_called()
        self.download.assert_not_called()

    def test_corrupted_complete_snapshot_is_not_silently_repaired(self):
        self.prepare()
        (self.target / "model.safetensors").write_bytes(b"changed")
        self.download.reset_mock()
        with self.assertRaisesRegex(ValueError, "Model asset changed"):
            self.prepare()
        self.download.assert_not_called()

    def test_partial_snapshot_cannot_mix_revisions(self):
        self.cached_download("openai/whisper-small", revision=self.revision, local_dir=self.target)
        self.info.sha = "b" * 40
        with self.assertRaisesRegex(ValueError, "belongs to another revision"):
            self.prepare("b" * 40)
        self.download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
