"""CarpeDiem - boat data collection & display app (Raspberry Pi port).

Ported from the ESP32-S3 Arduino sketch CarpeDiem_v4_5. See README.md for
the module map and the history of what changed in the port.
"""

import subprocess

def _get_version():
    try:
        return subprocess.check_output(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=__file__.rsplit("/", 1)[0],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"

__version__ = _get_version()
