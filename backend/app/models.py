from datetime import datetime
from decimal import Decimal

from sqlalchemy import DECIMAL, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Shop(Base):
    __tablename__ = "shops"

    shop_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sub_name: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)
    whatsapp_number: Mapped[str | None] = mapped_column(String(20))
    whatsapp_url: Mapped[str | None] = mapped_column(Text)
    maps_url: Mapped[str | None] = mapped_column(Text)
    telegram_chat_id: Mapped[str] = mapped_column(String(50), nullable=False)


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mobile_number: Mapped[str] = mapped_column(String(15), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LoyaltyCard(Base):
    __tablename__ = "loyalty_cards"
    __table_args__ = (UniqueConstraint("user_id", "shop_id", name="uq_user_shop"),)

    card_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.shop_id", ondelete="CASCADE"), nullable=False)
    current_stamps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_loop: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_visit: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped[User] = relationship(lazy="joined")
    shop: Mapped[Shop] = relationship(lazy="joined")


class ShopReward(Base):
    __tablename__ = "shop_rewards"

    shop_id: Mapped[int] = mapped_column(
        ForeignKey("shops.shop_id", ondelete="CASCADE"), primary_key=True, nullable=False
    )
    loop_number: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Transaction(Base):
    __tablename__ = "transactions"

    transaction_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("loyalty_cards.card_id", ondelete="CASCADE"), nullable=False)
    sale_amount: Mapped[Decimal | None] = mapped_column(DECIMAL(10, 2))
    discount_applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    handled_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Operator(Base):
    __tablename__ = "operators"

    chat_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="owner", nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
