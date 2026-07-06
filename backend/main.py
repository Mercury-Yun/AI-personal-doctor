import logging
import os
import socket
import threading


def _prefer_ipv4() -> None:
    """强制出站优先 IPv4。

    板子（Windows 网络共享子网）无可用 IPv6 出口，但 DNS 把 dashscope 的
    AAAA(IPv6) 记录排在前面。Python 的 requests/httpx/websocket-client 不做
    Happy Eyeballs，会先连 IPv6 卡到 TCP 超时(~20s)再回退 IPv4，导致云端
    TTS 挂死、LLM/VLM 极慢。这里让 getaddrinfo 只返回 IPv4（无 IPv4 时回退原始
    结果，兼容 IPv6-only 主机）。
    """
    if getattr(socket, "_ipv4_patched", False):
        return
    _orig = socket.getaddrinfo

    def _ipv4_only(host, *args, **kwargs):
        results = _orig(host, *args, **kwargs)
        ipv4 = [r for r in results if r[0] == socket.AF_INET]
        return ipv4 or results

    socket.getaddrinfo = _ipv4_only
    socket._ipv4_patched = True


def _setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    else:
        root.setLevel(level)
    logging.getLogger("backend").setLevel(level)


_prefer_ipv4()
_setup_logging()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import models
from .database import engine
from .migrations import run_startup_migrations
from .routers import chat, dashboard, device, garmin, medical_cases, medications, users
from .services.rag_service import get_rag_service
from .services.reminder_service import start_reminder_scheduler, stop_reminder_scheduler
from .services.notify_service import start_daily_report_scheduler, stop_daily_report_scheduler
from .services.cloud_warmup_service import warm_cloud_services
from .services.local_asr import asr_prewarm
from .services.local_kws import kws_prewarm

models.Base.metadata.create_all(bind=engine)
run_startup_migrations()

app = FastAPI(title="AI Personal Doctor API", version="0.2.0")

_cors_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
_extra_origins = os.getenv("CORS_ORIGINS", "")
if _extra_origins:
    _cors_origins.extend(origin.strip() for origin in _extra_origins.split(",") if origin.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router)
app.include_router(medications.router)
app.include_router(medical_cases.router)
app.include_router(dashboard.router)
app.include_router(chat.router)
app.include_router(device.router)
app.include_router(garmin.router)


@app.on_event("startup")
async def startup_event():
    start_reminder_scheduler()
    start_daily_report_scheduler()

    def _warmup_background() -> None:
        try:
            get_rag_service().initialize()
        except Exception as exc:
            logging.warning("RAG service is not ready: %s", exc)
        try:
            from .database import SessionLocal
            from .services.case_rag_service import get_case_rag_service

            db = SessionLocal()
            try:
                get_case_rag_service().initialize(db)
            finally:
                db.close()
        except Exception as exc:
            logging.warning("Case RAG warmup failed: %s", exc)
        warm_cloud_services()
        try:
            asr_prewarm()
        except Exception as exc:
            logging.warning("ASR prewarm failed: %s", exc)
        try:
            from .services.wake_service import ensure_wake_daemon
            ensure_wake_daemon()
        except Exception as exc:
            logging.warning("Wake daemon start failed: %s", exc)

    threading.Thread(target=_warmup_background, name="api-warmup", daemon=True).start()


@app.on_event("shutdown")
async def shutdown_event():
    stop_reminder_scheduler()
    stop_daily_report_scheduler()


@app.get("/health")
def health_check():
    return {"status": "ok"}
