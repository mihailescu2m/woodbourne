# Patch 3: PSM FuncA Skip Sleep

**Purpose:** Block the CPU deep-sleep path in PSM (Power Save Mode) FuncA.

**Region:** Seg1 code (ARM)
**Bytes modified:** 4

## Background

FuncA (at 0x286728) is the second of two PSM state handler functions that can call the deep-sleep function at 0x2BF0D4. Together with [Patch 2](patch-2-psm-funcb.md), this blocks all reachable paths to CPU deep sleep.

## Patch detail

| Offset | Original | Patched | Description |
|--------|----------|---------|-------------|
| 0x286728 | `69 E2 00 EB` | `1C 00 00 EA` | `BL 0x2BF0D4` -> `B 0x2867A0` |

The `BL` to the sleep function is replaced with a `B` to the function's epilogue at 0x2867A0.

### Branch encoding

- Target: 0x2867A0
- Source: 0x286728
- Offset: (0x2867A0 - 0x286728 - 8) / 4 = 0x1C
- Encoding: `0xEA00001C`

## Impact

Same as Patch 2. With both FuncA and FuncB patched, the sleep function at 0x2BF0D4 is unreachable -- no code path can put the CPU into deep sleep.
