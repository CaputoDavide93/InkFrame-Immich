"""requirements.txt and requirements.lock pin the same versions.

requirements.txt is the human-edited list of direct dependencies; the lock is
what the image installs, with hashes. Bumping one and not the other is a
version that reads as updated in the repository and ships unchanged, or the
reverse. Both files are small enough that the whole of each must agree."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\;]+)")


def _pins(path: pathlib.Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in path.read_text().splitlines():
        match = PIN.match(line.strip())
        if match:
            found[match.group(1).lower().replace("_", "-")] = match.group(2)
    return found


def test_the_lock_pins_exactly_the_requirements_versions():
    requirements = _pins(ROOT / "requirements.txt")
    lock = _pins(ROOT / "requirements.lock")
    assert requirements, "requirements.txt has no name==version pins"
    assert requirements == lock, (
        "requirements.txt and requirements.lock disagree:\n"
        f"  requirements.txt: {sorted(requirements.items())}\n"
        f"  requirements.lock: {sorted(lock.items())}"
    )


def test_every_lock_pin_carries_a_hash():
    hashes: dict[str, int] = {}
    current = None
    for line in (ROOT / "requirements.lock").read_text().splitlines():
        stripped = line.strip()
        if PIN.match(stripped):
            current = PIN.match(stripped).group(1)
            hashes[current] = 0
        elif stripped.startswith("--hash=sha256:") and current is not None:
            hashes[current] += 1
    assert hashes, "no pins found"
    unhashed = sorted(name for name, count in hashes.items() if count == 0)
    assert unhashed == [], f"pins with no --hash lines; the image build requires them: {unhashed}"
