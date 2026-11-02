"""Progress must not contaminate JSON outcomes, hide errors, or flood the terminal."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from lifemate.llm_training.progress import Progress, duration, terminal_line
from lifemate.llm_training.once import phase, WorkflowError
from llm_support import SuiteFixture


class ProgressTests(unittest.TestCase):
    def test_progress_is_throttled_and_eta_uses_only_work_done_after_resume(self):
        clock = [0.]
        stream = io.StringIO()
        progress = Progress('train L1',500,initial=100,clock=lambda:clock[0],stream=stream)
        self.assertIn('100/500',stream.getvalue())
        self.assertIn('ETA=--',stream.getvalue())
        progress.advance(101)
        self.assertEqual(len(stream.getvalue().splitlines()),1)
        clock[0]=40.
        progress.advance(104,'loss=0.5')
        self.assertIn('ETA=1h06m',stream.getvalue())
        progress.advance(500)
        self.assertIn('500/500 (100.0%)',stream.getvalue())

    def test_progress_uses_stderr_and_keeps_stdout_machine_readable(self):
        out,err=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            Progress('eval L0 G',1).advance(1)
            print(json.dumps({'status':'completed'}))
        self.assertEqual(json.loads(out.getvalue()),{'status':'completed'})
        self.assertIn('[LLM] eval L0 G',err.getvalue())

    def test_known_noise_is_hidden_but_new_warnings_and_failures_are_visible(self):
        for text in ('Loading checkpoint shards: 30%',
                     'Please use the new API settings to control TF32 behavior',
                     '  self.setter(val)\n',
                     "The following generation flags are not valid and may be ignored: ['temperature']"):
            self.assertFalse(terminal_line(text))
        for text in ('RuntimeError: out of memory','UserWarning: new numerical warning','[LLM] update 3/5',
                     'RuntimeError: Loading checkpoint shards: failed',
                     'RuntimeError: Please use the new API settings to control TF32 behavior'):
            self.assertTrue(terminal_line(text))
        self.assertEqual(duration(61),'1m01s')

    def test_phase_keeps_full_json_and_warning_logs_but_displays_only_progress(self):
        fx=SuiteFixture()
        self.addCleanup(fx.close)
        run=fx.root/'run'
        run.mkdir()
        stdout,stderr=io.StringIO(),io.StringIO()
        command=[sys.executable,'-c',
            "import json,sys; print(json.dumps({'status':'passed','payload':'x'*20000})); "
            "print('Loading checkpoint shards: 100%',file=sys.stderr); "
            "print('[LLM] eval L0 | 1/1',file=sys.stderr)"]
        with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
            result=phase(fx.root,run,'controlled',command,{'passed'})
        self.assertEqual(len(result['payload']),20000)
        self.assertNotIn('payload',stdout.getvalue())
        self.assertIn('controlled | passed',stdout.getvalue())
        self.assertIn('[LLM] eval L0',stderr.getvalue())
        self.assertNotIn('Loading checkpoint',stderr.getvalue())
        self.assertIn('Loading checkpoint',(run/'controlled/stderr.log').read_text())
        self.assertEqual(json.loads((run/'controlled/stdout.log').read_text()),result)

    def test_failed_child_still_shows_reason_and_preserves_original_exit(self):
        fx=SuiteFixture()
        self.addCleanup(fx.close)
        run=fx.root/'run'
        run.mkdir()
        stdout,stderr=io.StringIO(),io.StringIO()
        command=[sys.executable,'-c',
            "import json,sys; print(json.dumps({'status':'failed','reason':'memory headroom'})); "
            "print('RuntimeError: diagnostic failure',file=sys.stderr); sys.exit(4)"]
        with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
            with self.assertRaisesRegex(WorkflowError,'memory headroom'):
                phase(fx.root,run,'failed',command,{'passed'})
        self.assertIn('diagnostic failure',stderr.getvalue())
        self.assertEqual(json.loads((run/'failed/outcome.json').read_text())['exit_code'],4)

    def test_silent_child_has_heartbeat_without_changing_its_outcome(self):
        fx=SuiteFixture(proof=False)
        self.addCleanup(fx.close)
        run=fx.root/'run'
        run.mkdir()
        output=io.StringIO()
        with patch('lifemate.llm_training.progress.HEARTBEAT_SECONDS',.01),contextlib.redirect_stdout(output):
            result=phase(fx.root,run,'silent',[sys.executable,'-c',
                'import time; time.sleep(1.3); print(\'{"status":"passed"}\')'],{'passed'})
        self.assertIn('silent | running | elapsed=',output.getvalue())
        self.assertEqual(result,{'status':'passed'})
