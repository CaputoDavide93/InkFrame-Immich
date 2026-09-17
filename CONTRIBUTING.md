# 🤝 Contributing

Thanks for looking. Small, well-argued changes land fastest.

## Before you start

Open an issue for anything beyond a bug fix, so we can agree on the shape before you spend an evening on it. Other e-paper panels and other photo servers are the most wanted contributions.

## Working on the renderer

```bash
cd server
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest
python -m pytest tests -q
```

If you change what the code reads from the environment, the settings spec, or the routes, regenerate the docs and commit the result:

```bash
python ../tools/gen_docs.py
```

`gen_docs.py --check` fails when a table is stale, and also when a route or variable has no description, so add one.

## Working on the firmware

```bash
pip install esphome
esphome config firmware/immich-frame.yaml    # validates without a device
```

Two rules from experience, both explained in the file: keep `busy_pin` inverted, and keep the `switch.is_off: stay_awake` guard around `deep_sleep.enter`.

## Working on the integration

The integration imports and instantiates cleanly under the Home Assistant version on PyPI; a real Home Assistant is the only full test. Keep entity names in Title Case, keep the `/preview.png` rule (the integration never fetches `/frame.*`), and keep the docstrings honest about what an entity can and cannot know.

## Brand and demo images

`tools/gen_brand.py` draws `brand/` and `docs/assets/demo.png` from code. Edit the script, run it, commit the result; never edit the PNGs by hand.

## Style

- Comments explain why, not what. The code already says what.
- Documentation never lies. If you change behaviour, change the doc in the same commit.
- Plain English, active voice, no marketing.

## Commits

Conventional prefixes (`feat:`, `fix:`, `docs:`, `chore:`), one concern per commit, a body that says why. No sign-off trailers.
