"""Every diagram in this repository is a drawn SVG, and has to stay one.

Mermaid was removed because GitHub controls too much of it. It decodes HTML
entities before parsing -- which is what broke the architecture diagram, and
why nothing local caught it: parsing the file as written succeeds on every
Mermaid version from 9 to 11 and fails on all of them once decoded. It also
ignores `%%{init}%%`, pins its own version, and picks the theme.

What replaces it is `tools/gen_diagram.py`, which draws each diagram twice, one
file per colour scheme, served from a `<picture>` element. The tests below are
the obligations that come with that: the pictures are what the generator draws,
they reference files that exist, they carry nothing GitHub strips, and Mermaid
does not quietly come back.
"""
import html
import importlib
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve()
# Flat layout in the source monorepo, server/ layout in the public repository.
ROOT = next(p for p in (HERE.parents[1], HERE.parents[2]) if (p / "README.md").exists())
PAGES = sorted(ROOT.glob("*.md")) + sorted(ROOT.glob("docs/**/*.md"))
MERMAID = re.compile(r"^```mermaid[^\n]*\n(.*?)^```", re.S | re.M)
ENTITY = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]{1,31}|#\d{1,7}|#[Xx][0-9A-Fa-f]{1,6});")


def _generator():
    candidates = (ROOT / "tools" / "gen_diagram.py", ROOT.parent / "tools" / "gen_diagram.py")
    gen = next((p for p in candidates if p.exists()), None)
    # A missing generator means export-public.sh did not carry it: this
    # repository has more than one list that must name a file, and a file in
    # one but not the other passes every test in the tree it was written in.
    assert gen is not None, (
        "tools/gen_diagram.py is not beside this test. If this is the public "
        "repository, add it to the cp line in tools/export-public.sh."
    )
    sys.path.insert(0, str(gen.parent))
    module = importlib.import_module("gen_diagram")
    return importlib.reload(module)


def test_every_committed_svg_is_what_the_generator_draws():
    """A hand-edited SVG is a lie waiting to happen."""
    module = _generator()
    stale = []
    for name, fn in module.DIAGRAMS.items():
        for scheme in module.SCHEMES:
            path = ROOT / "docs" / "assets" / f"{name}-{scheme}.svg"
            if not path.exists():
                stale.append(f"{path.name} is missing")
            elif path.read_text(encoding="utf-8") != fn(scheme):
                stale.append(f"{path.name} differs from tools/gen_diagram.py")
    assert not stale, "re-run tools/gen_diagram.py rather than editing SVGs:\n  " + "\n  ".join(stale)


def test_every_picture_points_at_files_that_exist():
    """A `<picture>` with a wrong path shows the alt text and nothing else, on
    a page nobody reloads after editing."""
    missing = []
    for page in PAGES:
        base = page.parent
        for ref in re.findall(r'(?:srcset|src)="([^"]+\.svg)"', page.read_text(encoding="utf-8")):
            if not (base / ref).exists():
                missing.append(f"{page.relative_to(ROOT)} -> {ref}")
    assert not missing, "a diagram reference does not resolve:\n  " + "\n  ".join(missing)


def test_every_diagram_offers_both_schemes_and_alt_text():
    """One scheme is half a diagram, and no alt text is none of one."""
    problems = []
    for page in PAGES:
        text = page.read_text(encoding="utf-8")
        for block in re.findall(r"<picture>.*?</picture>", text, re.S):
            where = page.relative_to(ROOT)
            if "prefers-color-scheme: dark" not in block:
                problems.append(f"{where}: a <picture> with no dark source")
            if not re.search(r'alt="[^"]{40,}"', block):
                problems.append(f"{where}: a <picture> with missing or thin alt text")
    assert not problems, "\n  " + "\n  ".join(problems)


def test_the_svgs_carry_nothing_github_will_strip():
    """GitHub sanitises SVG in markdown. The failure is silent: the diagram
    still renders, just without whatever was removed."""
    bad = []
    for path in sorted((ROOT / "docs" / "assets").glob("*.svg")):
        svg = path.read_text(encoding="utf-8")
        for banned in ("<script", "<style", "@import", "<foreignObject"):
            if banned in svg:
                bad.append(f"{path.name} contains {banned}")
    assert not bad, "GitHub strips these without saying so:\n  " + "\n  ".join(bad)


def test_mermaid_has_not_come_back_unguarded():
    """If Mermaid ever returns, the entity trap returns with it.

    Not a ban -- a sequence or a quick sketch may be worth it one day -- but any
    block that comes back must not carry an HTML entity, because GitHub decodes
    it before Mermaid sees it and the diagram breaks on the rendered page while
    the file looks perfect.
    """
    bad = []
    for page in PAGES:
        text = page.read_text(encoding="utf-8")
        for match in MERMAID.finditer(text):
            line = text[: match.start()].count("\n") + 2
            for offset, row in enumerate(match.group(1).splitlines()):
                found = ENTITY.search(row)
                if found:
                    bad.append(f"{page.relative_to(ROOT)}:{line + offset}: {found.group(0)}")
            for offset, row in enumerate(html.unescape(match.group(1)).splitlines()):
                if row.count('"') % 2:
                    bad.append(f"{page.relative_to(ROOT)}:{line + offset}: odd quotes once decoded")
    assert not bad, "\n  " + "\n  ".join(bad)


def test_there_are_diagrams_to_check():
    """A regex that silently matches nothing is not a test."""
    module = _generator()
    assert len(module.DIAGRAMS) >= 6
    pictures = sum(len(re.findall(r"<picture>", p.read_text(encoding="utf-8"))) for p in PAGES)
    assert pictures >= 6, f"only {pictures} <picture> blocks found across the docs"
