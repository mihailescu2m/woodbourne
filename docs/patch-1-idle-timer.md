# Patch 1: Idle Timer NOP

**Purpose:** Prevent the idle timer from triggering standby when no audio is playing.

**Region:** Seg1 code (ARM)
**Bytes modified:** 16

## Background

The Woodbourne has an idle timer that counts up when no audio source is active. When the timer exceeds a threshold (~20 minutes), the firmware triggers a transition to standby/sleep state via the NapManager hierarchical state machine.

The trigger code is a conditional sequence at 0x3C6190 that checks the timer value and, if expired, initiates the standby transition. The four instructions form a single conditional block gated by the timer comparison result.

## Patch detail

Four ARM instructions are replaced with NOPs (MOV R0, R0):

| Offset | Original | Patched | Original instruction |
|--------|----------|---------|---------------------|
| 0x3C6190 | `0C D0 8D 82` | `00 00 A0 E1` | ADDHI SP, SP, #0xC |
| 0x3C6194 | `F0 4F BD 88` | `00 00 A0 E1` | LDMHI SP!, {R4-R11,PC} |
| 0x3C6198 | `1C 02 9F 85` | `00 00 A0 E1` | LDRHI R0, [PC, #0x21C] |
| 0x3C619C | `41 3C 00 8A` | `00 00 A0 E1` | BHI 0x3CF2A8 |

All four instructions are conditional on HI (unsigned higher), meaning they only execute when the idle timer exceeds the threshold. By NOPing them, the standby transition is never initiated regardless of how long the speaker sits idle.

The ARM NOP encoding `E1A00000` (MOV R0, R0) appears as bytes `00 00 A0 E1` in little-endian.

## Impact

- The idle timer still runs and counts, but its expiry has no effect.
- All other timer-related functionality (audio processing, network keepalives) is unaffected.
- This is a code patch in Seg1, so it affects the Fletcher-32 checksum and requires [compensation](patch-7-fletcher32-compensation.md).
