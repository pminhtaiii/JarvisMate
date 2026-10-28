import json
import unittest
from unittest.mock import patch

from lifemate.contracts import PipelineError
from lifemate.dataset import preflight
from support import Fixture


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture(2)
        self.addCleanup(self.fx.close)

    def test_selected_subset_ignores_unselected_missing_assets(self):
        (self.fx.split / self.fx.rows[1]["audio"]).unlink()
        (self.fx.split / "train_environment/train_0002/state.json").unlink()
        result = preflight(self.fx.config(input_mode="audio"))
        self.assertEqual(result.metadata["selected_ids"], ["train_0001"])
        self.assertEqual(result.metadata["coverage_scope"], "subset")

    def test_selection_is_dataset_order(self):
        data = preflight(self.fx.config(selected_ids=("train_0002", "train_0001")))
        self.assertEqual([s.id for s in data.samples], ["train_0001", "train_0002"])

    def test_no_label_or_audio_transcript_enters_audio_input(self):
        data = preflight(self.fx.config(input_mode="audio"))
        sample = data.samples[0]
        self.assertIsNone(sample.text)
        self.assertNotIn("GOLD_MUST_NOT_ENTER_PROMPT", repr(sample))

    def test_transcript_mode_does_not_require_wavs(self):
        (self.fx.split / self.fx.rows[0]["audio"]).unlink()
        self.assertEqual(preflight(self.fx.config()).samples[0].text, self.fx.rows[0]["audio_text"])

    def test_duplicate_and_unknown_selected_ids_fail(self):
        for ids in (("missing",), ("train_0001", "train_0001")):
            with self.subTest(ids=ids), self.assertRaises(PipelineError):
                preflight(self.fx.config(selected_ids=ids))

    def test_duplicate_dataset_ids_and_malformed_unselected_json_fail(self):
        path = self.fx.split / "train.jsonl"
        for suffix in (json.dumps(self.fx.rows[1]) + "\n", "not JSON\n"):
            self.fx.write()
            with path.open("a", encoding="utf-8") as stream:
                stream.write(suffix)
            with self.assertRaises(PipelineError):
                preflight(self.fx.config())

    def test_unsafe_audio_paths_fail(self):
        for value in (".", "./", "../outside.wav", "/audio.wav", "C:/audio.wav", "audio/../../outside.wav",
                      "train_environment/train_0001/state.json"):
            self.fx.rows[0]["audio"] = value
            self.fx.write()
            with self.subTest(value=value), self.assertRaises(PipelineError):
                preflight(self.fx.config())

    def test_audio_link_cannot_escape_split(self):
        path = self.fx.split / self.fx.rows[0]["audio"]
        outside = self.fx.root / "outside.wav"
        path.unlink()
        outside.touch()
        try:
            path.symlink_to(outside)
        except OSError:
            self.skipTest("Host cannot create symlinks")
        with self.assertRaises(PipelineError):
            preflight(self.fx.config())

    def test_state_is_checked_but_never_read_by_preflight(self):
        original = type(self.fx.root).open

        def guarded(path, *args, **kwargs):
            if "train_environment" in path.parts:
                self.fail("Pipeline attempted a hidden state read")
            return original(path, *args, **kwargs)

        with patch("pathlib.Path.open", guarded):
            preflight(self.fx.config())

    def test_audio_link_to_hidden_state_is_rejected_before_read(self):
        path = self.fx.split / self.fx.rows[0]["audio"]
        path.unlink()
        target = self.fx.split / "train_environment/train_0001/state.json"
        try:
            path.symlink_to(target)
        except OSError:
            self.skipTest("Host cannot create symlinks")
        with self.assertRaises(PipelineError):
            preflight(self.fx.config(input_mode="audio"))

    def test_exact_tool_membership_and_history_shape(self):
        self.fx.rows[0]["context"]["installed_apps"]["sms"]["tools"].append("contacts.get")
        self.fx.write()
        with self.assertRaises(PipelineError):
            preflight(self.fx.config())
        self.fx.rows[0]["context"]["installed_apps"]["sms"]["tools"].pop()
        self.fx.rows[0]["history"] = [{"role": "assistant", "text": "Wrong ordering"}]
        self.fx.write()
        with self.assertRaises(PipelineError):
            preflight(self.fx.config())

    def test_missing_selected_state_and_transcript_fail(self):
        self.fx.rows[0].pop("audio_text")
        self.fx.write()
        with self.assertRaises(PipelineError):
            preflight(self.fx.config())
        self.fx.rows[0]["audio_text"] = "Request"
        self.fx.write()
        (self.fx.split / "train_environment/train_0001/state.json").unlink()
        with self.assertRaises(PipelineError):
            preflight(self.fx.config())
