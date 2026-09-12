"""Diagnostic: list every device on the Ring account and dump the
attributes ring_client.py cares about (plus a few extra for context).

Run this after scripts/ring_auth_setup.py has cached a token (this script
only reads that cached token, same as RingClient - it never prompts for a
password/2FA):

    python -m scripts.ring_list_devices

Useful for confirming a newly added camera actually shows up under the
account, and for checking what a non-battery (wired) camera reports for
battery_life (expected: None) vs a battery-powered one.
"""
from __future__ import annotations

import asyncio
import json

import aiohttp
from ring_doorbell import Auth, Ring

from carpediem.config import config

USER_AGENT = "CarpeDiem/1.0"


async def main() -> None:
    if not config.ring.token_file.exists():
        print(f"No cached token at {config.ring.token_file} - run scripts/ring_auth_setup.py first.")
        return

    token = json.loads(config.ring.token_file.read_text())

    async with aiohttp.ClientSession() as session:
        auth = Auth(USER_AGENT, token, lambda new_token: config.ring.token_file.write_text(json.dumps(new_token)),
                    http_client_session=session)
        ring = Ring(auth)
        await ring.async_create_session()
        await ring.async_update_data()

        known_names = set(config.ring.camera_field_map)
        devices = ring.devices().all_devices
        print(f"{len(devices)} device(s) on the account:\n")
        for dev in devices:
            in_config = "yes" if dev.name in known_names else "NOT in camera_field_map"
            print(f"- {dev.name!r} ({in_config})")
            print(f"    family:            {dev.family}")
            print(f"    kind:              {dev.kind}")
            print(f"    model:             {dev.model}")
            print(f"    device_id:         {dev.device_id}")
            # Chimes don't implement battery_life (raises NotImplementedError)
            # or connection_status (not defined at all - falls through to
            # RingGeneric.__getattr__, which raises AttributeError) - guard
            # both so one chime on the account doesn't abort the listing.
            for attr in ("battery_life", "connection_status"):
                try:
                    print(f"    {attr}:{' ' * (18 - len(attr))}{getattr(dev, attr)}")
                except (NotImplementedError, AttributeError):
                    print(f"    {attr}:{' ' * (18 - len(attr))}<not supported by this device type>")
            print()


if __name__ == "__main__":
    asyncio.run(main())
