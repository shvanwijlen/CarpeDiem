"""One-time interactive Ring OAuth handshake.

RingClient (carpediem/ring_client.py) runs unattended and can only use a
cached refresh token - it can't prompt for a password or a 2FA code. Run
this script once, by hand, from a terminal to do that handshake:

    python -m scripts.ring_auth_setup

It asks for your Ring username/password (or reads RING_USERNAME/
RING_PASSWORD from .env if set) and, if Ring requires it, a 2FA code sent
to your account. The resulting token is cached to config.ring.token_file
(default ./ring_token.cache, see .env.example) - re-run this script if
that file is ever deleted or Ring revokes the token.
"""
from __future__ import annotations

import asyncio
import getpass
import json

import aiohttp
from ring_doorbell import Auth
from ring_doorbell.exceptions import Requires2FAError

from carpediem.config import config

USER_AGENT = "CarpeDiem/1.0"


async def main() -> None:
    username = config.ring.username or input("Ring username/email: ")
    password = config.ring.password or getpass.getpass("Ring password: ")

    def token_updater(token: dict) -> None:
        config.ring.token_file.write_text(json.dumps(token))

    async with aiohttp.ClientSession() as session:
        auth = Auth(USER_AGENT, None, token_updater, http_client_session=session)
        try:
            await auth.async_fetch_token(username, password)
        except Requires2FAError:
            code = input("2FA code sent to your Ring account: ")
            await auth.async_fetch_token(username, password, code)

    print(f"Ring token cached to {config.ring.token_file}")


if __name__ == "__main__":
    asyncio.run(main())
