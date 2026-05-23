# Polk Woodbourne (B9519) Firmware Patch

Custom firmware patch for the Polk Audio Woodbourne wireless speaker that disables all sleep/standby behavior and enables a telnet diagnostic shell.

## What it does

- **No sleep** -- The speaker stays powered on indefinitely. All three sleep entry paths (idle timer, IR/button standby via PSM, and config-driven sleep timer) are blocked.
- **Telnet shell** -- A full BridgeCo diagnostic shell is accessible via `telnet <speaker-ip> 10000`, providing memory read/write, config inspection, RTOS thread listing, network tools, and more.
- **Version marker** -- The firmware date field reads `NOSLEEP` and the revision bumps from `.0` to `.1`, visible on the speaker's web UI at `/firmware_update_prepare.asp`.

## Files

| File | Description |
|------|-------------|
| `AirplaySpeaker_B9519_H4_D18M12_BSL_Dec18_UART.FW` | Original unmodified firmware (7,490,336 bytes) |
| `AirplaySpeaker_B9519_H4_D18M12_BSL_Dec18_UART_patched.FW` | Patched firmware (7,490,336 bytes, 56 bytes differ) |
| `patch_nosleep.py` | Python 3 patcher script -- applies all patches and recomputes checksums |

## How to flash

1. Power on the speaker and hold the **Bluetooth** button for ~10 seconds until the power LED blinks. The speaker enters BL (Boot Loader) mode.
2. Connect to the speaker's Wi-Fi network or access it on your LAN.
3. Navigate to `http://<speaker-ip>:8000/bl_index.asp` in a browser.
4. Upload `AirplaySpeaker_B9519_H4_D18M12_BSL_Dec18_UART_patched.FW`.
5. Wait for the flash to complete and the speaker to reboot.

To revert, flash the original `.FW` file using the same procedure.

## Patches applied

56 bytes are modified across 7 patches. All five checksums (3 segment CRCs, aggregate CRC, overall CRC) are recomputed. The Fletcher-32 checksum is preserved via a compensation technique (see [Patch 7](docs/patch-7-fletcher32-compensation.md)).

| # | Patch | Region | Bytes |
|---|-------|--------|-------|
| 1 | [Idle timer NOP](docs/patch-1-idle-timer.md) | Seg1 code | 16 |
| 2 | [PSM FuncB skip](docs/patch-2-psm-funcb.md) | Seg1 code | 4 |
| 3 | [PSM FuncA skip](docs/patch-3-psm-funca.md) | Seg1 code | 4 |
| 4 | [Config defaults](docs/patch-4-config-defaults.md) | Seg2 config | 3 |
| 5 | [Version marker](docs/patch-5-version-marker.md) | bCoD header + Seg3 | 9 |
| 6 | [Telnet enable](docs/patch-6-telnet-enable.md) | Seg1 code | 8 |
| 7 | [Fletcher-32 compensation](docs/patch-7-fletcher32-compensation.md) | Seg1 padding | 4 |

## Telnet shell

Once the patched firmware is running:

```
$ telnet 192.168.1.92 10000
BridgeCo AG Telnet server

sds://>help
```

Useful commands: `sys ver`, `os th`, `netcfg`, `ls`, `get`, `set`, `rd`, `wr`, `ping`.

## Technical details

- [Firmware layout](docs/firmware-layout.md) -- File structure, segments, headers, checksums
- Per-patch details in [`docs/`](docs/)

## Platform

- **Hardware:** Polk Audio Woodbourne (product ID B9519)
- **SoC:** ARM926EJ-S (ARMv5TEJ), 32-bit Little Endian
- **RTOS:** BridgeCo DMP 3.x
- **Instruction sets:** Mixed ARM (32-bit) and Thumb (16-bit)
