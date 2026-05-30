"""Lightweight Telegram notifier for runtime activity + errors.

Routes messages to the same shop owner chat used for stamp approvals.
Failures are swallowed (logged) — notifications must never break a request.
"""

import asyncio
import logging
import traceback
from typing import Optional

from sqlalchemy import select

from .config import settings
from .database import SessionLocal
from .models import Shop
from .timeutil import now_ist

log = logging.getLogger("sikok.notify")


async def _owner_chat_id(shop_id: int) -> Optional[str]:
    async with SessionLocal() as db:
        shop = await db.scalar(select(Shop).where(Shop.shop_id == shop_id))
        return shop.telegram_chat_id if shop else None


async def _send(text: str, shop_id: Optional[int] = None) -> None:
    # Local import — avoids a circular dep with telegram_bot at module load.
    from . import telegram_bot

    app = telegram_bot._app  # noqa: SLF001
    if app is None:
        log.info("notify (bot offline): %s", text)
        return

    chat_id = await _owner_chat_id(shop_id or settings.default_shop_id)
    if not chat_id or chat_id.startswith("REPLACE"):
        log.info("notify (no chat_id): %s", text)
        return

    try:
        await app.bot.send_message(chat_id=chat_id, text=text, disable_notification=True)
    except Exception:  # noqa: BLE001
        log.exception("Failed to send Telegram notification")


def _ts() -> str:
    return now_ist().strftime("%d %b %H:%M IST")


# ---------------------------------------------------------------------------
# Public helpers — call from anywhere.
# ---------------------------------------------------------------------------


def fire(text: str, shop_id: Optional[int] = None) -> None:
    """Fire-and-forget: schedules `_send` on the running loop, no await needed."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_send(text, shop_id))


def notify_run(event: str, detail: str = "", shop_id: Optional[int] = None) -> None:
    msg = f"📈 {event}  ·  {_ts()}"
    if detail:
        msg += f"\n{detail}"
    fire(msg, shop_id)


def notify_error(where: str, exc: BaseException, shop_id: Optional[int] = None) -> None:
    tb = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    msg = f"❌ Error in {where}  ·  {_ts()}\n{tb}"
    fire(msg[:3500], shop_id)


def notify_boot(version: str = "1.0") -> None:
    notify_run("Sikok backend started", f"version {version}")
