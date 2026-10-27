# 🛠️ Troubleshooting

Find your symptom, then read down to the fix. For anything not listed, [open an issue](https://github.com/CaputoDavide93/InkFrame-Immich/issues) with the renderer's `GET /status` output (token removed) and the log lines from one wake. [FAQ](faq.md) has the short answers.

| Symptom | Go to |
|---|---|
| The frame shows the same photo and I want a new one | [The panel is asleep](#the-panel-is-asleep-and-i-need-it-now) and [The photo did not change](#the-photo-did-not-change) |
| Home Assistant setup says it could not reach the renderer | [Setup says "Could not reach an InkFrame renderer"](#setup-says-could-not-reach-an-inkframe-renderer) |
| The Source select lacks a person or an album | [People are missing](#people-i-expect-are-missing-from-the-source-select), [Albums](#i-made-an-album-in-immich-and-the-picker-does-not-offer-it) |
| `/wake` or `/next` fails with "nothing matched" | [Nothing matched](#wake-and-next-fail-with-nothing-matched) |
| The picture is speckled or a negative | [Too busy](#the-renderer-says-every-candidate-was-too-busy), [Negative](#the-picture-is-a-negative) |
| The container cannot read the API key | [Docker key](#docker-the-container-cannot-read-the-api-key) |

## The panel is asleep and I need it now

A sleeping panel has no network. It looks exactly like a dead one, and it will not answer until its timer fires or you press reset on the XIAO.

Arm the flash first, then press:

```bash
# Waits for the panel, flashes inside its wake window, exits 0 on success and 1 if it gave up.
until nc -z -G 1 <panel-ip> 3232 2>/dev/null; do sleep 1; done
esphome upload firmware/immich-frame.yaml --device <panel-ip>
```

The window is the OTA window (20 seconds by default) plus the time the fetch and draw take, about 35 seconds in total. If you want longer, turn the **Stay awake** switch on in Home Assistant while the panel is up.

If you can wait for the next check instead of pressing reset, follow [Flashing over the air, step by step](firmware.md#flashing-over-the-air-step-by-step).

## The photo did not change

Check `On panel` in Home Assistant, or `on_panel` in `/status`.

| `on_panel` | Rendered generation | Meaning |
|---|---|---|
| true | unchanged for longer than **Photo every** | The panel acknowledged the current generation. Check the configured refresh interval and renderer `wake:` logs |
| false | advanced | A newer frame has not been acknowledged. Check wake, download, display-driver and acknowledgement failures; `Last panel fetch` records the last acknowledged draw |
| false | unchanged | The renderer has not been asked to render. Nothing called `/wake` or `/next` |

E-paper keeps its image with no power, so the glass alone tells you nothing.

Older firmware downloads `/frame.bmp` and never sends `POST /frame/ack?gen=N`. Until the renderer has recorded one valid acknowledgement, a completed `/frame.bmp` or `/frame.bin` download counts as the draw, so a renderer updated before the panel keeps rotating. The first valid acknowledgement switches that fallback off and is remembered in `/data/panel-protocol.json`. If the panel is ever flashed back to firmware without acknowledgements, delete that file and restart the renderer, or the photo stops changing. The acknowledgement also cannot detect a physical display fault that the driver does not report.

## An album with photos in it reports as empty

Fixed on 2026-09-17, recorded because the shape recurs. `/api/albums/{id}`
returns the album's metadata and `assetCount` but **no `assets` key**, so
reading assets from it yields an empty list. The renderer reported "no
landscape photographs" about an album holding sixteen, which sent the blame to
the library rather than the code. Album assets come from
`/api/search/metadata` with `albumIds` now, and a test pins that choice.

If you see it again: compare `assetCount` from `/api/albums` against what
`/albums` and `/status` say the renderer found.

## I made an album in Immich and the picker does not offer it

Press **Refresh albums** in Home Assistant. The picker is filled from a cache
the renderer rebuilds once a day beside the per-person counts, so an album made
this afternoon is otherwise missing until tomorrow.

Rendering never used that cache -- `/source?mode=album&album=<name>` and the
render itself both read Immich live -- so an album was always usable by name
while being invisible in the list. Two views of the same library disagreeing
for a day reads as the integration not seeing the album at all, which is why
`GET /albums` now writes what it read back into the cache.

## `/wake` and `/next` fail with "nothing matched"

The chosen source has nothing eligible. For a person, check the count in the Source select's attributes; for an album, check it contains landscape photographs taken with a camera. Switch to Random to confirm the renderer itself is healthy. The message says
whether the source was empty or a filter rejected everything, and names
`landscape_only` when that is the filter in question.

## `online_image` logs an allocation failure

The 48 KB decode buffer could not be allocated. Watch **Heap largest block** on the panel: if it sits near 20 KB before the first fetch, something else grabbed memory first. Do not add components to the firmware; the budget is what it is. Power-cycle the panel to defragment.

## Portraits are still being skipped

`landscape_only` is on. Turn **Portraits** off in Home Assistant, or set
`LANDSCAPE_ONLY=0`. If portraits appear but are cropped oddly, check that the
API key carries `face.read`: without it Immich returns no boxes, the crop falls
back to centred, and a standing subject is cropped at the chest.

## The picture is a negative

`pack()` is inverting the wrong way for your panel, or the BMP palette is swapped. `tests/test_frame.py::test_pack_inverts_polarity` pins the current behaviour: a set bit means ink. If your display controller expects the opposite, invert in one place, `_INVERT` in `server/src/immich.py`, and update the test.

## People I expect are missing from the Source select

A person is offered only above `MIN_PERSON_PHOTOS` eligible landscape photographs. Check `/people` for their count. The count refreshes once a day; restart the renderer to force it.

## The renderer says every candidate was too busy

Your source is mostly foliage. Lower **Max busyness** and the frame will show calmer photos; raise it and accept some speckle. The `Candidates rejected` sensor tells you how hard the threshold is working.

## Setup says "Could not reach an InkFrame renderer"

Setup calls the renderer's `/status` with the token you entered, and requires a `generation` field in the reply. It fails when the address is wrong, when the renderer is not running, when the token does not match (the renderer answers `401`), or when the URL points at another service such as Immich itself. Check from the Home Assistant host:

```bash
curl -s -H "Authorization: Bearer $(cat ~/Secrets/inkframe_token)" http://<renderer-host>:8099/status
```

A JSON reply means the renderer is fine and the token or URL typed into the form is not. Setup logs the reason as a warning in **Settings → System → Logs**.

## Docker: the container cannot read the API key

Docker secrets are mounted read-only and the process runs as uid 1000. A key file with mode 0600 owned by you is unreadable inside the container. Use 0644.
