#!/usr/bin/env python3
"""
Polk Woodbourne (B9519) firmware patcher -- final release build.

Reads the stock firmware and produces a patched image that:

  1. TELNET            Routes the BridgeCo diagnostic shell to TCP port 10000
                       (the stock firmware sends it to serial UART1).

  2. KEEPALIVE         Installs a small Thumb "code cave" that hooks the 1 s
                       UITimerEvtHandler tick.  When the speaker is NOT playing
                       audio it increments an idle counter; after 1024 ticks
                       (~17 min) it performs a clean soft reboot via
                       setSystemPowerState(PowerManager, {3,6}).  Rebooting
                       resets the *host* companion-chip's 20-minute standby
                       timer, so the speaker never reaches deep standby.  If
                       audio IS playing the counter is held at 0, so playback
                       is never interrupted.

  3. WEP PATH FIX      Corrects a stock typo in a web-UI ASP template
                       ('/cf?/...' -> '/cfg/...') that made the wireless config
                       page log "webCfgNetGetCneValue: bad path".

  4. INTEGRITY         Recomputes Seg1/Seg2/Seg3 CRC-32, the aggregate CRC and
                       the overall CRC, and inserts two Fletcher-32 compensation
                       half-words so the BSL's boot-time Fletcher-32 check
                       (whose expected value is frozen in the preserved BSL
                       header) still passes.  See docs/patch-3-fletcher32-compensation.md.

The patch deliberately leaves all version/header fields and all logging code at
their stock values -- forcing verbose logging on (an earlier experiment) made
the firmware fault into a broken bootloader state when long UPnP/SSDP log lines
overflowed a fixed 268-byte logger stack buffer.  See docs/power.md.

Usage:
    python3 patch.py
Produces: AirplaySpeaker_B9519_H4_D18M12_BSL_Dec18_UART_patched.FW

Platform: ARM926EJ-S (ARMv5TE), little-endian, mixed ARM/Thumb. Python 3, stdlib only.
"""

import struct
import zlib

INPUT  = 'AirplaySpeaker_B9519_H4_D18M12_BSL_Dec18_UART.FW'
OUTPUT = 'AirplaySpeaker_B9519_H4_D18M12_BSL_Dec18_UART_patched.FW'

# --- firmware geometry ------------------------------------------------------
FS = 0x20D8            # Fletcher-32 range start (Seg1 data + 0x2000)
FE = 0x4FCCB4          # Fletcher-32 range end (exclusive) = end of Seg1 data
OF = 0xF7D16EC9        # original (expected) Fletcher-32 -- must be preserved
RB = 0x60005F28        # RAM base: runtime_addr = file_offset + RB (Seg1)

# --- keepalive hook ---------------------------------------------------------
INJ      = 0x3D222                       # the 1 s tick log site we redirect to the cave
INJ_OLD  = bytes([0x5C, 0xF1, 0x5F, 0xFA])  # original bl 0x1996e4 (tick log) we displace
CAVE     = 0x432894                      # 383 free zero bytes inside Seg1 for our code
IDLE_TICKS = 1024                        # idle ticks (~1 s each) before the soft reboot

# runtime addresses the cave calls (looked up via the Fletcher-safe literal pool)
AUDIO  = 0x205730 + RB        # audioStatus()  (ARM, even -> blx)   1 == playing
GETPM  = (0x207F3C + RB) | 1  # getPowerManager()        (Thumb, low bit set)
SETPWR = (0x206A74 + RB) | 1  # setSystemPowerState()    (Thumb, low bit set)

# --- web-UI typo fix --------------------------------------------------------
WEP_FIX = 0x54FFA4   # '?' -> 'g' so the ASP path becomes '/cfg/...'

# --- Fletcher-32 compensation slot (two adjacent zero half-words in Seg1) ----
COMP1, COMP2 = 0x4A4F58, 0x4A4F5A


# ---------------------------------------------------------------------------
# checksum helpers
# ---------------------------------------------------------------------------
def fletcher32(fw, s, e):
    a = b = 0xFFFF
    for i in range(s, e - 1, 2):
        w = fw[i] | (fw[i + 1] << 8)
        a = (a + w) % 65535
        b = (b + a) % 65535
    return (b << 16) | a


def seg_crc(fw, base):
    """CRC-32 of the segment whose descriptor lives at `base` (0x50/0x70/0x90)."""
    off  = struct.unpack_from('<I', fw, base)[0]
    size = struct.unpack_from('<I', fw, base + 8)[0]
    return zlib.crc32(fw[off + 0x20: off + 0x20 + size]) & 0xFFFFFFFF


def aggregate_crc(fw):
    d = bytearray(fw[0x20:0xD0])
    d[0x2C:0x30] = b'\0\0\0\0'          # zero the aggregate-CRC field itself
    return zlib.crc32(bytes(d)) & 0xFFFFFFFF


def overall_crc(fw):
    return zlib.crc32(fw[0x20:]) & 0xFFFFFFFF


def fletcher_compensation(patches, p1, p2):
    """
    Solve for two half-words at file offsets p1,p2 (adjacent, both inside the
    Fletcher range) that cancel the net delta introduced by `patches`, so the
    overall Fletcher-32 equals the original.  Closed form over GF(65535).
    """
    M = 65535
    N = (FE - FS) // 2
    d1 = d2 = 0
    for off, old, new in patches:
        for i in range(len(old)):
            ab = off + i
            if not (FS <= ab < FE) or old[i] == new[i]:
                continue
            rel = ab - FS
            j   = rel // 2
            sh  = 8 * (rel % 2)
            hd  = ((new[i] - old[i]) << sh) % M
            d1 = (d1 + hd) % M
            d2 = (d2 + (N - j) * hd) % M
    n1 = (-d1) % M
    n2 = (-d2) % M
    j1 = (p1 - FS) // 2
    j2 = (p2 - FS) // 2
    assert j2 == j1 + 1
    w2 = (N - j2) % M
    a  = (n2 - w2 * n1) % M
    b  = (n1 - a) % M
    assert (a + b) % M == n1 and ((N - j1) * a + (N - j2) * b) % M == n2
    return a, b


# ---------------------------------------------------------------------------
# encoders
# ---------------------------------------------------------------------------
def thumb_bl(src, dst):
    """Encode a Thumb BL/BLX from `src` to `dst` (4 bytes, little-endian)."""
    off = dst - (src + 4)
    S    = (off >> 24) & 1
    I1   = (off >> 23) & 1
    I2   = (off >> 22) & 1
    imm10 = (off >> 12) & 0x3FF
    imm11 = (off >> 1) & 0x7FF
    J1 = (~I1 ^ S) & 1
    J2 = (~I2 ^ S) & 1
    return struct.pack('<HH', 0xF000 | (S << 10) | imm10,
                              0xD000 | (J1 << 13) | (J2 << 11) | imm11)


def H(v):
    return struct.pack('<H', v)


def cave_bytes():
    """
    Keepalive code cave (Thumb).  Layout (offsets from CAVE):

      +00 push {r4,lr}
      +02 ldr  r3,[pc,#0x3C] ; AUDIO
      +04 blx  r3            ; r0 = audioStatus()  (1 == playing)
      +06 cmp  r0,#0
      +08 bne  .reset        ; playing -> hold counter at 0
      +0A ldr  r4,[pc,#0x44] ; &counter
      +0C ldr  r0,[r4]
      +0E adds r0,#1
      +10 ldr  r1,[pc,#0x38] ; IDLE_TICKS
      +12 cmp  r0,r1
      +14 bge  .reboot
      +16 str  r0,[r4]       ; counter++
      +18 pop  {r4,pc}
      +1A .reset:  ldr r4,[pc,#0x34]; movs r0,#0; str r0,[r4]; pop {r4,pc}
      +22 .reboot: ldr r4,[pc,#0x2C]; movs r0,#0; str r0,[r4]   ; counter=0
      +28 sub  sp,#8
      +2A movs r0,#3 ; str r0,[sp]        ; power-state struct {3,
      +2E movs r0,#6 ; str r0,[sp,#4]     ;                       6}
      +32 ldr  r3,[pc,#0x10]; blx r3      ; getPowerManager()
      +36 mov  r1,sp
      +38 ldr  r3,[pc,#0x0C]; blx r3      ; setSystemPowerState(PM,&{3,6}) -> soft reboot
      +3C add  sp,#8
      +3E pop  {r4,pc}
      +40 literal pool: AUDIO, GETPM, SETPWR, IDLE_TICKS, &counter, counter(=0)
    """
    code = b''.join([
        H(0xB510), H(0x4B0F), H(0x4798), H(0x2800), H(0xD107), H(0x4C11), H(0x6820), H(0x3001),
        H(0x490E), H(0x4288), H(0xDA05), H(0x6020), H(0xBD10), H(0x4C0D), H(0x2000), H(0x6020),
        H(0xBD10), H(0x4C0B), H(0x2000), H(0x6020), H(0xB082), H(0x2003), H(0x9000), H(0x2006),
        H(0x9001), H(0x4B04), H(0x4798), H(0x4669), H(0x4B03), H(0x4798), H(0xB002), H(0xBD10),
    ])
    assert len(code) == 0x40
    # literal pool: counter lives in-cave at CAVE+0x54 (RAM addr stored as a literal)
    pool = struct.pack('<IIIII', AUDIO, GETPM, SETPWR, IDLE_TICKS, CAVE + 0x54 + RB)
    pool += struct.pack('<I', 0)   # the idle counter itself, initialised to 0
    return code + pool


def apply_patch(fw, off, new, desc):
    old = bytes(fw[off:off + len(new)])
    fw[off:off + len(new)] = new
    print("  0x%06X: %-23s -> %-23s (%s)" % (
        off,
        ' '.join('%02X' % x for x in old[:8]),
        ' '.join('%02X' % x for x in new[:8]),
        desc))


# ---------------------------------------------------------------------------
def main():
    fw = bytearray(open(INPUT, 'rb').read())
    assert fletcher32(fw, FS, FE) == OF, "input is not the expected stock firmware"

    # Collect (offset, old, new) tuples first so the Fletcher compensation can
    # account for every code change before we write anything.
    patches = []

    # 1. telnet: force the UART1 shell-mode handler to store TELNET (1) instead
    ta = struct.pack('<I', 0xE3A00001)   # MOV  R0, #1
    tb = struct.pack('<I', 0xE5C4001D)   # STRB R0, [R4, #0x1D]
    patches.append((0x107628, bytes(fw[0x107628:0x10762C]), ta))
    patches.append((0x10762C, bytes(fw[0x10762C:0x107630]), tb))

    # 3. WEP web-UI path typo fix: '?' -> 'g'
    assert fw[WEP_FIX] == 0x3F, "WEP path byte is not '?'"
    patches.append((WEP_FIX, b'?', b'g'))

    # 2. keepalive cave + the tick-hook redirect
    cave = cave_bytes()
    assert fw[CAVE:CAVE + len(cave)] == b'\x00' * len(cave), "cave region is not free"
    patches.append((CAVE, b'\x00' * len(cave), cave))
    assert fw[INJ:INJ + 4] == INJ_OLD, "tick hook site does not match"
    patches.append((INJ, INJ_OLD, thumb_bl(INJ, CAVE)))

    # 4. Fletcher compensation (computed over the code patches above)
    assert fw[COMP1:COMP1 + 4] == b'\0\0\0\0', "compensation slot is not free"
    d1, d2 = fletcher_compensation(patches, COMP1, COMP2)

    print("Applying patches...")
    apply_patch(fw, 0x107628, ta, 'telnet: shell -> TELNET')
    apply_patch(fw, 0x10762C, tb, 'telnet: store TELNET mode')
    apply_patch(fw, WEP_FIX, b'g', "WEP ASP path '/cf?/' -> '/cfg/'")
    apply_patch(fw, CAVE, cave, 'keepalive cave (idle %d ticks -> soft reboot)' % IDLE_TICKS)
    apply_patch(fw, INJ, thumb_bl(INJ, CAVE), 'tick hook 0x3D222 -> cave')
    apply_patch(fw, COMP1, struct.pack('<H', d1), 'Fletcher compensation #1')
    apply_patch(fw, COMP2, struct.pack('<H', d2), 'Fletcher compensation #2')

    # integrity: Fletcher must match the frozen original; recompute every CRC
    assert fletcher32(fw, FS, FE) == OF, "FLETCHER MISMATCH -- would brick"
    for name, base in (("Seg1", 0x50), ("Seg2", 0x70), ("Seg3", 0x90)):
        struct.pack_into('<I', fw, base + 12, seg_crc(fw, base))
    struct.pack_into('<I', fw, 0x4C, aggregate_crc(fw))
    struct.pack_into('<I', fw, 0x10, overall_crc(fw))

    open(OUTPUT, 'wb').write(fw)
    orig = open(INPUT, 'rb').read()
    diff = sum(1 for i in range(len(fw)) if fw[i] != orig[i])
    print("\nFletcher-32: 0x%08X (OK)  |  bytes changed: %d" % (fletcher32(fw, FS, FE), diff))
    print("Output: %s" % OUTPUT)


if __name__ == '__main__':
    main()
