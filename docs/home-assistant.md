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
| **Recent window** | number, days | The N in Recent |
| **Next photo** | button | Render a new photo now. The panel collects it at its next wake |
| **Max busyness** | number | Reject threshold for the busyness score. The knob that most changes which photos appear |
| **Sleep interval** | number, hours | Delivered to the panel at its next wake |
| **OTA window** | number, seconds | How long the panel stays reachable after drawing. Config section |
| **Smooth**, **Tone curve**, **Edge** | number | Render treatment. Config section |
| **Photographs only** | switch | The EXIF camera filter. Config section |
| **Preview** | image | The one-bit frame the panel will collect |
| **Photo** | sensor | Filename, with taken date, source and busyness as attributes |
| **Busyness** | sensor | The chosen photo's score |
| **On panel** | binary sensor | Whether the panel has collected the rendered frame |
| **Last panel fetch** | timestamp | The panel's last wake |
| **Candidates rejected**, **Last error** | sensor | Diagnostic section |

Contrast and the candidate count are deliberately not exposed. Contrast overlaps the tone curve, and twenty candidates is right; more only costs time. Both stay settable on the renderer by environment variable.

## Sources

**Random** draws from the whole library. **Recent** draws from the last N days. **Album** draws from one album; if your library has none yet, the select says so and the option appears the day you make one.

**People** is a union. Tick the people you want and the frame draws from photos of any of them. Immich's own multi-person search is an intersection, photos containing everyone at once, which is rarely what "photos of the kids" means, so the renderer queries each person and merges.

A person is offered only above a minimum number of landscape photographs (20 by default, `MIN_PERSON_PHOTOS` on the renderer). Below that a source runs dry against the recently-shown list and repeats. The renderer counts each named person's eligible photos in the background once a day; the counts are attributes on the Source select.

## Rendered is not displayed

E-paper holds its last image with no power, so a frame the panel never fetched looks identical to one on the wall. **On panel** is the one entity that can tell them apart: it is true when the panel has fetched the generation currently rendered, and false from the moment a new photo is rendered until the panel collects it.

This is why the **Preview** image and the coordinator fetch `/preview.png` and never `/frame.png`. The renderer marks a frame as collected when anything fetches `/frame.*`; if Home Assistant used that path, opening your dashboard would mark the photo as displayed.

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
