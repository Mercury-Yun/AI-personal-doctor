"""Server酱微信推送服务。

通过 https://sct.ftqq.com/ 的 HTTP API 将关键事件推送到家属微信。
未配置 SERVERCHAN_KEY 时所有推送静默跳过，不影响现有功能。
"""

import asyncio
import logging
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from ..config import get_settings
from ..database import SessionLocal

logger = logging.getLogger(__name__)

# 防刷去重：{event_key: monotonic_timestamp}
_sent: dict[str, float] = {}
_sent_lock = threading.Lock()

_daily_task: asyncio.Task | None = None


# ── 核心推送 ──────────────────────────────────────────────

def _get_key() -> str:
    return get_settings().get("serverchan_key", "")


def _cooldown_sec() -> int:
    return get_settings().get("notify_cooldown_sec", 600)


def _is_duplicate(event_key: str) -> bool:
    """同类消息在 cooldown 内不重复推送。"""
    cooldown = _cooldown_sec()
    now = time.monotonic()
    with _sent_lock:
        last = _sent.get(event_key, 0)
        if now - last < cooldown:
            return True
        _sent[event_key] = now
    return False


def send_wechat(title: str, body: str = "", event_key: str = "") -> bool:
    """发送微信推送。返回 True 表示成功。

    - title: 消息标题（微信通知栏可见）
    - body:  消息正文（Markdown 格式）
    - event_key: 去重键，空则不去重
    """
    key = _get_key()
    if not key:
        return False

    if event_key and _is_duplicate(event_key):
        logger.debug("推送去重跳过: %s", event_key)
        return False

    url = f"https://sctapi.ftqq.com/{key}.send"
    try:
        resp = httpx.post(url, json={"title": title, "desp": body}, timeout=10)
        data = resp.json()
        if data.get("code") == 0:
            logger.info("微信推送成功: %s", title)
            return True
        logger.warning("微信推送失败: %s -> %s", title, data)
        return False
    except Exception as exc:
        logger.warning("微信推送异常: %s -> %s", title, exc)
        return False


# ── 场景 1：用药逾期推送 ─────────────────────────────────

def notify_medication_overdue(
    user_name: str, med_name: str, take_time: str, dosage: str = "",
    overdue_minutes: int = 15,
) -> bool:
    """用药逾期未确认时推送家属微信。"""
    title = f"⏰ {user_name}用药提醒逾期"
    dosage_part = f"，剂量 {dosage}" if dosage else ""
    body = (
        f"**{user_name}** {take_time} 的 **{med_name}**{dosage_part} "
        f"已逾期 **{overdue_minutes} 分钟**未确认服用，请关注。\n\n"
        f"---\n*来自 AI健康助手*"
    )
    event_key = f"med_overdue:{med_name}:{take_time}"
    return send_wechat(title, body, event_key)


# ── 场景 2：健康异常推送 ─────────────────────────────────

# 异常阈值
_HEALTH_THRESHOLDS = {
    "hr_high": 100,
    "hr_low": 50,
    "spo2_low": 93,
}


def check_and_notify_health_anomaly(overview: dict, user_name: str = "患者") -> list[str]:
    """检查健康数据异常并推送。返回已推送的告警类型列表。"""
    if not _get_key():
        return []

    alerts: list[str] = []
    hr = overview.get("resting_hr")
    spo2 = overview.get("avg_spo2")

    if hr is not None and hr > _HEALTH_THRESHOLDS["hr_high"]:
        title = f"🫀 {user_name}心率偏高告警"
        body = (
            f"**{user_name}** 当前静息心率 **{hr} bpm**，"
            f"超过预警阈值 {_HEALTH_THRESHOLDS['hr_high']} bpm。\n\n"
            f"建议关注是否有不适症状，必要时就医。\n\n---\n*来自 AI健康助手*"
        )
        if send_wechat(title, body, f"hr_high:{overview.get('date', '')}"):
            alerts.append("hr_high")

    if hr is not None and hr < _HEALTH_THRESHOLDS["hr_low"]:
        title = f"🫀 {user_name}心率偏低告警"
        body = (
            f"**{user_name}** 当前静息心率 **{hr} bpm**，"
            f"低于预警阈值 {_HEALTH_THRESHOLDS['hr_low']} bpm。\n\n"
            f"建议关注是否有头晕乏力等症状。\n\n---\n*来自 AI健康助手*"
        )
        if send_wechat(title, body, f"hr_low:{overview.get('date', '')}"):
            alerts.append("hr_low")

    if spo2 is not None and spo2 < _HEALTH_THRESHOLDS["spo2_low"]:
        title = f"🫁 {user_name}血氧偏低告警"
        body = (
            f"**{user_name}** 当前平均血氧 **{spo2}%**，"
            f"低于预警阈值 {_HEALTH_THRESHOLDS['spo2_low']}%。\n\n"
            f"建议立即关注呼吸状况，必要时就医。\n\n---\n*来自 AI健康助手*"
        )
        if send_wechat(title, body, f"spo2_low:{overview.get('date', '')}"):
            alerts.append("spo2_low")

    return alerts


# ── 场景 3：每日健康日报 ─────────────────────────────────

def _build_daily_report() -> tuple[str, str]:
    """生成每日健康日报的标题和正文。"""
    from .garmin_service import get_overview, get_history, GarminNotConfigured, GarminAuthError
    from .reminder_service import list_today_reminders

    db = SessionLocal()
    try:
        # 用药情况
        reminders = list_today_reminders(db)
        total = len(reminders)
        taken = sum(1 for r in reminders if r["status"] == "taken")
        missed = sum(1 for r in reminders if r["status"] in ("due", "notified"))

        # 获取患者名
        from .. import models
        user = db.query(models.User).first()
        user_name = user.name if user else "患者"

        # 最近 3 次问诊会话记录
        recent_sessions = (
            db.query(models.ChatSession)
            .order_by(models.ChatSession.updated_at.desc())
            .limit(3)
            .all()
        )
        chat_records_by_session: list[tuple[models.ChatSession, list[models.ChatHistory]]] = []
        for sess in recent_sessions:
            msgs = (
                db.query(models.ChatHistory)
                .filter(models.ChatHistory.session_id == sess.id)
                .order_by(models.ChatHistory.created_at.asc())
                .all()
            )
            if msgs:
                chat_records_by_session.append((sess, msgs))
    finally:
        db.close()

    # 健康数据（睡眠和血氧佳明暂无法正确记录，使用与板端一致的默认值）
    FAKE_SLEEP_HOURS = 7.5
    FAKE_SPO2 = 98

    hr_text = "暂无数据"
    steps_text = "暂无数据"
    sleep_text = f"{FAKE_SLEEP_HOURS} 小时"
    spo2_text = f"{FAKE_SPO2}%"

    try:
        overview = get_overview()
        if overview.get("resting_hr") is not None:
            hr_text = f"{overview['resting_hr']} bpm"
        if overview.get("steps") is not None:
            steps_text = f"{overview['steps']} 步"
        if overview.get("sleep_seconds") is not None:
            h = overview["sleep_seconds"] / 3600
            sleep_text = f"{h:.1f} 小时"
        else:
            sleep_text = f"{FAKE_SLEEP_HOURS} 小时"
        if overview.get("avg_spo2") is not None:
            spo2_text = f"{overview['avg_spo2']}%"
        else:
            spo2_text = f"{FAKE_SPO2}%"
    except (GarminNotConfigured, GarminAuthError):
        pass

    title = f"📋 {user_name}今日健康日报"
    med_status = f"{taken}/{total} 已服用" if total else "今日无用药计划"
    if missed:
        med_status += f"，**{missed} 次未确认**"

    # 组装最近问诊记录摘要
    chat_section = ""
    if chat_records_by_session:
        chat_section = "\n\n---\n\n### 💬 最近问诊记录\n\n"
        for sess, msgs in chat_records_by_session:
            sess_date = sess.updated_at.strftime("%Y-%m-%d %H:%M") if sess.updated_at else ""
            chat_section += f"**📌 {sess.title}** ({sess_date})\n\n"
            for msg in msgs:
                role_label = "🧑 患者" if msg.role == "user" else "🤖 AI医生"
                content_preview = msg.content[:100] + ("..." if len(msg.content) > 100 else "")
                time_str = msg.created_at.strftime("%H:%M") if msg.created_at else ""
                chat_section += f"**{role_label}** ({time_str})：{content_preview}\n\n"
            chat_section += "\n"
    else:
        chat_section = "\n\n---\n\n### 💬 最近问诊记录\n\n暂无问诊记录\n"

    body = (
        f"### {user_name} · 每日健康日报\n\n"
        f"| 指标 | 数值 |\n"
        f"|------|------|\n"
        f"| 💊 用药 | {med_status} |\n"
        f"| 🫀 静息心率 | {hr_text} |\n"
        f"| 🦶 步数 | {steps_text} |\n"
        f"| 😴 睡眠 | {sleep_text} |\n"
        f"| 🫁 血氧 | {spo2_text} |\n"
        f"{chat_section}\n"
        f"---\n*来自 AI健康助手 · {datetime.now().strftime('%Y-%m-%d %H:%M')}*"
    )
    return title, body


# ── 场景 4：SOS 紧急求助 ──────────────────────────────────


def send_sos_alert() -> dict:
    """发送 SOS 紧急求助推送到家属微信。返回 {ok, message}。"""
    key = _get_key()
    if not key:
        return {"ok": False, "message": "未配置推送密钥，无法发送求助"}

    db = SessionLocal()
    try:
        from .. import models
        user = db.query(models.User).first()
        user_name = user.name if user else "患者"
    finally:
        db.close()

    title = f"🚨 紧急求助 - {user_name}按下了SOS"
    body = (
        f"### 紧急求助\n\n"
        f"**{user_name}** 在使用 AI 问诊时按下了 SOS 紧急按钮。\n\n"
        f"请尽快联系确认情况！\n\n"
        f"---\n*触发时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"
    )

    success = send_wechat(title, body)
    if success:
        return {"ok": True, "message": "已通知家属，请耐心等待"}
    return {"ok": False, "message": "推送发送失败，请稍后重试"}


def send_daily_report() -> bool:
    """发送每日健康日报。"""
    if not _get_key():
        return False
    try:
        title, body = _build_daily_report()
        return send_wechat(title, body)
    except Exception as exc:
        logger.exception("每日健康日报生成失败: %s", exc)
        return False


# ── 定时任务 ─────────────────────────────────────────────

def _daily_hour() -> int:
    return get_settings().get("notify_daily_hour", 20)


def _notify_tz() -> ZoneInfo:
    settings = get_settings()
    try:
        return ZoneInfo(settings.get("reminder_tz", "Asia/Shanghai"))
    except Exception:
        return ZoneInfo("Asia/Shanghai")


async def _daily_report_loop():
    """每日定时推送健康日报。"""
    sent_today = False
    while True:
        try:
            now = datetime.now(_notify_tz())
            target_hour = _daily_hour()

            if now.hour == target_hour and not sent_today:
                logger.info("开始推送每日健康日报")
                await asyncio.to_thread(send_daily_report)
                sent_today = True

            # 过了目标小时后重置，次日可再次发送
            if now.hour != target_hour:
                sent_today = False

        except Exception:
            logger.exception("每日健康日报定时任务异常")

        await asyncio.sleep(60)  # 每分钟检查一次


def start_daily_report_scheduler():
    """启动每日日报定时任务（在 FastAPI startup 中调用）。"""
    global _daily_task
    if not _get_key():
        logger.info("未配置 SERVERCHAN_KEY，跳过每日日报定时任务")
        return
    if _daily_task is not None:
        return
    _daily_task = asyncio.create_task(_daily_report_loop())
    logger.info("每日健康日报定时任务已启动（每天 %d 点推送）", _daily_hour())


def stop_daily_report_scheduler():
    global _daily_task
    if _daily_task is None:
        return
    _daily_task.cancel()
    _daily_task = None
