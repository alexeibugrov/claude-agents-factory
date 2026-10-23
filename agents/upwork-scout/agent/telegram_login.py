"""One-off interactive Telegram login that creates this stack's Telethon session file.

Run by the OPERATOR only — it asks for the phone number, the login code, and the 2FA password if
one is set. Same flow as ``bb-trade-agent/deploy/sdk-session-setup/generate_session.py``, but it
ships inside the image, because CI copies only the compose file and the config to the VM.

On the VM (session lands in the bind-mounted ./telegram-session directory)::

    cd /app/upwork-scout && docker compose run --rm -it agent python -m agent.telegram_login

Locally (a separate session — never reuse the VM's)::

    TELEGRAM_SESSION_PATH=./telegram-session/upwork_scout_local uv run python -m agent.telegram_login

Reads TELEGRAM_API_ID / TELEGRAM_API_HASH from the environment.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from telethon import TelegramClient

from agent.config import AgentConfig


async def _login() -> int:
    session_path = AgentConfig.load().telegram.session_path
    api_id, api_hash = os.environ.get("TELEGRAM_API_ID"), os.environ.get("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        print("TELEGRAM_API_ID and TELEGRAM_API_HASH must be set (from my.telegram.org).", file=sys.stderr)
        return 1
    Path(session_path).parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(session_path, int(api_id), api_hash)
    await client.start()  # pyright: ignore[reportGeneralTypeIssues] — interactive: phone, code, 2FA
    me = await client.get_me()
    print(f"Logged in as {getattr(me, 'username', None) or getattr(me, 'id', '?')}; session: {session_path}.session")
    await client.disconnect()  # pyright: ignore[reportGeneralTypeIssues]
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_login()))
