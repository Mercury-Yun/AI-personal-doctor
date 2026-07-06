import os
import time
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import (
    DeviceCameraCaptureResponse,
    DeviceListenRequest,
    DeviceSpeakRequest,
    DeviceStatusResponse,
    IntentClassifyRequest,
    IntentClassifyResponse,
    PhotoSessionIntentRequest,
    PhotoSessionIntentResponse,
    TodayReminderItem,
    WakeInfoResponse,
    WakeSessionResponse,
)
from ..services.local_camera import capture_photo as local_capture_photo
from ..services.local_camera import get_camera_stream
from ..services.local_audio import record_wav as local_record_wav
from ..services.local_asr import transcribe_wav as local_transcribe, asr_prewarm, is_asr_available
from ..services.local_kws import listener_running as kws_listener_running
from ..services.listen_filter import is_listen_prompt_echo
from ..services.medication_intent import classify_intent, classify_photo_session_action
from ..services.reminder_service import (
    get_reminder_public_settings,
    list_pending_reminders,
    list_today_reminders,
    mark_taken,
    nudge_due_reminders,
    pause_reminder_tts,
    resume_reminder_tts,
    speak_active_reminder,
)
from ..services.tts_service import (
    speak as tts_speak,
    speak_or_raise,
    stop_active_speech,
    tts_enabled,
    tts_is_playing,
    tts_recently_active,
    tts_source,
    use_cloud_tts,
    wait_for_tts_idle,
)
from ..services.wake_service import (
    cancel_pending_wake,
    enter_photo_mode,
    get_wake_info,
    leave_photo_mode,
    pause_wake_listening,
    photo_mode_active,
    resume_wake_listening,
    run_wake_session,
)

router = APIRouter(prefix="/device", tags=["device"])


@router.get("/status", response_model=DeviceStatusResponse)
def device_status():
    """
    云端化后的状态接口（不再依赖 demo）
    """
    payload = {
        "online": True,                    # 云端服务只要网络可用就在线
        "demo_busy": False,
        "capture_active": False,           # 拍照状态由前端管理
        "photo_mode": photo_mode_active(),
        "voice_mode": False,
        "tts_enabled": tts_enabled(),
        "tts_source": tts_source(),
        "tts_busy": tts_is_playing(),
        "tts_playing": tts_is_playing(),
        "demo_url": "",
        "error": None,
    }
    return payload


@router.get("/wake/info", response_model=WakeInfoResponse)
def wake_info():
    return get_wake_info()


@router.post("/wake/session", response_model=WakeSessionResponse)
def wake_session(db: Session = Depends(get_db)):
    return run_wake_session(db)


@router.post("/wake/cancel")
def wake_cancel():
    from ..services.wake_service import cancel_wake_from_client

    cancel_wake_from_client()
    return {"ok": True}


@router.post("/wake/reset")
def wake_reset():
    from ..services.wake_service import force_reset_wake_session

    force_reset_wake_session()
    return {"ok": True}


class WakePauseRequest(BaseModel):
    seconds: int = 120
    interrupt: bool = True


@router.post("/wake/pause")
def wake_pause(body: WakePauseRequest = WakePauseRequest()):
    pause_wake_listening(max(30, body.seconds), voice_interrupt=body.interrupt)
    if body.interrupt:
        cancel_pending_wake()
    return {"ok": True, "paused_seconds": body.seconds}


@router.post("/wake/resume")
def wake_resume():
    resume_wake_listening()
    return {"ok": True}


@router.post("/intent/classify", response_model=IntentClassifyResponse)
def device_intent_classify(body: IntentClassifyRequest):
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    return {"ok": True, "intent": classify_intent(text), "text": text}


@router.post("/intent/photo-session", response_model=PhotoSessionIntentResponse)
def device_photo_session_intent(body: PhotoSessionIntentRequest):
    text = (body.text or "").strip()
    return {
        "ok": True,
        "action": classify_photo_session_action(text, body.has_photo),
        "text": text,
    }


def _wait_kws_mic_released(timeout: float = 2.5) -> None:
    """等待 KWS 常驻 arecord 退出并释放 ALSA 设备后再录音。"""
    deadline = time.monotonic() + max(0.3, timeout)
    while time.monotonic() < deadline:
        if not kws_listener_running():
            time.sleep(0.25)  # 给 ALSA 设备完全释放留一点余量
            return
        time.sleep(0.1)
    logger.warning("device_listen: KWS 常驻监听未在 %.1fs 内释放麦克风", timeout)


@router.post("/listen")
def device_listen(body: DeviceListenRequest = DeviceListenRequest()):
    """
    本地麦克风录音 + DashScope ASR 转文字
    """
    # KWS 常驻监听独占麦克风（arecord -D plughw:1,0）。录音前必须暂停唤醒守护并等它
    # 释放设备，否则新的 arecord 抢不到设备 -> 503「设备不支持录音」（问诊连续对话之前
    # 就卡在这里）。暂停窗口 45s：连续对话每轮都会再调本接口而续期，整段会话期间 KWS
    # 保持关闭；会话结束回首页时 stopPhotoMode()/超时会自动恢复唤醒。
    pause_wake_listening(45)
    _wait_kws_mic_released(2.5)

    # 1. 录音（默认 6 秒，立体声）
    record_result = local_record_wav(duration_sec=6.0, channels=2)
    if not record_result.get("ok"):
        raise HTTPException(status_code=503, detail=record_result.get("error", "录音失败"))

    wav_path = record_result.get("path")

    # 2. 调用本地 Sherpa ASR
    if not is_asr_available():
        logger.warning("ASR 模型不可用，跳过语音识别")
        return {"ok": True, "text": "", "wav_path": wav_path, "note": "ASR 模型未加载"}

    asr_result = local_transcribe(wav_path)
    text = asr_result.get("text", "").strip() if asr_result.get("ok") else ""

    # 3. 过滤提示语回声（如果有）
    if is_listen_prompt_echo(text, body.speak_first):
        text = ""

    return {"ok": True, "text": text, "wav_path": wav_path}


@router.post("/camera/reset")
def camera_reset():
    # 云端化后不需要 demo 的恢复逻辑
    return {"ok": True}


@router.post("/photo/mode/start")
def photo_mode_start(body: WakePauseRequest = WakePauseRequest()):
    if body.interrupt:
        try:
            stop_active_speech()
            wait_for_tts_idle(2.0)
        except Exception:
            pass
    enter_photo_mode(max(60, body.seconds))
    return {"ok": True, "seconds": body.seconds}


@router.post("/photo/mode/stop")
def photo_mode_stop():
    leave_photo_mode()
    return {"ok": True}


@router.post("/camera/stream/start")
def camera_stream_start():
    """启动摄像头实时流"""
    stream = get_camera_stream()
    stream.start()
    return {"ok": True, "streaming": stream.is_running}


@router.get("/camera/stream")
def camera_stream():
    """MJPEG 实时视频流"""
    stream = get_camera_stream()
    if not stream.is_running:
        stream.start()
        import time as _time
        _time.sleep(0.5)  # 等待摄像头初始化
    return StreamingResponse(
        stream.generate_mjpeg(fps=15),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@router.post("/camera/stream/stop")
def camera_stream_stop():
    """停止摄像头实时流"""
    stream = get_camera_stream()
    stream.stop()
    return {"ok": True, "streaming": stream.is_running}


@router.post("/camera/capture", response_model=DeviceCameraCaptureResponse)
def camera_capture():
    try:
        stop_active_speech()
    except Exception:
        pass

    # 如果实时流正在运行，直接从流中截帧
    stream = get_camera_stream()
    if stream.is_running:
        result = stream.snapshot()
    else:
        cam_idx = int(os.getenv("CAMERA_DEVICE_INDEX", "11"))
        result = local_capture_photo(preferred="auto", width=1280, height=720, device_index=cam_idx)

    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "拍照失败"))

    return {
        "ok": True,
        "width": int(result.get("width") or 0),
        "height": int(result.get("height") or 0),
        "path": result.get("path"),
    }


@router.get("/camera/last/image")
def camera_last_image():
    # 简单实现：返回最近一次拍照的文件（由 local_camera 保存到 /tmp）
    # 实际项目中建议在 capture 后记录 last_path
    capture_dir = "/tmp/ai_doctor_captures"
    try:
        files = sorted(Path(capture_dir).glob("capture_*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            raise HTTPException(status_code=404, detail="没有可用的照片")
        latest = files[0]
        data = latest.read_bytes()
        return Response(content=data, media_type="image/jpeg")
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/speak")
def device_speak(body: DeviceSpeakRequest):
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    try:
        if body.wait:
            stop_active_speech()
            wait_for_tts_idle(5.0)
        result = speak_or_raise(body.text.strip(), wait=body.wait)
        return {"ok": True, "result": result, "source": tts_source()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/speak/stop")
def device_speak_stop():
    try:
        result = stop_active_speech()
        return {"ok": True, "result": result, "source": tts_source()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/voice/start")
def device_voice_start():
    # 云端化后不再需要本地 voice mode
    return {"ok": True, "skipped": True, "reason": "cloud-only mode"}


@router.post("/voice/stop")
def device_voice_stop():
    # 云端化后不再需要本地 voice mode
    return {"ok": True, "skipped": True, "reason": "cloud-only mode"}


@router.get("/reminders/settings")
def reminders_settings():
    return {"ok": True, **get_reminder_public_settings()}


@router.post("/reminders/nudge")
def reminders_nudge(db: Session = Depends(get_db)):
    return nudge_due_reminders(db)


@router.post("/reminders/speak-now")
def reminders_speak_now(db: Session = Depends(get_db)):
    """弹窗显示时强制播报（按 repeat_sec 间隔重复）。"""
    return speak_active_reminder(db, force=True)


@router.post("/reminders/resume-tts")
def reminders_resume_tts():
    resume_reminder_tts()
    return {"ok": True}


@router.get("/reminders/today", response_model=list[TodayReminderItem])
def reminders_today(db: Session = Depends(get_db)):
    return list_today_reminders(db)


@router.get("/reminders/pending", response_model=list[TodayReminderItem])
def reminders_pending(user_id: int | None = None, db: Session = Depends(get_db)):
    return list_pending_reminders(db, user_id=user_id)


class ReminderAckRequest(BaseModel):
    medication_id: int
    take_time: str | None = None


class ReminderPauseTtsRequest(BaseModel):
    seconds: int = 300


@router.post("/reminders/pause-tts")
def reminders_pause_tts(body: ReminderPauseTtsRequest = ReminderPauseTtsRequest()):
    pause_reminder_tts(max(30, body.seconds))
    try:
        stop_active_speech()
    except Exception:
        pass
    return {"ok": True, "paused_seconds": body.seconds}


@router.post("/reminders/ack")
def reminders_ack(body: ReminderAckRequest, db: Session = Depends(get_db)):
    try:
        log = mark_taken(db, body.medication_id, body.take_time)
        return {
            "ok": True,
            "medication_id": body.medication_id,
            "status": log.status,
            "taken_at": log.taken_at.isoformat() if log.taken_at else None,
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sos")
def device_sos():
    """SOS 紧急求助：推送消息到家属微信。"""
    from ..services.notify_service import send_sos_alert
    result = send_sos_alert()
    if not result["ok"]:
        raise HTTPException(status_code=429, detail=result["message"])
    return result
