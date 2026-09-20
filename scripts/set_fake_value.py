"""Change a fake data value while the app is running, e.g. to see how a
screen reacts to a low battery or a hot engine room without restarting.

Only works when the app runs in fake mode (CARPEDIEM_DO_FAKE=true) and only
from the Pi itself - it talks to the running app's web server (the app's data
lives in that process's memory, so a second process can't touch it directly),
and that server refuses these requests otherwise.

Run in a second terminal (same venv as the app):

    python -m scripts.set_fake_value                            interactive
    python -m scripts.set_fake_value "Battery SOC (%)" 15        one shot
    python -m scripts.set_fake_value --list                      what you've changed
    python -m scripts.set_fake_value --reset "Battery SOC (%)"   back to normal
    python -m scripts.set_fake_value --reset-all

A changed value stays put: things that would normally overwrite it (e.g. the
wind calculation, Wunderground) are held back until you reset it. Resetting
restores the original fake value (or whatever a live producer wrote since).
Values are JSON where possible: 15, 12.5, true, null, "text" - anything that
isn't valid JSON (like online) is taken as plain text. Restarting the app
also resets everything.
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys

import requests

from carpediem.config import config

BASE = f"http://127.0.0.1:{config.webserver.port}"
TIMEOUT = 5.0
MAX_CHOICES = 15


def parse_value(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text


def show(value) -> str:
    return "null" if value is None else json.dumps(value) if not isinstance(value, str) else f'"{value}"'


def call(method: str, path: str, **kwargs):
    """Returns (status_code, json_body); exits with a helpful message if the app isn't reachable."""
    try:
        headers = {"X-API-Key": config.webserver.api_key} if config.webserver.api_key else None
        resp = requests.request(method, BASE + path, timeout=TIMEOUT, headers=headers, **kwargs)
    except requests.ConnectionError:
        sys.exit(f"Can't reach the app at {BASE} - is it running (python -m carpediem.main) "
                 f"with CARPEDIEM_USE_WEBSERVER=true, and on the port WEBSERVER_PORT says?")
    try:
        body = resp.json()
    except ValueError:
        body = {"error": resp.text.strip()[:200]}
    return resp.status_code, body


def all_fields() -> dict:
    status, body = call("GET", "/api/data")
    if status == 401:
        sys.exit("The app rejected the API key - it was probably started with a different WEBSERVER_API_KEY; restart it.")
    if status != 200:
        sys.exit(f"GET /api/data failed: HTTP {status}")
    return body


def set_value(label: str, value) -> bool:
    status, body = call("POST", "/api/fake", json={"label": label, "value": value})
    if status == 200:
        print(f"  OK - {label} = {show(value)}   ({body['changed']} field(s) changed - "
              f"'reset {label}' or --reset-all to undo)")
        return True
    print(f"  Refused: {body.get('error', body)}")
    if body.get("suggestions"):
        print("  Did you mean: " + ", ".join(body["suggestions"]))
    return False


def reset(label: str | None) -> None:
    status, body = call("DELETE", "/api/fake", params={"label": label} if label else None)
    if status == 200:
        print(f"  Reset {body['reset']} field(s)" + (f": {label}" if label else ""))
    else:
        print(f"  Refused: {body.get('error', body)}")


def list_changed() -> None:
    status, body = call("GET", "/api/fake")
    if status != 200:
        print(f"  Refused: {body.get('error', body)}")
    elif not body["changed"]:
        print("  Nothing changed yet.")
    else:
        for label, value in sorted(body["changed"].items()):
            print(f"  {label} = {show(value)}")


def find_field(query: str, fields: dict) -> str | None:
    """Exact (case-insensitive) match, else a numbered pick among substring matches."""
    lowered = {name.lower(): name for name in fields}
    if query.lower() in lowered:
        return lowered[query.lower()]
    matches = sorted(name for name in fields if query.lower() in name.lower())
    if not matches:
        close = difflib.get_close_matches(query, list(fields), n=5, cutoff=0.4)
        print("  No field matches '%s'." % query + (("  Close: " + ", ".join(close)) if close else ""))
        return None
    if len(matches) == 1:
        return matches[0]
    shown = matches[:MAX_CHOICES]
    for i, name in enumerate(shown, 1):
        print(f"  {i:2d}) {name} = {show(fields[name])}")
    if len(matches) > len(shown):
        print(f"  ... and {len(matches) - len(shown)} more - type more of the name to narrow it down")
        return None
    choice = input("  pick a number (empty = cancel) > ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(shown):
        return shown[int(choice) - 1]
    return None


def interactive() -> None:
    fields = all_fields()
    print(f"Connected to {BASE} ({len(fields)} fields).")
    print("Type part of a field name to change it.   list = what's changed   "
          "reset <name> | reset all   quit\n")
    while True:
        try:
            line = input("field > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        lowered = line.lower()
        if lowered in ("q", "quit", "exit"):
            return
        if lowered == "list":
            list_changed()
        elif lowered == "reset all":
            reset(None)
        elif lowered.startswith("reset "):
            name = find_field(line[6:].strip(), fields)
            if name:
                reset(name)
        else:
            fields = all_fields()  # fresh values (live producers may have moved them)
            name = find_field(line, fields)
            if not name:
                continue
            raw = input(f"  {name} is now {show(fields[name])}.  New value (empty = cancel) > ").strip()
            if raw:
                set_value(name, parse_value(raw))


def main() -> None:
    parser = argparse.ArgumentParser(description="Change fake data values while the app runs (fake mode only).")
    parser.add_argument("field", nargs="?", help="exact field name, e.g. \"Battery SOC (%%)\"")
    parser.add_argument("value", nargs="?", help='new value: 15, 12.5, true, null, "text"')
    parser.add_argument("--list", action="store_true", help="show the fields you've changed")
    parser.add_argument("--reset", metavar="FIELD", help="put one field back")
    parser.add_argument("--reset-all", action="store_true", help="put every changed field back")
    args = parser.parse_args()

    if args.list:
        list_changed()
    elif args.reset_all:
        reset(None)
    elif args.reset:
        reset(args.reset)
    elif args.field is not None and args.value is not None:
        sys.exit(0 if set_value(args.field, parse_value(args.value)) else 1)
    elif args.field is None:
        interactive()
    else:
        parser.error("give both a field and a value, or neither for interactive mode")


if __name__ == "__main__":
    main()
