# Patch 1: Telnet Enable

**Purpose:** Activate the built-in BridgeCo telnet diagnostic shell, accessible on TCP port 10000.

**Region:** Seg1 code (ARM)
**Bytes modified:** 8

## Background

The BridgeCo DMP 3.x RTOS includes a full telnet shell service (`TelnetShellService`) compiled into the firmware. The shell provides memory read/write, config tree browsing, RTOS thread inspection, network tools, and dozens of other diagnostic commands.

However, the shell is routed to serial UART by default. The `loadSettingsFromCne` function in the firmware reads the `Shell` key from the `[CommunicationSettings]` RSDB section and sets a mode byte that determines where the shell is directed:

| Config value | Mode byte | Effect |
|-------------|-----------|--------|
| `OFF` | 0x00 | Shell disabled |
| `TELNET` | 0x01 | Shell on telnet socket |
| `UART0` | 0x65 | Shell on serial UART0 |
| `UART1` | 0x66 | Shell on serial UART1 |

The factory default is `Shell=UART1`, which stores mode byte 0x66. Changing the RSDB default string is not feasible because `"TELNET"` (6 chars) is longer than `"UART1"` (5 chars), and the RSDB uses null-delimited fixed-layout entries. A code patch is required instead.

## Patch detail

The `loadSettingsFromCne` function compares the Shell config value against each known string. The UART1 case is the last comparison, at the end of a chain of if/else-if blocks:

```
107618:  ADR R1, "UART1"           ; load comparison string
10761C:  ADD R0, SP, #4            ; config value buffer
107620:  BL strcmp
107624:  CMP R0, #0
107628:  BNE 0x107670              ; if not "UART1" -> error handler
10762C:  STRB R5, [R4, #0x1D]     ; store R5 (0x66 = UART1 mode)
```

The patch changes the UART1 handler to store TELNET mode (1) instead:

| Offset | Original | Patched | Description |
|--------|----------|---------|-------------|
| 0x107628 | `10 00 00 1A` | `01 00 A0 E3` | `BNE 0x107670` -> `MOV R0, #1` |
| 0x10762C | `1D 50 C4 E5` | `1D 00 C4 E5` | `STRB R5, [R4,#0x1D]` -> `STRB R0, [R4,#0x1D]` |

After this patch, whenever the firmware reads `Shell=UART1` from config, it stores TELNET mode instead. The telnet server starts its TCP listener on port 10000 (the `TelnetPort_Obsolete` value from `[CommunicationSettings]`).

## Connection

```
$ telnet <speaker-ip> 10000
BridgeCo AG Telnet server

sds://>
```

## Available commands

```
help          List all commands
sys ver       Firmware version info
os th         List RTOS threads
netcfg        Network configuration
ls            Browse config tree
cd / pwd      Navigate config tree
get / set     Read/write config values
rd / wr       Read/write memory addresses
ping          Ping from the speaker
persparam     Read/write persistent NVRAM parameters
fburn         Flash burn operations
```

## Impact

- The shell is redirected from serial UART1 to the telnet TCP socket. Serial console output is no longer available on UART1.
- The telnet server listens on port 10000 with no authentication. This is suitable for a trusted home network.
- This is a code patch in Seg1, so it affects the Fletcher-32 checksum and requires [compensation](patch-3-fletcher32-compensation.md).
