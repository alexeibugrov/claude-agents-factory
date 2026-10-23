"""Telegram from the agent's own user account (Telethon, MTProto), in one private group.

Configured like the operator's ``bb-trade-agent`` ``info_agent``: ``TELEGRAM_API_ID`` and
``TELEGRAM_API_HASH`` come from the env file, the login lives in a per-stack Telethon session file
(created once by ``python -m agent.telegram_login``) of a separate agent account, and everything
happens in ``chat_id``, optionally inside a forum topic (``topic_id``).

The agent posts offers (HTML), reads the group with ``fetch_after`` from a stored cursor, and
replies with proposals in plain text. A new-message event (``on_reply``) only wakes that read, so a
reply is picked up at once, while the cursor stays the single path that handles messages: a dropped
update stream or a restart misses nothing, and nothing is handled twice. The session file
grants full access to the agent account; it is never logged, and Telethon's logger stays at WARNING.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any, Protocol

from agent.config import TelegramConfig

logger = logging.getLogger(__name__)
logging.getLogger("telethon").setLevel(logging.WARNING)


@dataclass(frozen=True)
class Incoming:
    """A group message as the poller sees it. ``own`` marks the agent's own messages."""

    id: int
    sender_id: int | None
    reply_to: int | None
    text: str
    own: bool


class Chat(Protocol):
    chat_id: str

    async def post(self, html_text: str) -> int: ...

    async def reply(self, to_id: int, texts: list[str]) -> list[int]: ...

    async def latest_id(self) -> int: ...

    async def fetch_after(self, min_id: int, limit: int) -> list[Incoming]: ...


class FloodWait(Exception):
    """Telegram asked us to back off; sending stops until the next cycle or poll."""


class TelethonChat:
    """The agent account's connection to the group. ``start`` once; every call reconnects if needed."""

    def __init__(self, cfg: TelegramConfig) -> None:
        self.cfg = cfg
        self.chat_id = str(cfg.chat_id)
        self.client: Any = None
        self.entity: Any = None
        self.me_id: int | None = None

    async def start(self) -> "TelethonChat":
        from telethon import TelegramClient

        self.client = TelegramClient(
            self.cfg.session_path, int(os.environ["TELEGRAM_API_ID"]), os.environ["TELEGRAM_API_HASH"]
        )
        await self.client.connect()
        if not await self.client.is_user_authorized():
            await self.client.disconnect()
            raise RuntimeError(
                f"Telegram session at {self.cfg.session_path} is not logged in; run python -m agent.telegram_login"
            )
        me = await self.client.get_me()
        self.me_id = getattr(me, "id", None)
        # A fresh session has an empty entity cache: without the dialog list, Telethon has no
        # access_hash for the group and get_entity fails.
        await self.client.get_dialogs()
        try:
            self.entity = await self.client.get_entity(self.cfg.chat_id)
        except Exception as exc:  # noqa: BLE001 — re-raised with the fix attached
            raise RuntimeError(
                f"telegram.chat_id {self.cfg.chat_id} not found ({exc}). Add the agent account to the group;"
                " a supergroup id starts with -100, a basic group id does not."
            ) from exc
        logger.info("telegram ready: agent account %s in chat %s", self.me_id, self.chat_id)
        return self

    async def close(self) -> None:
        if self.client is not None:
            await self.client.disconnect()

    async def _connected(self) -> None:
        if not self.client.is_connected():
            await self.client.connect()

    async def post(self, html_text: str) -> int:
        from telethon.errors import FloodWaitError

        await self._connected()
        try:
            msg = await self.client.send_message(
                self.entity, html_text, parse_mode="html", link_preview=False, reply_to=self.cfg.topic_id
            )
        except FloodWaitError as exc:
            raise FloodWait(f"flood wait {exc.seconds}s") from exc
        await asyncio.sleep(self.cfg.send_interval_s)
        return msg.id

    async def reply(self, to_id: int, texts: list[str]) -> list[int]:
        """Plain text (no parse mode), so the proposal is copied exactly as written."""
        from telethon.errors import FloodWaitError

        await self._connected()
        ids: list[int] = []
        try:
            for text in texts:
                msg = await self.client.send_message(
                    self.entity, text, parse_mode=None, link_preview=False, reply_to=to_id
                )
                ids.append(msg.id)
                await asyncio.sleep(self.cfg.send_interval_s)
        except FloodWaitError as exc:
            raise FloodWait(f"flood wait {exc.seconds}s") from exc
        return ids

    def on_reply(self, wake: Callable[[], None]) -> None:
        """Call ``wake`` when a member replies to a message in the group. It only signals the poll;
        the message itself is read through the cursor like any other."""
        from telethon import events

        async def handler(event: Any) -> None:
            if event.message.reply_to_msg_id is not None:
                wake()

        self.client.add_event_handler(handler, events.NewMessage(chats=self.entity, incoming=True))

    async def latest_id(self) -> int:
        await self._connected()
        messages = await self.client.get_messages(self.entity, limit=1)
        return messages[0].id if messages else 0

    async def fetch_after(self, min_id: int, limit: int) -> list[Incoming]:
        """Messages newer than ``min_id``, oldest first."""
        await self._connected()
        messages = await self.client.get_messages(self.entity, min_id=min_id, limit=limit, reverse=True)
        return [
            Incoming(
                id=m.id,
                sender_id=m.sender_id,
                reply_to=m.reply_to_msg_id,
                text=m.message or "",
                own=bool(m.out) or (self.me_id is not None and m.sender_id == self.me_id),
            )
            for m in messages
        ]
