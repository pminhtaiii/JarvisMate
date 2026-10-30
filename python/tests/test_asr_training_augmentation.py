"""Augmentation checks use synthetic PCM and leave Validation untouched."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from lifemate.asr_training.augmentation import augment, load_noises
from lifemate.asr_training.config import DEFAULTS
from lifemate.asr_training.storage import write
from lifemate.jsonio import digest
from asr_training_support import make_audio


class AugmentationTests(unittest.TestCase):
    def test_reproducible_and_bounded_train_audio(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'noise.wav'
            make_audio(path,10)
            noise={'path':str(path),'sha256':digest(path),'license':'synthetic','reviewed':True,'contains_speech':False}
            row={'partition':'train','utterance_id':'train/current','reference':'unchanged'}
            samples=np.sin(np.arange(1600)/100).astype(np.float32)*.1
            first,log=augment(samples,row,DEFAULTS,1,[noise],np)
            second,again=augment(samples,row,DEFAULTS,1,[noise],np)
            np.testing.assert_array_equal(first,second)
            self.assertEqual(log,again)
            self.assertLess(np.max(np.abs(first)),1)
            self.assertEqual(row['reference'],'unchanged')
            with self.assertRaises(ValueError):
                augment(samples,row|{'partition':'validation'},DEFAULTS,1,[noise],np)

    def test_noise_inside_competition_dataset_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            path=root/'data/noise.wav'
            make_audio(path,10)
            write(root/'manifest.json',[{'path':str(path),'sha256':digest(path),'license':'synthetic',
                                       'reviewed':True,'contains_speech':False}])
            with self.assertRaises(ValueError):
                load_noises(root/'manifest.json',root/'data')

    def test_speed_would_exceed_window_is_logged_without_truncation(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'noise.wav'
            make_audio(path,10)
            noise={'path':str(path),'sha256':digest(path)}
            rng=Mock()
            rng.random.return_value=0.
            rng.choice.return_value=.9
            rng.integers.return_value=0
            rng.uniform.side_effect=[0.,20.]
            original=np.full(480000,.1,dtype=np.float32)
            with patch.object(np.random,'default_rng',return_value=rng):
                result,log=augment(original,{'partition':'train','utterance_id':'s/current'},DEFAULTS,0,[noise],np)
            self.assertEqual(len(result),len(original))
            self.assertEqual(log['speed_fallback'],'would_exceed_30_seconds')
            self.assertEqual(log['noise_sha256'],noise['sha256'])
            self.assertIn('volume_gain',log)

    def test_clipping_transform_falls_back_to_clean_audio(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'noise.wav'
            make_audio(path,100)
            rng=Mock()
            rng.random.return_value=0.
            rng.choice.return_value=1.
            rng.integers.return_value=0
            rng.uniform.side_effect=[6.,15.]
            original=np.full(1600,.95,dtype=np.float32)
            with patch.object(np.random,'default_rng',return_value=rng):
                result,log=augment(original,{'partition':'train','utterance_id':'s/current'},DEFAULTS,0,
                                   [{'path':str(path),'sha256':digest(path)}],np)
            self.assertEqual(log['fallback'],'invalid_or_clipping_transform')
            np.testing.assert_array_equal(result,original)


if __name__=='__main__': unittest.main()
