# Patch 5: Version Marker

**Purpose:** Add a visible indicator that the patched firmware is running, viewable through the speaker's web UI.

**Region:** bCoD header + Seg3 data
**Bytes modified:** 9

## Patch detail

### bCoD date field (header)

| Offset | Original | Patched | Description |
|--------|----------|---------|-------------|
| 0x30 | `30 39 34 35 34 30 20 20` | `4E 4F 53 4C 45 45 50 20` | `"094540  "` -> `"NOSLEEP "` |

This is the 8-byte time field in the bCoD header (part of the build timestamp `"20130531094540  "`). After patching, the firmware date string reads `"20130531NOSLEEP "`.

### Firmwarerevision (Seg3)

| Offset | Original | Patched | Description |
|--------|----------|---------|-------------|
| 0x50C43F | `30` | `31` | ASCII `'0'` -> `'1'` |

This changes the `Firmwarerevision` RSDB value from `0` to `1`, bumping the version number visible in the web UI.

## Where to check

Navigate to `http://<speaker-ip>:8000/firmware_update_prepare.asp`:

- **Firmware Date** -- will show `NOSLEEP` (rendered via `aspGetFirmwareDate()` / `aspGetFirmwareTime()` template tags)
- **Firmware Version** -- will show `X.X.9519.1` instead of `X.X.9519.0` (the last digit is the patched `Firmwarerevision` field, rendered via `aspGetFirmwareVersion()`)

## Impact

- The bCoD date field change is in the header area (0x20-0xB7), which affects the aggregate CRC and overall CRC but not segment CRCs or Fletcher-32.
- The Firmwarerevision change is in Seg3, which affects the Seg3 CRC and overall CRC. It does not affect Fletcher-32 (which only covers Seg1).
- Neither change affects any runtime behavior.
