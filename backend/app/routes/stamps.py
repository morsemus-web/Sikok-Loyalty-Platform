from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import current_user
from ..config import settings
from ..database import get_db
from ..models import LoyaltyCard, User
from ..notify import notify_run
from ..pending import pending_store
from ..schemas import CardOut, StampRequestIn, StampRequestOut
from ..telegram_bot import bot_send_stamp_request
from ..timeutil import format_ist, is_same_ist_day, now_ist

router = APIRouter(prefix="/api", tags=["stamps"])


def _card_payload(card: LoyaltyCard) -> dict:
    return {
        "card_id": card.card_id,
        "shop_id": card.shop_id,
        "current_stamps": card.current_stamps,
        "current_loop": card.current_loop,
        "last_visit": card.last_visit,
        "last_visit_ist": format_ist(card.last_visit) or None,
        "stamped_today": is_same_ist_day(card.last_visit, now_ist()),
    }


@router.get("/me/card")
async def my_card(
    shop_id: int,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    card = await db.scalar(
        select(LoyaltyCard).where(LoyaltyCard.user_id == user.user_id, LoyaltyCard.shop_id == shop_id)
    )
    if card is None:
        card = LoyaltyCard(user_id=user.user_id, shop_id=shop_id, current_stamps=0)
        db.add(card)
        await db.commit()
        await db.refresh(card)
    return _card_payload(card)


@router.post("/stamps/request", response_model=StampRequestOut)
async def request_stamp(
    payload: StampRequestIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    if pending_store.is_debounced(user.user_id):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Please wait before requesting again")

    card = await db.scalar(
        select(LoyaltyCard).where(
            LoyaltyCard.user_id == user.user_id, LoyaltyCard.shop_id == payload.shop_id
        )
    )
    if card is None:
        card = LoyaltyCard(user_id=user.user_id, shop_id=payload.shop_id, current_stamps=0)
        db.add(card)
        await db.commit()
        await db.refresh(card)

    # One stamp per IST day per customer.
    if is_same_ist_day(card.last_visit, now_ist()):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Today's stamp is already collected. Come back tomorrow!",
        )

    pending_id = pending_store.create(
        kind="stamp",
        user_id=user.user_id,
        shop_id=payload.shop_id,
        socket_room="",  # set below
    )
    req = pending_store.get(pending_id)
    req.socket_room = pending_id  # room name == pending_id

    pending_store.mark_stamp_request(user.user_id)

    await bot_send_stamp_request(
        shop_id=payload.shop_id,
        pending_id=pending_id,
        name=user.name,
        mobile=user.mobile_number,
        current_stamps=card.current_stamps,
        current_loop=card.current_loop,
    )

    notify_run(
        "Stamp request awaiting owner",
        f"{user.name} · {user.mobile_number} · loop {card.current_loop} · "
        f"stamps {card.current_stamps}/{settings.stamps_to_reward}",
    )

    return StampRequestOut(pending_id=pending_id, socket_room=pending_id)
