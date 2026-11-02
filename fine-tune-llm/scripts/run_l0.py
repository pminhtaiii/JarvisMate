"""One explicit L0 phase; dependencies never run automatically."""
from _entry import run

if __name__ == "__main__":
    raise SystemExit(run("L0"))
