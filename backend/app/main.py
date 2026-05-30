import logging
from contextlib import asynccontextmanager

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import shops as shops_router
from .routes import stamps as stamps_router
from .routes import users as users_router
from .sockets import sio
from .telegram_bot import start_bot, stop_bot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await start_bot()
    try:
        yield
    finally:
        await stop_bot()


api = FastAPI(title="Sikok API", version="1.0", lifespan=lifespan)
api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

api.include_router(users_router.router)
api.include_router(shops_router.router)
api.include_router(stamps_router.router)


@api.get("/api/health")
async def health():
    return {"ok": True}


# Mount Socket.IO on top of FastAPI as the outermost ASGI app.
app = socketio.ASGIApp(sio, other_asgi_app=api, socketio_path="socket.io")
