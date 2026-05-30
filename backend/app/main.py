import logging
from contextlib import asynccontextmanager

import socketio
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .notify import notify_boot, notify_error
from .routes import shops as shops_router
from .routes import stamps as stamps_router
from .routes import users as users_router
from .sockets import sio
from .telegram_bot import start_bot, stop_bot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("sikok.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await start_bot()
    notify_boot()
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


@api.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    """Anything not handled below — pipe a short trace to Telegram and log."""
    log.exception("Unhandled exception on %s %s", request.method, request.url.path)
    notify_error(f"{request.method} {request.url.path}", exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@api.exception_handler(StarletteHTTPException)
async def _http_exc(request: Request, exc: StarletteHTTPException):
    # 5xx HTTPExceptions are worth surfacing; 4xx are expected client errors.
    if exc.status_code >= 500:
        notify_error(f"{request.method} {request.url.path}", exc)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@api.exception_handler(RequestValidationError)
async def _validation_exc(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


api.include_router(users_router.router)
api.include_router(shops_router.router)
api.include_router(stamps_router.router)


@api.get("/api/health")
async def health():
    return {"ok": True}


# Mount Socket.IO on top of FastAPI as the outermost ASGI app.
app = socketio.ASGIApp(sio, other_asgi_app=api, socketio_path="socket.io")
