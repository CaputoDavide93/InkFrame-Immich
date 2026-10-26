# Agent instructions

This repository follows the house standards of its owner, Davide Caputo.

## Rules that apply to every change

- **Documentation never lies.** Every command, flag, feature, count and badge must be true of the code. Verify before writing; delete what you cannot verify. No hand-typed counts that can drift: generate them (`tools/gen_docs.py`) or leave them out.
- **Commits:** conventional (`fix:`, `feat:`, `docs:`, `refactor:`, `ci:`, `chore:`), authored by the repo owner. Never add co-author trailers, session identifiers, "generated with" lines or any other tool attribution, in commits, pull request bodies, issues or comments.
- **Never** force-push the default branch, commit secrets, or change runtime identifiers (the `inkframe` domain, environment variable names, container and image names, entity ids, public URLs) as a side effect.
- Run the repo's own checks before and after a change, and keep anything that was green green: `make check`.
- Public repository: demo data only. Addresses are `192.0.2.x`, names are placeholders, photographs are drawings.

## README

- Centered header: one emoji H1 (the same emoji as the GitHub description), a **bold** one-line tagline, flat shields.io badges (tech, then platform, then license, then live CI; no `style=`), then `---`.
- Emoji `##` headings in the canonical order, `---` between sections, features as an emoji-lead table, a repo tree in a `text` block that matches `git ls-files`.
- `## 🗺️ Architecture` opens with the house-kit diagram: `tools/gen_diagram.py` writes `docs/assets/architecture-{light,dark}.svg`, embedded with `<picture>` (dark `<source>`, light `<img width="100%">`, a one-sentence alt). No Mermaid for architecture, no ASCII boxes.
- Screenshots live in `docs/assets/screenshots/<screen>-{light,dark}.png`, taken by `make screenshots`.
- The README ends with `---` and then exactly:
  `<p align="center"><sub>Made with ❤️ by <a href="https://github.com/CaputoDavide93">Davide Caputo</a></sub></p>`
  No star request, no extra lines.

## Layout and naming

- Directories `lowercase-kebab`; docs `docs/lowercase-kebab.md`; shell scripts `kebab-case.sh`; Python `snake_case`. Toolchain rules win (Home Assistant `custom_components/<domain>`, ESPHome `.yaml`).
- Code in `server/src/`, tests in `server/tests/`, repo generators in `tools/`, docs in `docs/` with `docs/README.md` as the index.
- One `.env.example` with every variable the code reads, obviously fake placeholders.
