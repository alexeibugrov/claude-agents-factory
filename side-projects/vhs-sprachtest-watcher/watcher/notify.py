"""Telegram delivery from the operator's own account via a Telethon user session."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from telethon import TelegramClient

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelegramConfig:
    api_id: int
    api_hash: str
    chat: str
    session_path: Path


def _chat_entity(chat: str) -> int | str:
    # Numeric IDs (-100… for supergroups) must be ints; usernames and invite links stay strings.
    try:
        return int(chat)
    except ValueError:
        return chat


def _client(cfg: TelegramConfig) -> TelegramClient:
    # Telethon appends ".session" itself.
    return TelegramClient(str(cfg.session_path.with_suffix("")), cfg.api_id, cfg.api_hash)


async def _send(cfg: TelegramConfig, text: str) -> None:
    client = _client(cfg)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError(
                f"Telegram session {cfg.session_path} is not logged in — run `python -m watcher login`"
            )
        # A user session only resolves a numeric group ID it has already seen in its dialogs.
        await client.get_dialogs(limit=None)
        await client.send_message(_chat_entity(cfg.chat), text, link_preview=False)
    finally:
        await client.disconnect()  # pyright: ignore[reportGeneralTypeIssues]  # Telethon types it sync; it is a coroutine here


def send(cfg: TelegramConfig, text: str) -> None:
    asyncio.run(_send(cfg, text))
    log.info("telegram message sent to %s", cfg.chat)


async def _login(cfg: TelegramConfig) -> None:
    client = _client(cfg)
    # Prompts for phone, code, and 2FA password on the TTY.
    await client.start()  # pyright: ignore[reportGeneralTypeIssues]  # Telethon types it sync; it is a coroutine here
    try:
        me = await client.get_me()
        who = getattr(me, "username", None) or getattr(me, "first_name", "unknown")
        print(f"\nLogged in as {who} → {cfg.session_path}")
        print("\nYour groups and channels (put the ID of the target group in TELEGRAM_CHAT):\n")
        async for dialog in client.iter_dialogs():
            if dialog.is_group or dialog.is_channel:
                print(f"  {dialog.id:>16}  {dialog.name}")
    finally:
        await client.disconnect()  # pyright: ignore[reportGeneralTypeIssues]  # Telethon types it sync; it is a coroutine here


def login(cfg: TelegramConfig) -> None:
    asyncio.run(_login(cfg))
