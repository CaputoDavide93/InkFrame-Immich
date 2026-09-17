"""A file present in the tree and absent from the Dockerfile COPY passes every
other test and then does not exist at runtime. That has happened four times in
this repository; each time it failed at start-up, in a log nobody reads."""
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _copied_files() -> set[str]:
    text = (ROOT / "Dockerfile").read_text()
    copied: set[str] = set()
    for line in text.splitlines():
        if not line.strip().upper().startswith("COPY"):
            continue
        for token in re.split(r"\s+", line.strip())[1:-1]:
            copied.add(pathlib.PurePath(token).name)
    return copied


def test_every_local_import_is_copied_into_the_image():
    local_modules = {p.stem for p in SRC.glob("*.py")}
    copied = _copied_files()

    missing: list[str] = []
    for path in SRC.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module.split(".")[0]]
            for name in names:
                if name in local_modules and f"{name}.py" not in copied:
                    missing.append(f"{path.name} imports {name}, but {name}.py is not COPYed")

    assert not missing, "Dockerfile ship list is incomplete:\n" + "\n".join(missing)


def test_the_entrypoint_itself_is_copied():
    assert "app.py" in _copied_files()
