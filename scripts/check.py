"""Run every check a change must pass: lint, format check, type check and the unit tests (not the tmux tests)."""

import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
STEPS = [
    ("lint", ["ruff", "check", "."]),
    ("format", ["ruff", "format", "--check", "."]),
    ("types", ["basedpyright", "."]),
    ("tests", [sys.executable, "-m", "pytest", "-q"]),
]


def run(steps):
    """Run every step even after one fails; return 0 only if all passed."""
    failed = []
    for name, argv in steps:
        print(f"== {name}: {' '.join(argv)}", flush=True)
        try:
            code = subprocess.run(argv, cwd=ROOT, check=False).returncode
        except FileNotFoundError:
            print(f"{argv[0]}: command not found", flush=True)
            code = 127
        if code:
            failed.append(name)
    if failed:
        print(f"== FAILED: {', '.join(failed)}", flush=True)
        return 1
    print(f"== all {len(steps)} checks passed", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(run(STEPS))
