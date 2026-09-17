"""The inventory tables in the docs are generated from the code. A table that
drifts from the code is a lie in a costume, so staleness fails the suite."""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_generated_tables_match_the_code():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "gen_docs.py"), "--check"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
