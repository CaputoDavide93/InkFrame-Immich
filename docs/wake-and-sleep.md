# ⏰ Wake and sleep

How often the frame wakes, what that costs, and why a frame that has stopped
working looks exactly like one that has not.

## The one thing to understand

**You cannot wake the panel.** It is an ESP32-C3 in deep sleep: the radio is
off, it does not answer a ping, and nothing on the network can reach it. The
server prepares the next photo and waits; the panel collects it when it next
wakes, on its own timer.

Frames built this way have no remote wake. What makes one *feel* instant is
only the cadence, minutes rather than hours.

Two consequences worth internalising:

- **"Change Next Photo" on the frame page does not change the glass.** It
  picks a different next photo and holds it for the scheduled draw. The
  picture changes on schedule, as it would have anyway.
- **Pressing reset on the back is the only instant path.** It reboots the
  node, which wakes it and calls `/wake`. A wake draws only when a draw is
  due or a photo was asked for, so to put a photo up now, call
  `/next?now=1` on the renderer first (see [Setup](setup.md#7-check-that-a-photo-reaches-the-glass)),
  then press reset. The draw takes about thirty-five seconds.

## What a wake costs

From `hardware.md`, in order of cost:

| | |
|---|---|
| 1. Time awake | Dominant. More than everything below combined |
| 2. Wi-Fi association | 3 to 5 seconds, every wake |
| 3. E-paper refresh | About 5 seconds, fixed by physics |
| 4. The fetch | About 4 seconds for a 48 KB BMP |

A wake that **draws** runs about 35 seconds: associate, call `/wake`, fetch,
refresh, then hold the OTA window before sleeping.

A wake that only **checks** skips the fetch, the refresh *and* the OTA hold,
because that hold lives inside `on_download_finished` and there is no
download. That is roughly 7 seconds.

The one exception is a flash. With the **OTA window** at 60 seconds or more the
renderer answers every wake with `draw: true` and the generation already on the
glass, so a check redraws the same photo and holds the window. Nothing on the
wall or in the schedule moves. See [Firmware](firmware.md#flashing-over-the-air-step-by-step).

So checking is about five times cheaper than drawing. The intuition that
"not changing the photo saves nothing because waking is the cost" is wrong:
most of a drawing wake is the drawing.

| Pattern | Awake per day |
|---|--:|
| Every 8 h, always drawing | ~105 s |
| Four checks a day, drawing every third day | **~40 s** |
| Every 6 h, always drawing | ~140 s |

## Battery, and why there is no battery sensor

A 2000 mAh Li-Po, charged over USB-C. Seeed rate it at about three months
refreshing every six hours.

**The cell's voltage is not wired to the ESP32 on this board.** Reading it
needs two resistors soldered on. So the firmware exposes no battery sensor,
and none can be added in software. You are flying blind on charge, and that is
a hardware fact rather than an oversight.

## The failure you cannot see

E-paper holds its last image with no power. A frame whose battery died in
September shows the same photograph, at the same brightness, as one that woke
ten minutes ago. Nothing about the wall tells you.

It happened on the author's frame: the panel stopped collecting for four days,
and was found only because somebody pressed "new photo" and noticed nothing
changed. Nothing was watching.

The cause was a transient `/wake` failure. `sleep_seconds` stayed 0, so the
firmware fell back to its static duration, which was **seven days**. The photo
still drew, because the script fetches `/frame.bmp` whether or not `/wake`
succeeded, so the failure was invisible from every angle.

Three fixes came out of it:

- The `/wake` fallback and the `run_duration` backstop are **one hour**, not a
  week. A path that has already gone wrong should come back soon.
- The download retry is **counted**. It said "retrying once" and counted
  nothing, so a failed `component.update` re-entered `on_error` every ten
  seconds until the backstop killed the node, and then slept a week.
- `on_boot` re-arms `deep_sleep.prevent` when `stay_awake` is restored on, at
  priority **-100**. Higher priority runs *earlier* in ESPHome, and at the 600
  default the switch has not restored from flash yet.

## Knowing it stopped

Build an automation that alerts you when either of two things is true: the
panel has not **checked in** (`sensor.inkframe_last_check_in`) for three sleep
intervals, or it has not **fetched** a photo (`sensor.inkframe_last_panel_fetch`)
for longer than the draw interval plus a day of grace. The first catches a
panel that stopped waking; the second catches one that wakes but cannot draw.

Read each sensor's **value**, never its `last_changed`. Each value is a
timestamp the renderer sets. `last_changed` is re-stamped whenever Home
Assistant restarts, so a `last_changed` check would report a dead frame as
minutes old.

Take the check-in threshold from `number.inkframe_sleep_interval`, so changing
the cadence moves the alarm with it and the two cannot disagree. The entity ids
follow the device name you chose at setup.

## Stay awake

The panel's **Stay awake** switch blocks the sleep so you can flash or
tune. It is stored in flash and survives deep sleep.

Turn it **off** when you are done. On a battery frame with no battery sensor,
leaving it on drains the cell with no warning at all.

## Changing the cadence

`number.inkframe_sleep_interval`, 1 to 336 hours. The renderer delivers it on
the next `/wake`, so it takes effect one wake later, never immediately. The
firmware's own value is only a fallback for a wake where `/wake` could not be
reached.
