"""Occasional build step: downloads Rijkswaterstaat's complete bridge list
(~7000 bridges) into carpediem/data/vaarweg_bridges.json, which
vaarweg_client.py loads at runtime.

Why: the public BGV `bridge` bounding-box endpoint only lists ~400 bridges
(those with a live status feed), so small, phone-operated ones like
Pier-Christiaanbrug (Echtenerbrug) are never found by it. The same
Rijkswaterstaat site that shows them on vaarweginformatie.nl serves the
full list from an undocumented endpoint used by its own web frontend
(https://vaarweginformatie.nl/frp/api/geo/all?types=BRIDGE, ~1.5 MB).
That's too heavy (and too unofficial) to fetch at runtime over a boat's
metered connection, so it's extracted once into a compact static file
instead, same idea as build_vaarweg_contacts.py. ISRS codes are the same
ones the BGV details endpoint accepts, so live status still works.

Usage: python -m scripts.build_vaarweg_bridges
Re-run every few months (new/renamed bridges are rare).
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

URL = "https://vaarweginformatie.nl/frp/api/geo/all?types=BRIDGE"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "carpediem" / "data" / "vaarweg_bridges.json"


def main() -> None:
    req = urllib.request.Request(URL, headers={"User-Agent": "CarpeDiem/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        items = json.load(resp)

    bridges = []
    for it in items:
        coords = (it.get("geo") or {}).get("coord") or []
        if it.get("geoType") != "BRIDGE" or not it.get("isrs") or not coords:
            continue
        bridges.append([it["isrs"], it.get("name") or it["isrs"],
                        round(coords[0]["lat"], 6), round(coords[0]["lon"], 6)])
    bridges.sort()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(bridges, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(bridges)} bridges to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
