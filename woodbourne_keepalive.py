#!/usr/bin/env python3
"""
Woodbourne Keep-Alive

Prevents the Polk Woodbourne from sleeping by sending a brief silent
AirPlay burst every N minutes when the speaker is idle.

Detection: UPnP SOAP query to GetDeviceStatusInfo on port 8080.
           Uses Connection: close to be gentle on GoAhead's limited slots.
Streaming: PulseAudio module-raop-discover + paplay to the auto-discovered sink.

Requirements:
  sudo apt install pulseaudio pulseaudio-module-raop

Usage:
  python3 woodbourne_keepalive.py [--host 192.168.1.92] [--interval 600]
"""

import argparse
import http.client
import os
import signal
import subprocess
import sys
import tempfile
import time
import wave
import xml.etree.ElementTree as ET

# --- UPnP PlayState query ---

SOAP_BODY = b"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:GetDeviceStatusInfo
       xmlns:u="urn:schemas-smsc-com:service:X_WholeHomeAudio:1"/>
  </s:Body>
</s:Envelope>"""

SOAP_ACTION = '"urn:schemas-smsc-com:service:X_WholeHomeAudio:1#GetDeviceStatusInfo"'


def get_play_state(host, timeout=3.0):
    """Query PlayState. Returns 0 (idle), 1 (playing), or None (error)."""
    conn = None
    try:
        conn = http.client.HTTPConnection(host, 8080, timeout=timeout)
        conn.request(
            "POST",
            "/WholeHomeAudio/ctrl",
            body=SOAP_BODY,
            headers={
                "Content-Type": 'text/xml; charset="utf-8"',
                "SOAPAction": SOAP_ACTION,
                "Connection": "close",
                "Content-Length": str(len(SOAP_BODY)),
            },
        )
        body = conn.getresponse().read().decode("utf-8", errors="replace")
    except Exception as e:
        print("  SOAP error: %s" % e)
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    try:
        root = ET.fromstring(body)
        for el in root.iter():
            if "GetDeviceStatusInfoResponse" in el.tag:
                for child in el:
                    tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if tag == "PlayState":
                        return int(child.text)
        return None
    except (ET.ParseError, ValueError, TypeError) as e:
        print("  XML parse error: %s" % e)
        return None


# --- Silent WAV ---

def ensure_silent_wav(path, duration_sec=2, sample_rate=44100, channels=2):
    """Create a short silent WAV file if it doesn't exist."""
    if os.path.exists(path):
        return path
    with wave.open(path, "w") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * channels * sample_rate * duration_sec)
    return path


# --- PulseAudio RAOP ---

def ensure_raop_discover(force_reload=False):
    """Make sure module-raop-discover is loaded. If force_reload, unload first."""
    try:
        result = subprocess.run(
            ["pactl", "list", "modules", "short"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            print("  pactl list modules failed: %s" % result.stderr.strip())
            return False

        already_loaded = "module-raop-discover" in result.stdout

        if already_loaded and force_reload:
            # Extract module ID and unload to clear stale sinks
            for line in result.stdout.strip().split("\n"):
                if "module-raop-discover" in line:
                    mod_id = line.split("\t")[0]
                    print("  Unloading stale module-raop-discover (id %s)..." % mod_id)
                    subprocess.run(
                        ["pactl", "unload-module", mod_id],
                        capture_output=True, text=True, timeout=5,
                    )
            already_loaded = False
            time.sleep(1)

        if already_loaded:
            return True

        # Load it
        print("  Loading module-raop-discover...")
        result = subprocess.run(
            ["pactl", "load-module", "module-raop-discover"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            print("  module-raop-discover loaded")
            time.sleep(3)
            return True
        print("  Failed to load module-raop-discover: %s" % result.stderr.strip())
        return False
    except Exception as e:
        print("  ensure_raop_discover error: %s" % e)
        return False


def find_woodbourne_sink(speaker_name="Woodbourne"):
    """Find the auto-discovered RAOP sink name for the Woodbourne."""
    try:
        result = subprocess.run(
            ["pactl", "list", "sinks", "short"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.strip().split("\n"):
            if speaker_name in line and "raop_output" in line:
                return line.split("\t")[1]  # sink name is second field
        return None
    except Exception:
        return None


def send_silence(sink_name, wav_path, verbose=False):
    """Play the silent WAV to the RAOP sink."""
    try:
        result = subprocess.run(
            ["paplay", "--device=%s" % sink_name, wav_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            if verbose:
                print("    paplay error: %s" % result.stderr.strip())
            return False
        return True
    except subprocess.TimeoutExpired:
        if verbose:
            print("    paplay timed out")
        return False
    except Exception as e:
        if verbose:
            print("    paplay exception: %s" % e)
        return False


# --- Main ---

def main():
    parser = argparse.ArgumentParser(
        description="Woodbourne Keep-Alive: prevents speaker sleep")
    parser.add_argument("--host", default="192.168.1.92",
                        help="Speaker IP (default: 192.168.1.92)")
    parser.add_argument("--interval", type=float, default=600,
                        help="Seconds between checks (default: 600 = 10 min)")
    parser.add_argument("--speaker-name", default="Woodbourne",
                        help="Speaker name in RAOP discovery (default: Woodbourne)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    wav_path = os.path.join(tempfile.gettempdir(), "woodbourne_silence.wav")
    ensure_silent_wav(wav_path)

    def cleanup(signum=None, frame=None):
        try:
            os.unlink(wav_path)
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    print("Woodbourne Keep-Alive")
    print("  Speaker:  %s (%s)" % (args.speaker_name, args.host))
    print("  Interval: %.0fs (%.1f min)" % (args.interval, args.interval / 60))

    # Ensure RAOP discovery is running
    if not ensure_raop_discover():
        print("  ERROR: Could not load module-raop-discover", file=sys.stderr)
        print("  Install: sudo apt install pulseaudio-module-raop", file=sys.stderr)
        sys.exit(1)

    sink_name = find_woodbourne_sink(args.speaker_name)
    if sink_name:
        print("  Sink:     %s" % sink_name)
    else:
        print("  WARNING: Sink not found yet, will retry")
    print("")

    consecutive_errors = 0

    while True:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")

        # Query speaker state
        play_state = get_play_state(args.host)

        if play_state is None:
            consecutive_errors += 1
            backoff = min(args.interval, 60.0 * (2 ** min(consecutive_errors - 1, 3)))
            if consecutive_errors == 1 or consecutive_errors % 5 == 0:
                print("[%s] Speaker unreachable (attempt %d)" % (ts, consecutive_errors))
            time.sleep(backoff)
            continue

        if consecutive_errors > 0 and args.verbose:
            print("[%s] Speaker reconnected" % ts)
        consecutive_errors = 0

        if play_state == 0:
            # Speaker is idle — send keep-alive
            # Re-check sink availability (it may have disappeared/reappeared)
            if sink_name is None or find_woodbourne_sink(args.speaker_name) is None:
                ensure_raop_discover(force_reload=(sink_name is not None))
                time.sleep(2)
                sink_name = find_woodbourne_sink(args.speaker_name)

            if sink_name:
                print("[%s] Idle — sending keep-alive" % ts)
                ok = send_silence(sink_name, wav_path, args.verbose)
                if not ok:
                    # Sink is stale — force reload RAOP module to get fresh connection
                    print("[%s] Keep-alive failed — reloading RAOP module" % ts)
                    ensure_raop_discover(force_reload=True)
                    time.sleep(2)
                    sink_name = find_woodbourne_sink(args.speaker_name)
                    if sink_name:
                        print("[%s] Retrying with fresh sink %s" % (ts, sink_name))
                        ok = send_silence(sink_name, wav_path, args.verbose)
                        if not ok:
                            print("[%s] Retry failed" % ts)
                            sink_name = None
                    else:
                        print("[%s] No sink after reload" % ts)
            else:
                print("[%s] Idle — but sink not found, skipping" % ts)
        else:
            if args.verbose:
                print("[%s] Playing — skipping" % ts)

        time.sleep(args.interval)


if __name__ == "__main__":
    main()
