"""Telegram notifier for runtime activity + errors — routed to the TECH chat.

Two separate Telegram audiences:
  - Shop owner (chat id on shops.telegram_chat_id) — interactive approval UI
    for stamp requests, ForceReply amount entry, password reset approvals.
  - Tech operator (settings.tech_telegram_chat_id) — informational feed only.
    Receives every signup, scan, sale, decline, plus boot events and errors.

Failures are swallowed (logged) — notifications must never break a request.
"""

import asyncio
import logging
import traceback
from typing import Any, Optional

from .config import settings
from .timeutil import now_ist

log = logging.getLogger("sikok.notify")


async def _send(text: str) -> None:
    # Local import — avoids a circular dep with telegram_bot at module load.
    from . import telegram_bot

    app = telegram_bot._app  # noqa: SLF001
    if app is None:
        log.info("notify (bot offline): %s", text)
        return

    chat_id = settings.tech_telegram_chat_id
    if not chat_id:
        log.info("notify (no tech chat_id): %s", text)
        return

    try:
        await app.bot.send_message(chat_id=chat_id, text=text, disable_notification=True)
    except Exception:  # noqa: BLE001
        log.exception("Failed to send tech Telegram notification")


def _ts() -> str:
    return now_ist().strftime("%d %b %H:%M IST")


# ---------------------------------------------------------------------------
# Public helpers — call from anywhere.
# `shop_id` is accepted for context but no longer affects routing.
# ---------------------------------------------------------------------------


def fire(text: str, shop_id: Optional[int] = None) -> None:
    """Fire-and-forget: schedules `_send` on the running loop, no await needed."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_send(text))


def notify_run(event: str, detail: str = "", shop_id: Optional[int] = None) -> None:
    msg = f"📈 {event}  ·  {_ts()}"
    if detail:
        msg += f"\n{detail}"
    fire(msg)


def notify_error(where: str, exc: BaseException, shop_id: Optional[int] = None) -> None:
    tb = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    msg = f"❌ Error in {where}  ·  {_ts()}\n{tb}"
    fire(msg[:3500])


def notify_boot(version: str = "1.0") -> None:
    notify_run("Sikok backend started", f"version {version}")
