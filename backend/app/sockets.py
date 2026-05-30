import socketio

from .auth import decode_token

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    logger=False,
    engineio_logger=False,
)


@sio.event
async def connect(sid, environ, auth):
    """Client must send `auth = { token, pending_id }` on connect.

    We join the client to a room named after their pending_id so the
    Telegram handlers can target them precisely with sio.emit(..., room=room).
    """
    if not auth or "token" not in auth or "pending_id" not in auth:
        return False
    try:
        decode_token(auth["token"])
    except Exception:
        return False
    await sio.enter_room(sid, auth["pending_id"])
    return True


@sio.event
async def disconnect(sid):
    return None


async def emit_approved(room: str, payload: dict) -> None:
    await sio.emit("stamp_approved", payload, room=room)


async def emit_declined(room: str, payload: dict) -> None:
    await sio.emit("stamp_declined", payload, room=room)


async def emit_password_reset(room: str, payload: dict) -> None:
    await sio.emit("password_reset", payload, room=room)
