import os
from functools import lru_cache
from pathlib import Path


def _load_dotenv():
    root = Path(__file__).resolve().parents[1]
    env_path = root / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@lru_cache
def get_settings():
    _load_dotenv()
    return {
        # 云端化配置（已移除所有 demo 相关设置）
        "reminder_enabled": os.getenv("REMINDER_ENABLED", "1") != "0",
        "reminder_tz": os.getenv("REMINDER_TZ", "Asia/Shanghai"),
        "reminder_check_interval_sec": int(os.getenv("REMINDER_CHECK_INTERVAL_SEC", "15")),
        "reminder_repeat_sec": int(os.getenv("REMINDER_REPEAT_SEC", "45")),
        "reminder_repeat_minutes": int(os.getenv("REMINDER_REPEAT_MINUTES", "2")),
        "chat_use_cloud_llm": True,  # 强制使用云端 LLM
        "dashscope_api_key": os.getenv("DASHSCOPE_API_KEY", ""),
        "dashscope_base_url": os.getenv(
            "DASHSCOPE_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ).rstrip("/"),
        "dashscope_model": os.getenv("DASHSCOPE_MODEL", "qwen-turbo"),
        "dashscope_vision_model": os.getenv("DASHSCOPE_VISION_MODEL", "qwen-vl-max"),
        "dashscope_enable_thinking": os.getenv("DASHSCOPE_ENABLE_THINKING", "0") != "0",
        "tts_use_cloud": True,  # 强制使用云端 TTS
        "cosyvoice_model": os.getenv("COSYVOICE_MODEL", "cosyvoice-v3-flash"),
        "cosyvoice_voice": os.getenv("COSYVOICE_VOICE", "longanhuan"),
        "cosyvoice_format": os.getenv("COSYVOICE_FORMAT", "wav"),
        "cosyvoice_sample_rate": int(os.getenv("COSYVOICE_SAMPLE_RATE", "22050")),
        "cosyvoice_speech_rate": float(os.getenv("COSYVOICE_SPEECH_RATE", "0.90")),
        "cosyvoice_batch_max_chars": int(os.getenv("COSYVOICE_BATCH_MAX_CHARS", "160")),
        "cosyvoice_first_batch_chars": int(os.getenv("COSYVOICE_FIRST_BATCH_CHARS", "36")),
        "cloud_warmup": os.getenv("CLOUD_WARMUP", "1") != "0",
        "tts_play_command": os.getenv("TTS_PLAY_COMMAND", "aplay -D plughw:1,0 -q"),
        "wake_enabled": os.getenv("WAKE_ENABLED", "1") != "0",
        "wake_word": os.getenv("VOICE_WAKE_WORD", "小医"),
        # 佳明手表健康数据（Garmin Connect 国内 garmin.cn）
        "garmin_enabled": os.getenv("GARMIN_ENABLED", "1") != "0",
        "garmin_email": os.getenv("GARMIN_EMAIL", ""),
        "garmin_password": os.getenv("GARMIN_PASSWORD", ""),
        "garmin_is_cn": os.getenv("GARMIN_IS_CN", "1") != "0",
        "garmin_token_dir": os.getenv(
            "GARMIN_TOKEN_DIR",
            str(Path(__file__).resolve().parents[1] / ".garmin_tokens"),
        ),
        "garmin_cache_ttl_sec": int(os.getenv("GARMIN_CACHE_TTL_SEC", "300")),
        # Server酱微信推送
        "serverchan_key": os.getenv("SERVERCHAN_KEY", ""),
        "notify_overdue_minutes": int(os.getenv("NOTIFY_OVERDUE_MINUTES", "15")),
        "notify_daily_hour": int(os.getenv("NOTIFY_DAILY_HOUR", "20")),
        "notify_cooldown_sec": int(os.getenv("NOTIFY_COOLDOWN_SEC", "600")),
    }
