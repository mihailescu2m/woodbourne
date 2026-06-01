# Patch 4: WEP config‑path typo fix

**Purpose:** Fix a stock firmware typo that makes the wireless‑config web page log a
`webCfgNetGetCneValue: bad path` error.

**Region:** Seg3 web resources (ASP template)
**Bytes modified:** 1

## Background

The wireless setup page contains an ASP template that pre‑fills the WEP key field:

```html
<input type="password" name="Key0"
  value="<% aspGetWNCSelProfCneWepKey("/cf?/Networking/DrvCfg/WlanCfg/SELPROFI/WEP","Key0"); %>" ...>
```

At runtime the handler substitutes `SELPROFI` → the selected profile (e.g. `Profile1`)
and passes the result to `webCfgNetGetCneValue`. But the path prefix is `/cf?/` — a
literal `?` (byte `0x3F`) where it should read `/cfg/`. The config engine rejects it:

```
webCfgNetGetCneValue: bad path(/cf?/Networking/DrvCfg/WlanCfg/Profile1/WEP).
aspGetWNCSelProfCneVal: error.
```

This is a genuine typo in the factory image. Every other reference to this subtree uses
the correct prefix — the firmware's own WEP read/write code hard‑codes, for example,
`/cfg/Networking/DrvCfg/WlanCfg/Profile1/WEP` (at file offset `0x01D913`) and the
template `/cfg/Networking/DrvCfg/WlanCfg/Profile%d/WEP` at several sites. `/cfg/` is the
CNE config root; `/cne/` is a *different* namespace reserved for shell/streaming paths
(`/cne/Shell/`, `/cne/Lastfm/`, `sds://cne/Sirius/`) and is **not** valid here.

## Impact when unfixed

Harmless in practice — it only fails to pre‑fill the WEP Key0 box when rendering the
wireless page. Modern WPA/WPA2/open networks have no WEP key, so the field is irrelevant
and scanning/connecting are unaffected. The error is normally invisible because the log
that prints it is muted in the stock build.

## Patch detail

| Offset | Original | Patched | Description |
|--------|----------|---------|-------------|
| 0x54FFA4 | `3F` (`?`) | `67` (`g`) | `/cf?/` → `/cfg/` |

After the fix the resolved path is `/cfg/Networking/DrvCfg/WlanCfg/Profile1/WEP`, which
matches the firmware's own hard‑coded path and is accepted by `webCfgNetGetCneValue`.

## Checksum note

`0x54FFA4` lies in **Seg3**, outside the Fletcher‑32 range (which only covers Seg1), so
no Fletcher compensation is needed. The patcher recomputes the Seg3 CRC‑32 and the
overall CRC‑32 to keep the image valid.
