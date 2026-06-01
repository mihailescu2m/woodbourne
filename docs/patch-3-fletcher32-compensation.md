# Patch 3: Fletcher-32 Compensation

**Purpose:** Ensure the patched firmware passes the BSL's Fletcher-32 integrity check despite code modifications in Seg1.

**Region:** Seg1 zero-padding area
**Bytes modified:** 4

## The problem

The BSL (Boot Strap Loader) validates firmware integrity at every boot by computing a Fletcher-32 checksum over Seg1 code and comparing it against an expected value stored at file offset 0x104.

When firmware is flashed via the BL-mode web interface (`bl_index.asp`), the bootloader **preserves the first 0x2000 bytes of Seg1 in flash** as a self-protection measure. Offset 0x104 falls within this preserved region, so the expected Fletcher-32 value is never updated -- it always holds the original firmware's checksum.

This means any code patch that changes Seg1 data will cause a Fletcher-32 mismatch at boot. The BSL enters an infinite loop (brick state, power LED blinks) and the firmware never executes.

Simply recomputing and writing the new Fletcher-32 to offset 0x104 in the `.FW` file does not help, because the BL-mode flasher skips that region.

## The solution

Instead of updating the expected value, we make the patched code produce the **same** Fletcher-32 as the original (0xF7D16EC9). This is done by inserting two carefully computed halfword values into an unused zero-padding area within the Fletcher-32 range.

### Compensation math

Fletcher-32 operates on 16-bit little-endian words with two accumulators:
- **s1** = running sum of all words, mod 65535
- **s2** = running sum of all s1 values, mod 65535

Changing word at position `j` (0-indexed from the Fletcher range start) by `delta` affects:
- s1 by `+delta`
- s2 by `+(N - j) * delta`

where N is the total number of halfwords in the range.

Given all code patches, we compute the total `(delta_s1, delta_s2)` they introduce. We then solve for two compensation values `(d1, d2)` at adjacent positions `(j1, j2)` such that:

```
d1 + d2             = -delta_s1  (mod 65535)
(N-j1)*d1 + (N-j2)*d2 = -delta_s2  (mod 65535)
```

This is a 2x2 linear system over GF(65535). With `j2 = j1 + 1`:

```
d1 = (need_s2 - (N - j2) * need_s1) mod 65535
d2 = (need_s1 - d1) mod 65535
```

### Compensation location

The two halfwords are placed at file offsets **0x4A4F58** and **0x4A4F5A**, inside a region of consecutive zero bytes. This region sits within an uninitialized data table in Seg1 and is not referenced by any code -- modifying it has no runtime effect.

## Patch detail

| Offset | Original | Patched | Description |
|--------|----------|---------|-------------|
| 0x4A4F58 | `00 00` | `69 72` | Compensation word 1 (0x7269) |
| 0x4A4F5A | `00 00` | `14 BF` | Compensation word 2 (0xBF14) |

These values are specific to the exact set of code patches applied (telnet + keepalive). If any code patch changes, the compensation values must be recomputed. The `patch.py` script does this automatically every run.

## Verification

After all patches and compensation are applied:

```
Fletcher-32 of patched Seg1[0x2000:] = 0xF7D16EC9
Original Fletcher-32 at 0x104        = 0xF7D16EC9
Match -- BSL accepts the firmware.
```

## Why not just update 0x104?

The BL-mode web flasher (`bl_index.asp`) writes firmware to flash starting at Seg1 offset 0x2000, skipping the first 0x2000 bytes. This protects the bootloader's own code and the BSL header (which includes the Fletcher-32 expected value at offset 0x104, i.e., Seg1 byte 0x2C).

Any value written to offset 0x104 in the `.FW` file is simply ignored during flashing. The flash retains whatever was there from the original firmware. The compensation approach works around this by ensuring the checksum matches without needing to change the expected value.
