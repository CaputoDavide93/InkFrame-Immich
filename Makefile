# One entry point for the checks CI runs. `make check` before every push.
PYTHON := .venv/bin/python

.PHONY: venv test docs diagram check brand screenshots firmware

venv: ## Renderer test environment
	python3 -m venv .venv
	.venv/bin/pip install -q -r server/requirements.txt pytest

test: venv ## The renderer's pytest suite
	$(PYTHON) -m pytest server/tests -q

docs: ## Regenerate the tables in the docs from the code
	python3 tools/gen_docs.py

diagram: ## Redraw docs/assets/*.svg
	python3 tools/gen_diagram.py

check: test ## Everything the renderer job in CI checks
	python3 tools/gen_docs.py --check
	python3 tools/gen_diagram.py --check

brand: venv ## Redraw brand/, the demo image and the social preview
	$(PYTHON) tools/gen_brand.py

firmware: ## Validate the ESPHome config with example secrets (needs esphome installed)
	cp firmware/secrets.yaml.example firmware/secrets.yaml
	sed -i.bak "s|CHANGE_ME_KEY|$$(openssl rand -base64 32)|" firmware/secrets.yaml
	esphome config firmware/immich-frame.yaml > /dev/null; status=$$?; \
		rm -f firmware/secrets.yaml firmware/secrets.yaml.bak; exit $$status

screenshots: ## Retake docs/assets/screenshots/ from a real renderer and Home Assistant (not CI)
	test -x .venv-screenshots/bin/python || ( \
		python3 -m venv .venv-screenshots && \
		.venv-screenshots/bin/pip install -q -r tools/screenshots/requirements.txt )
	.venv-screenshots/bin/python -m playwright install chromium
	.venv-screenshots/bin/python tools/screenshots/take_screenshots.py
