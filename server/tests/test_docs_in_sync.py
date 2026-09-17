"""The inventory tables in the docs are generated from the code. A table that
drifts from the code is a lie in a costume, so staleness fails the suite."""
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve()
# Flat layout in the source monorepo (tools/ beside tests/); server/ layout in
# the public repository (tools/ one level above server/).
GEN_DOCS = next(
    p for p in (HERE.parents[1] / "tools" / "gen_docs.py",
                HERE.parents[2] / "tools" / "gen_docs.py")
    if p.exists()
)


def test_generated_tables_match_the_code():
    result = subprocess.run(
        [sys.executable, str(GEN_DOCS), "--check"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
