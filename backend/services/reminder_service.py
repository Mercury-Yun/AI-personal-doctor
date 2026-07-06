import asyncio
import logging
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, joinedload

from .. import models
from ..config import get_settings
from ..database import SessionLocal
from .cloud_tts_service import CloudTtsError
from .medication_times import parse_take_times
from .notify_service import notify_medication_overdue
from .tts_service import speak as tts_speak

logger = logging.getLogger(__name__)

_scheduler_task: asyncio.Task | None = None
_reminder_tts_pause_until = 0.0
_reminder_pause_lock = threading.Lock()
_reminder_speak_lock = threading.Lock()


def pause_reminder_tts(seconds: float = 300) -> None:
    """问药/拍照期间暂停用药提醒播报，避免与问药语音重叠。"""
    global _reminder_tts_pause_until
    with _reminder_pause_lock:
        _reminder_tts_pause_until = time.monotonic() + max(1.0, seconds)


def resume_reminder_tts() -> None:
    """恢复用药提醒播报（离开拍照页或手动恢复）。"""
    global _reminder_tts_pause_until
    with _reminder_pause_lock:
        _reminder_tts_pause_until = 0.0


def reminder_tts_paused() -> bool:
    with _reminder_pause_lock:
        return time.monotonic() < _reminder_tts_pause_until


def _reminder_tz() -> ZoneInfo:
    settings = get_settings()
    try:
        return ZoneInfo(settings["reminder_tz"])
    except Exception:
        return ZoneInfo("Asia/Shanghai")


def _now_local() -> datetime:
    return datetime.now(_reminder_tz())


def _today_str() -> str:
    return _now_local().date().isoformat()


def _now_hhmm() -> str:
    return _now_local().strftime("%H:%M")


def _dose_index(medication: models.Medication, take_time: str) -> tuple[int, int]:
    times = sorted(parse_take_times(medication))
    total = max(1, len(times))
    try:
        index = times.index(take_time) + 1
    except ValueError:
        index = 1
    return index, total


def build_reminder_message(
    medication: models.Medication, user: models.User | None, take_time: str
) -> str:
    user_name = user.name if user else "您"
    dose_index, dose_total = _dose_index(medication, take_time)
    parts = [
        f"{user_name}，现在是今天第{dose_index}次吃药，一共{dose_total}次。",
        f"请服用{medication.name}",
    ]
    if medication.dosage:
        parts.append(f"，剂量 {medication.dosage}")
    if medication.note:
        parts.append(f"，{medication.note}")
    else:
        parts.append("，请遵医嘱")
    parts.append("。请在屏幕中间点「我已吃药」确认；不确定是哪个药，可以点「拍照确认」。")
    return "".join(parts)


def build_repeat_reminder_message(
    medication: models.Medication, user: models.User | None, take_time: str
) -> str:
    user_name = user.name if user else "您"
    dose_index, dose_total = _dose_index(medication, take_time)
    parts = [
        f"{user_name}，吃药提醒还没确认。",
        f"今天是第{dose_index}次，共{dose_total}次，请服用{medication.name}",
    ]
    if medication.dosage:
        parts.append(f"，剂量 {medication.dosage}")
    parts.append("。请点屏幕「我已吃药」确认；不确定请点「拍照确认」。")
    return "".join(parts)


def get_reminder_public_settings() -> dict:
    settings = get_settings()
    repeat_sec = max(20, settings.get("reminder_repeat_sec", 45))
    return {
        "repeat_sec": repeat_sec,
        "repeat_minutes": max(1, settings["reminder_repeat_minutes"]),
        "check_interval_sec": max(10, settings["reminder_check_interval_sec"]),
    }


_last_overlay_speak_mono = 0.0


def _as_local_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(_reminder_tz()).replace(tzinfo=None)
    return value


def get_pending_reminder_for_verify(db: Session, user_id: int) -> dict | None:
    """返回当前待确认服用的药物（已提醒/到点且未标记已服）。"""
    schedule_date = _today_str()
    current_minute = _now_hhmm()
    medications = (
        db.query(models.Medication)
        .options(joinedload(models.Medication.user))
        .filter(models.Medication.user_id == user_id)
        .all()
    )

    candidates: list[dict] = []
    for medication in medications:
        for take_time in parse_take_times(medication):
            log = (
                db.query(models.MedicationReminderLog)
                .filter(
                    models.MedicationReminderLog.medication_id == medication.id,
                    models.MedicationReminderLog.schedule_date == schedule_date,
                    models.MedicationReminderLog.schedule_time == take_time,
                )
                .first()
            )
            status = log.status if log else "pending"
            if status == "taken":
                continue
            if status not in ("due", "notified") and not (status == "pending" and take_time <= current_minute):
                continue
            candidates.append(
                {
                    "medication_id": medication.id,
                    "user_id": medication.user_id,
                    "name": medication.name,
                    "dosage": medication.dosage,
                    "take_time": take_time,
                    "dose_index": _dose_index(medication, take_time)[0],
                    "dose_total": _dose_index(medication, take_time)[1],
                    "status": status,
                    "notified_at": log.notified_at if log and log.notified_at else None,
                }
            )

    if not candidates:
        return None

    def sort_key(item: dict):
        notified_ts = item["notified_at"].timestamp() if item["notified_at"] else 0
        status_rank = 0 if item["status"] == "notified" else 1
        return (status_rank, -notified_ts, item["take_time"])

    candidates.sort(key=sort_key)
    return candidates[0]


def get_or_create_log(db: Session, medication: models.Medication, schedule_time: str) -> models.MedicationReminderLog:
    schedule_date = _today_str()
    log = (
        db.query(models.MedicationReminderLog)
        .filter(
            models.MedicationReminderLog.medication_id == medication.id,
            models.MedicationReminderLog.schedule_date == schedule_date,
            models.MedicationReminderLog.schedule_time == schedule_time,
        )
        .first()
    )
    if log is None:
        log = models.MedicationReminderLog(
            medication_id=medication.id,
            user_id=medication.user_id,
            schedule_date=schedule_date,
            schedule_time=schedule_time,
            status="pending",
        )
        db.add(log)
        db.flush()
    return log


def list_today_reminders(db: Session) -> list[dict]:
    schedule_date = _today_str()
    current_minute = _now_hhmm()
    medications = (
        db.query(models.Medication)
        .options(joinedload(models.Medication.user))
        .order_by(models.Medication.id.asc())
        .all()
    )

    items: list[dict] = []
    for medication in medications:
        for take_time in parse_take_times(medication):
            log = (
                db.query(models.MedicationReminderLog)
                .filter(
                    models.MedicationReminderLog.medication_id == medication.id,
                    models.MedicationReminderLog.schedule_date == schedule_date,
                    models.MedicationReminderLog.schedule_time == take_time,
                )
                .first()
            )
            status = log.status if log else "pending"
            if status != "taken" and take_time <= current_minute:
                display_status = "due" if status == "pending" else status
            else:
                display_status = status
            dose_index, dose_total = _dose_index(medication, take_time)
            items.append(
                {
                    "medication_id": medication.id,
                    "user_id": medication.user_id,
                    "user_name": medication.user.name if medication.user else "",
                    "name": medication.name,
                    "dosage": medication.dosage,
                    "frequency": medication.frequency,
                    "take_time": take_time,
                    "dose_index": dose_index,
                    "dose_total": dose_total,
                    "note": medication.note,
                    "status": display_status,
                    "notified_at": log.notified_at.isoformat() if log and log.notified_at else None,
                    "taken_at": log.taken_at.isoformat() if log and log.taken_at else None,
                }
            )
    items.sort(key=lambda item: (item["take_time"], item["medication_id"]))
    return items


def list_pending_reminders(db: Session, user_id: int | None = None) -> list[dict]:
    """返回当前到点且未确认服用的提醒（用于全屏弹层）。"""
    pending = [
        item
        for item in list_today_reminders(db)
        if item["status"] in ("due", "notified")
    ]
    if user_id is not None:
        pending = [item for item in pending if item["user_id"] == user_id]

    def sort_key(item: dict):
        status_rank = 0 if item["status"] == "notified" else 1
        return (status_rank, item["take_time"], item["medication_id"])

    pending.sort(key=sort_key)
    return pending


def build_intake_log_summary(db: Session, user_id: int, days: int = 7) -> str:
    """近几日服药记录摘要，供 AI 判断该不该吃、是否漏服。"""
    days = max(1, min(days, 14))
    end_date = _now_local().date()
    start_date = end_date - timedelta(days=days - 1)
    start_str = start_date.isoformat()
    end_str = end_date.isoformat()

    logs = (
        db.query(models.MedicationReminderLog)
        .options(joinedload(models.MedicationReminderLog.medication))
        .filter(
            models.MedicationReminderLog.user_id == user_id,
            models.MedicationReminderLog.schedule_date >= start_str,
            models.MedicationReminderLog.schedule_date <= end_str,
        )
        .order_by(
            models.MedicationReminderLog.schedule_date.desc(),
            models.MedicationReminderLog.schedule_time.asc(),
        )
        .all()
    )
    if not logs:
        return "近7日服药记录：暂无记录。"

    today = _today_str()
    current_minute = _now_hhmm()
    lines: list[str] = []
    for log in logs:
        med = log.medication
        name = med.name if med else f"药物#{log.medication_id}"
        dosage = med.dosage if med and med.dosage else ""
        label = f"{name}{(' ' + dosage) if dosage else ''}"
        if log.status == "taken" and log.taken_at:
            state = f"已服（{log.taken_at.strftime('%H:%M')}确认）"
        elif log.schedule_date == today and log.schedule_time <= current_minute:
            state = "到点待确认" if log.status in ("pending", "notified", "due") else "待服"
        elif log.schedule_date < today or (
            log.schedule_date == today and log.schedule_time <= current_minute
        ):
            state = "漏服/未确认" if log.status != "taken" else "已服"
        else:
            state = "未到点"
        lines.append(f"- {log.schedule_date} {log.schedule_time} {label}：{state}")

    return "近7日服药记录（供判断该不该吃、是否重复/漏服）：\n" + "\n".join(lines[:40])


def try_ack_from_verify_answer(db: Session, user_id: int, answer: str) -> dict | None:
    """拍照验药回答若确认是该吃的药，自动标记已服。"""
    from backend.services.medication_intent import classify_verify_answer

    pending = get_pending_reminder_for_verify(db, user_id)
    if not pending:
        return None
    normalized = (answer or "").strip()
    if not normalized:
        return None
    expected = pending.get("name") or ""
    if classify_verify_answer(normalized, expected) != "correct":
        return None
    try:
        log = mark_taken(db, pending["medication_id"], pending["take_time"])
        return {
            "medication_id": pending["medication_id"],
            "take_time": pending["take_time"],
            "name": pending.get("name"),
            "taken_at": log.taken_at.isoformat() if log.taken_at else None,
        }
    except ValueError:
        return None


def mark_taken(db: Session, medication_id: int, schedule_time: str | None = None) -> models.MedicationReminderLog:
    medication = db.get(models.Medication, medication_id)
    if not medication:
        raise ValueError("Medication not found")

    times = parse_take_times(medication)
    if not times:
        raise ValueError("Medication has no take_time")

    take_time = (schedule_time or "").strip()
    if not take_time:
        if len(times) == 1:
            take_time = times[0]
        else:
            raise ValueError("请指定要确认的服用时间")
    if take_time not in times:
        raise ValueError("无效的服用时间")

    log = get_or_create_log(db, medication, take_time)
    log.status = "taken"
    log.taken_at = _now_local().replace(tzinfo=None)
    db.commit()
    db.refresh(log)
    return log


def _should_notify(log: models.MedicationReminderLog, repeat_sec: int) -> bool:
    if log.status == "taken":
        return False
    if log.status == "pending":
        return True
    if log.status != "notified" or log.notified_at is None:
        return False
    notified_at = _as_local_naive(log.notified_at)
    now = _now_local().replace(tzinfo=None)
    if notified_at is None:
        return False
    gap = max(20, repeat_sec)
    return (now - notified_at).total_seconds() >= gap


def _repeat_sec() -> int:
    settings = get_settings()
    return max(20, settings.get("reminder_repeat_sec", 45))


def _speak_reminder_for_log(
    db: Session,
    medication: models.Medication,
    take_time: str,
    log: models.MedicationReminderLog,
) -> dict | None:
    if reminder_tts_paused():
        return None
    is_repeat = log.status == "notified" and log.notified_at is not None
    message = (
        build_repeat_reminder_message(medication, medication.user, take_time)
        if is_repeat
        else build_reminder_message(medication, medication.user, take_time)
    )
    try:
        with _reminder_speak_lock:
            if reminder_tts_paused():
                return None
            tts_speak(message, wait=True)
        log.status = "notified"
        log.notified_at = _now_local().replace(tzinfo=None)
        db.commit()
        return {
            "medication_id": medication.id,
            "name": medication.name,
            "take_time": take_time,
            "message": message,
            "status": log.status,
            "repeat": is_repeat,
        }
    except CloudTtsError as exc:
        db.rollback()
        logger.warning("Reminder TTS failed for %s: %s", medication.name, exc)
    except Exception as exc:
        db.rollback()
        logger.exception("Reminder failed for %s: %s", medication.name, exc)
    return None


def speak_active_reminder(db: Session, *, force: bool = False) -> dict:
    """播报当前待确认提醒；force 供弹窗循环调用，间隔 repeat_sec。"""
    global _last_overlay_speak_mono
    settings = get_settings()
    if not settings["reminder_enabled"]:
        return {"ok": False, "reason": "disabled"}
    if reminder_tts_paused():
        return {"ok": False, "reason": "paused"}

    repeat_sec = _repeat_sec()
    now_mono = time.monotonic()
    min_gap = max(20, repeat_sec - 3)
    if force and now_mono - _last_overlay_speak_mono < min_gap:
        return {"ok": False, "reason": "too_soon"}

    pending = list_pending_reminders(db)
    if not pending:
        return {"ok": False, "reason": "none"}

    item = pending[0]
    medication = db.get(models.Medication, item["medication_id"])
    if medication is None:
        return {"ok": False, "reason": "not_found"}

    log = get_or_create_log(db, medication, item["take_time"])
    if log.status == "taken":
        return {"ok": False, "reason": "taken"}
    if not force and not _should_notify(log, repeat_sec):
        return {"ok": False, "reason": "not_due"}

    spoken = _speak_reminder_for_log(db, medication, item["take_time"], log)
    if spoken:
        _last_overlay_speak_mono = now_mono
        return {"ok": True, **spoken}
    return {"ok": False, "reason": "tts_failed"}


def nudge_due_reminders(db: Session) -> dict:
    """未确认且到达重复间隔时播一次（前端 overlay 可定时调用）。"""
    result = speak_active_reminder(db, force=False)
    if result.get("ok"):
        logger.info(
            "Reminder nudge for %s at %s (repeat=%s)",
            result.get("name"),
            result.get("take_time"),
            result.get("repeat"),
        )
    return result


def check_and_notify_due_reminders(db: Session) -> list[dict]:
    settings = get_settings()
    if not settings["reminder_enabled"]:
        return []

    repeat_sec = _repeat_sec()
    current_minute = _now_hhmm()
    medications = (
        db.query(models.Medication)
        .options(joinedload(models.Medication.user))
        .order_by(models.Medication.id.asc())
        .all()
    )

    triggered: list[dict] = []
    for medication in medications:
        for take_time in parse_take_times(medication):
            if take_time > current_minute:
                continue

            log = get_or_create_log(db, medication, take_time)
            if log.status == "taken":
                continue

            # 用药逾期微信推送：已通知超过 N 分钟仍未确认
            if log.status == "notified" and log.notified_at is not None:
                overdue_minutes = settings.get("notify_overdue_minutes", 15)
                notified_at = _as_local_naive(log.notified_at)
                now = _now_local().replace(tzinfo=None)
                if notified_at and (now - notified_at).total_seconds() >= overdue_minutes * 60:
                    user_name = medication.user.name if medication.user else "患者"
                    notify_medication_overdue(
                        user_name=user_name,
                        med_name=medication.name,
                        take_time=take_time,
                        dosage=medication.dosage or "",
                        overdue_minutes=overdue_minutes,
                    )

            if not _should_notify(log, repeat_sec):
                continue

            spoken = _speak_reminder_for_log(db, medication, take_time, log)
            if spoken:
                triggered.append(spoken)
                logger.info(
                    "Reminder spoken for %s at %s (now %s, repeat=%s)",
                    medication.name,
                    take_time,
                    current_minute,
                    spoken.get("repeat"),
                )
    return triggered


async def _reminder_loop():
    settings = get_settings()
    interval = max(10, settings["reminder_check_interval_sec"])
    while True:
        try:
            await asyncio.to_thread(_run_reminder_tick)
        except Exception:
            logger.exception("Reminder scheduler tick failed")
        await asyncio.sleep(interval)


def _run_reminder_tick() -> None:
    db = SessionLocal()
    try:
        check_and_notify_due_reminders(db)
    finally:
        db.close()


def start_reminder_scheduler():
    global _scheduler_task
    if _scheduler_task is not None:
        return
    _scheduler_task = asyncio.create_task(_reminder_loop())
    logger.info("Medication reminder scheduler started")


def stop_reminder_scheduler():
    global _scheduler_task
    if _scheduler_task is None:
        return
    _scheduler_task.cancel()
    _scheduler_task = None
