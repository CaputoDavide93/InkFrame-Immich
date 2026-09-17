# 📟 Hardware

## The panel

[Seeed Studio XIAO 7.5" ePaper Panel](https://wiki.seeedstudio.com/xiao_075inch_epaper_panel/): a carrier board with a XIAO ESP32-C3 module, a 7.5" 800x480 black-and-white e-paper display (UC8179 controller, ESPHome model `7.50inv2`), a 2000 mAh Li-Po cell and a USB-C port that charges it.

The ESP32-C3 has 400 KB of SRAM and no PSRAM. That single fact shapes the whole project; see [Architecture](architecture.md#why-the-renderer-exists).

## Pinout

From the [Seeed ESPHome cookbook](https://wiki.seeedstudio.com/xiao_075inch_epaper_panel_esphome/), verified on the device:

| Signal | GPIO |
|---|---|
| SPI CLK | 8 |
| SPI MOSI | 10 |
| CS | 3 |
| DC | 5 |
| RESET | 2 |
| BUSY | 4, **inverted** |

> **The BUSY pin must be configured `inverted: true`.** Seeed's documentation states that omitting the inversion can damage the panel. The firmware has it; do not tidy it away.

## Battery

Seeed rate the cell at about three months when refreshing every six hours in deep sleep. This project refreshes once a week and keeps the panel awake for about 35 seconds per wake, so the limit becomes the cell's self-discharge rather than the panel's draw. Expect many months; measure your own.

Battery voltage is not wired to the ESP32 on this panel. Reading it needs two resistors soldered on, which is why the firmware exposes no battery sensor. The wiki has the details for the related EE04 driver board.

What costs battery, in order:

1. Time awake. Ninety seconds of idle after the draw cost more than everything else on this list together; the firmware now sleeps as soon as the photo is on the glass plus a short OTA window.
2. Wi-Fi association, about 3 to 5 seconds per wake.
3. The e-paper refresh itself, about 5 seconds and fixed by physics.
4. The fetch, about 4 seconds for a 48 KB BMP.

## The reset button

A panel in deep sleep has no network. If you ever need it before its next scheduled wake, press the XIAO's reset button: the panel boots, connects, fetches and stays reachable for the OTA window (20 seconds by default) before sleeping again. Arm any flash you intend to do before you press it; see [Troubleshooting](troubleshooting.md#the-panel-is-asleep-and-i-need-it-now).

## Other panels

The renderer is panel-agnostic in principle: change `PANEL_W` and `PANEL_H` in `server/src/immich.py`, the `resize` and `model` in the firmware, and the BMP writer's row size follows. Colour and greyscale panels would need a different dither target and are not supported today. Pull requests welcome.
