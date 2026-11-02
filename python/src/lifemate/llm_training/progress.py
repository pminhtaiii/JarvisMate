"""Small stderr progress reports; stdout remains the machine-readable outcome."""
import sys
import time

HEARTBEAT_SECONDS = 30.


def duration(seconds):
    seconds = max(0, int(seconds))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours}h{minutes:02}m" if hours else f"{minutes}m{seconds:02}s"


class Progress:
    def __init__(self, label, total, *, initial=0, interval=30., clock=time.monotonic, stream=None):
        self.label, self.total, self.initial = label, total, initial
        self.done, self.interval, self.clock = initial, interval, clock
        self.stream = sys.stderr if stream is None else stream
        self.started = self.last = clock()
        self.advance(initial, force=True)

    def advance(self, done, detail="", *, force=False):
        self.done = done
        now = self.clock()
        if not (force or done == self.total or now-self.last >= self.interval):
            return
        elapsed = now-self.started
        completed = done-self.initial
        eta = duration(elapsed*(self.total-done)/completed) if completed > 0 else "--"
        percent = 100*done/self.total if self.total else 100.
        fields = [f"[LLM] {self.label}", f"{done}/{self.total} ({percent:.1f}%)"]
        if detail:
            fields.append(detail)
        fields.extend((f"elapsed={duration(elapsed)}", f"ETA={eta}"))
        print(" | ".join(fields), file=self.stream, flush=True)
        self.last = now

    def note(self, detail, *, force=False):
        self.advance(self.done, detail, force=force)


def terminal_line(line):
    """Hide only known repeat noise; preserve unfamiliar warnings and failures."""
    line = line.lstrip('\r')
    tf32 = "Please use the new API settings to control TF32 behavior"
    return not (line.startswith("Loading checkpoint shards:")
                or line.startswith(tf32) or f"UserWarning: {tf32}" in line
                or line.strip() == "self.setter(val)"
                or line.startswith("The following generation flags are not valid and may be ignored:"))
