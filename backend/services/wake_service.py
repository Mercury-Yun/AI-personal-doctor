"""
唤醒服务：后台 KWS 守护线程持续监听「小医」，HTTP 会话只等待唤醒事件。

（与 demo 一致：一个进程里只有一个麦克风监听循环，不会被 HTTP 长连接卡死。）
"""

import logging
import random
import re
import threading
import time
import uuid
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..config import get_settings
from .local_audio import record_wav as local_record_wav
from .local_kws import is_kws_available, run_persistent_listener, kws_prewarm
from .local_asr import is_asr_available, transcribe_wav as local_transcribe
from .listen_filter import is_listen_prompt_echo
from .medication_intent import classify_intent
from .tts_service import (
    speak as tts_speak,
    speak_prompt as tts_speak_prompt,
    stop_active_speech,
    tts_is_playing,
    wait_for_tts_idle,
)

logger = logging.getLogger(__name__)

_wake_cancel = threading.Event()
_wake_paused_until = 0.0
_photo_mode_until = 0.0

# 守护线程：检测到唤醒时递增
_wake_hits = 0
_consumed_hits = 0          # 已被某个 HTTP 会话消费的唤醒计数
_last_wake_at = 0.0         # 最近一次唤醒的 monotonic 时刻
_RECENT_WAKE_WINDOW = 2.5   # 会话启动时，这么多秒内未消费的唤醒直接视为「刚被唤醒」
_wake_cond = threading.Condition()
_daemon_thread: Optional[threading.Thread] = None
_daemon_started = False
_last_ack_spoken_at = 0.0

# HTTP 等待者：新请求抢占旧请求
_waiter_gen = 0
_active_waiter_id: Optional[str] = None


def _wake_cancelled() -> bool:
    return _wake_cancel.is_set()


def cancel_pending_wake() -> None:
    _wake_cancel.set()


def force_reset_wake_session() -> None:
    global _waiter_gen, _active_waiter_id
    with _wake_cond:
        _waiter_gen += 1
        _active_waiter_id = None
        _wake_cancel.set()
        _wake_cond.notify_all()


def cancel_wake_from_client() -> None:
    force_reset_wake_session()


def pause_wake_listening(seconds: float = 120, *, voice_interrupt: bool = True) -> None:
    global _wake_paused_until
    _wake_paused_until = time.monotonic() + max(5.0, seconds)


def resume_wake_listening() -> None:
    global _wake_paused_until
    _wake_paused_until = 0.0
    _wake_cancel.clear()


def wake_listening_paused() -> bool:
    return time.monotonic() < _wake_paused_until


def enter_photo_mode(seconds: float = 180) -> None:
    global _photo_mode_until, _wake_paused_until
    now = time.monotonic()
    _photo_mode_until = now + max(30.0, seconds)
    _wake_paused_until = _photo_mode_until
    cancel_pending_wake()


def leave_photo_mode() -> None:
    global _photo_mode_until, _wake_paused_until
    _photo_mode_until = 0.0
    _wake_paused_until = 0.0


def photo_mode_active() -> bool:
    return time.monotonic() < _photo_mode_until


def force_abort_wake_for_capture() -> None:
    enter_photo_mode(120)


def wait_for_wake_session_idle(timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + max(0.5, timeout)
    while time.monotonic() < deadline:
        with _wake_cond:
            if _active_waiter_id is None:
                return True
        time.sleep(0.15)
    return False


def _daemon_should_listen() -> bool:
    if _wake_cancelled():
        return False
    if wake_listening_paused() or photo_mode_active():
        return False
    settings = get_settings()
    if not settings.get("wake_enabled", True):
        return False
    return True


def _speak_wake_ack_immediate() -> None:
    """检测到唤醒词后立刻播应答，不阻塞监听线程。随机选择亲切用语。"""
    global _last_ack_spoken_at
    _last_ack_spoken_at = time.monotonic()

    _WAKE_ACKS = ("我在呢", "哎，我在", "来了", "嗯，怎么了")

    def _play():
        try:
            ack = random.choice(_WAKE_ACKS)
            tts_speak_prompt(ack, wait=False)
        except Exception as exc:
            logger.warning("wake ack TTS failed: %s", exc)

    threading.Thread(target=_play, daemon=True, name="wake-ack-tts").start()


def _on_wake_detected() -> None:
    global _wake_hits, _last_wake_at
    with _wake_cond:
        _wake_hits += 1
        _last_wake_at = time.monotonic()
        logger.info("wake daemon: detected 小医 (hits=%d)", _wake_hits)
        _wake_cond.notify_all()
    _speak_wake_ack_immediate()


def _wake_daemon_loop() -> None:
    logger.info("wake daemon started")
    while True:
        if not _daemon_should_listen():
            time.sleep(0.25)
            continue
        if not is_kws_available():
            time.sleep(2.0)
            continue
        settings = get_settings()
        wake_word = settings["wake_word"]

        def should_stop():
            return not _daemon_should_listen()

        run_persistent_listener(wake_word, _on_wake_detected, should_stop)


def ensure_wake_daemon() -> None:
    global _daemon_thread, _daemon_started
    if _daemon_started and _daemon_thread and _daemon_thread.is_alive():
        return
    _daemon_started = True
    kws_prewarm()
    _daemon_thread = threading.Thread(target=_wake_daemon_loop, daemon=True, name="wake-daemon")
    _daemon_thread.start()


def _clean_asr_text(text: str) -> str:
    return re.sub(r"<\|[^|]+\|>", "", text or "").strip()


def _listen_question_after_wake(prompt: str = "您说，我听着呢") -> str:
    pause_wake_listening(25)
    # 唤醒应答已在检测瞬间播出，这里只补一句短提示（不等待播完）
    if time.monotonic() - _last_ack_spoken_at > 1.5:
        try:
            tts_speak_prompt("我在呢", wait=False)
        except Exception:
            pass
    else:
        try:
            tts_speak_prompt(prompt, wait=False)
        except Exception:
            pass
    # 等提示音（我在/请说）播完再录音：避免把 TTS 回声录进去，并给用户留出完整说话窗口
    try:
        wait_for_tts_idle(5.0)
    except Exception:
        pass
    time.sleep(0.2)
    record_result = local_record_wav(duration_sec=6.0, prefer_stereo=True)
    if not record_result.get("ok"):
        return ""
    if not is_asr_available():
        return ""
    text = _clean_asr_text(local_transcribe(record_result["path"]).get("text", ""))
    if is_listen_prompt_echo(text, prompt):
        return ""
    logger.info("wake post-listen: %r", text[:80] if text else "")
    return text


def get_wake_info() -> dict:
    settings = get_settings()
    if not settings["wake_enabled"]:
        return {"ok": True, "enabled": False, "kws_enabled": False, "wake_word": settings["wake_word"]}

    ready = is_kws_available()
    with _wake_cond:
        waiting = _active_waiter_id is not None
    return {
        "ok": True,
        "enabled": True,
        "kws_enabled": ready,
        "wake_word": settings["wake_word"],
        "listening": waiting,
        "error": None if ready else "KWS 唤醒加载中，请稍候",
    }


def _wait_for_next_wake(waiter_id: str, waiter_gen: int, hits_at_start: int) -> None:
    deadline = time.monotonic() + 600.0
    while time.monotonic() < deadline:
        if _wake_cancelled():
            raise HTTPException(status_code=499, detail="唤醒已取消")
        with _wake_cond:
            if waiter_gen != _waiter_gen:
                raise HTTPException(status_code=499, detail="唤醒已取消")
            if _active_waiter_id != waiter_id:
                raise HTTPException(status_code=499, detail="唤醒已取消")
            if _wake_hits > hits_at_start:
                return
            _wake_cond.wait(timeout=0.2)
    raise HTTPException(status_code=504, detail="等待唤醒超时")


def run_wake_session(db: Session) -> dict:
    global _waiter_gen, _active_waiter_id, _wake_hits, _consumed_hits

    settings = get_settings()
    if not settings["wake_enabled"]:
        raise HTTPException(status_code=503, detail="唤醒功能未启用")
    if not is_kws_available():
        raise HTTPException(status_code=503, detail="KWS 唤醒未就绪，请稍候")

    if photo_mode_active():
        leave_photo_mode()

    resume_wake_listening()
    ensure_wake_daemon()

    user = db.query(models.User).order_by(models.User.id.asc()).first()
    if not user:
        raise HTTPException(status_code=404, detail="请先创建患者档案")

    waiter_id = uuid.uuid4().hex
    with _wake_cond:
        _waiter_gen += 1
        waiter_gen = _waiter_gen
        _active_waiter_id = waiter_id
        # 若会话间隙里刚发生过、但没有会话消费的唤醒（用户已喊「小医」并听到「我在」），
        # 本次会话就从「已消费点」起算，使唤醒条件立即成立 → 直接进入「请说」+录音，
        # 避免因长轮询恰好不在飞行中而漏掉这次唤醒。
        if _wake_hits > _consumed_hits and (time.monotonic() - _last_wake_at) <= _RECENT_WAKE_WINDOW:
            hits_at_start = _consumed_hits
        else:
            hits_at_start = _wake_hits
        _wake_cancel.clear()
        _wake_cond.notify_all()

    logger.info("wake session wait start id=%s hits=%d", waiter_id[:8], hits_at_start)
    try:
        _wait_for_next_wake(waiter_id, waiter_gen, hits_at_start)
        with _wake_cond:
            _consumed_hits = _wake_hits
        logger.info("wake word detected for session %s", waiter_id[:8])

        if tts_is_playing():
            try:
                stop_active_speech()
                wait_for_tts_idle(3.0)
            except Exception as exc:
                logger.warning("wake stop TTS failed: %s", exc)

        heard_text = _listen_question_after_wake("请说")
        intent = classify_intent(heard_text)
        photo_prep = False
        if intent == "photo":
            try:
                enter_photo_mode(180)
                photo_prep = photo_mode_active()
            except Exception as exc:
                logger.warning("wake photo pre-enter failed: %s", exc)

        response = {
            "ok": True,
            "wake_word": settings["wake_word"],
            "intent": intent,
            "text": heard_text,
            "needs_listen": not bool(heard_text),
            "user_id": user.id,
            "photo_prep": photo_prep,
        }
        logger.info("wake session complete intent=%s text=%r", intent, heard_text[:80] if heard_text else "")
        return response
    finally:
        with _wake_cond:
            if _active_waiter_id == waiter_id:
                _active_waiter_id = None
            resume_wake_listening()
            _wake_cond.notify_all()
