# Firmware File Layout

The `.FW` file is a BridgeCo firmware image containing an outer header, a `bCoD` inner header with segment descriptors, three data segments, and a secondary bootloader image.

Total size: **7,490,336 bytes** (0x724B20).

## File map

```
Offset      Size        Contents
----------------------------------------------------------------------
0x000000    0x20        Outer header
0x000020    0x98        bCoD header (signature, date, segment descriptors)
0x0000B8    0x20        Seg1 per-segment header ("DMP 3.x")
0x0000D8    0x4FCBDC    Seg1 data (5,229,532 bytes) -- ARM/Thumb code
0x4FCC94    0x20        Seg2 per-segment header
0x4FCCB4    0xFED8      Seg2 data (65,240 bytes) -- RSDB config
0x50CB6C    0x20        Seg3 per-segment header
0x50CB8C    0x95A20     Seg3 data (612,896 bytes) -- Thumb code + HTML
0x5A25AC    0x254       Padding (0xFF fill)
0x5A2800    0x182320    BSL_CE2 bootloader image (second bCoD)
```

## Outer header (0x00 - 0x1F)

```
Offset  Size  Value         Description
------  ----  -----------   -------------------------------------------
0x00    4     0x00000002    Header version
0x04    4     0x00709000    Unknown (possibly total payload size)
0x08    4     0x00166800    Unknown
0x0C    4     0x0001BB00    Unknown
0x10    4     0x52B8CA90    Overall CRC-32 (covers 0x20 to EOF)
0x14    12    0x00...       Reserved / padding
```

The overall CRC is a standard CRC-32 (`zlib.crc32`) computed over all bytes from offset 0x20 to end of file.

## bCoD header (0x20 - 0xB7)

The inner header starts with the ASCII signature `bCoD` and contains firmware metadata and three segment descriptors.

```
Offset  Size  Value              Description
------  ----  -----------------  ------------------------------------------
0x20    4     "bCoD"             Signature (0x446F4362)
0x24    4     0x00000001         Header version
0x28    8     "20130531"         Build date (ASCII YYYYMMDD)
0x30    8     "094540  "         Build time (ASCII HHMMSS + padding)
0x38    4     0x00000074         Unknown (header size?)
0x3C    2     9519               Firmware ID (product B9519)
0x3E    2     0x0000             Reserved
0x40    4     0x000200BD         Unknown
0x44    4     0x0007F510         Unknown
0x48    4     0x00000002         Segment count minus one? (3 segments)
0x4C    4     0x3E0DB07E         Aggregate CRC-32
0x50    32    (Seg1 descriptor)
0x70    32    (Seg2 descriptor)
0x90    32    (Seg3 descriptor)
```

**Aggregate CRC:** CRC-32 of bytes 0x20..0xCF, with the aggregate CRC field itself (bytes 0x4C..0x4F) zeroed before computation.

**Patched field:** Offset 0x30 is changed from `"094540  "` to `"NOSLEEP "` as a version marker.

## Segment descriptors

Each segment descriptor is 32 bytes. The first 16 bytes are the essential fields:

```
Offset  Size  Description
------  ----  --------------------------------------------------
+0x00   4     File offset of per-segment header
+0x04   4     Load address (where segment is loaded in memory)
+0x08   4     Data size (excluding 0x20-byte per-segment header)
+0x0C   4     CRC-32 of segment data
+0x10   16    Extended fields (varies per segment)
```

### Seg1 -- Code (descriptor at 0x50)

| Field | Value | Notes |
|-------|-------|-------|
| Offset | 0x000000B8 | Per-segment header at 0xB8, data at 0xD8 |
| Load addr | 0x401C0000 | Main RAM |
| Data size | 0x004FCBDC | 5,229,532 bytes |
| CRC-32 | 0xF2DD2FD5 | |

Contains all ARM and Thumb executable code, the BSL header, interrupt vectors, and the RTOS kernel. The per-segment header contains the string `"DMP 3.x"` identifying the BridgeCo platform.

### Seg2 -- Config (descriptor at 0x70)

| Field | Value | Notes |
|-------|-------|-------|
| Offset | 0x004FCC94 | Per-segment header, data at 0x4FCCB4 |
| Load addr | 0x00000000 | Overlaid by NVRAM at runtime |
| Data size | 0x0000FED8 | 65,240 bytes |
| CRC-32 | 0x73814064 | |

Contains the RSDB (Resource/Settings Database) default configuration. Structured as null-delimited `[Section\0Key\0Value\0...]` blocks. Runtime values may be overridden by persistent NVRAM storage.

### Seg3 -- Resources (descriptor at 0x90)

| Field | Value | Notes |
|-------|-------|-------|
| Offset | 0x0050CB6C | Per-segment header, data at 0x50CB8C |
| Load addr | 0x40700000 | Resource RAM region |
| Data size | 0x00095A20 | 612,896 bytes |
| CRC-32 | 0xE6DC40A9 | |

Contains Thumb code for the web interface, ASP template pages (HTML with `<% aspFunction %>` tags), UPnP device descriptions, and string resources.

## BSL header (0xD8 - 0x117)

The first 0x2000 bytes of Seg1 data form the BSL (Boot Strap Loader) header area. This region is **preserved in flash** when firmware is uploaded via the BL-mode web interface -- the bootloader protects its own header from being overwritten.

```
Offset  Size  Value         Description
------  ----  -----------   -------------------------------------------
0x0D8   4     0xAAAA5555    BSL magic number
0x0DC   4     0x00000001    BSL version
0x0E0   4     0xA5A5A5A5    Marker
0x0E4   4     0x0040DA00    Initial stack pointer
0x0E8   4     0x000002E7    Type / entry count
0x0EC   4     0x9F6C171F    Boot mode selector (not a CRC)
0x0F0   4     0xEA000008    ARM reset vector: B 0x118
0x0F4   4     0xA5A5A5A5    Marker
0x0F8   4     0x00008000    Fletcher-32 start offset (relative to seg1 start)
0x0FC   4     0x001C2080    Unknown (possibly entry point related)
0x100   4     0x004FABDC    Fletcher-32 range size (seg1_size - 0x2000)
0x104   4     0xF7D16EC9    Fletcher-32 checksum
```

### Fletcher-32 validation

At boot, the BSL:
1. Copies firmware from flash to RAM
2. Reads the expected Fletcher-32 from offset 0x104 (which is in the preserved BSL area)
3. Computes Fletcher-32 over Seg1 data from offset 0x2000 to end (file offsets 0x20D8 - 0x4FCCB4)
4. If match: branches to firmware entry point
5. If mismatch: enters infinite loop (brick state, requires BL-mode reflash)

The Fletcher-32 uses little-endian 16-bit words with initial values s1=0xFFFF, s2=0xFFFF, and per-word modulo 65535.

**Critical implication:** Since the BSL area is preserved during BL-mode flashing, the Fletcher-32 expected value at 0x104 always retains the **original** firmware's value. Any code patches must therefore produce the same Fletcher-32 as the original, which is achieved through a [compensation technique](patch-7-fletcher32-compensation.md).

## Checksum summary

| Checksum | Location | Algorithm | Covers |
|----------|----------|-----------|--------|
| Overall CRC | 0x10 | CRC-32 | 0x20 to EOF |
| Aggregate CRC | 0x4C | CRC-32 | 0x20..0xCF (with 0x4C..0x4F zeroed) |
| Seg1 CRC | 0x5C | CRC-32 | Seg1 data (0xD8..0x4FCCB3) |
| Seg2 CRC | 0x7C | CRC-32 | Seg2 data (0x4FCCB4..0x50CB8B) |
| Seg3 CRC | 0x9C | CRC-32 | Seg3 data (0x50CB8C..0x5A25AB) |
| Fletcher-32 | 0x104 | Fletcher-32 | Seg1 data[0x2000:] (0x20D8..0x4FCCB3) |

The CRC-32 values are standard (`zlib.crc32`). The patcher recomputes all four CRC-32 values. The Fletcher-32 at 0x104 is **not** updated (BSL area is preserved in flash); instead, compensation values are inserted to maintain the original checksum.

## BSL_CE2 (0x5A2800 - EOF)

A secondary bootloader image with its own `bCoD` header (dated `20130603125231`). This is the BL-mode recovery bootloader that provides the web-based firmware upload interface. It is not modified by the patch.

## RSDB config format (Seg2)

Configuration defaults are stored as null-delimited text blocks:

```
[SectionName\0Key1\0Value1\0Key2\0Value2\0]\0
```

Example from the firmware:
```
[UartSwitch\0UartPortSelect\00\0TelnetShellEnable\01\0TelnetShellPort\08000\0]\0
[CommunicationSettings\0Shell\0UART1\0TelnetPort_Obsolete\010000\0...]\0
```

At runtime, these defaults are loaded first, then overlaid with any values stored in persistent NVRAM. This means patching a default value in Seg2 only takes effect if NVRAM does not contain an override for that key.
