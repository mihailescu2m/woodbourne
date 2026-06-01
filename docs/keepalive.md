# The Raspberry Pi keepalive daemon (the workaround that didn't stick)

Before the firmware keepalive existed, the standby was attacked from *outside* the
speaker: a small always‑on Linux host (a **Raspberry Pi Zero 2 W**) on the same LAN that
kept the Woodbourne awake. It worked well enough to prove the concept but was fragile in
daily use, which is ultimately why the logic was moved *into* the firmware
([Patch 2](patch-2-keepalive-reboot.md)).

This page documents that approach for completeness — the files
[`woodbourne_keepalive.py`](../woodbourne_keepalive.py) and
[`woodbourne-keepalive.service`](../woodbourne-keepalive.service) are included in the repo.

## How it worked

1. **Detect idle.** Every *N* seconds, send a UPnP SOAP `GetDeviceStatusInfo` request to
   the speaker's `X_WholeHomeAudio` service on port 8080 and read back `PlayState`
   (`0` = idle, `1` = playing). `Connection: close` is used to be gentle on the speaker's
   GoAhead web server, which has very few concurrent slots.
2. **Nudge it awake.** When idle, stream ~2 s of **silence** to the speaker over AirPlay
   via PulseAudio's `module-raop-discover` + `paplay` to the auto‑discovered RAOP sink.
   A short silent burst restarts the host's idle clock just like real playback would.
3. **Self‑heal.** RAOP sinks disappear and reappear; on a failed `paplay` the daemon
   force‑reloads `module-raop-discover` and retries with a fresh sink. Unreachable‑speaker
   errors back off exponentially.

```
UPnP GetDeviceStatusInfo (8080)  ->  PlayState?
        idle ──> paplay 2 s silence ──> RAOP sink ──> speaker stays awake
     playing ──> do nothing
```

## Install (systemd)

`woodbourne-keepalive.service`:

```ini
[Unit]
Description=Woodbourne AirPlay Keep-Alive
After=network-online.target avahi-daemon.service pulseaudio.service
Wants=network-online.target

[Service]
Type=simple
User=volumio
Environment=XDG_RUNTIME_DIR=/run/user/1000
Environment=PYTHONUNBUFFERED=1
ExecStartPre=/bin/sleep 15
ExecStart=/usr/bin/python3 /home/volumio/woodbourne_keepalive.py --host 192.168.1.92 --interval 300 --verbose
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo apt install pulseaudio pulseaudio-module-raop
sudo cp woodbourne_keepalive.py /home/volumio/
sudo cp woodbourne-keepalive.service /etc/systemd/system/
sudo systemctl enable --now woodbourne-keepalive
```

Run it by hand to watch it work:

```bash
python3 woodbourne_keepalive.py --host 192.168.1.92 --interval 300 --verbose
```

## Why it ultimately failed

- **Stale RAOP sinks.** PulseAudio's auto‑discovered RAOP sink for the speaker would go
  stale (the speaker drops the AirPlay session aggressively), so `paplay` failed and the
  daemon had to keep tearing down and reloading `module-raop-discover`. Reliability was
  poor over days/weeks.
- **GoAhead slot pressure.** The speaker's tiny embedded web server has only a handful of
  connection slots; polling it plus everything else on the network occasionally starved it.
- **Racy detection.** Polling every few minutes means standby sometimes started *between*
  polls; the nudge then arrived too late, and the speaker had already begun tearing down.
- **Extra always‑on hardware.** It needed a dedicated Pi running 24/7, with PulseAudio +
  Avahi configured correctly — a lot of moving parts to keep one speaker awake.

The lesson — *the reliable way to reset the host's idle clock is a reboot, and the
cleanest place to trigger that is inside the firmware on a tick the DMP already
services* — is exactly what the firmware keepalive implements, with no external
dependencies. See [power.md](power.md) for the full reasoning.
