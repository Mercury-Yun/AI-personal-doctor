"""佳明手表健康数据服务（Garmin Connect，国内 garmin.cn）。

设计要点：
- 运行期只用「token 免密复用」——首次登录（可能要短信/邮箱验证码）由交互脚本
  backend/garmin_login.py 完成，token 存到 GARMIN_TOKEN_DIR；本服务加载 token 即可拉数据。
- 无 token 且配了账号密码时，尝试无验证码登录；若佳明要求验证码则明确报错，提示去跑登录脚本。
- 每日汇总内存缓存 TTL（默认 300s），并落库 garmin_daily 供历史趋势/离线展示。
- token 过期时自动重登一次（garminconnect 会用 refresh token 续期）。
"""

import json
import logging
import threading
import time
from datetime import date as date_cls, datetime
from pathlib import Path
from typing import Optional

from ..config import get_settings
from ..database import SessionLocal
from .. import models

logger = logging.getLogger(__name__)


class GarminNotConfigured(Exception):
    """未启用 / 未安装库 / 未登录（缺 token 且无法免验证码登录）。"""


class GarminAuthError(Exception):
    """已配置但登录/拉取失败（token 失效、网络、限流等）。"""


_client = None
_client_lock = threading.RLock()
_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def _token_dir_has_data(token_dir: str) -> bool:
    p = Path(token_dir)
    return p.is_dir() and any(p.iterdir())


def _load_client():
    """加载/创建 garminconnect 客户端（优先 token，失败再账号密码免验证码登录）。"""
    settings = get_settings()
    if not settings["garmin_enabled"]:
        raise GarminNotConfigured("佳明功能未启用（GARMIN_ENABLED=0）")

    try:
        from garminconnect import Garmin
    except ImportError as exc:
        raise GarminNotConfigured("garminconnect 未安装，请先在 venv 安装") from exc

    token_dir = settings["garmin_token_dir"]
    is_cn = settings["garmin_is_cn"]

    if _token_dir_has_data(token_dir):
        try:
            g = Garmin(is_cn=is_cn)
            g.login(token_dir)  # 恢复 token，必要时自动续期
            logger.info("Garmin: 已用 token 登录（%s）", token_dir)
            return g
        except Exception as exc:
            logger.warning("Garmin: token 登录失败，尝试账号密码登录: %s", exc)

    email = settings["garmin_email"]
    password = settings["garmin_password"]
    if not email or not password:
        raise GarminNotConfigured(
            "佳明未登录：请在板子上运行 `python -m backend.garmin_login` 完成首次登录（含验证码）"
        )

    g = Garmin(email=email, password=password, is_cn=is_cn, return_on_mfa=True)
    result, _ = g.login()
    if result == "needs_mfa":
        raise GarminNotConfigured(
            "佳明登录需要验证码：请在板子上运行 `python -m backend.garmin_login` 完成首次登录"
        )
    try:
        Path(token_dir).mkdir(parents=True, exist_ok=True)
        g.garth.dump(token_dir)
        logger.info("Garmin: 账号密码登录成功，token 已保存到 %s", token_dir)
    except Exception as exc:
        logger.warning("Garmin: 保存 token 失败: %s", exc)
    return g


def _get_client(force_reload: bool = False):
    global _client
    with _client_lock:
        if force_reload:
            _client = None
        if _client is None:
            _client = _load_client()
        return _client


def _reset_client() -> None:
    global _client
    with _client_lock:
        _client = None


def _pick(d: Optional[dict], *keys):
    if not isinstance(d, dict):
        return None
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return None


def _to_int(v):
    try:
        if v is None:
            return None
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def _today_str() -> str:
    return date_cls.today().isoformat()


def get_status() -> dict:
    settings = get_settings()
    token_present = _token_dir_has_data(settings["garmin_token_dir"])
    try:
        from garminconnect import Garmin  # noqa: F401
        lib_ok = True
    except ImportError:
        lib_ok = False
    return {
        "ok": True,
        "enabled": settings["garmin_enabled"],
        "lib_installed": lib_ok,
        "token_present": token_present,
        "has_credentials": bool(settings["garmin_email"] and settings["garmin_password"]),
        "is_cn": settings["garmin_is_cn"],
    }


def _downsample(series: list, max_points: int = 120) -> list:
    n = len(series)
    if n <= max_points:
        return series
    step = n / max_points
    return [series[int(i * step)] for i in range(max_points)]


def _fetch_heart_rate(g, cdate: str) -> dict:
    try:
        raw = g.get_heart_rates(cdate) or {}
    except Exception as exc:
        logger.warning("Garmin get_heart_rates 失败: %s", exc)
        raw = {}
    values = raw.get("heartRateValues") or []
    series = []
    latest = None
    for item in values:
        if not item or len(item) < 2:
            continue
        ts, val = item[0], item[1]
        if val is None:
            continue
        series.append({"t": int(ts), "v": int(val)})
        latest = int(val)
    return {
        "resting": _to_int(_pick(raw, "restingHeartRate")),
        "max": _to_int(_pick(raw, "maxHeartRate")),
        "min": _to_int(_pick(raw, "minHeartRate")),
        "latest": latest,
        "series": _downsample(series),
    }


def _fetch_raw(g, cdate: str) -> dict:
    """一次拉齐：stats + sleep + spo2（每项独立 try，单项失败不影响整体）。"""
    out = {}
    try:
        out["stats"] = g.get_stats(cdate) or {}
    except Exception as exc:
        logger.warning("Garmin get_stats 失败: %s", exc)
        out["stats"] = {}
    try:
        out["sleep"] = g.get_sleep_data(cdate) or {}
    except Exception as exc:
        logger.debug("Garmin get_sleep_data 失败: %s", exc)
        out["sleep"] = {}
    try:
        out["spo2"] = g.get_spo2_data(cdate) or {}
    except Exception as exc:
        logger.debug("Garmin get_spo2_data 失败: %s", exc)
        out["spo2"] = {}
    return out


def _build_overview(g, cdate: str) -> dict:
    stats = _fetch_raw(g, cdate)
    s = stats["stats"]
    sleep = stats["sleep"]
    spo2 = stats["spo2"]
    hr = _fetch_heart_rate(g, cdate)

    sleep_dto = sleep.get("dailySleepDTO") if isinstance(sleep, dict) else None
    sleep_seconds = _to_int(_pick(sleep_dto, "sleepTimeSeconds")) if sleep_dto else _to_int(
        _pick(s, "sleepingSeconds")
    )

    overview = {
        "ok": True,
        "date": cdate,
        "resting_hr": hr["resting"] if hr["resting"] is not None else _to_int(_pick(s, "restingHeartRate")),
        "max_hr": hr["max"] if hr["max"] is not None else _to_int(_pick(s, "maxHeartRate")),
        "min_hr": hr["min"] if hr["min"] is not None else _to_int(_pick(s, "minHeartRate")),
        "latest_hr": hr["latest"],
        "steps": _to_int(_pick(s, "totalSteps")),
        "sleep_seconds": sleep_seconds,
        "avg_stress": _to_int(_pick(s, "averageStressLevel")),
        "avg_spo2": _to_int(_pick(spo2, "averageSpO2", "averageSpo2") or _pick(s, "averageSpo2")),
        "lowest_spo2": _to_int(_pick(spo2, "lowestSpO2", "lowestSpo2")),
        "body_battery": _to_int(
            _pick(s, "bodyBatteryMostRecentValue", "bodyBatteryHighestValue")
        ),
        "hr_series": hr["series"],
        "synced_at": datetime.now().isoformat(timespec="seconds"),
        "source": "garmin",
    }
    return overview


def _persist(overview: dict) -> None:
    if not overview.get("date"):
        return
    db = SessionLocal()
    try:
        row = (
            db.query(models.GarminDaily)
            .filter(models.GarminDaily.date == overview["date"])
            .first()
        )
        if row is None:
            row = models.GarminDaily(date=overview["date"])
            db.add(row)
        row.resting_hr = overview.get("resting_hr")
        row.max_hr = overview.get("max_hr")
        row.min_hr = overview.get("min_hr")
        row.steps = overview.get("steps")
        row.sleep_seconds = overview.get("sleep_seconds")
        row.avg_stress = overview.get("avg_stress")
        row.avg_spo2 = overview.get("avg_spo2")
        row.lowest_spo2 = overview.get("lowest_spo2")
        row.body_battery = overview.get("body_battery")
        row.raw_json = json.dumps(
            {k: v for k, v in overview.items() if k != "hr_series"}, ensure_ascii=False
        )
        row.synced_at = datetime.now()
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("Garmin 落库失败: %s", exc)
    finally:
        db.close()


def get_overview(cdate: Optional[str] = None, force: bool = False) -> dict:
    settings = get_settings()
    cdate = cdate or _today_str()
    ttl = settings["garmin_cache_ttl_sec"]

    if not force:
        with _cache_lock:
            cached = _cache.get(cdate)
            if cached and (time.monotonic() - cached[0]) < ttl:
                return cached[1]

    def _do() -> dict:
        g = _get_client()
        return _build_overview(g, cdate)

    try:
        overview = _do()
    except GarminNotConfigured:
        raise
    except Exception as exc:
        logger.warning("Garmin 拉取失败，重登后重试一次: %s", exc)
        try:
            _get_client(force_reload=True)
            overview = _do()
        except GarminNotConfigured:
            raise
        except Exception as exc2:
            raise GarminAuthError(f"佳明数据拉取失败: {exc2}") from exc2

    _persist(overview)
    with _cache_lock:
        _cache[cdate] = (time.monotonic(), overview)

    # 健康异常微信推送
    try:
        from .notify_service import check_and_notify_health_anomaly
        user_name = "患者"
        try:
            db = SessionLocal()
            row = db.query(models.User).first()
            if row:
                user_name = row.name
            db.close()
        except Exception:
            pass
        check_and_notify_health_anomaly(overview, user_name)
    except Exception as exc:
        logger.debug("健康异常推送检查失败: %s", exc)

    return overview


def get_history(days: int = 7) -> dict:
    days = max(1, min(60, days))
    db = SessionLocal()
    try:
        rows = (
            db.query(models.GarminDaily)
            .order_by(models.GarminDaily.date.desc())
            .limit(days)
            .all()
        )
        items = [
            {
                "date": r.date,
                "resting_hr": r.resting_hr,
                "max_hr": r.max_hr,
                "min_hr": r.min_hr,
                "steps": r.steps,
                "sleep_seconds": r.sleep_seconds,
                "avg_stress": r.avg_stress,
                "avg_spo2": r.avg_spo2,
                "lowest_spo2": r.lowest_spo2,
                "body_battery": r.body_battery,
            }
            for r in reversed(rows)
        ]
        return {"ok": True, "days": days, "items": items}
    finally:
        db.close()
