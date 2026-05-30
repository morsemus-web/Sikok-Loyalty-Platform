import asyncio
import secrets
import time
from dataclasses import dataclass, field
from typing import Literal, Optional

from .config import settings

Kind = Literal["stamp", "password_reset"]


@dataclass
class PendingRequest:
    pending_id: str
    kind: Kind
    user_id: int
    shop_id: int
    created_at: float
    socket_room: str = ""
    awaiting_amount: bool = False
    telegram_message_id: Optional[int] = None
    extra: dict = field(default_factory=dict)


class PendingStore:
    """In-memory store of pending stamp / password-reset requests.

    Also tracks per-user debounce timestamps so we ignore duplicate
    Stamp requests within the configured window.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, PendingRequest] = {}
        # Maps owner chat_id (str) -> pending_id currently in ForceReply state.
        self._owner_waiting: dict[str, str] = {}
        self._last_stamp_request: dict[int, float] = {}
        self._lock = asyncio.Lock()

    def is_debounced(self, user_id: int) -> bool:
        last = self._last_stamp_request.get(user_id)
        if last is None:
            return False
        return (time.time() - last) < settings.debounce_seconds

    def mark_stamp_request(self, user_id: int) -> None:
        self._last_stamp_request[user_id] = time.time()

    def create(
        self,
        kind: Kind,
        user_id: int,
        shop_id: int,
        socket_room: str = "",
    ) -> str:
        pid = secrets.token_urlsafe(12)
        self._by_id[pid] = PendingRequest(
            pending_id=pid,
            kind=kind,
            user_id=user_id,
            shop_id=shop_id,
            created_at=time.time(),
            socket_room=socket_room,
        )
        return pid

    def get(self, pending_id: str) -> Optional[PendingRequest]:
        return self._by_id.get(pending_id)

    def pop(self, pending_id: str) -> Optional[PendingRequest]:
        self._owner_waiting = {k: v for k, v in self._owner_waiting.items() if v != pending_id}
        return self._by_id.pop(pending_id, None)

    def mark_awaiting_amount(self, pending_id: str, owner_chat_id: str, telegram_message_id: int) -> None:
        req = self._by_id.get(pending_id)
        if req is None:
            return
        req.awaiting_amount = True
        req.telegram_message_id = telegram_message_id
        self._owner_waiting[owner_chat_id] = pending_id

    def pending_for_owner(self, owner_chat_id: str) -> Optional[PendingRequest]:
        pid = self._owner_waiting.get(owner_chat_id)
        if pid is None:
            return None
        return self._by_id.get(pid)

    def clear_owner_waiting(self, owner_chat_id: str) -> None:
        self._owner_waiting.pop(owner_chat_id, None)


pending_store = PendingStore()
