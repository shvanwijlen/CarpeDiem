"""Keeps the iPhone app's version in step with the Raspberry Pi app's.

The Pi app's version is `git describe --tags` (carpediem/__init__.py), so a git
tag like v1.2.0 IS the version. Apple needs a plain x.y.z, so the iPhone app's
`version` in mobile/app.json is set to the latest tag, without the "v"
(EAS manages the build number itself - see mobile/eas.json).

Release flow:
    python scripts/sync_version.py 1.2.0      # writes mobile/app.json
    git commit -am "Release 1.2.0" && git tag v1.2.0 && git push --tags
    (Pi: git pull --tags   ->  the log says "version v1.2.0")
    cd mobile && npm run release:ios          # refuses to build if the two disagree

    python scripts/sync_version.py            # set app.json from the latest tag
    python scripts/sync_version.py --check    # exit 1 if app.json differs from the latest tag
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JSON = ROOT / "mobile" / "app.json"
VERSION_LINE = re.compile(r'("version"\s*:\s*")([^"]*)(")')  # the first one in app.json is expo.version
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def latest_tag_version() -> str:
    """Same lookup as the Pi app's `git describe`: the newest tag reachable from HEAD."""
    try:
        tag = subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*"],
            cwd=ROOT, stderr=subprocess.PIPE, text=True).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        sys.exit("No version tag (like v1.2.0) found. Create one with: git tag v1.2.0")
    m = re.match(r"^v(\d+\.\d+\.\d+)$", tag)
    if not m:
        sys.exit(f"Latest tag '{tag}' isn't of the form vX.Y.Z, which Apple requires for the app version.")
    return m.group(1)


def app_json_version() -> str:
    m = VERSION_LINE.search(APP_JSON.read_text(encoding="utf-8"))
    if not m:
        sys.exit(f'No "version" found in {APP_JSON}')
    return m.group(2)


def write_app_json_version(version: str) -> None:
    # Edit the text in place rather than round-tripping through json, so app.json's formatting and line endings stay untouched.
    raw = APP_JSON.read_bytes().decode("utf-8")
    APP_JSON.write_bytes(VERSION_LINE.sub(lambda m: m.group(1) + version + m.group(3), raw, count=1).encode("utf-8"))


def main(argv: list[str]) -> int:
    check = "--check" in argv
    explicit = [a for a in argv if not a.startswith("--")]
    if explicit and not SEMVER.match(explicit[0]):
        sys.exit(f"'{explicit[0]}' isn't a version like 1.2.0")

    current = app_json_version()
    if check:
        wanted = latest_tag_version()
        if current == wanted:
            print(f"OK: iPhone app and latest tag are both {current}")
            return 0
        print(f"MISMATCH: mobile/app.json says {current}, the latest tag is v{wanted}.\n"
              f"  If {current} is the release you're about to make: commit, then  git tag v{current}\n"
              f"  Otherwise put app.json back in step with the tag:  python scripts/sync_version.py {wanted}")
        return 1

    wanted = explicit[0] if explicit else latest_tag_version()
    if wanted == current:
        print(f"mobile/app.json already at {current}")
    else:
        write_app_json_version(wanted)
        print(f"mobile/app.json: {current} -> {wanted}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
