from ..config import get_settings
from .cloud_tts_service import (
    CloudTtsError,
    cloud_tts_configured,
    prewarm_prompt as cloud_prewarm_prompt,
    speak as cloud_speak,
    speak_prompt as cloud_speak_prompt,
    stop_tts as cloud_stop_tts,
    tts_recently_active as cloud_tts_recently_active,
    wait_until_idle as cloud_wait_until_idle,
)


def use_cloud_tts() -> bool:
    settings = get_settings()
    return settings["tts_use_cloud"] and cloud_tts_configured()


def tts_enabled() -> bool:
    return True  # 云端 TTS 始终可用


def tts_source() -> str:
    return "cosyvoice"


def speak(text: str, wait: bool = False) -> dict:
    return cloud_speak(text, wait=wait)


def speak_prompt(text: str, wait: bool = False) -> dict:
    return cloud_speak_prompt(text, wait=wait)


def prewarm_prompt(text: str):
    return cloud_prewarm_prompt(text)


def speak_or_raise(text: str, wait: bool = False) -> dict:
    try:
        return speak(text, wait=wait)
    except CloudTtsError as exc:
        raise exc


def stop_active_speech() -> dict:
    return cloud_stop_tts()


def wait_for_tts_idle(timeout: float = 300) -> bool:
    return cloud_wait_until_idle(timeout)


def tts_is_playing() -> bool:
    from .cloud_tts_service import tts_is_playing as cloud_tts_is_playing
    return cloud_tts_is_playing()


def tts_recently_active(within_sec: float = 5.0) -> bool:
    if use_cloud_tts():
        return cloud_tts_recently_active(within_sec)
    return False
