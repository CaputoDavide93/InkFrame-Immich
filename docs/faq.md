# ❓ FAQ

Short answers to the questions people ask before and after building the frame. Setup is in [setup.md](setup.md), problems are in [troubleshooting.md](troubleshooting.md), and the reasoning is in [how-it-works.md](how-it-works.md).

## Getting started

### What is InkFrame for Immich?

InkFrame is a free, open-source (MIT) photo frame that shows a photo from your own Immich library on a battery-powered 7.5-inch e-paper panel. A small server picks and prepares the photo, the panel draws it and sleeps for days, and a Home Assistant integration chooses the source and shows what is on the glass.

### What hardware does it need?

It needs the Seeed Studio XIAO 7.5" ePaper Panel, a host with Docker for the renderer, an Immich server and, for the controls, Home Assistant. The panel is the only hardware tested. See [Hardware](hardware.md) and the [supported table](../README.md#supported-hardware-and-software).

### Do I need Home Assistant?

The frame works without it, but you lose the controls and the status. The renderer and the panel need only each other and Immich. Without the integration you change the source and settings by calling the renderer's `/source` and `/settings` endpoints, which are listed in [the API doc](api.md).

### Do I need HACS?

No. HACS is the easy way to install and update the integration. You can copy `custom_components/inkframe` into your Home Assistant `custom_components` folder and restart instead.

### Is it free?

Yes. It is MIT licensed, with no account, subscription or cloud service. You pay for the panel and for the host that runs the renderer.

## How it behaves

### Can I wake the panel from Home Assistant?

No. The panel is in deep sleep between wakes: its radio is off and nothing on the network can reach it. The renderer prepares the next photo and waits, and the panel collects it at its next wake. Pressing the reset button on the back of the XIAO wakes it at once.

### Why did my change not appear on the frame?

A change made in Home Assistant is stored on the renderer and reaches the glass at the panel's next wake, and a photo changes only when a draw is due. **Next photo** picks a different photo for the scheduled draw rather than drawing now.

### How often does the photo change?

<!-- AUTOGEN:cadence -->
By default the renderer draws a new photo every 3 days at 07:00 (Photo every and Photo hour). With the default Sleep interval of 168 h the panel wakes on those mornings only. A shorter Sleep interval adds checks on a fixed clock grid anchored on the draw hour: 6 h gives 01:00, 07:00, 13:00 and 19:00. A check takes about 7 seconds awake and a draw about 35.
<!-- /AUTOGEN:cadence -->

Both the interval and the draw schedule are settings in Home Assistant (**Sleep interval**, **Photo every**, **Photo hour**), so changing them needs no reflash. See [Wake and sleep](wake-and-sleep.md).

### How do I put a new photo up right now?

Ask the renderer for one and wake the panel. Call `/next?now=1` on the renderer with the token, then press the reset button on the panel. The panel draws on that wake. Pressing reset alone only checks and sleeps again when no draw is due. The command is in [setup.md](setup.md#7-check-that-a-photo-reaches-the-glass).

### How long does the battery last?

Seeed rate the 2000 mAh cell at about three months when refreshing every six hours. Awake time is about 35 seconds for each draw and 7 for each check, so the limit becomes the cell's own discharge; expect many months and measure your own. The panel has no battery sensor: the cell's voltage is not wired to the ESP32 on this board, so charge cannot be read in software. See [Hardware](hardware.md#battery).

### How do I know whether the frame is working?

Check **On panel** and **Last check-in** in Home Assistant. **Last check-in** moves every time the panel calls the renderer, so if it stops moving for longer than a few sleep intervals, the panel is not waking. A dead battery shows the same photo as a healthy frame, because e-paper holds its image without power. See [The failure you cannot see](wake-and-sleep.md#the-failure-you-cannot-see).

### Why is there a server at all?

The panel's chip, an ESP32-C3, has no PSRAM and about 200 KB of heap, so it cannot fetch, decode, scale or dither a photograph. The renderer does that and sends a finished one-bit frame of 48,000 bytes that the panel copies to the display. See [Architecture](architecture.md#why-the-renderer-exists).

## Photos

### Which photos does it pick?

Landscape photos taken by a camera that are calm enough to dither well. It filters by EXIF orientation, by whether the EXIF `make` is set, and by a texture score, then downloads twenty candidates and renders a random one that is calm enough, or the calmest when none is. See [Rendering](rendering.md).

### Can I choose people, an album or a pet?

Yes. The source can be random, recent, people, one person, an album, or a text search. A search for `cat` finds the cat, because Immich clusters people's faces and a pet has no person to select. See [Home Assistant](home-assistant.md#sources).

### Why are some of my photos never shown?

They fail a filter. Portraits are cropped rather than skipped by default, but photos without camera EXIF, photos with no readable orientation, and photos whose texture score is above **Max busyness** are passed over. A person appears as a source only above 20 landscape photographs by default. Check `/people` and `/status` on the renderer.

### Can it show screenshots or memes?

Not by default. The camera filter drops anything without an EXIF `make`. Turn **Photographs only** off in Home Assistant, or set `REQUIRE_CAMERA=0`, to allow them.

### Why does a photo look speckled?

Fine texture such as grass and foliage turns into dot noise on a one-bit panel. Lower **Max busyness** so the renderer prefers calmer photos, or raise **Smooth**. The **Busyness** sensor shows the chosen photo's score. See [Rendering](rendering.md#busyness).

### Does it support colour?

No. The panel is black and white and the renderer dithers to one bit. Colour and greyscale panels would need a different dither target and are not supported.

### Can I use another e-paper panel?

Possibly, but it is untested. Change `PANEL_W` and `PANEL_H` in `server/src/immich.py` and the display model and size in the firmware. See [Hardware](hardware.md#other-panels). If you try it, [open an issue](https://github.com/CaputoDavide93/InkFrame-Immich/issues) with the model and the result.

## Privacy and security

### Do my photos leave my network?

No. The renderer reads from your Immich server and serves frames to the panel and to Home Assistant. It makes no other outbound connection. See [SECURITY.md](../SECURITY.md).

### Is the traffic encrypted?

No. The renderer speaks plain HTTP and every endpoint except `/healthz` needs the shared bearer token, which travels in a header. Keep the renderer on a network you trust and do not expose port 8099 to the internet.

### What does the Immich API key need?

`asset.read`, `asset.view`, `asset.statistics`, `album.read` and `person.read`. Add `face.read` to crop portraits around faces. Nothing here needs more, and the key is never logged or returned by an endpoint.

## Reporting

### How do I report a problem or a new panel?

Open an [issue](https://github.com/CaputoDavide93/InkFrame-Immich/issues) and attach the renderer's `GET /status` output with the token removed, the log lines from one wake, and your Immich, Home Assistant and ESPHome releases. The list is in the [README](../README.md#-contributing).

### Is this affiliated with Immich or Seeed Studio?

No. It is an independent project. Immich and Seeed Studio are names of their owners, used here only to say what it works with.
