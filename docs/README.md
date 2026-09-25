# 📚 InkFrame docs

| Doc | What it covers |
|---|---|
| [architecture.md](architecture.md) | The three parts — renderer, Home Assistant integration, panel — and how they talk |
| [api.md](api.md) | The renderer's HTTP API and every environment variable |
| [rendering.md](rendering.md) | Choosing a photograph and turning it into one-bit pixels |
| [wake-and-sleep.md](wake-and-sleep.md) | How often the frame wakes, what that costs, and how to tell asleep from dead |
| [firmware.md](firmware.md) | The ESPHome configuration and the decisions in it |
| [hardware.md](hardware.md) | The panel and its hardware |
| [home-assistant.md](home-assistant.md) | The `inkframe` integration: device, entities, polling |
| [operations.md](operations.md) | Running the renderer |
| [releasing.md](releasing.md) | How the renderer, integration and firmware each ship |
| [troubleshooting.md](troubleshooting.md) | Symptom-first fixes |

Diagrams and the demo image live in [assets/](assets/); they are drawn by `tools/gen_diagram.py` and `tools/gen_brand.py`.
