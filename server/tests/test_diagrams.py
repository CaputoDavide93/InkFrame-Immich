"""Every Mermaid diagram in this repository has to survive GitHub.

The architecture diagram in the README shipped broken and stayed that way:
the node label `PN["XIAO 7.5&quot; panel"]` renders as a red "Unable to render
rich display" box on the repository's front page.

The mechanism is worth knowing, because nothing local could see it. **GitHub
HTML-decodes the contents of a fenced block before handing it to Mermaid.** So
Mermaid receives `PN["XIAO 7.5" panel"]`, the label ends at the inch mark, and
the rest of the diagram is garbage. Parsing the file as written succeeds on
every Mermaid version from 9 to 11; parsing the decoded form fails on every
one of them. Checked against the real thing with a browser, the error is
byte-for-byte the one GitHub showed.

So the rule is simply: no HTML entities inside a Mermaid block. There is never
a need for one -- write the character, or reword.
"""
import html
import pathlib
import re

HERE = pathlib.Path(__file__).resolve()
# Flat layout in the source monorepo, server/ layout in the public repository.
ROOT = next(p for p in (HERE.parents[1], HERE.parents[2]) if (p / "README.md").exists())
BLOCK = re.compile(r"^```mermaid[^\n]*\n(.*?)^```", re.S | re.M)
ENTITY = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]{1,31}|#\d{1,7}|#[Xx][0-9A-Fa-f]{1,6});")


def _blocks():
    for path in sorted(ROOT.glob("*.md")) + sorted(ROOT.glob("docs/**/*.md")):
        text = path.read_text(encoding="utf-8")
        for match in BLOCK.finditer(text):
            yield path.relative_to(ROOT), text[: match.start()].count("\n") + 2, match.group(1)


def test_there_are_diagrams_to_check():
    """A regex that silently matches nothing is not a test."""
    assert len(list(_blocks())) >= 5


def test_no_html_entity_inside_a_mermaid_block():
    bad = [
        f"{path}:{line + offset}: {entity.group(0)}  in: {src.splitlines()[offset].strip()[:70]}"
        for path, line, src in _blocks()
        for offset, text in enumerate(src.splitlines())
        for entity in [ENTITY.search(text)]
        if entity
    ]
    assert not bad, (
        "GitHub decodes these before Mermaid parses them, which breaks the "
        "diagram on the rendered page while the file looks correct:\n  "
        + "\n  ".join(bad)
    )


def test_quotes_balance_once_github_has_decoded_the_block():
    """The failure the entity actually causes, checked directly.

    Belt and braces: an entity is the way it happened, but any stray quote in
    a label ends it early just the same.
    """
    bad = []
    for path, line, src in _blocks():
        for offset, text in enumerate(html.unescape(src).splitlines()):
            if text.count('"') % 2:
                bad.append(f"{path}:{line + offset}: odd number of quotes: {text.strip()[:70]}")
    assert not bad, "a label ends early once decoded:\n  " + "\n  ".join(bad)
