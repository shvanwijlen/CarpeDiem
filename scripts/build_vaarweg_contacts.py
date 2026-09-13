"""One-time (well, occasional) build step: extracts VHF channel / phone
number per bridge and lock from Rijkswaterstaat's "Bedieningstijden van
sluizen en bruggen" PDF into carpediem/data/vaarweg_contacts.json, which
vaarweg_client.py loads at runtime.

Why this is a separate offline step instead of a live lookup: unlike
bridge/lock position and status (ring the live BGV API, see
vaarweg_client.py), VHF channel and phone number aren't in that API at
all - Rijkswaterstaat only publishes them in this PDF, updated every few
months. Re-parsing a >100k-line PDF text dump on every poll (or even
every app start) would be wasteful for data that essentially never
changes, so it's extracted once here into a small JSON file that ships
in the repo, and only needs re-running when you download a newer PDF.

Usage (from a dev machine, not the Pi - needs poppler's pdftotext, which
this doesn't try to vendor or require at app runtime):

    python -m scripts.build_vaarweg_contacts "path/to/bedientijden.pdf"

Download the current PDF from https://www.vaarweginformatie.nl/frp/page/downloads
("Bedieningstijden van sluizen en bruggen").

Parsing approach: the PDF's text layout (via `pdftotext -layout`) prints
each object as a name/route-code header line, e.g. "Zijlbrug (13.2)",
immediately followed by "marifoonkanaal: <channel>" and
"telefoonnummer: <number>" lines (either can read "[onbekend]" - unknown
- which is treated as "not published", not stored). Page-footer lines
("Rijkswaterstaat CIV, bron: FIS-VNDS, ...") are stripped first since
they sometimes land in the middle of an entry, splitting fields that
belong together onto non-adjacent lines otherwise.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "carpediem" / "data" / "vaarweg_contacts.json"

_NAME_RE = re.compile(r"^([^\s].{2,80}?)\s+\(([0-9]+[a-z]?(?:\.[0-9]+[a-z]?)?)\)\s*(.*)$")
_VHF_RE = re.compile(r"marifoonkanaal:\s*(\S+)")
_TEL_RE = re.compile(r"telefoonnummer:\s*(\S+)")
_UNKNOWN = "[onbekend]"


def _clean(value: str | None) -> str | None:
    if value is None or value == _UNKNOWN:
        return None
    # The PDF's phone numbers sometimes contain a soft hyphen (U+00AD, a
    # line-wrap hint invisible in most viewers) instead of a plain "-" -
    # normalize it so it actually renders on the touchscreen.
    return value.replace("­", "-")


def parse(pdf_path: Path) -> dict[str, dict[str, str]]:
    result = subprocess.run(
        ["pdftotext", "-layout", "-enc", "Latin1", str(pdf_path), "-"],
        capture_output=True, check=True,
    )
    lines = result.stdout.decode("latin-1").splitlines()
    lines = [ln for ln in lines
             if "Rijkswaterstaat CIV, bron:" not in ln and not ln.strip().startswith("Bedieningstijden van")]

    entries: dict[str, dict[str, str]] = {}
    name: str | None = None
    vhf: str | None = None
    tel: str | None = None

    def flush() -> None:
        if name and (vhf or tel):
            data = {}
            if vhf:
                data["vhf"] = vhf
            if tel:
                data["phone"] = tel
            entries.setdefault(name, data)
            # Bridges with an alternate name in parentheses, e.g.
            # "Truitjezijlbrug (Blokjesbrug)", are also indexed under just
            # the primary part - the live BGV API's `name` field usually
            # only uses one of the two, and we can't know which up front.
            alt_match = re.match(r"^(.+?)\s+\(.+\)$", name)
            if alt_match:
                entries.setdefault(alt_match.group(1).strip(), data)

    for line in lines:
        m = _NAME_RE.match(line)
        if m and "marifoonkanaal" not in line and "telefoonnummer" not in line:
            flush()
            name, vhf, tel = m.group(1).strip(), None, None
            continue
        m = _VHF_RE.search(line)
        if m:
            vhf = _clean(m.group(1))
        m = _TEL_RE.search(line)
        if m:
            tel = _clean(m.group(1))
    flush()
    return entries


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.build_vaarweg_contacts <path to bedientijden PDF>")
        raise SystemExit(1)
    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        print(f"No such file: {pdf_path}")
        raise SystemExit(1)

    entries = parse(pdf_path)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(f"Wrote {len(entries)} entries to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
