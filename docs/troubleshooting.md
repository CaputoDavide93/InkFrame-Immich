# 🛠️ Troubleshooting

## The panel is asleep and I need it now

A sleeping panel has no network. It looks exactly like a dead one, and it will not answer until its timer fires or you press reset on the XIAO.

Arm the flash first, then press:

```bash
# Waits for the panel, flashes inside its wake window, exits 0 on success and 1 if it gave up.
until nc -z -G 1 <panel-ip> 3232 2>/dev/null; do sleep 1; done
esphome upload firmware/immich-frame.yaml --device <panel-ip>
```

The window is the OTA window (20 seconds by default) plus the time the fetch and draw take, about 35 seconds in total. If you want longer, turn the **Stay awake** switch on in Home Assistant while the panel is up.

## The photo did not change

Check `On panel` in Home Assistant, or `on_panel` in `/status`.

| `on_panel` | Rendered generation | Meaning |
|---|---|---|
| true | unchanged for a week | The panel woke and collected, and `/wake` chose not to rotate because... it should have. Check the renderer log for `wake:` lines |
| false | advanced | A new frame exists and the panel has not fetched it. Either the panel has not woken yet, or its fetch failed. Look at `Last panel fetch` |
| false | unchanged | The renderer has not been asked to render. Nothing called `/wake` or `/next` |

E-paper keeps its image with no power, so the glass alone tells you nothing.

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

## Setup says "Could not reach an ImmichFrame renderer"

The URL answered, but not with a renderer. Setup probes `/healthz` and requires a `generation` field so that pointing the integration at Immich itself, or at another service on the same host, fails at setup instead of on the first poll.

## Docker: the container cannot read the API key

Docker secrets are mounted read-only and the process runs as uid 1000. A key file with mode 0600 owned by you is unreadable inside the container. Use 0644.
