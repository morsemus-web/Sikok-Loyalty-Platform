from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import current_user, hash_password, make_token, verify_password
from ..database import get_db
from ..models import LoyaltyCard, User
from ..schemas import AuthResponse, ForgotPasswordIn, ForgotPasswordOut, LoginRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _normalize_mobile(raw: str) -> str:
    return "".join(ch for ch in raw if ch.isdigit() or ch == "+")[:15]


@router.post("/login", response_model=AuthResponse)
async def login_or_register(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    mobile = _normalize_mobile(payload.mobile_number)
    user = await db.scalar(select(User).where(User.mobile_number == mobile))

    if user is None:
        if not payload.name:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "NEW_USER_NAME_REQUIRED")
        user = User(
            mobile_number=mobile,
            name=payload.name.strip(),
            password_hash=hash_password(payload.password),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        new_account = True
    else:
        if not verify_password(payload.password, user.password_hash):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
        new_account = False

    return AuthResponse(
        token=make_token(user.user_id),
        user_id=user.user_id,
        name=user.name,
        mobile_number=user.mobile_number,
        new_account=new_account,
    )


@router.get("/me")
async def me(user: User = Depends(current_user)):
    return {"user_id": user.user_id, "name": user.name, "mobile_number": user.mobile_number}


# Forgot-password lives here but the actual Telegram routing is in stamps router
# to share the pending-request store. We just expose the trigger.
@router.post("/forgot-password", response_model=ForgotPasswordOut)
async def forgot_password(payload: ForgotPasswordIn, db: AsyncSession = Depends(get_db)):
    from ..pending import pending_store
    from ..config import settings
    from ..telegram_bot import bot_send_password_reset

    mobile = _normalize_mobile(payload.mobile_number)
    user = await db.scalar(select(User).where(User.mobile_number == mobile))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No account for that number")

    pending_id = pending_store.create(
        kind="password_reset",
        user_id=user.user_id,
        shop_id=settings.default_shop_id,
    )
    await bot_send_password_reset(
        shop_id=settings.default_shop_id,
        pending_id=pending_id,
        name=user.name,
        mobile=user.mobile_number,
    )
    return ForgotPasswordOut(pending_id=pending_id)
