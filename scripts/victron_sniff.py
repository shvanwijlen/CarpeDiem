"""Throwaway diagnostic: dump EVERY value the Cerbo GX (Venus OS) publishes
over MQTT, to find out which topic actually carries a reading mqtt_client.py
isn't picking up (e.g. "DC Power (W)", which the app reads from
system/0/Dc/System/Power).

Venus republishes its whole D-Bus tree when it receives a keepalive on
R/<portal>/keepalive, so one subscription to N/<portal>/# plus that poke
gives the complete picture - every service (system, battery, vebus,
solarcharger, dcload, temperature, ...), grouped by device instance, with
the device's name where it has one.

Run on the Pi (or any machine that can reach the Cerbo and has the same
.env / venv as the app):

    python -m scripts.victron_sniff                  # 15 s snapshot, everything
    python -m scripts.victron_sniff -f Dc/System     # only topics containing this (repeatable)
    python -m scripts.victron_sniff -f power -s 30   # all power topics, listen 30 s
    python -m scripts.victron_sniff --watch -f power # live stream instead of a summary

After the table it prints how each topic mqtt_client.py maps to a display
field is doing (OK / NULL / NOT PUBLISHED) and lists other numeric
power-like topics - a topic that is NULL means Venus knows the path but has
no valid reading for it (mqtt_client.py drops those silently); NOT
PUBLISHED means that path doesn't exist on this installation, so look for
the right one in the candidates list.
"""
from __future__ import annotations

import argparse
import json
import time

import paho.mqtt.client as mqtt

from carpediem.config import config
from carpediem.mqtt_client import _TOPIC_TO_FIELD

portal = config.mqtt.portal_id
prefix = f"N/{portal}/"

seen: dict[str, object] = {}  # topic suffix (after N/<portal>/) -> decoded value
args: argparse.Namespace


def _matches(topic: str) -> bool:
    if not args.filter:
        return True
    low = topic.lower()
    return any(f.lower() in low for f in args.filter)


def _decode(payload: bytes) -> object:
    text = payload.decode("utf-8", errors="replace")
    try:
        data = json.loads(text)
    except ValueError:
        return text
    if isinstance(data, dict) and "value" in data:
        return data["value"]
    return data


def _poke(client: mqtt.Client) -> None:
    client.publish(f"R/{portal}/keepalive", payload="")  # full republish
    client.publish(f"R/{portal}/system/0/Serial", payload="")  # same poke mqtt_client.py uses


def on_connect(client, userdata, flags, rc) -> None:
    print(f"connected to {config.mqtt.host}:{config.mqtt.port} (rc={rc}), subscribing to N/{portal}/#")
    client.subscribe(f"N/{portal}/#")
    _poke(client)


def on_message(client, userdata, msg) -> None:
    if not msg.topic.startswith(prefix):
        return
    suffix = msg.topic[len(prefix):]
    value = _decode(msg.payload)
    seen[suffix] = value
    if args.watch and _matches(suffix):
        mark = "  <-- " + _TOPIC_TO_FIELD[suffix][0] if suffix in _TOPIC_TO_FIELD else ""
        print(f"{time.strftime('%H:%M:%S')}  {suffix} = {value!r}{mark}")


def _is_number(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def print_summary() -> None:
    shown = {t: v for t, v in seen.items() if _matches(t)}
    print(f"\n{len(seen)} topics received, {len(shown)} shown\n")

    # Group by "<service>/<instance>" (first two path parts, e.g. "battery/278").
    groups: dict[str, dict[str, object]] = {}
    for topic, value in sorted(shown.items()):
        parts = topic.split("/", 2)
        key = "/".join(parts[:2])
        groups.setdefault(key, {})["/".join(parts[2:]) or "(root)"] = value

    for key, items in groups.items():
        name = seen.get(f"{key}/CustomName") or seen.get(f"{key}/ProductName") or ""
        print(f"=== {key}  {name}")
        for rest, value in items.items():
            mark = f"   <-- {_TOPIC_TO_FIELD[f'{key}/{rest}'][0]}" if f"{key}/{rest}" in _TOPIC_TO_FIELD else ""
            print(f"  {rest:<48} {value!r}{mark}")
        print()

    print("=== Topics mqtt_client.py maps to display fields")
    for topic, (field, _scale) in _TOPIC_TO_FIELD.items():
        if topic not in seen:
            status = "NOT PUBLISHED"
        elif seen[topic] is None:
            status = "NULL (path exists, no valid reading - app drops this)"
        else:
            status = f"OK  value={seen[topic]!r}"
        print(f"  {field:<34} {topic:<36} {status}")

    print("\n=== Other numeric power-like topics not mapped by the app (candidates)")
    candidates = {t: v for t, v in seen.items()
                  if t not in _TOPIC_TO_FIELD and _is_number(v)
                  and (t.endswith("/Power") or "Dc/System" in t or t.endswith("/P"))}
    if not candidates:
        print("  (none)")
    for topic, value in sorted(candidates.items()):
        print(f"  {topic:<56} {value!r}")


def main() -> None:
    global args
    parser = argparse.ArgumentParser(description="Dump everything the Cerbo GX publishes over MQTT.")
    parser.add_argument("-f", "--filter", action="append", metavar="TEXT",
                        help="only show topics containing TEXT (case-insensitive, repeatable)")
    parser.add_argument("-s", "--seconds", type=float, default=15.0,
                        help="how long to listen before printing the summary (default 15)")
    parser.add_argument("--watch", action="store_true",
                        help="stream matching messages live until Ctrl+C instead of a summary")
    args = parser.parse_args()

    client = mqtt.Client(client_id="CarpeDiem-victron-sniff", clean_session=True)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(config.mqtt.host, config.mqtt.port, keepalive=60)

    if args.watch:
        client.loop_start()
        try:
            while True:
                time.sleep(30)
                _poke(client)
        except KeyboardInterrupt:
            pass
        finally:
            client.loop_stop()
        return

    client.loop_start()
    deadline = time.monotonic() + args.seconds
    try:
        while time.monotonic() < deadline:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    client.loop_stop()
    client.disconnect()
    if not seen:
        print(f"Nothing received from {config.mqtt.host}:{config.mqtt.port} - check MQTT_HOST / the "
              f"portal id ({portal!r}) in .env and that MQTT on LAN is enabled on the Cerbo.")
        return
    print_summary()


if __name__ == "__main__":
    main()
