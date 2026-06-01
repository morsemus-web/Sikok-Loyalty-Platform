"""Telegram Mini App (WebApp) authentication for the operator dashboard.

Flow:
  1. The Mini App page reads `Telegram.WebApp.initData` (a signed query string
     Telegram injects into the webview) and POSTs it to /api/admin/auth.
  2. validate_init_data() verifies the HMAC against the bot token, proving the
     request really came from Telegram and identifying the Telegram user.
  3. We check that user's id is a registered operator (operators table, shop
     owner, or env tech) and issue a short-lived admin JWT.
  4. Subsequent /api/admin/* calls present that JWT via current_operator().
"""

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import get_db
from .models import Operator, Shop

# initData older than this is rejected (replay protection).
_MAX_AUTH_AGE_SECONDS = 24 * 3600


def validate_init_data(init_data: str) -> dict | None:
    """Verify Telegram WebApp initData. Returns the parsed fields on success."""
    if not init_data or not settings.telegram_bot_token:
        return None
    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None

    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={parsed[k]}" for k in sorted(parsed))
    secret_key = hmac.new(b"WebAppData", settings.telegram_bot_token.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        return None

    # Reject stale initData.
    try:
        auth_date = int(parsed.get("auth_date", "0"))
    except ValueError:
        return None
    if auth_date <= 0 or (time.time() - auth_date) > _MAX_AUTH_AGE_SECONDS:
        return None

    return parsed


def extract_user_id(parsed: dict) -> str | None:
    try:
        user = json.loads(parsed.get("user", "{}"))
        uid = user.get("id")
        return str(uid) if uid is not None else None
    except (json.JSONDecodeError, AttributeError):
        return None


async def is_operator_chat(db: AsyncSession, chat_id: str) -> bool:
    """Operator = in operators table, OR env tech chat, OR the shop owner chat."""
    if chat_id == settings.tech_telegram_chat_id:
        return True
    op = await db.scalar(select(Operator).where(Operator.chat_id == chat_id))
    if op is not None:
        return True
    shop = await db.scalar(select(Shop).where(Shop.shop_id == settings.default_shop_id))
    return shop is not None and shop.telegram_chat_id == chat_id


async def operator_name(db: AsyncSession, chat_id: str) -> str:
    op = await db.scalar(select(Operator).where(Operator.chat_id == chat_id))
    if op is not None:
        return op.name
    if chat_id == settings.tech_telegram_chat_id:
        return "Tech"
    return "Operator"


def make_admin_token(chat_id: str, name: str) -> str:
    payload = {
        "op": chat_id,
        "name": name,
        "role": "operator",
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.admin_token_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


async def current_operator(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
    if payload.get("role") != "operator":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not an operator session")
    return {"chat_id": payload.get("op"), "name": payload.get("name")}
