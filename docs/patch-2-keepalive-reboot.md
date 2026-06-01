# Patch 2: Idle Keepalive (soft reboot)

**Purpose:** Stop the speaker from ever reaching the 20‑minute idle standby, without
breaking BL‑mode reflashing.

**Region:** Seg1 code (Thumb) — a code cave at `0x432894` plus a 4‑byte hook at `0x3D222`
**Bytes added:** 88 (cave) + 4 (hook)

## Background — why a reboot, not a "block"

The single most important discovery of this project is that **the 20‑minute standby
is not decided by the DMP firmware at all.** It is owned by the *host* companion chip
(`CommunicationSettings/HostController = SPI`, a DM1000‑class part). The DMP only
*reacts* to the host: when the host's idle timer expires it injects the AirPlay
teardown (EVkCmd `0xDE`/`0xDF`/`0xE1` → "Apple Stop"), and the DMP obediently powers
down.

Every attempt to *veto* that teardown from inside the DMP failed, because the host
keeps its own clock and simply re‑issues the command (or cuts power) regardless of
what the DMP does. The full list of dead ends is in [power.md](power.md).

The one lever that genuinely resets the host's clock is a **real reboot.** When the
DMP soft‑reboots, the host re‑initialises the link and restarts its 20‑minute timer
from zero. So instead of fighting the standby, we pre‑empt it: a self‑hosted timer
inside the DMP triggers a clean reboot a few minutes *before* the host would standby,
and the cycle repeats forever.

This is BL‑safe: the reboot path used here (`setSystemPowerState`) is **not** the
BL/"Sending control to host" path, so bootloader reflashing is untouched.

## The hook

The DMP's `UITimerEvtHandler` fires roughly once per second. One of its tick sites at
file offset `0x3D222` is a `bl` to the gated logger (the per‑second tick trace). We
displace that call with a `bl` into our cave:

| Offset | Original | Patched | Meaning |
|--------|----------|---------|---------|
| 0x3D222 | `5C F1 5F FA` (`bl 0x1996E4`, tick log) | `F5 F3 37 FB` (`bl 0x432894`) | redirect the 1 s tick into the cave |

A side benefit: because the tick log call is replaced, the otherwise per‑second tick
trace is silenced automatically.

## The cave (`0x432894`)

88 bytes of Thumb in a region of free zero bytes inside Seg1. On every tick it:

1. Calls `audioStatus()` (`blx 0x205730`, returns `1` while audio is playing — covers
   AirPlay, Bluetooth, AUX, etc. via the NAP state, not just AirTunes).
2. **If playing** → reset the idle counter to `0` and return (never reboots mid‑playback).
3. **If idle** → increment the idle counter.
4. When the counter reaches **1024 ticks (~17 min)** → reset the counter and perform a
   soft reboot:
   - `getPowerManager()` (`blx 0x207F3C`)
   - `setSystemPowerState(PM, &{3,6})` (`blx 0x206A74`) — state struct `{3, 6}` = the
     clean "sys reboot".

```asm
        push {r4,lr}
        ldr  r3,[pc,#0x3C]   ; AUDIO  = 0x205730 (ARM)
        blx  r3              ; r0 = audioStatus()   (1 == playing)
        cmp  r0,#0
        bne  .reset          ; playing -> hold counter at 0
        ldr  r4,[pc,#0x44]   ; &counter
        ldr  r0,[r4]
        adds r0,#1
        ldr  r1,[pc,#0x38]   ; IDLE_TICKS = 1024
        cmp  r0,r1
        bge  .reboot
        str  r0,[r4]         ; counter++
        pop  {r4,pc}
.reset: ldr  r4,[pc,#0x34]
        movs r0,#0
        str  r0,[r4]         ; counter = 0
        pop  {r4,pc}
.reboot:ldr  r4,[pc,#0x2C]
        movs r0,#0
        str  r0,[r4]         ; counter = 0
        sub  sp,#8
        movs r0,#3
        str  r0,[sp]         ; power-state struct {3,
        movs r0,#6
        str  r0,[sp,#4]      ;                       6}
        ldr  r3,[pc,#0x10]   ; GETPM  = 0x207F3C|1 (Thumb)
        blx  r3              ; r0 = getPowerManager()
        mov  r1,sp
        ldr  r3,[pc,#0x0C]   ; SETPWR = 0x206A74|1 (Thumb)
        blx  r3              ; setSystemPowerState(PM, &{3,6}) -> soft reboot
        add  sp,#8
        pop  {r4,pc}

; literal pool (CAVE+0x40):
;   AUDIO, GETPM, SETPWR, IDLE_TICKS, &counter(=CAVE+0x54), counter(=0)
```

The idle counter lives **inside the cave** (the last pool word), so no extra RAM is
needed and it survives as long as the firmware runs (and is reset to 0 on each reboot).

## Tuning the interval

`IDLE_TICKS` in `patch.py` controls how long the speaker sits idle before the keepalive
reboot. `1024` (~17 min) leaves a safe margin under the host's 20‑minute standby. Lower
it for more headroom, raise it (toward but below ~1180) to reboot less often.

## Observed behaviour

```
sds://> os timestamp
uptime = 939116 ms        <- ~15.6 min idle
Connection closed ...     <- keepalive fired the soft reboot
...
sds://> os timestamp
uptime = 292761 ms        <- fresh, clean boot (NOT bootloader); fully functional
```

- Idle → automatic clean reboot every ~17 minutes; the host standby timer never expires.
- Playing → no reboot; playback continues uninterrupted.
- A reboot costs a few seconds of downtime, after which AirPlay/Bluetooth re‑announce
  normally.
- This is a Seg1 code patch, so it affects the Fletcher‑32 checksum and is covered by
  [Patch 3 (compensation)](patch-3-fletcher32-compensation.md).

## Why this is safe for BL mode

`setSystemPowerState(PM, {3,6})` is the firmware's *internal* reboot, distinct from the
host‑handoff used to enter the bootloader (`writeHostReg(0x27,0)`, "Sending control to
host"). The keepalive never touches that path, and the proof is empirical: the speaker
reboots straight back into the patched application firmware every time, and BL‑mode
flashing continues to work for revert/update.
