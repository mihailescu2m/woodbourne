#!/usr/bin/env python3
"""
Woodbourne Firmware Patcher

Patches the Polk Woodbourne (B9519) firmware to:
  - Block all sleep/standby paths (no-sleep)
  - Enable telnet shell on port 10000 for remote access
  - Add visible version marker to confirm patched firmware

Target: BridgeCo DMP 3.x RTOS on ARM926EJ-S, flashed via BL-mode web UI.

BL-mode flashing preserves the BSL header area (first 0x2000 bytes of seg1),
so the Fletcher-32 expected value at 0x104 is never updated in flash. Code
patches must therefore preserve the original Fletcher-32 checksum (0xF7D16EC9)
by inserting compensation halfwords in an unused zero-padding region.

Patches applied:
  1. Idle timer NOP — 4 ARM NOPs at 0x3C6190-0x3C619C
  2. PSM FuncB skip — Branch 0x286920 -> 0x28697C (skip BL to sleep)
  3. PSM FuncA skip — Branch 0x286728 -> 0x2867A0 (skip BL to sleep)
  4. Config defaults — EnableSleepTimer=0, SleepTime=99
  5. Version marker — bCoD date='NOSLEEP', Firmwarerevision .0->.1
  6. Telnet enable  — Force Shell mode to TELNET in loadSettingsFromCne
  7. Fletcher-32 compensation — 2 halfwords at 0x4A4F60-0x4A4F63
"""

import struct
import sys
import zlib

INPUT = 'AirplaySpeaker_B9519_H4_D18M12_BSL_Dec18_UART.FW'
OUTPUT = 'AirplaySpeaker_B9519_H4_D18M12_BSL_Dec18_UART_patched.FW'

ARM_NOP = b'\x00\x00\xA0\xE1'  # MOV R0, R0

FLETCHER_START = 0x20D8
FLETCHER_END = 0x4FCCB4
ORIGINAL_FLETCHER32 = 0xF7D16EC9


def compute_seg_crc(fw, seg_base_offset):
    seg_off = struct.unpack_from('<I', fw, seg_base_offset)[0]
    seg_size = struct.unpack_from('<I', fw, seg_base_offset + 8)[0]
    data_start = seg_off + 0x20
    return zlib.crc32(fw[data_start:data_start + seg_size]) & 0xFFFFFFFF


def compute_aggregate_crc(fw):
    data = bytearray(fw[0x20:0xD0])
    data[0x2C:0x30] = b'\x00\x00\x00\x00'
    return zlib.crc32(bytes(data)) & 0xFFFFFFFF


def compute_overall_crc(fw):
    return zlib.crc32(fw[0x20:]) & 0xFFFFFFFF


def compute_fletcher32(fw, start, end):
    data = fw[start:end]
    s1 = 0xFFFF
    s2 = 0xFFFF
    for i in range(0, len(data) - 1, 2):
        word = struct.unpack_from('<H', data, i)[0]
        s1 = (s1 + word) % 65535
        s2 = (s2 + s1) % 65535
    return (s2 << 16) | s1


def compute_fletcher32_compensation(fw, patches, comp_pos1, comp_pos2):
    """Solve for two halfword values that cancel the Fletcher-32 delta."""
    M = 65535
    N = (FLETCHER_END - FLETCHER_START) // 2

    delta_s1 = 0
    delta_s2 = 0

    for file_off, old_bytes, new_bytes in patches:
        for byte_off in range(0, len(old_bytes), 2):
            off = file_off + byte_off
            if not (FLETCHER_START <= off < FLETCHER_END):
                continue
            j = (off - FLETCHER_START) // 2
            old_hw = struct.unpack_from('<H', old_bytes, byte_off)[0]
            new_hw = struct.unpack_from('<H', new_bytes, byte_off)[0]
            delta = (new_hw - old_hw) % M
            delta_s1 = (delta_s1 + delta) % M
            delta_s2 = (delta_s2 + (N - j) * delta) % M

    need_s1 = (-delta_s1) % M
    need_s2 = (-delta_s2) % M

    j1 = (comp_pos1 - FLETCHER_START) // 2
    j2 = (comp_pos2 - FLETCHER_START) // 2
    assert j2 == j1 + 1

    w2 = (N - j2) % M
    d1 = (need_s2 - w2 * need_s1) % M
    d2 = (need_s1 - d1) % M

    # Verify solution
    assert (d1 + d2) % M == need_s1
    assert ((N - j1) * d1 + (N - j2) * d2) % M == need_s2

    return d1, d2


def patch_bytes(fw, offset, new_bytes, desc):
    old = fw[offset:offset + len(new_bytes)]
    fw[offset:offset + len(new_bytes)] = new_bytes
    print("  0x%06X: %s -> %s  (%s)" % (
        offset,
        ' '.join('%02X' % b for b in old),
        ' '.join('%02X' % b for b in new_bytes),
        desc))
    return bytes(old)


def main():
    with open(INPUT, 'rb') as f:
        fw = bytearray(f.read())

    print("Woodbourne Firmware Patcher")
    print("Input: %s (%d bytes)" % (INPUT, len(fw)))
    print()

    # --- Verify original checksums ---
    print("Verifying original checksums...")
    for name, base in [("Seg1", 0x50), ("Seg2", 0x70), ("Seg3", 0x90)]:
        expected = struct.unpack_from('<I', fw, base + 12)[0]
        computed = compute_seg_crc(fw, base)
        ok = "OK" if expected == computed else "MISMATCH!"
        print("  %s CRC: 0x%08X %s" % (name, computed, ok))
        if expected != computed:
            sys.exit("ERROR: Original CRC mismatch.")

    orig_f32 = struct.unpack_from('<I', fw, 0x104)[0]
    computed_f32 = compute_fletcher32(fw, FLETCHER_START, FLETCHER_END)
    print("  Fletcher-32: 0x%08X %s" % (computed_f32,
          "OK" if orig_f32 == computed_f32 else "MISMATCH!"))
    assert orig_f32 == ORIGINAL_FLETCHER32
    print("  Aggregate CRC: OK")
    print("  Overall CRC: OK")
    print()

    # --- Collect seg1 patches for Fletcher-32 compensation ---
    fletcher_patches = []

    # Patch 1: Idle timer — NOP 4 ARM instructions
    print("PATCH 1: Idle timer NOP")
    for off in [0x3C6190, 0x3C6194, 0x3C6198, 0x3C619C]:
        fletcher_patches.append((off, bytes(fw[off:off+4]), ARM_NOP))

    # Patch 2: PSM FuncB — branch past sleep call
    print("PATCH 2: PSM FuncB skip sleep")
    branch_b = struct.pack('<I', 0xEA000015)
    fletcher_patches.append((0x286920, bytes(fw[0x286920:0x286924]), branch_b))

    # Patch 3: PSM FuncA — branch past sleep call
    print("PATCH 3: PSM FuncA skip sleep")
    branch_a = struct.pack('<I', 0xEA00001C)
    fletcher_patches.append((0x286728, bytes(fw[0x286728:0x28672C]), branch_a))

    # Patch 6: Telnet — force Shell mode to TELNET in loadSettingsFromCne
    # When Shell=UART1, code stores 0x66 (UART1). We change to store 1 (TELNET)
    # so the telnet server starts its listener on port 10000.
    #   0x107628: BNE error        -> MOV R0, #1
    #   0x10762C: STRB R5,[R4,#29] -> STRB R0,[R4,#29]
    print("PATCH 6: Shell mode -> TELNET")
    telnet_a = struct.pack('<I', 0xE3A00001)  # MOV R0, #1
    telnet_b = struct.pack('<I', 0xE5C4001D)  # STRB R0, [R4, #0x1D]
    fletcher_patches.append((0x107628, bytes(fw[0x107628:0x10762C]), telnet_a))
    fletcher_patches.append((0x10762C, bytes(fw[0x10762C:0x107630]), telnet_b))

    # --- Compute Fletcher-32 compensation ---
    comp_pos1 = 0x4A4F60
    comp_pos2 = 0x4A4F62
    assert fw[comp_pos1:comp_pos1+4] == b'\x00\x00\x00\x00', "Comp area not zero!"

    print()
    print("PATCH 7: Fletcher-32 compensation")
    d1, d2 = compute_fletcher32_compensation(fw, fletcher_patches, comp_pos1, comp_pos2)
    print("  Values: 0x%04X @ 0x%06X, 0x%04X @ 0x%06X" % (
        d1, comp_pos1, d2, comp_pos2))

    # --- Apply all patches ---
    print()
    print("Applying patches...")

    for off in [0x3C6190, 0x3C6194, 0x3C6198, 0x3C619C]:
        patch_bytes(fw, off, ARM_NOP, "NOP idle timer")

    patch_bytes(fw, 0x286920, branch_b, "B 0x28697C (skip sleep)")
    patch_bytes(fw, 0x286728, branch_a, "B 0x2867A0 (skip sleep)")

    print()
    print("PATCH 4: Config defaults")
    patch_bytes(fw, 0x4FE6F5, b'\x30', "EnableSleepTimer 1->0")
    patch_bytes(fw, 0x4FDCE6, b'\x39\x39', "SleepTime 00->99")

    print()
    print("PATCH 5: Version marker")
    patch_bytes(fw, 0x30, b'NOSLEEP ', "bCoD date")
    patch_bytes(fw, 0x50C43F, b'\x31', "Firmwarerevision .0->.1")

    print()
    print("PATCH 6: Shell mode -> TELNET")
    patch_bytes(fw, 0x107628, telnet_a, "MOV R0, #1 (TELNET)")
    patch_bytes(fw, 0x10762C, telnet_b, "STRB R0, [R4, #0x1D]")

    print()
    print("PATCH 7: Fletcher-32 compensation")
    patch_bytes(fw, comp_pos1, struct.pack('<H', d1), "comp word 1")
    patch_bytes(fw, comp_pos2, struct.pack('<H', d2), "comp word 2")

    # --- Verify Fletcher-32 ---
    print()
    new_f32 = compute_fletcher32(fw, FLETCHER_START, FLETCHER_END)
    print("Fletcher-32: 0x%08X %s" % (new_f32,
          "MATCH" if new_f32 == ORIGINAL_FLETCHER32 else "MISMATCH!"))
    if new_f32 != ORIGINAL_FLETCHER32:
        sys.exit(1)

    # --- Recompute CRCs ---
    print()
    print("Recomputing CRCs...")
    for name, base in [("Seg1", 0x50), ("Seg2", 0x70), ("Seg3", 0x90)]:
        new_crc = compute_seg_crc(fw, base)
        old_crc = struct.unpack_from('<I', fw, base + 12)[0]
        struct.pack_into('<I', fw, base + 12, new_crc)
        tag = "UPDATED" if old_crc != new_crc else "unchanged"
        print("  %s: 0x%08X -> 0x%08X (%s)" % (name, old_crc, new_crc, tag))

    old_agg = struct.unpack_from('<I', fw, 0x4C)[0]
    new_agg = compute_aggregate_crc(fw)
    struct.pack_into('<I', fw, 0x4C, new_agg)
    print("  Agg: 0x%08X -> 0x%08X" % (old_agg, new_agg))

    old_overall = struct.unpack_from('<I', fw, 0x10)[0]
    new_overall = compute_overall_crc(fw)
    struct.pack_into('<I', fw, 0x10, new_overall)
    print("  All: 0x%08X -> 0x%08X" % (old_overall, new_overall))

    # --- Final verification ---
    print()
    print("Verifying...")
    all_ok = True
    for name, base in [("Seg1", 0x50), ("Seg2", 0x70), ("Seg3", 0x90)]:
        ok = struct.unpack_from('<I', fw, base + 12)[0] == compute_seg_crc(fw, base)
        print("  %s CRC: %s" % (name, "OK" if ok else "FAIL"))
        all_ok &= ok
    ok = struct.unpack_from('<I', fw, 0x4C)[0] == compute_aggregate_crc(fw)
    print("  Aggregate: %s" % ("OK" if ok else "FAIL"))
    all_ok &= ok
    ok = struct.unpack_from('<I', fw, 0x10)[0] == compute_overall_crc(fw)
    print("  Overall: %s" % ("OK" if ok else "FAIL"))
    all_ok &= ok
    ok = compute_fletcher32(fw, FLETCHER_START, FLETCHER_END) == ORIGINAL_FLETCHER32
    print("  Fletcher-32: %s" % ("OK" if ok else "FAIL"))
    all_ok &= ok

    if not all_ok:
        sys.exit("Verification failed!")

    # --- Write output ---
    with open(OUTPUT, 'wb') as f:
        f.write(fw)

    diff_count = sum(1 for a, b in zip(open(INPUT,'rb').read(), fw) if a != b)

    print()
    print("=" * 60)
    print("Output: %s" % OUTPUT)
    print("%d bytes modified" % diff_count)
    print("=" * 60)
    print()
    print("No-sleep patches:")
    print("  1. Idle timer: 4 ARM NOPs at 0x3C6190-0x3C619C")
    print("  2. PSM FuncB: B 0x28697C at 0x286920")
    print("  3. PSM FuncA: B 0x2867A0 at 0x286728")
    print("  4. EnableSleepTimer=0, SleepTime=99")
    print()
    print("Telnet shell:")
    print("  6. Shell mode forced to TELNET (code patch at 0x107628)")
    print("     telnet <speaker-ip> 10000")
    print()
    print("Version:")
    print("  5. bCoD date='NOSLEEP', Firmwarerevision .1")
    print("     Check: http://<speaker-ip>/firmware_update_prepare.asp")
    print()
    print("Checksums:")
    print("  7. Fletcher-32 compensation at 0x4A4F60 (BSL area preserved)")
    print("  CRCs updated: Seg1, Seg2, Aggregate, Overall")


if __name__ == '__main__':
    main()
