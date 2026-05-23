# Patch 2: PSM FuncB Skip Sleep

**Purpose:** Block the CPU deep-sleep path in PSM (Power Save Mode) FuncB.

**Region:** Seg1 code (ARM)
**Bytes modified:** 4

## Background

The firmware has exactly one function that puts the CPU into deep sleep: the PSM sleep function at 0x2BF0D4. This function is called from three places in the codebase. FuncB (at 0x286920) is one of two PSM state handler functions that can invoke it.

FuncB is reached when a standby command propagates through the NapManager state machine to the PSM layer. The function performs pre-sleep housekeeping, calls `BL 0x2BF0D4` to enter deep sleep, then runs post-wake recovery code.

## Patch detail

| Offset | Original | Patched | Description |
|--------|----------|---------|-------------|
| 0x286920 | `EB E1 00 EB` | `15 00 00 EA` | `BL 0x2BF0D4` -> `B 0x28697C` |

The original `BL` (branch-with-link) to the sleep function is replaced with an unconditional `B` (branch) that jumps forward to the function's epilogue at 0x28697C, skipping the sleep call and all pre-sleep setup.

### Branch encoding

ARM branch offset = (target - source - 8) / 4:
- Target: 0x28697C
- Source: 0x286920
- Offset: (0x28697C - 0x286920 - 8) / 4 = 0x15
- Encoding: `0xEA000015`

## Impact

- When the system attempts to enter standby via this path, FuncB runs its entry code but immediately skips to cleanup/return without sleeping.
- The third caller of the sleep function (HSM Thumb NOP) was removed in earlier patch iterations as unnecessary -- Patches 2 and 3 together cover the two PSM entry points which are the only reachable sleep paths.
- This is a code patch in Seg1, so it affects the Fletcher-32 checksum and requires [compensation](patch-7-fletcher32-compensation.md).
