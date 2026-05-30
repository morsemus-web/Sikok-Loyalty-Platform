from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class ShopOut(BaseModel):
    shop_id: int
    name: str
    sub_name: Optional[str] = None
    address: Optional[str] = None
    whatsapp_number: Optional[str] = None
    whatsapp_url: Optional[str] = None
    maps_url: Optional[str] = None

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    mobile_number: str = Field(min_length=7, max_length=15)
    password: str = Field(min_length=4, max_length=128)
    name: Optional[str] = Field(default=None, max_length=100)


class AuthResponse(BaseModel):
    token: str
    user_id: int
    name: str
    mobile_number: str
    new_account: bool


class CardOut(BaseModel):
    card_id: int
    shop_id: int
    current_stamps: int
    last_visit: Optional[datetime] = None

    class Config:
        from_attributes = True


class StampRequestIn(BaseModel):
    shop_id: int


class StampRequestOut(BaseModel):
    pending_id: str
    socket_room: str


class ForgotPasswordIn(BaseModel):
    mobile_number: str


class ForgotPasswordOut(BaseModel):
    pending_id: str


class TransactionOut(BaseModel):
    transaction_id: int
    sale_amount: Decimal
    discount_applied: bool
    created_at: datetime

    class Config:
        from_attributes = True
