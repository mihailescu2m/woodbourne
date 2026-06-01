# Polk Woodbourne (B9519) — No‑Standby Firmware Patch

> Keep your Polk Audio Woodbourne **awake forever**, add a **telnet diagnostic shell**,
> and never lose the ability to re‑flash it. A clean, reversible, checksum‑correct patch
> for the stock firmware — built entirely through black‑box reverse engineering.

```
   ┌───────────────────────────────────────────────────────────────┐
   │  Stock:   plays → 20 min idle → deep standby → silence 😴       │
   │  Patched: plays → idle → self‑reboot every ~17 min → awake 🔊   │
   └───────────────────────────────────────────────────────────────┘
```

---

## The problem

The Woodbourne drops into a deep **standby after ~20 minutes of inactivity** (and on a
power‑button press). For an always‑available AirPlay/Bluetooth speaker that's
maddening — it disappears from the network and has to be woken up by hand.

The obvious fix — "find the sleep timer and disable it" — **does not exist inside the
audio processor.** The speaker has two brains:

- a **DMP** (BridgeCo ARM926EJ‑S) running the application firmware this project patches, and
- a **host companion chip** (`HostController = SPI`) that owns power and the **20‑minute
  idle clock**.

When the host's timer expires it *tells* the DMP to tear down audio and then powers the
system down. The DMP is just following orders. We spent dozens of builds trying to veto
that teardown from the DMP — blocking NAP states, guarding `PowerManager`, NOP‑ing the
EVkCmd power‑down chain, flipping config defaults, writing host registers, even an
external Raspberry Pi daemon — **and none of it held**, because the host keeps its own
clock. The complete post‑mortem of every dead end is in **[docs/power.md](docs/power.md)**.

## The solution

You can't stop the host's clock — but a **real reboot resets it.** So instead of
fighting the standby, the patch **pre‑empts** it:

- A tiny code cave hooks the DMP's 1‑second timer tick.
- While **idle**, it counts up; after **~17 minutes** it performs a clean
  `setSystemPowerState({3,6})` **soft reboot**.
- While **playing** (AirPlay, Bluetooth, AUX…) the counter is held at 0 — playback is
  never interrupted.
- Each reboot re‑initialises the host link and restarts its 20‑minute clock from zero,
  so deep standby is **never reached.**

The reboot uses the firmware's internal power path, **not** the bootloader handoff — so
BL‑mode re‑flashing keeps working and the speaker is always recoverable.

> Proven in the field: idle uptime climbs to ~15–16 min, the speaker cleanly reboots
> (not into the bootloader), and comes right back as a fully functional AirPlay target.

---

## What's in the patch

Four changes, **106 bytes** different from stock, all checksums kept valid.

| # | Patch | What it does | Region | Doc |
|---|-------|--------------|--------|-----|
| 1 | **Telnet shell** | Routes the BridgeCo diagnostic shell to TCP **port 10000** | Seg1 (ARM) | [patch‑1](docs/patch-1-telnet-enable.md) |
| 2 | **Idle keepalive** | Tick‑hook code cave → soft reboot after ~17 min idle; skips during playback | Seg1 (Thumb) | [patch‑2](docs/patch-2-keepalive-reboot.md) |
| 3 | **Fletcher‑32 compensation** | Keeps the BSL boot‑time integrity check passing despite code edits | Seg1 padding | [patch‑3](docs/patch-3-fletcher32-compensation.md) |
| 4 | **WEP path typo fix** | Fixes a stock `/cf?/` → `/cfg/` typo in a web‑UI config template | Seg3 (ASP) | [patch‑4](docs/patch-4-wep-path-fix.md) |

All Seg1/Seg2/Seg3 CRC‑32s, the aggregate CRC and the overall CRC are recomputed, and
the Fletcher‑32 (frozen in the preserved bootloader header) is preserved by inserting
two compensation half‑words. See **[docs/firmware-layout.md](docs/firmware-layout.md)**
for the full file format.

---

## Files

| File | Description |
|------|-------------|
| [`AirplaySpeaker_…_patched.FW`](AirplaySpeaker_B9519_H4_D18M12_BSL_Dec18_UART_patched.FW) | **Flash this.** Patched firmware (7,490,336 bytes) |
| [`AirplaySpeaker_…_UART.FW`](AirplaySpeaker_B9519_H4_D18M12_BSL_Dec18_UART.FW) | Original unmodified firmware (for revert / rebuild) |
| [`patch.py`](patch.py) | Standalone Python 3 patcher — reproduces the patched image byte‑for‑byte |
| [`woodbourne_keepalive.py`](woodbourne_keepalive.py) | The earlier Raspberry Pi keepalive daemon (superseded; see below) |
| [`woodbourne-keepalive.service`](woodbourne-keepalive.service) | systemd unit for the Pi daemon |

---

## How to flash

1. Put the speaker into **BL (Boot Loader) mode**.
2. On the same LAN, open the bootloader's upload page in a browser
   (`http://<speaker-ip>:8000/bl_index.asp`).
3. Upload `AirplaySpeaker_B9519_H4_D18M12_BSL_Dec18_UART_patched.FW`.
4. Wait for the flash to finish and the speaker to reboot.

**To revert:** flash the original `…_UART.FW` the same way. The patch changes nothing
the bootloader can't overwrite, so reverting is always possible.

## Build it yourself

The patcher is pure‑stdlib Python 3 and needs only the original firmware in the same
folder:

```bash
python3 patch.py
# -> AirplaySpeaker_B9519_H4_D18M12_BSL_Dec18_UART_patched.FW
#    Fletcher-32: 0xF7D16EC9 (OK)  |  bytes changed: 106
```

It collects every byte change, solves the Fletcher‑32 compensation, applies the patches,
and recomputes all CRCs — fully deterministic and self‑verifying.

## Telnet shell

Once the patched firmware is running:

```
$ telnet <speaker-ip> 10000
BridgeCo AG Telnet server

sds://> os timestamp
uptime = 292761 ms
sds://> help
```

Handy commands: `sys ver`, `os th`, `os timestamp`, `netcfg`, `ls`, `get` / `set`,
`rd` / `wr`, `ping`, `persparam`. (No authentication — use only on a trusted network.)

---

## Documentation

| Doc | Contents |
|-----|----------|
| [firmware-layout.md](docs/firmware-layout.md) | `.FW` file format: headers, segments, all five checksums, the BSL header |
| [patch-1-telnet-enable.md](docs/patch-1-telnet-enable.md) | Telnet shell enable — how the shell mode byte is forced to TELNET |
| [patch-2-keepalive-reboot.md](docs/patch-2-keepalive-reboot.md) | The keepalive code cave, tick hook, and soft‑reboot mechanism |
| [patch-3-fletcher32-compensation.md](docs/patch-3-fletcher32-compensation.md) | How the boot‑time Fletcher‑32 is preserved with two half‑words |
| [patch-4-wep-path-fix.md](docs/patch-4-wep-path-fix.md) | The stock `/cf?/`→`/cfg/` web‑UI config‑path typo fix |
| [power.md](docs/power.md) | **The full standby investigation** — every approach tried and why it failed |
| [keepalive.md](docs/keepalive.md) | The Raspberry Pi keepalive daemon: design, install, and why it was abandoned |

---

## Platform

- **Hardware:** Polk Audio Woodbourne (product ID **B9519**)
- **SoC:** ARM926EJ‑S (ARMv5TEJ), 32‑bit little‑endian
- **RTOS:** BridgeCo DMP 3.x
- **Instruction sets:** mixed ARM (32‑bit) and Thumb (16‑bit)
- **Companion:** SPI host controller (DM1000‑class) — owns power & the idle timer

## Safety notes

- **BL mode is the only confirmed re‑flash path.** Every patch here is BL‑safe by
  design; the keepalive reboot deliberately avoids the bootloader‑handoff code.
- Software patches can't damage the hardware. A speaker that won't boot after a *bad*
  experimental patch recovers with a long power cycle (full capacitor discharge).
- The Fletcher‑32 expected value lives in the preserved bootloader header and is never
  updated by flashing — which is exactly why the [compensation technique](docs/patch-3-fletcher32-compensation.md)
  exists. Don't skip it.

---

## Project by the numbers

This was a months‑long, fully black‑box reverse‑engineering effort against an
undocumented firmware — no source, no symbols, no datasheet for the host chip.

| Metric | Value |
|--------|------:|
| Firmware builds produced (all sessions) | **~100** |
| Patch scripts | 20 |
| Analysis / RE / checksum‑cracking tools | 27 |
| Distinct standby‑defeat strategies attempted | 9+ |
| Checksums reverse‑engineered | 5 (3× CRC‑32, aggregate CRC, Fletcher‑32) |
| Bytes in the final winning patch | 106 |
| Span | several months of part‑time work |

### Estimated cost (just for fun 🧮)

If this had been billed as a professional embedded reverse‑engineering contract, with
human‑equivalent hours for the AI pair‑programming, the owner's design ideas and
direction, the (long, attended) flash‑and‑wait testing, and the hardware:

| Line item | Hours | Rate | Cost |
|-----------|------:|-----:|-----:|
| Firmware RE + disassembly + checksum cracking + patch dev (AI, human‑equivalent) | ~160 | $120/h | **$19,200** |
| Owner — ideas, architecture & direction (host‑driven insight, reboot strategy, NAP/audio‑state, `{3,6}` params) | ~25 | $55/h | **$1,375** |
| Owner — testing: ~100 flash cycles + dozens of 17–20 min standby/reboot waits | ~55 | $55/h | **$3,025** |
| Hardware — Raspberry Pi Zero 2 W, microSD, PSU, USB‑serial adapter, cables | — | — | **~$45** |
| **Total** | **~240 h** | | **≈ $23,600** |

*(Rough, tongue‑in‑cheek figures — the speaker itself isn't counted. The real point:
"just disable the sleep timer" turned into a ~240‑hour archaeology dig because the timer
was on a chip we could never read.)*

---

## ☕ Support this work

If this saved you from a sleepy speaker — or you just enjoyed the write‑up — a small
donation is hugely appreciated and keeps projects like this coming.

<p align="center">
  <a href="https://www.paypal.com/cgi-bin/webscr?cmd=_donations&business=mihailescu2m%40gmail%2Ecom&lc=AU&item_name=memeka&item_number=odroid&currency_code=AUD&bn=PP%2DDonationsBF%3Abtn_donate_LG%2Egif%3ANonHosted">
    <img src="https://www.paypalobjects.com/en_US/i/btn/btn_donateCC_LG.gif" alt="Donate with PayPal" />
  </a>
</p>

---

## Disclaimer

Provided as‑is, for educational and interoperability purposes, for firmware you own.
Modifying device firmware may void your warranty. You flash at your own risk — though
every effort was made to keep this patch reversible and BL‑recoverable.
