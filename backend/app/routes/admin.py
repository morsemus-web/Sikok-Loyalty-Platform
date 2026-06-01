from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import Integer, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..admin_auth import (
    current_operator,
    extract_user_id,
    is_operator_chat,
    make_admin_token,
    operator_name,
    validate_init_data,
)
from ..config import settings
from ..database import get_db
from ..models import LoyaltyCard, Operator, ShopReward, Transaction, User
from ..timeutil import format_ist

router = APIRouter(prefix="/api/admin", tags=["admin"])


class AuthIn(BaseModel):
    init_data: str


class AuthOut(BaseModel):
    token: str
    name: str
    chat_id: str


@router.post("/auth", response_model=AuthOut)
async def auth(payload: AuthIn, db: AsyncSession = Depends(get_db)):
    parsed = validate_init_data(payload.init_data)
    if parsed is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid Telegram sign-in")
    chat_id = extract_user_id(parsed)
    if chat_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No Telegram user")
    if not await is_operator_chat(db, chat_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You're not a Sikok operator")
    name = await operator_name(db, chat_id)
    return AuthOut(token=make_admin_token(chat_id, name), name=name, chat_id=chat_id)


@router.get("/stats")
async def stats(op: dict = Depends(current_operator), db: AsyncSession = Depends(get_db)):
    total_users = await db.scalar(select(func.count(User.user_id))) or 0
    total_tx = await db.scalar(select(func.count(Transaction.transaction_id))) or 0
    revenue = await db.scalar(select(func.coalesce(func.sum(Transaction.sale_amount), 0))) or 0
    rewards = await db.scalar(
        select(func.count()).where(Transaction.discount_applied.is_(True))
    ) or 0
    return {
        "customers": total_users,
        "sales": total_tx,
        "revenue": float(revenue),
        "rewards_redeemed": rewards,
    }


@router.get("/customers")
async def customers(op: dict = Depends(current_operator), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(
                User.user_id,
                User.name,
                User.mobile_number,
                User.created_at,
                LoyaltyCard.current_stamps,
                LoyaltyCard.current_loop,
                LoyaltyCard.last_visit,
            )
            .join(LoyaltyCard, LoyaltyCard.user_id == User.user_id, isouter=True)
            .order_by(User.created_at.desc())
        )
    ).all()

    totals = {
        r.user_id: r
        for r in (
            await db.execute(
                select(
                    User.user_id,
                    func.count(Transaction.transaction_id).label("visits"),
                    func.coalesce(func.sum(Transaction.sale_amount), 0).label("ltv"),
                )
                .join(LoyaltyCard, LoyaltyCard.user_id == User.user_id)
                .join(Transaction, Transaction.card_id == LoyaltyCard.card_id, isouter=True)
                .group_by(User.user_id)
            )
        ).all()
    }

    out = []
    for r in rows:
        t = totals.get(r.user_id)
        out.append({
            "user_id": r.user_id,
            "name": r.name,
            "mobile_number": r.mobile_number,
            "joined_ist": format_ist(r.created_at),
            "current_loop": r.current_loop or 1,
            "current_stamps": r.current_stamps if r.current_stamps is not None else 0,
            "last_visit_ist": format_ist(r.last_visit) if r.last_visit else "",
            "visits": t.visits if t else 0,
            "ltv": float(t.ltv) if t else 0.0,
        })
    return {"customers": out, "total": len(out)}


@router.get("/rewards")
async def rewards(op: dict = Depends(current_operator), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(ShopReward)
            .where(ShopReward.shop_id == settings.default_shop_id)
            .order_by(ShopReward.loop_number)
        )
    ).scalars().all()
    return {"rewards": [{"loop": r.loop_number, "description": r.description} for r in rows]}


class RewardIn(BaseModel):
    loop: int = Field(ge=1, le=999)
    description: str = Field(min_length=1, max_length=500)


@router.post("/rewards")
async def set_reward(
    payload: RewardIn,
    op: dict = Depends(current_operator),
    db: AsyncSession = Depends(get_db),
):
    stmt = pg_insert(ShopReward).values(
        shop_id=settings.default_shop_id,
        loop_number=payload.loop,
        description=payload.description.strip(),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["shop_id", "loop_number"],
        set_=dict(description=payload.description.strip(), updated_at=func.now()),
    )
    await db.execute(stmt)
    await db.commit()

    # Notify the activity feed who changed it.
    from ..notify import notify_run

    notify_run("Reward updated (dashboard)", f"Loop {payload.loop}: {payload.description} · by {op['name']}")
    return {"ok": True, "loop": payload.loop, "description": payload.description.strip()}


@router.get("/operators")
async def operators(op: dict = Depends(current_operator), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Operator).order_by(Operator.added_at))).scalars().all()
    return {"operators": [{"chat_id": o.chat_id, "name": o.name, "role": o.role} for o in rows]}
