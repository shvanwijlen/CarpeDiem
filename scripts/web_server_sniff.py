"""Throwaway diagnostic: polls this Pi's own web_server.py (GET
/api/data) and prints every field back, so you can confirm the data API
itself works - the app (carpediem/main.py, CARPEDIEM_USE_WEBSERVER=true,
the default) needs to already be running - before pointing an Arduino or
the iPhone app at it.

Run on the Pi:
    python -m scripts.web_server_sniff

Ctrl+C to stop.
"""
from __future__ import annotations

import time

import requests

from carpediem.config import config

_HOST = "127.0.0.1"  # the Pi itself - WEBSERVER_HOST (0.0.0.0 by default) isn't a connectable target
_POLL_INTERVAL_SECONDS = 5.0
_REQUEST_TIMEOUT_SECONDS = 5.0

url = f"http://{_HOST}:{config.webserver.port}/api/data"
print(f"Polling {url} every {_POLL_INTERVAL_SECONDS:.0f}s - Ctrl+C to stop")

try:
    while True:
        try:
            resp = requests.get(url, timeout=_REQUEST_TIMEOUT_SECONDS,
                                headers={"X-API-Key": config.webserver.api_key} if config.webserver.api_key else None)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            print(f"request failed: {exc}")
        else:
            print(f"\n{len(data)} fields:")
            for label in sorted(data):
                print(f"  {label}: {data[label]}")
        time.sleep(_POLL_INTERVAL_SECONDS)
except KeyboardInterrupt:
    pass
