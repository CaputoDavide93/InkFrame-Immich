# 🏠 Home Assistant

`custom_components/inkframe` presents the renderer as one device. It polls `/status` every five minutes and writes back through `/source`, `/settings` and `/next`. It never talks to the panel.

## Install

1. In HACS, **Custom repositories**, add `https://github.com/CaputoDavide93/InkFrame-Immich` with category *Integration*, then install **InkFrame for Immich**. Without HACS, copy `custom_components/inkframe` into `<config>/custom_components/`.
2. Restart Home Assistant. Custom integrations load at start.
3. **Settings → Devices & Services → Add Integration → InkFrame for Immich.**
4. Enter the renderer URL, for example `http://<renderer-host>:8099`. Setup probes `/healthz` and checks the reply is a renderer, not just something listening on that port.

The poll interval is an option on the integration; the default is 300 seconds.

## Entities

| Entity | Kind | What it does |
|---|---|---|
| **Source** | select | Random, Recent, People, Album, or one named person |
| **Include *Name*** | switch, one per eligible person | Who the People source draws from |
| **Album** | select | Which album, when Source is Album. Choosing one switches Source to Album |
| **Refresh albums** | button | Re-read the album list from Immich. The picker is otherwise filled once a day, so a new album waits until tomorrow. Config section |
| **Recent window** | number, days | The N in Recent |
| **Next photo** | button | Pick a different next photo. It goes up at the scheduled draw, not sooner |
| **Max busyness** | number | Reject threshold for the busyness score. The knob that most changes which photos appear |
| **Sleep interval** | number, hours | Delivered to the panel at its next wake |
| **OTA window** | number, seconds | How long the panel stays reachable after drawing. At 60 or more every wake redraws the photo already shown, so a check holds the window too; set it back after a flash. Config section |
| **Smooth**, **Tone curve**, **Edge** | number | Render treatment. Config section |
| **Photographs only** | switch | The EXIF camera filter. Config section |
| **On the panel** | image | The photo acknowledged after the panel's display update |
| **Up next** | image | The most recent render, which the panel collects at its next wake |
| **Portraits** | switch | Off: portraits are cropped to fit. On: they are skipped |
| **Photo** | sensor | Filename, with taken date, source and busyness as attributes |
| **Busyness** | sensor | The chosen photo's score |
| **On panel** | binary sensor | Whether the panel acknowledged the rendered generation |
| **Last panel fetch** | timestamp | The last acknowledged display update; the entity name is retained |
| **Candidates rejected**, **Last error** | sensor | Diagnostic section |

Contrast and the candidate count are deliberately not exposed. Contrast overlaps the tone curve, and twenty candidates is right; more only costs time. Both stay settable on the renderer by environment variable.

## Sources

<!-- AUTOGEN:modes -->
| API `mode` | Home Assistant Source | Draws from |
|---|---|---|
| `random` | Random | The whole library, filtered by the settings |
| `person` | a person's name | Photos of one named person from Immich's face recognition |
| `people` | People | Photos of any of the people whose Include switch is on (a union, not an intersection) |
| `recent` | Recent | Photos taken in the last N days |
| `album` | Album | One album, read live from Immich |
| `search` | Search | Photos matching a description, ranked by Immich's smart search; the best 120 are kept |
<!-- /AUTOGEN:modes -->

**Album** draws from one album; if your library has none yet, the select says so and the option appears the day you make one.

**Search** asks Immich what the photo looks like rather than who is in it.
Type a description into **Search for** and the frame draws from the matches:
`cat` is why it exists, because face recognition clusters people and a pet has
no person to select, but `beach`, `snow` and `birthday cake` work the same way.
Matches are ranked rather than filtered, so the pool is trimmed to the best
hundred and twenty; taking everything would let a loose description quietly
turn Search into Random.

**People** is a union. Tick the people you want and the frame draws from photos of any of them. Immich's own multi-person search is an intersection, photos containing everyone at once, which is rarely what "photos of the kids" means, so the renderer queries each person and merges.

A person is offered only above a minimum number of landscape photographs (20 by default, `MIN_PERSON_PHOTOS` on the renderer). Below that a source runs dry against the recently-shown list and repeats. The renderer counts each named person's eligible photos in the background once a day; the counts are attributes on the Source select.

## Two pictures, and why

**On the panel** and **Up next** usually show the same photograph. They differ
from the moment something renders a new one until the panel next wakes, which
on a weekly cycle is days. That gap is the point: e-paper holds its last image
with no power, so nothing about the wall tells you a newer photo is waiting.

`On the panel` reads unknown until a display acknowledgement is recorded.
Acknowledged images and their generation identities survive renderer restarts.

Each card asks for its frame **by generation number**. A generation the
renderer no longer holds is a 404, never a substitute photo, which is the whole
reason the numbers exist.

## Rendered is not displayed

E-paper holds its last image with no power. **On panel** is true when the panel has acknowledged the generation currently rendered, and false while a newer photo is waiting. A completed download alone is not a display acknowledgement.

The **Preview** image and coordinator fetch `/preview.png`. Only panel firmware sends the authenticated `POST /frame/ack?gen=N` after its display update. Opening the dashboard cannot acknowledge a draw. The acknowledgement reflects the driver's reported result, not independent verification of physical pixels.

The contract test in the source repository checks this by scanning the integration's string literals.

## Settings survive a redeploy

Anything you set from Home Assistant is written to the renderer's state file on a named volume. Redeploying the container, or changing an environment variable, does not undo a change made from the dashboard. Environment variables are defaults for a fresh state file only.

## Example automation

Show only photos of the household for the week of a birthday:

```yaml
automation:
  - alias: Frame shows the family this week
    triggers:
      - trigger: calendar
        entity_id: calendar.birthdays
        event: start
    actions:
      - action: select.select_option
        target:
          entity_id: select.inkframe_source
        data:
          option: People
      - action: button.press
        target:
          entity_id: button.inkframe_next_photo
```

Turn the relevant **Include** switches on once; they persist.
