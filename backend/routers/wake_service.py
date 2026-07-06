import logging
import threading
import time

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..config import get_settings
from .demo_bridge import DemoBridgeError, friendly_demo_error, get_demo_bridge, update_demo_availability
from .tts_service import speak as tts_speak, stop_active_speech, tts_is_playing, wait_for_tts_idle

logger = logging.getLogger(__name__)

_wake_cancel = threading.Event()
_wake_session_lock = threading.Lock()
_wake_session_active = threading.Event()
_wake_paused_until = 0.0
_wake_session_started_at = 0.0
_WAKE_LISTEN_SEC = 30
_WAKE_STALE_LOCK_SEC = 45.0


def cancel_pending_wake() -> None:
    _wake_cancel.set()


def interrupt_demo_voice(*, force: bool = False) -> None:
    """打断 demo 上的唤醒等待/录音；活跃唤醒会话中默认不打断、不置取消标志。"""
    if _wake_session_active.is_set() and not force:
        return
    cancel_pending_wake()
    try:
        get_demo_bridge().voice_stop(force=True)
    except Exception:
        pass


def cancel_wake_from_client() -> None:
    """前端取消唤醒：仅打断空闲 demo，勿在 wake/session 进行中 voice_stop。"""
    cancel_pending_wake()
    if not _wake_session_active.is_set():
        interrupt_demo_voice(force=True)


def _acquire_wake_session_lock() -> bool:
    """获取唤醒会话锁；僵尸会话超时后强制打断并接管。"""
    global _wake_session_started_at
    if _wake_session_lock.acquire(blocking=False):
        _wake_session_started_at = time.monotonic()
        return True
    stale_for = time.monotonic() - _wake_session_started_at
    if stale_for < _WAKE_STALE_LOCK_SEC:
        return False
    logger.warning("wake: reclaiming stale session lock (%.1fs)", stale_for)
    interrupt_demo_voice(force=True)
    time.sleep(0.4)
    if _wake_session_lock.acquire(blocking=False):
        _wake_session_started_at = time.monotonic()
        return True
    return False


def pause_wake_listening(seconds: float = 120, *, voice_interrupt: bool = True) -> None:
    global _wake_paused_until
    _wake_paused_until = time.monotonic() + max(5.0, seconds)
    if voice_interrupt:
        interrupt_demo_voice(force=True)


def resume_wake_listening() -> None:
    """问药/问诊结束回首页后恢复「豆包」唤醒。"""
    global _wake_paused_until
    _wake_paused_until = 0.0
    _wake_cancel.clear()


def wake_listening_paused() -> bool:
    return time.monotonic() < _wake_paused_until


def wait_for_wake_session_idle(timeout: float = 8.0) -> bool:
    """等待在途 wake/session 释放锁（拍照/提醒 handoff 前调用）。"""
    acquired = _wake_session_lock.acquire(timeout=max(0.5, timeout))
    if acquired:
        _wake_session_lock.release()
        return True
    return False


def _wake_cancelled() -> bool:
    return _wake_cancel.is_set()


def _wait_wake_until(bridge, total_sec: int = _WAKE_LISTEN_SEC) -> bool:
    """分片等待唤醒，便于 cancel / voice_stop 快速打断。"""
    if _wake_cancelled():
        return False
    remaining = max(1, int(total_sec))
    chunk = 3
    while remaining > 0:
        if _wake_cancelled():
            return False
        step = min(chunk, remaining)
        try:
            if bridge.wait_wake(timeout=step):
                return True
        except DemoBridgeError as exc:
            if _wake_cancelled():
                return False
            lowered = str(exc).lower()
            payload = getattr(exc, "payload", None) or {}
            status_hint = str(payload.get("status") or payload.get("code") or "")
            if "wake timeout" in lowered or status_hint == "504":
                remaining -= step
                continue
            raise
        remaining -= step
    return False


def get_wake_info() -> dict:
    settings = get_settings()
    if not settings["wake_enabled"]:
        return {"ok": True, "enabled": False, "kws_enabled": False, "wake_word": settings["wake_word"]}
    bridge = get_demo_bridge()
    online, busy = update_demo_availability(bridge)
    if not online:
        return {
            "ok": True,
            "enabled": True,
            "kws_enabled": False,
            "wake_word": settings["wake_word"],
            "error": "语音引擎离线，请稍后重试",
        }
    if busy:
        return {
            "ok": True,
            "enabled": True,
            "kws_enabled": True,
            "wake_word": settings["wake_word"],
            "error": None,
        }
    try:
        info = bridge.wake_info()
        return {
            "ok": True,
            "enabled": True,
            "kws_enabled": bool(info.get("kws_enabled")),
            "wake_word": info.get("wake_word") or settings["wake_word"],
        }
    except DemoBridgeError as exc:
        if busy:
            return {
                "ok": True,
                "enabled": True,
                "kws_enabled": True,
                "wake_word": settings["wake_word"],
            }
        return {
            "ok": True,
            "enabled": True,
            "kws_enabled": False,
            "wake_word": settings["wake_word"],
            "error": friendly_demo_error(exc),
        }


def run_wake_session(db: Session) -> dict:
    settings = get_settings()
    if not settings["wake_enabled"]:
        raise HTTPException(status_code=503, detail="关键词唤醒未启用")

    from .demo_bridge import demo_capture_active

    if demo_capture_active():
        raise HTTPException(status_code=503, detail="正在拍照，请稍后再唤醒")

    resume_wake_listening()

    bridge = get_demo_bridge()
    online, _busy = update_demo_availability(bridge, force=True)
    if not online:
        raise HTTPException(status_code=503, detail="语音引擎离线，请稍后重试")

    info = get_wake_info()
    if not info.get("kws_enabled"):
        try:
            raw = bridge.wake_info()
            if raw.get("kws_enabled"):
                info = {**info, "kws_enabled": True, "wake_word": raw.get("wake_word") or info.get("wake_word")}
        except DemoBridgeError:
            pass
    if not info.get("kws_enabled"):
        raise HTTPException(
            status_code=503,
            detail=info.get("error") or "关键词唤醒未就绪，请在板子上运行 setup_sherpa_kws.sh",
        )

    user = db.query(models.User).order_by(models.User.id.asc()).first()
    if not user:
        raise HTTPException(status_code=404, detail="请先创建患者档案")

    if not _acquire_wake_session_lock():
        raise HTTPException(status_code=409, detail="唤醒监听已在进行，请稍候")

    try:
        _wake_cancel.clear()
        _wake_session_active.set()
        if not _wait_wake_until(bridge, _WAKE_LISTEN_SEC):
            if _wake_cancelled():
                raise HTTPException(status_code=499, detail="唤醒已取消")
            raise HTTPException(status_code=408, detail="唤醒超时，请再说一次唤醒词")
        logger.info("wake word detected")
        if tts_is_playing():
            logger.info("wake detected during TTS, stopping playback")
            try:
                stop_active_speech()
                wait_for_tts_idle(3.0)
            except Exception as exc:
                logger.warning("wake stop TTS failed: %s", exc)
        if _wake_cancelled():
            raise HTTPException(status_code=499, detail="唤醒已取消")
        response = {
            "ok": True,
            "wake_word": info.get("wake_word") or settings["wake_word"],
            "intent": "chat",
            "text": "",
            "needs_listen": True,
            "user_id": user.id,
        }
        try:
            tts_speak("我在，请说", wait=False)
        except Exception as exc:
            logger.warning("wake ready TTS failed: %s", exc)
        logger.info("wake detected, defer listen to doctor chat page")
        return response
    except DemoBridgeError as exc:
        if _wake_cancelled():
            raise HTTPException(status_code=499, detail="唤醒已取消") from exc
        detail = friendly_demo_error(exc)
        lowered = str(exc).lower()
        if "refused" in lowered or "connection" in lowered:
            raise HTTPException(status_code=503, detail="语音引擎重启中，请稍候再试") from exc
        if "timed out" in lowered or "timeout" in lowered:
            raise HTTPException(status_code=408, detail="唤醒超时，请再说一次唤醒词") from exc
        raise HTTPException(status_code=503, detail=detail) from exc
    finally:
        _wake_session_active.clear()
        _wake_session_lock.release()
