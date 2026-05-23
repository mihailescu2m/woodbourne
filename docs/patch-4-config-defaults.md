# Patch 4: Config Defaults

**Purpose:** Change RSDB default values to disable the sleep timer and set a very high sleep timeout as a defense-in-depth measure.

**Region:** Seg2 config (RSDB)
**Bytes modified:** 3

## Background

The RSDB (Resource/Settings Database) in Seg2 stores default configuration values as null-delimited ASCII text. Two entries control timer-based sleep:

- `EnableSleepTimer` -- `1` (enabled) or `0` (disabled)
- `SleepTime` -- timeout value in minutes

These defaults can be overridden by NVRAM, so this patch is a belt-and-suspenders measure alongside the code patches. If the user has never changed these settings through the speaker's UI, the patched defaults take effect.

## Patch detail

| Offset | Original | Patched | Description |
|--------|----------|---------|-------------|
| 0x4FE6F5 | `31` | `30` | EnableSleepTimer: ASCII `'1'` -> `'0'` |
| 0x4FDCE6 | `30 30` | `39 39` | SleepTime: ASCII `"00"` -> `"99"` |

### In context

Before:
```
...EnableSleepTimer\x001\x00...
...SleepTime\x0000\x00...
```

After:
```
...EnableSleepTimer\x000\x00...
...SleepTime\x0099\x00...
```

## Impact

- If NVRAM has no override for these keys, the sleep timer is disabled and the timeout is set to 99 (likely interpreted as 99 minutes or hours, depending on the timer resolution).
- If NVRAM does have overrides, this patch has no effect -- the code patches (1, 2, 3) still block sleep regardless.
- This is a Seg2-only change. It affects the Seg2 CRC and overall CRC but does **not** affect the Fletcher-32 checksum (which only covers Seg1).
