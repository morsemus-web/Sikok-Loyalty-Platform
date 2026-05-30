import asyncio
import logging
import secrets
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import select
from telegram import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden, NetworkError, TelegramError, TimedOut
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .auth import hash_password
from .config import settings
from .database import SessionLocal
from .models import LoyaltyCard, Shop, Transaction, User
from .notify import notify_error, notify_run
from .pending import pending_store
from .sockets import emit_approved, emit_declined, emit_password_reset

log = logging.getLogger("sikok.bot")

_app: Optional[Application] = None


def _approval_keyboard(pending_id: str, reward_visit: bool) -> InlineKeyboardMarkup:
    approve_label = "🎁 Approve REWARD Sale" if reward_visit else "✅ Approve & Log Sale"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(approve_label, callback_data=f"approve:{pending_id}"),
                InlineKeyboardButton("🚫 Disregard", callback_data=f"decline:{pending_id}"),
            ]
        ]
    )


def _reset_keyboard(pending_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Approve Reset", callback_data=f"reset_ok:{pending_id}"),
                InlineKeyboardButton("🚫 Disregard", callback_data=f"reset_no:{pending_id}"),
            ]
        ]
    )


def _confirm_keyboard(pending_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Yes, log it", callback_data=f"confirm:{pending_id}"),
                InlineKeyboardButton("✏️ Re-enter", callback_data=f"reenter:{pending_id}"),
            ]
        ]
    )


# Per-shop sanity bounds. The owner can override by tapping "Yes, log it"
# on the confirm step, but typos like ₹25000 instead of ₹2500 will at least
# get a visible "are you sure" before being committed.
AMOUNT_MIN = Decimal("10")
AMOUNT_MAX = Decimal("100000")


async def _owner_chat_id_for_shop(shop_id: int) -> Optional[str]:
    async with SessionLocal() as db:
        shop = await db.scalar(select(Shop).where(Shop.shop_id == shop_id))
        return shop.telegram_chat_id if shop else None


# ---------------------------------------------------------------------------
# Resilient send: retries network/timeout errors with exponential backoff,
# gives up immediately on BadRequest / Forbidden (chat not found, bot blocked).
# ---------------------------------------------------------------------------

_RETRY_DELAYS = (0.5, 1.5, 3.0)


async def send_with_retry(**kwargs: Any) -> None:
    if _app is None:
        return
    last_err: Optional[BaseException] = None
    for attempt, delay in enumerate((0.0, *_RETRY_DELAYS)):
        if delay:
            await asyncio.sleep(delay)
        try:
            await _app.bot.send_message(**kwargs)
            return
        except (BadRequest, Forbidden) as e:
            # Won't fix on retry — chat doesn't exist or user blocked the bot.
            log.warning("Telegram send not retryable (%s): %s", type(e).__name__, e)
            return
        except (NetworkError, TimedOut) as e:
            last_err = e
            log.warning("Telegram send transient failure (attempt %d): %s", attempt + 1, e)
        except TelegramError as e:
            last_err = e
            log.warning("Telegram send error (attempt %d): %s", attempt + 1, e)
    log.error("Telegram send exhausted retries: %s", last_err)


async def bot_send_stamp_request(
    *, shop_id: int, pending_id: str, name: str, mobile: str, current_stamps: int
) -> None:
    if _app is None:
        log.warning("Telegram bot not initialised; skipping send")
        return
    chat_id = await _owner_chat_id_for_shop(shop_id)
    if not chat_id:
        return

    reward_visit = current_stamps >= (settings.stamps_to_reward - 1)
    if reward_visit:
        text = (
            f"🚨 REWARD UNLOCKED: {name} is on Visit "
            f"{settings.stamps_to_reward}/{settings.stamps_to_reward}!\n"
            f"Apply ₹{settings.discount_per_item} off PER CLOTHING ITEM.\n"
            f"Mobile: {mobile}"
        )
    else:
        text = (
            f"Stamp Request: {name}\n"
            f"Mobile: {mobile}\n"
            f"Stamps: {current_stamps}/{settings.stamps_to_reward}"
        )

    await send_with_retry(
        chat_id=chat_id,
        text=text,
        reply_markup=_approval_keyboard(pending_id, reward_visit),
    )


async def bot_send_password_reset(*, shop_id: int, pending_id: str, name: str, mobile: str) -> None:
    if _app is None:
        return
    chat_id = await _owner_chat_id_for_shop(shop_id)
    if not chat_id:
        return
    await send_with_retry(
        chat_id=chat_id,
        text=f"Password Reset Request: {name} — {mobile}. Approve?",
        reply_markup=_reset_keyboard(pending_id),
    )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def _on_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"Sikok bot online.\nYour chat_id is: {update.effective_chat.id}\n"
        "Put this in the shops.telegram_chat_id column.\n\n"
        "Commands:\n"
        "  /start  — show this message\n"
        "  /status — runtime health check"
    )


async def _on_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from .timeutil import now_ist

    text = f"✅ Sikok backend alive · {now_ist().strftime('%d %b %Y, %I:%M %p IST')}"
    await update.message.reply_text(text)


async def _on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if ":" not in data:
        return
    action, pending_id = data.split(":", 1)
    req = pending_store.get(pending_id)
    if req is None:
        await query.edit_message_text(query.message.text + "\n\n(Already handled or expired.)")
        return

    chat_id = str(update.effective_chat.id)

    if action == "decline":
        pending_store.pop(pending_id)
        await query.edit_message_text(query.message.text + "\n\n🚫 Disregarded.")
        await emit_declined(req.socket_room, {"reason": "Declined by Counter"})
        notify_run("Stamp request declined", f"user_id={req.user_id}")
        return

    if action == "reset_no":
        pending_store.pop(pending_id)
        await query.edit_message_text(query.message.text + "\n\n🚫 Disregarded.")
        await emit_declined(req.socket_room, {"reason": "Reset declined"})
        notify_run("Password reset declined", f"user_id={req.user_id}")
        return

    if action == "approve":
        prompt = await ctx.bot.send_message(
            chat_id=chat_id,
            text="Enter total sale amount:",
            reply_markup=ForceReply(selective=True),
        )
        pending_store.mark_awaiting_amount(pending_id, chat_id, prompt.message_id)
        await query.edit_message_text(query.message.text + "\n\n⏳ Awaiting amount…")
        return

    if action == "reenter":
        # Owner spotted a typo — re-prompt for the amount.
        prompt = await ctx.bot.send_message(
            chat_id=chat_id,
            text="Re-enter total sale amount:",
            reply_markup=ForceReply(selective=True),
        )
        pending_store.mark_awaiting_amount(pending_id, chat_id, prompt.message_id)
        await query.edit_message_text(query.message.text + "\n\n✏️ Awaiting new amount…")
        return

    if action == "confirm":
        amount_str = req.extra.get("amount")
        if not amount_str:
            await query.edit_message_text(query.message.text + "\n\n⚠️ Lost the amount, please re-enter.")
            return
        amount = Decimal(amount_str)
        try:
            new_stamps, is_reward = await _commit_sale(req, chat_id, amount)
        except Exception as e:  # noqa: BLE001
            log.exception("Failed to commit sale")
            notify_error("commit_sale", e)
            await query.edit_message_text(query.message.text + "\n\n❌ Save failed. Try again.")
            return

        pending_store.pop(req.pending_id)
        pending_store.clear_owner_waiting(chat_id)

        await query.edit_message_text(
            query.message.text
            + f"\n\n✅ Logged ₹{amount}"
            + (" (discount applied, card reset)" if is_reward else "")
            + f"\nNew stamp count: {new_stamps}/{settings.stamps_to_reward}"
        )
        await emit_approved(
            req.socket_room,
            {
                "current_stamps": new_stamps,
                "sale_amount": str(amount),
                "discount_applied": is_reward,
            },
        )
        if is_reward:
            notify_run("🎁 Reward redeemed", f"₹{amount} · user_id={req.user_id}")
        else:
            notify_run(
                "Stamp logged",
                f"₹{amount} · stamps {new_stamps}/{settings.stamps_to_reward} · user_id={req.user_id}",
            )
        return

    if action == "reset_ok":
        pin = f"{secrets.randbelow(10000):04d}"
        async with SessionLocal() as db:
            user = await db.scalar(select(User).where(User.user_id == req.user_id))
            if user is None:
                pending_store.pop(pending_id)
                await query.edit_message_text(query.message.text + "\n\n⚠️ User not found.")
                return
            user.password_hash = hash_password(pin)
            await db.commit()
            user_name = user.name
        pending_store.pop(pending_id)
        await query.edit_message_text(
            query.message.text + f"\n\n✅ Temporary PIN: *{pin}*\nRead this to the customer.",
            parse_mode="Markdown",
        )
        await emit_password_reset(req.socket_room, {"ok": True})
        notify_run("Password reset issued", f"{user_name}")
        return


async def _on_reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner typed an amount in response to ForceReply — parse + ask to confirm."""
    msg = update.message
    if msg is None or msg.reply_to_message is None:
        return
    chat_id = str(update.effective_chat.id)
    req = pending_store.pending_for_owner(chat_id)
    if req is None or not req.awaiting_amount:
        return
    if req.telegram_message_id != msg.reply_to_message.message_id:
        return

    raw = (msg.text or "").strip().replace(",", "").replace("₹", "").replace("rs", "").replace("Rs", "")
    try:
        amount = Decimal(raw)
        if amount <= 0:
            raise InvalidOperation
    except InvalidOperation:
        await msg.reply_text("That doesn't look like a number. Reply with just the amount, e.g. 2500.")
        return

    # Stash the parsed amount on the pending request for the confirm step.
    req.extra["amount"] = str(amount)

    warning = ""
    if amount < AMOUNT_MIN or amount > AMOUNT_MAX:
        warning = f"\n⚠️ ₹{amount} is outside the usual range (₹{AMOUNT_MIN}–₹{AMOUNT_MAX}). Double-check."

    await msg.reply_text(
        f"Confirm sale amount: *₹{amount}*?{warning}",
        reply_markup=_confirm_keyboard(req.pending_id),
        parse_mode="Markdown",
    )


async def _commit_sale(req, chat_id: str, amount: Decimal) -> tuple[int, bool]:
    """Apply the sale + stamp/reset to the database. Returns (new_stamps, is_reward)."""
    from sqlalchemy import func as sa_func

    async with SessionLocal() as db:
        card = await db.scalar(
            select(LoyaltyCard).where(
                LoyaltyCard.user_id == req.user_id, LoyaltyCard.shop_id == req.shop_id
            )
        )
        if card is None:
            card = LoyaltyCard(user_id=req.user_id, shop_id=req.shop_id, current_stamps=0)
            db.add(card)
            await db.flush()

        is_reward = card.current_stamps >= (settings.stamps_to_reward - 1)

        db.add(Transaction(card_id=card.card_id, sale_amount=amount, discount_applied=is_reward))

        if is_reward:
            card.current_stamps = 0
        else:
            card.current_stamps += 1
        card.last_visit = sa_func.now()
        await db.commit()
        await db.refresh(card)
        return card.current_stamps, is_reward


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


async def start_bot() -> None:
    """Build and start the Telegram bot in polling mode as a background task."""
    global _app
    if not settings.telegram_bot_token:
        log.warning("TELEGRAM_BOT_TOKEN not set — bot disabled")
        return

    async def _on_bot_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        err = ctx.error
        log.exception("Bot handler error", exc_info=err)
        if err is not None:
            notify_error("telegram handler", err)

    _app = ApplicationBuilder().token(settings.telegram_bot_token).build()
    _app.add_handler(CommandHandler("start", _on_start))
    _app.add_handler(CommandHandler("status", _on_status))
    _app.add_handler(CallbackQueryHandler(_on_callback))
    _app.add_handler(MessageHandler(filters.REPLY & filters.TEXT, _on_reply))
    _app.add_error_handler(_on_bot_error)

    await _app.initialize()
    await _app.start()
    await _app.updater.start_polling(drop_pending_updates=True)
    log.info("Telegram bot started")


async def stop_bot() -> None:
    global _app
    if _app is None:
        return
    try:
        await _app.updater.stop()
        await _app.stop()
        await _app.shutdown()
    except Exception:  # noqa: BLE001
        log.exception("Error stopping Telegram bot")
    _app = None
