"""Run the integration CLI in a child process with optional supervisor-death injection.

``python -m integration_harness POINT -- <integration argv>``; POINT is ``none`` or one
of the supervisor ordering points (reserved, dispatched, received). At POINT for the
first sample the supervisor process exits abruptly, as a crash would.
"""
import os
import sys

from lifemate.integration import main


def worker_command():
    return [sys.executable, "-m", "lifemate.worker", "--factory", "integration_doubles:factory"]


def run():
    point = sys.argv[1]
    argv = sys.argv[sys.argv.index("--") + 1:]

    def fault(name):
        if name == point:
            os._exit(9)

    return main(argv, worker_command=worker_command(), worker_env=dict(os.environ), fault=fault)


if __name__ == "__main__":
    sys.exit(run())
