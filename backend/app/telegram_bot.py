import asyncio
import logging
import secrets
from typing import Any, Optional

from sqlalchemy import Integer, func, select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.error import BadRequest, Forbidden, NetworkError, TelegramError, TimedOut
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from .auth import hash_password
from .config import settings
from .database import SessionLocal
from .models import LoyaltyCard, Operator, Shop, ShopReward, Transaction, User
from .notify import notify_error, notify_run
from .pending import pending_store
from .sockets import emit_approved, emit_declined, emit_password_reset
from .timeutil import format_ist, now_ist

log = logging.getLogger("sikok.bot")

_app: Optional[Application] = None

# In-memory cache of registered operators: chat_id -> display name.
# Loaded at startup and refreshed whenever /add or /removeop runs, so the
# sync _label_for() doesn't need a DB round-trip on every callback.
_operators: dict[str, str] = {}


async def reload_operators() -> None:
    global _operators
    try:
        async with SessionLocal() as db:
            rows = (await db.execute(select(Operator))).scalars().all()
            _operators = {r.chat_id: r.name for r in rows}
        log.info("Loaded %d operators", len(_operators))
    except Exception:  # noqa: BLE001
        log.exception("Failed to load operators")


def _approval_keyboard(pending_id: str, reward_visit: bool) -> InlineKeyboardMarkup:
    approve_label = "🎁 Approve Reward" if reward_visit else "✅ Approve & Stamp"
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


async def _owner_chat_id_for_shop(shop_id: int) -> Optional[str]:
    async with SessionLocal() as db:
        shop = await db.scalar(select(Shop).where(Shop.shop_id == shop_id))
        if shop is None:
            return None
        cid = shop.telegram_chat_id
        if not cid or cid.startswith("REPLACE"):
            return None
        return cid


async def _all_operator_ids(shop_id: int) -> set[str]:
    """Every chat id with operator powers: registered operators + shop owner + env tech."""
    ids = set(_operators.keys())
    owner = await _owner_chat_id_for_shop(shop_id)
    if owner:
        ids.add(owner)
    if settings.tech_telegram_chat_id:
        ids.add(settings.tech_telegram_chat_id)
    return ids


async def _operator_chats(shop_id: int) -> list[tuple[str, str]]:
    """Return [(name, chat_id), ...] for every operator chat that should receive
    approval prompts. First to tap wins; the others get a 'being handled' notice."""
    owner = await _owner_chat_id_for_shop(shop_id)
    return [(_label_for(cid, owner), cid) for cid in await _all_operator_ids(shop_id)]


async def _is_operator(chat_id: str, shop_id: int = settings.default_shop_id) -> bool:
    return chat_id in await _all_operator_ids(shop_id)


def _label_for(chat_id: str, owner_chat_id: Optional[str] = None) -> str:
    """Display name for an operator. Registered name wins; else fall back to role."""
    if chat_id in _operators:
        return _operators[chat_id]
    if chat_id == settings.tech_telegram_chat_id:
        return "Tech"
    if owner_chat_id and chat_id == owner_chat_id:
        return "Owner"
    return "another operator"


# ---------------------------------------------------------------------------
# Resilient send: retries network/timeout errors with exponential backoff,
# gives up immediately on BadRequest / Forbidden (chat not found, bot blocked).
# ---------------------------------------------------------------------------

_RETRY_DELAYS = (0.5, 1.5, 3.0)


async def send_with_retry(**kwargs: Any) -> Optional[int]:
    """Send a message with exponential-backoff retry. Returns message_id on success."""
    if _app is None:
        return None
    last_err: Optional[BaseException] = None
    for attempt, delay in enumerate((0.0, *_RETRY_DELAYS)):
        if delay:
            await asyncio.sleep(delay)
        try:
            msg = await _app.bot.send_message(**kwargs)
            return msg.message_id
        except (BadRequest, Forbidden) as e:
            # Won't fix on retry — chat doesn't exist or user blocked the bot.
            log.warning("Telegram send not retryable (%s): %s", type(e).__name__, e)
            return None
        except (NetworkError, TimedOut) as e:
            last_err = e
            log.warning("Telegram send transient failure (attempt %d): %s", attempt + 1, e)
        except TelegramError as e:
            last_err = e
            log.warning("Telegram send error (attempt %d): %s", attempt + 1, e)
    log.error("Telegram send exhausted retries: %s", last_err)
    return None


async def _broadcast_to_operators(shop_id: int, **kwargs: Any) -> dict[str, int]:
    """Send the same message to every operator chat. Returns {chat_id: message_id}."""
    sent: dict[str, int] = {}
    for _label, cid in await _operator_chats(shop_id):
        mid = await send_with_retry(chat_id=cid, **kwargs)
        if mid is not None:
            sent[cid] = mid
    return sent


async def _edit_other_operators(actor_chat: str, req, status_line: str) -> None:
    """Append `status_line` to every operator's copy of the approval message EXCEPT the actor's."""
    messages: dict[str, int] = req.extra.get("messages", {})
    original = req.extra.get("original_text", "")
    for cid, mid in messages.items():
        if cid == actor_chat:
            continue
        try:
            await _app.bot.edit_message_text(
                chat_id=cid,
                message_id=mid,
                text=f"{original}\n\n{status_line}",
            )
        except (BadRequest, Forbidden, TelegramError) as e:
            log.warning("Couldn't edit other operator's message: %s", e)


async def _get_reward_text(shop_id: int, loop_number: int) -> str:
    """Look up the configured reward for this shop+loop; fall back to a default."""
    async with SessionLocal() as db:
        row = await db.scalar(
            select(ShopReward).where(
                ShopReward.shop_id == shop_id,
                ShopReward.loop_number == loop_number,
            )
        )
        if row is not None:
            return row.description
        # Fall back to loop 1's reward if no specific one is set.
        fallback = await db.scalar(
            select(ShopReward).where(
                ShopReward.shop_id == shop_id, ShopReward.loop_number == 1
            )
        )
        if fallback is not None:
            return f"{fallback.description} (loop {loop_number} not configured, using loop 1)"
    return f"₹{settings.discount_per_item} off per item (no reward set for loop {loop_number})"


async def bot_send_stamp_request(
    *,
    shop_id: int,
    pending_id: str,
    name: str,
    mobile: str,
    current_stamps: int,
    current_loop: int,
) -> None:
    if _app is None:
        log.warning("Telegram bot not initialised; skipping send")
        return

    reward_visit = current_stamps >= (settings.stamps_to_reward - 1)
    if reward_visit:
        reward_text = await _get_reward_text(shop_id, current_loop)
        text = (
            f"🚨 REWARD UNLOCKED — Loop {current_loop}\n"
            f"{name} is on Visit "
            f"{settings.stamps_to_reward}/{settings.stamps_to_reward}!\n"
            f"Apply: {reward_text}\n"
            f"Mobile: {mobile}"
        )
    else:
        text = (
            f"Stamp Request: {name}\n"
            f"Mobile: {mobile}\n"
            f"Loop {current_loop} · Stamps {current_stamps}/{settings.stamps_to_reward}"
        )

    sent = await _broadcast_to_operators(
        shop_id,
        text=text,
        reply_markup=_approval_keyboard(pending_id, reward_visit),
    )

    req = pending_store.get(pending_id)
    if req is not None:
        req.extra["messages"] = sent
        req.extra["original_text"] = text


async def bot_send_password_reset(*, shop_id: int, pending_id: str, name: str, mobile: str) -> None:
    if _app is None:
        return

    text = f"Password Reset Request: {name} — {mobile}. Approve?"
    sent = await _broadcast_to_operators(
        shop_id,
        text=text,
        reply_markup=_reset_keyboard(pending_id),
    )

    req = pending_store.get(pending_id)
    if req is not None:
        req.extra["messages"] = sent
        req.extra["original_text"] = text


# ---------------------------------------------------------------------------
# Safe send/edit wrappers
#
# Legacy Telegram Markdown is fragile: a single unbalanced * _ ` [ in a
# customer name, reward text, or an appended original message triggers
# "BadRequest: can't parse entities" and the handler crashes. These wrappers
# try the formatted send, and on a parse error fall back to plain text so the
# operator always gets *something*. They also swallow the harmless
# "message is not modified" edit error.
# ---------------------------------------------------------------------------


def _is_parse_error(e: BadRequest) -> bool:
    return "parse entities" in str(e).lower() or "can't parse" in str(e).lower()


async def _reply(message, text: str, markdown: bool = False, **kwargs: Any) -> None:
    try:
        await message.reply_text(
            text, parse_mode=("Markdown" if markdown else None), **kwargs
        )
    except BadRequest as e:
        if markdown and _is_parse_error(e):
            log.warning("Markdown parse failed, resending plain: %s", e)
            await message.reply_text(text, **kwargs)
        else:
            raise


async def _edit(query, text: str, markdown: bool = False, **kwargs: Any) -> None:
    try:
        await query.edit_message_text(
            text, parse_mode=("Markdown" if markdown else None), **kwargs
        )
    except BadRequest as e:
        msg = str(e).lower()
        if "not modified" in msg:
            return
        if markdown and _is_parse_error(e):
            log.warning("Markdown parse failed on edit, resending plain: %s", e)
            try:
                await query.edit_message_text(text, **kwargs)
            except BadRequest as e2:
                if "not modified" not in str(e2).lower():
                    raise
        else:
            raise


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def _on_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(
        update.message,
        f"Sikok bot online.\n"
        f"Your chat ID is: `{update.effective_chat.id}`\n\n"
        "Type /help for the full command list.",
        markdown=True,
    )


async def _on_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = f"✅ Sikok backend alive · {now_ist().strftime('%d %b %Y, %I:%M %p IST')}"
    await update.message.reply_text(text)


async def _on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if ":" not in data:
        return
    action, pending_id = data.split(":", 1)

    # ---- Operator-add approval (tech only) ----
    if action in ("addok", "addno"):
        chat_id = str(update.effective_chat.id)
        if chat_id != settings.tech_telegram_chat_id:
            await query.answer("Only Tech can approve operator requests.", show_alert=True)
            return
        pend = _pending_adds.pop(pending_id, None)
        if pend is None:
            await _edit(query, query.message.text + "\n\n(Already handled or expired.)")
            return
        if action == "addno":
            await _edit(query, query.message.text + "\n\n🚫 Rejected by Tech.")
            notify_run("Operator add rejected", f"{pend['name']} ({pend['new_chat']})")
            return
        await _commit_operator(pend["new_chat"], pend["name"])
        await _edit(
            query,
            query.message.text + f"\n\n✅ Approved by Tech. {pend['name']} is now an operator.",
        )
        notify_run(
            "Operator added",
            f"{pend['name']} ({pend['new_chat']}) · requested by {pend['requester']} · approved by Tech",
        )
        return

    req = pending_store.get(pending_id)
    if req is None:
        await _edit(query,query.message.text + "\n\n(Already handled or expired.)")
        return

    chat_id = str(update.effective_chat.id)
    owner_chat = await _owner_chat_id_for_shop(req.shop_id)
    actor_label = _label_for(chat_id, owner_chat)

    # ---- Cross-operator lock ----
    # Once the first operator taps anything, the pending is locked to them.
    # The other operator's message gets edited to "being handled" and they
    # can't take further action until the lock clears (commit/decline pops
    # the pending entirely).
    locked_to = req.extra.get("locked_to")
    if locked_to and locked_to != chat_id:
        other_label = _label_for(locked_to, owner_chat)
        await _edit(query,
            query.message.text + f"\n\n🔒 Being handled by {other_label}."
        )
        return

    if action == "decline":
        pending_store.pop(pending_id)
        await _edit(query,query.message.text + f"\n\n🚫 Disregarded by {actor_label}.")
        await _edit_other_operators(chat_id, req, f"🚫 Disregarded by {actor_label}.")
        await emit_declined(req.socket_room, {"reason": "Declined by Counter"})
        notify_run("Stamp request declined", f"by {actor_label} · user_id={req.user_id}")
        return

    if action == "reset_no":
        pending_store.pop(pending_id)
        await _edit(query,query.message.text + f"\n\n🚫 Disregarded by {actor_label}.")
        await _edit_other_operators(chat_id, req, f"🚫 Disregarded by {actor_label}.")
        await emit_declined(req.socket_room, {"reason": "Reset declined"})
        notify_run("Password reset declined", f"by {actor_label} · user_id={req.user_id}")
        return

    if action == "approve":
        # Lock the pending so the other operator can't also approve.
        req.extra["locked_to"] = chat_id
        try:
            new_stamps, new_loop, is_reward = await _commit_sale(req, chat_id, actor_label)
        except Exception as e:  # noqa: BLE001
            log.exception("Failed to commit stamp")
            notify_error("commit_sale", e)
            await _edit(query, query.message.text + "\n\n❌ Save failed. Try again.")
            return

        pending_store.pop(req.pending_id)
        pending_store.clear_owner_waiting(chat_id)

        if is_reward:
            success_line = (
                f"✅ 🎁 Reward applied · now on Loop {new_loop} "
                f"(0/{settings.stamps_to_reward}) · by {actor_label}"
            )
        else:
            success_line = (
                f"✅ Stamped · Loop {new_loop} · "
                f"{new_stamps}/{settings.stamps_to_reward} · by {actor_label}"
            )
        await _edit(query, query.message.text + f"\n\n{success_line}")
        await _edit_other_operators(chat_id, req, success_line)
        await emit_approved(
            req.socket_room,
            {
                "current_stamps": new_stamps,
                "current_loop": new_loop,
                "discount_applied": is_reward,
            },
        )
        if is_reward:
            notify_run(
                f"🎁 Reward redeemed by {actor_label}",
                f"ended loop {new_loop - 1} · user_id={req.user_id}",
            )
        else:
            notify_run(
                f"🛒 Stamp added by {actor_label}",
                f"loop {new_loop} · stamps {new_stamps}/{settings.stamps_to_reward} · "
                f"user_id={req.user_id}",
            )
        return

    if action == "reset_ok":
        req.extra["locked_to"] = chat_id  # in case they also re-enter
        pin = f"{secrets.randbelow(10000):04d}"
        async with SessionLocal() as db:
            user = await db.scalar(select(User).where(User.user_id == req.user_id))
            if user is None:
                pending_store.pop(pending_id)
                await _edit(query,query.message.text + "\n\n⚠️ User not found.")
                return
            user.password_hash = hash_password(pin)
            await db.commit()
            user_name = user.name
        pending_store.pop(pending_id)
        await _edit(query,
            query.message.text + f"\n\n✅ Temporary PIN: *{pin}*\nRead this to the customer.",
            markdown=True,
        )
        await _edit_other_operators(
            chat_id,
            req,
            f"✅ Reset approved by {actor_label}. PIN was shown to {actor_label}.",
        )
        await emit_password_reset(req.socket_room, {"ok": True})
        notify_run("Password reset issued", f"{user_name} · by {actor_label}")
        return


async def _commit_sale(req, chat_id: str, handled_by: str) -> tuple[int, int, bool]:
    """Apply the stamp/loop advance (no sale amount). Returns (new_stamps, new_loop, is_reward)."""
    from sqlalchemy import func as sa_func

    async with SessionLocal() as db:
        card = await db.scalar(
            select(LoyaltyCard).where(
                LoyaltyCard.user_id == req.user_id, LoyaltyCard.shop_id == req.shop_id
            )
        )
        if card is None:
            card = LoyaltyCard(
                user_id=req.user_id, shop_id=req.shop_id, current_stamps=0, current_loop=1
            )
            db.add(card)
            await db.flush()

        is_reward = card.current_stamps >= (settings.stamps_to_reward - 1)

        db.add(Transaction(
            card_id=card.card_id,
            sale_amount=None,
            discount_applied=is_reward,
            handled_by=handled_by,
        ))

        if is_reward:
            # Reward redeemed — reset stamps, advance to next loop.
            card.current_stamps = 0
            card.current_loop += 1
        else:
            card.current_stamps += 1
        card.last_visit = sa_func.now()
        await db.commit()
        await db.refresh(card)
        return card.current_stamps, card.current_loop, is_reward


# ---------------------------------------------------------------------------
# Admin commands (operator-gated)
# ---------------------------------------------------------------------------


async def _on_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    is_op = await _is_operator(chat_id)
    text = (
        "*Sikok bot commands*\n\n"
        "/start — bot status + your chat ID\n"
        "/status — runtime health\n"
        "/help — this message\n"
    )
    if is_op:
        text += (
            "\n*Operator commands*\n"
            "/dashboard — open the visual dashboard (Mini App)\n"
            "/users — list registered customers (top 30)\n"
            "/export — full customer + transaction CSV\n"
            "/rewards — show reward per loop\n"
            "/setreward `<loop> <text>` — e.g. `/setreward 2 ₹150 off per item`\n"
            "/stats — quick numbers\n"
            "\n*Team*\n"
            "/operators — list everyone who can manage the counter\n"
            "/add `<chat_id> <name>` — request a new operator (Tech approves)\n"
            "/removeop `<chat_id>` — revoke access\n"
        )
    await _reply(update.message, text, markdown=True)


async def _on_dashboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    if not await _is_operator(chat_id):
        return
    url = f"{settings.public_base_url.rstrip('/')}/admin.html"
    await update.message.reply_text(
        "Open the Sikok operator dashboard:",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("📊 Open Dashboard", web_app=WebAppInfo(url=url))]]
        ),
    )


async def _on_operators(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    if not await _is_operator(chat_id):
        return
    owner = await _owner_chat_id_for_shop(settings.default_shop_id)
    ids = await _all_operator_ids(settings.default_shop_id)
    lines = ["*Counter operators*", "```"]
    for cid in sorted(ids):
        lines.append(f"{_label_for(cid, owner):<20} {cid}")
    lines.append("```")
    lines.append("Add with `/add <chat_id> <name>`")
    await _reply(update.message, "\n".join(lines), markdown=True)


# Pending /add requests awaiting tech approval: token -> {new_chat, name, requester}
_pending_adds: dict[str, dict] = {}


async def _commit_operator(new_chat: str, name: str) -> None:
    """Insert/update an operator and refresh the in-memory cache."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    async with SessionLocal() as db:
        stmt = pg_insert(Operator).values(chat_id=new_chat, name=name, role="owner")
        stmt = stmt.on_conflict_do_update(
            index_elements=["chat_id"], set_=dict(name=name)
        )
        await db.execute(stmt)
        await db.commit()
    await reload_operators()
    await send_with_retry(
        chat_id=new_chat,
        text=f"You've been added as a Sikok operator ({name}). Send /help to begin.",
    )


async def _on_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    if not await _is_operator(chat_id):
        return

    args = ctx.args or []
    # First arg must be a numeric chat id; the rest is the display name.
    if len(args) < 2 or not args[0].lstrip("-").isdigit():
        await _reply(
            update.message,
            "Usage: `/add <chat_id> <name>`\n"
            "Example: `/add 123456789 Ravi`\n\n"
            "The new person should open the bot and send /start to see their chat ID.",
            markdown=True,
        )
        return

    new_chat = args[0]
    name = " ".join(args[1:]).strip()[:100]
    requester = _label_for(chat_id, await _owner_chat_id_for_shop(settings.default_shop_id))
    tech = settings.tech_telegram_chat_id

    # Tech is the approver — if tech initiates, or if no tech chat is configured,
    # commit straight away. Otherwise route the request to tech for sign-off.
    if chat_id == tech or not tech:
        await _commit_operator(new_chat, name)
        await _reply(
            update.message,
            f"✅ {name} (chat `{new_chat}`) can now manage the counter as owner.",
            markdown=True,
        )
        notify_run("Operator added", f"{name} ({new_chat}) · by {requester}")
        return

    token = secrets.token_urlsafe(8)
    _pending_adds[token] = {"new_chat": new_chat, "name": name, "requester": requester}
    await _reply(
        update.message,
        f"📨 Request sent to Tech for approval:\nadd *{name}* (chat `{new_chat}`) as operator.",
        markdown=True,
    )
    await send_with_retry(
        chat_id=tech,
        text=(
            f"🆕 Operator add request from {requester}:\n"
            f"Name: {name}\nChat: {new_chat}\n\nApprove?"
        ),
        reply_markup=InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("✅ Approve", callback_data=f"addok:{token}"),
                InlineKeyboardButton("🚫 Reject", callback_data=f"addno:{token}"),
            ]]
        ),
    )


async def _on_removeop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    if not await _is_operator(chat_id):
        return

async def _on_removeop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    if not await _is_operator(chat_id):
        return

    args = ctx.args or []
    if len(args) < 1 or not args[0].lstrip("-").isdigit():
        await _reply(update.message, "Usage: `/removeop <chat_id>`", markdown=True)
        return

    target = args[0]
    # Don't let anyone remove the seeded owner/tech via this command — those are
    # anchored in config and the shops table.
    if target == settings.tech_telegram_chat_id or target == await _owner_chat_id_for_shop(
        settings.default_shop_id
    ):
        await _reply(update.message, "That operator is the primary owner/tech and can't be removed here.")
        return

    async with SessionLocal() as db:
        op = await db.scalar(select(Operator).where(Operator.chat_id == target))
        if op is None:
            await _reply(update.message, "No registered operator with that chat ID.")
            return
        name = op.name
        await db.delete(op)
        await db.commit()

    await reload_operators()
    actor = _label_for(chat_id, await _owner_chat_id_for_shop(settings.default_shop_id))
    await _reply(update.message, f"🚫 Removed {name} (chat {target}).")
    notify_run("Operator removed", f"{name} ({target}) · by {actor}")


async def _on_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    if not await _is_operator(chat_id):
        return

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(
                    User.user_id,
                    User.name,
                    User.mobile_number,
                    LoyaltyCard.current_stamps,
                    LoyaltyCard.current_loop,
                    User.created_at,
                )
                .join(LoyaltyCard, LoyaltyCard.user_id == User.user_id, isouter=True)
                .order_by(User.created_at.desc())
                .limit(30)
            )
        ).all()
        total = await db.scalar(select(func.count(User.user_id))) or 0

    if not rows:
        await update.message.reply_text("No customers yet.")
        return

    lines = [f"*Customers* (showing latest {len(rows)} of {total})", "```"]
    for r in rows:
        stamps = r.current_stamps if r.current_stamps is not None else 0
        loop = r.current_loop if r.current_loop is not None else 1
        # Strip backticks so a name can't break out of the code block.
        name = (r.name or "").replace("`", "")[:18]
        lines.append(f"#{r.user_id:>3}  {name:<18}  {r.mobile_number:<12}  L{loop}·{stamps}/4")
    lines.append("```")
    if total > 30:
        lines.append(f"\nUse /export for the full {total}-row CSV.")
    await _reply(update.message, "\n".join(lines), markdown=True)


async def _on_export(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    import csv
    import io

    chat_id = str(update.effective_chat.id)
    if not await _is_operator(chat_id):
        return

    async with SessionLocal() as db:
        users = (
            await db.execute(
                select(
                    User.user_id,
                    User.name,
                    User.mobile_number,
                    User.created_at,
                    LoyaltyCard.shop_id,
                    LoyaltyCard.current_stamps,
                    LoyaltyCard.current_loop,
                    LoyaltyCard.last_visit,
                )
                .join(LoyaltyCard, LoyaltyCard.user_id == User.user_id, isouter=True)
                .order_by(User.user_id)
            )
        ).all()

        total_sales = (
            await db.execute(
                select(
                    User.user_id,
                    func.count(Transaction.transaction_id).label("tx_count"),
                    func.sum(
                        func.cast(Transaction.discount_applied, Integer)
                    ).label("rewards_redeemed"),
                )
                .join(LoyaltyCard, LoyaltyCard.user_id == User.user_id)
                .join(Transaction, Transaction.card_id == LoyaltyCard.card_id, isouter=True)
                .group_by(User.user_id)
            )
        ).all()

        # Most recent handler per customer (DISTINCT ON, newest first).
        last_handlers = (
            await db.execute(
                select(LoyaltyCard.user_id, Transaction.handled_by)
                .join(Transaction, Transaction.card_id == LoyaltyCard.card_id)
                .order_by(LoyaltyCard.user_id, Transaction.created_at.desc())
                .distinct(LoyaltyCard.user_id)
            )
        ).all()
    totals_by_user = {r.user_id: r for r in total_sales}
    last_handler_by_user = {r.user_id: r.handled_by for r in last_handlers}

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "user_id", "name", "mobile_number", "joined_ist",
        "shop_id", "current_loop", "current_stamps", "last_visit_ist",
        "lifetime_visits", "rewards_redeemed", "last_managed_by",
    ])
    for u in users:
        t = totals_by_user.get(u.user_id)
        w.writerow([
            u.user_id,
            u.name,
            u.mobile_number,
            format_ist(u.created_at),
            u.shop_id or "",
            u.current_loop or 1,
            u.current_stamps if u.current_stamps is not None else 0,
            format_ist(u.last_visit) if u.last_visit else "",
            t.tx_count if t else 0,
            t.rewards_redeemed if t else 0,
            last_handler_by_user.get(u.user_id) or "",
        ])

    data = buf.getvalue().encode("utf-8")
    fname = f"sikok-customers-{now_ist().strftime('%Y%m%d-%H%M')}.csv"
    await update.message.reply_document(
        document=io.BytesIO(data),
        filename=fname,
        caption=f"📋 {len(users)} customers · generated {format_ist(now_ist())}",
    )


async def _on_rewards(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    if not await _is_operator(chat_id):
        return
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(ShopReward)
                .where(ShopReward.shop_id == settings.default_shop_id)
                .order_by(ShopReward.loop_number)
            )
        ).scalars().all()

    if not rows:
        await update.message.reply_text(
            "No rewards configured. Set one with /setreward 1 ₹100 off per item"
        )
        return

    lines = ["*Rewards by loop*"]
    for r in rows:
        lines.append(f"  Loop {r.loop_number}: {r.description}")
    lines.append("\nChange with `/setreward <loop> <text>`")
    lines.append("Example: `/setreward 3 Free t-shirt`")
    await _reply(update.message, "\n".join(lines), markdown=True)


async def _on_setreward(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    if not await _is_operator(chat_id):
        return

    args = ctx.args or []
    if len(args) < 2 or not args[0].isdigit():
        await _reply(
            update.message,
            "Usage: `/setreward <loop> <text>`\nExample: `/setreward 2 ₹150 off per item`",
            markdown=True,
        )
        return

    loop_num = int(args[0])
    description = " ".join(args[1:]).strip()
    if loop_num < 1 or len(description) > 500:
        await update.message.reply_text("Loop must be ≥1 and description ≤500 chars.")
        return

    from sqlalchemy import func as sa_func
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    async with SessionLocal() as db:
        stmt = pg_insert(ShopReward).values(
            shop_id=settings.default_shop_id,
            loop_number=loop_num,
            description=description,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["shop_id", "loop_number"],
            set_=dict(description=description, updated_at=sa_func.now()),
        )
        await db.execute(stmt)
        await db.commit()

    actor = _label_for(chat_id, await _owner_chat_id_for_shop(settings.default_shop_id))
    await update.message.reply_text(
        f"✅ Loop {loop_num} reward set to:\n  {description}"
    )
    notify_run("Reward updated", f"Loop {loop_num}: {description} · by {actor}")


async def _on_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    if not await _is_operator(chat_id):
        return
    async with SessionLocal() as db:
        total_users = await db.scalar(select(func.count(User.user_id))) or 0
        total_tx = await db.scalar(select(func.count(Transaction.transaction_id))) or 0
        rewards_given = await db.scalar(
            select(func.count()).where(Transaction.discount_applied.is_(True))
        ) or 0
    await _reply(
        update.message,
        f"*Sikok stats* · {now_ist().strftime('%d %b %I:%M %p IST')}\n\n"
        f"Customers: *{total_users}*\n"
        f"Stamps given: *{total_tx}*\n"
        f"Rewards redeemed: *{rewards_given}*",
        markdown=True,
    )


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
    _app.add_handler(CommandHandler("help", _on_help))
    _app.add_handler(CommandHandler("users", _on_users))
    _app.add_handler(CommandHandler("export", _on_export))
    _app.add_handler(CommandHandler("rewards", _on_rewards))
    _app.add_handler(CommandHandler("setreward", _on_setreward))
    _app.add_handler(CommandHandler("stats", _on_stats))
    _app.add_handler(CommandHandler("operators", _on_operators))
    _app.add_handler(CommandHandler("dashboard", _on_dashboard))
    _app.add_handler(CommandHandler("add", _on_add))
    _app.add_handler(CommandHandler("removeop", _on_removeop))
    _app.add_handler(CallbackQueryHandler(_on_callback))
    _app.add_error_handler(_on_bot_error)

    await _app.initialize()
    await _app.start()
    await reload_operators()
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
