import hashlib
import logging
import os
import queue
import re
import subprocess
import tempfile
import threading
import time
import urllib.request

from ..config import get_settings

logger = logging.getLogger(__name__)

_POISON = object()

_text_queue: queue.Queue = queue.Queue()
_audio_queue: queue.Queue = queue.Queue(maxsize=32)
_pipeline_lock = threading.Lock()
_pipeline_started = False
_idle_event = threading.Event()
_idle_event.set()
_pending_jobs = 0
_pending_lock = threading.Lock()
_play_lock = threading.Lock()
_active_play_proc: subprocess.Popen | None = None
_stop_requested = threading.Event()
_last_tts_end_at = 0.0
_tts_timing_lock = threading.Lock()

_PROMPT_CACHE_DIR = "/tmp/ai_doctor_tts_cache"
_prompt_cache: dict[str, bytes] = {}
_prompt_cache_lock = threading.Lock()


class CloudTtsError(Exception):
    pass


def cloud_tts_configured() -> bool:
    settings = get_settings()
    key = (settings.get("dashscope_api_key") or "").strip()
    return bool(key) and not key.startswith("REPLACE_")


def _sanitize_tts_text(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[#*_~>\[\](){}|\\]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", text):
        return ""
    return text


def _tts_kwargs(text: str) -> dict:
    settings = get_settings()
    return {
        "model": settings["cosyvoice_model"],
        "text": text,
        "voice": settings["cosyvoice_voice"],
        "audio_format": settings["cosyvoice_format"],
        "sample_rate": settings["cosyvoice_sample_rate"],
        "rate": settings["cosyvoice_speech_rate"],
        "api_key": settings["dashscope_api_key"],
    }


def _load_synthesizer():
    try:
        from dashscope.audio.http_tts.http_speech_synthesizer import HttpSpeechSynthesizer
    except ImportError as exc:
        raise CloudTtsError("缺少 dashscope 依赖，请执行 pip install dashscope") from exc
    return HttpSpeechSynthesizer


def _set_active_play_proc(proc: subprocess.Popen | None) -> None:
    global _active_play_proc
    _active_play_proc = proc


def _kill_active_playback() -> None:
    global _active_play_proc
    proc = _active_play_proc
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.kill()
        proc.wait(timeout=2)
    except Exception as exc:
        logger.debug("kill active TTS playback: %s", exc)
    finally:
        _active_play_proc = None


def _play_wav_file(path: str) -> None:
    if _stop_requested.is_set():
        return
    player = get_settings()["tts_play_command"].split()
    if not player:
        player = ["aplay", "-q"]
    with _play_lock:
        if _stop_requested.is_set():
            return
        proc = subprocess.Popen([*player, path])
        _set_active_play_proc(proc)
        try:
            proc.wait(timeout=45)
            if proc.returncode not in (0, -9, -15):
                raise subprocess.CalledProcessError(proc.returncode, player)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
            raise
        finally:
            if _active_play_proc is proc:
                _set_active_play_proc(None)


def _play_wav_bytes(data: bytes) -> None:
    if not data:
        return
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        handle.write(data)
        path = handle.name
    try:
        _play_wav_file(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _play_pcm_bytes(data: bytes, sample_rate: int) -> None:
    if not data:
        return
    cmd = get_settings()["tts_play_command"].split() or ["aplay", "-q"]
    if cmd[0] == "aplay":
        cmd = [
            *cmd,
            "-f",
            "S16_LE",
            "-r",
            str(sample_rate),
            "-c",
            "1",
            "-t",
            "raw",
            "-",
        ]
    else:
        cmd = [*cmd, "-"]
    with _play_lock:
        if _stop_requested.is_set():
            return
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        _set_active_play_proc(proc)
        try:
            assert proc.stdin is not None
            proc.stdin.write(data)
            proc.stdin.close()
            proc.wait(timeout=45)
        except Exception:
            proc.kill()
            raise
        finally:
            if _active_play_proc is proc:
                _set_active_play_proc(None)


def _play_audio_bytes(data: bytes) -> None:
    if not data:
        return
    if data[:4] == b"RIFF":
        _play_wav_bytes(data)
        return
    _play_pcm_bytes(data, int(get_settings()["cosyvoice_sample_rate"]))


def _fetch_audio_bytes(text: str) -> bytes:
    HttpSpeechSynthesizer = _load_synthesizer()
    kwargs = _tts_kwargs(text)
    parts: list[bytes] = []
    try:
        stream = HttpSpeechSynthesizer.call(stream=True, **kwargs)
        for chunk in stream:
            if chunk.audio_url:
                continue
            if chunk.audio_data:
                parts.append(chunk.audio_data)
    except Exception as exc:
        logger.warning("cloud TTS stream synth fallback: %s", exc)

    audio = b"".join(parts)
    if audio:
        return audio

    result = HttpSpeechSynthesizer.call(stream=False, **kwargs)
    if result.audio_url:
        with urllib.request.urlopen(result.audio_url, timeout=60) as resp:
            return resp.read()
    if result.audio_data:
        return result.audio_data
    raise CloudTtsError("CosyVoice 未返回音频")


def _synthesize_to_queue(text: str, done_event: threading.Event | None) -> None:
    audio = _fetch_audio_bytes(text)
    _audio_queue.put(("audio", audio, done_event))


def _mark_job_started() -> None:
    global _pending_jobs
    with _pending_lock:
        _pending_jobs += 1
        _idle_event.clear()


def _mark_job_finished() -> None:
    global _pending_jobs, _last_tts_end_at
    with _pending_lock:
        _pending_jobs = max(0, _pending_jobs - 1)
        if _pending_jobs == 0:
            _idle_event.set()
            with _tts_timing_lock:
                _last_tts_end_at = time.monotonic()


def tts_recently_active(within_sec: float = 5.0) -> bool:
    if not _idle_event.is_set():
        return True
    with _tts_timing_lock:
        return (time.monotonic() - _last_tts_end_at) < within_sec


def _heal_orphaned_busy() -> bool:
    """pending 计数与队列/播放进程不一致时自愈，避免 tts_busy 永久为 true。"""
    global _pending_jobs
    if _idle_event.is_set():
        return False
    proc = _active_play_proc
    proc_alive = proc is not None and proc.poll() is None
    if _pending_jobs > 0 and _text_queue.empty() and _audio_queue.empty() and not proc_alive:
        logger.warning("cloud TTS: healing orphaned busy state (pending=%s)", _pending_jobs)
        with _pending_lock:
            _pending_jobs = 0
            _idle_event.set()
            with _tts_timing_lock:
                _last_tts_end_at = time.monotonic()
        return True
    return False


def tts_is_playing() -> bool:
    _heal_orphaned_busy()
    return not _idle_event.is_set()


def _drain_queue(q: queue.Queue) -> int:
    drained = 0
    while True:
        try:
            q.get_nowait()
            q.task_done()
            drained += 1
        except queue.Empty:
            break
    return drained


def stop_tts() -> dict:
    """中断当前播报并清空待播队列（切页/回首页时调用）。"""
    global _pending_jobs
    _stop_requested.set()
    _kill_active_playback()
    text_drained = _drain_queue(_text_queue)
    audio_drained = _drain_queue(_audio_queue)
    with _pending_lock:
        _pending_jobs = 0
        _idle_event.set()
        with _tts_timing_lock:
            _last_tts_end_at = time.monotonic()
    _stop_requested.clear()
    return {
        "ok": True,
        "stopped": True,
        "drained_text": text_drained,
        "drained_audio": audio_drained,
    }


def _synth_worker() -> None:
    while True:
        item = _text_queue.get()
        try:
            if item is _POISON:
                _audio_queue.put(_POISON)
                return
            text, done_event = item
            try:
                _synthesize_to_queue(text, done_event)
            except Exception as exc:
                logger.warning("cloud TTS synth failed: %s", exc)
                _audio_queue.put(("audio", b"", done_event))
        finally:
            _text_queue.task_done()


def _play_worker() -> None:
    while True:
        item = _audio_queue.get()
        try:
            if item is _POISON:
                return
            _, audio, done_event = item
            try:
                if audio:
                    _play_audio_bytes(audio)
            except Exception as exc:
                logger.warning("cloud TTS play failed: %s", exc)
            finally:
                if done_event is not None:
                    done_event.set()
                _mark_job_finished()
        finally:
            _audio_queue.task_done()


def _ensure_pipeline() -> None:
    global _pipeline_started
    with _pipeline_lock:
        if _pipeline_started:
            return
        threading.Thread(target=_synth_worker, name="cloud-tts-synth", daemon=True).start()
        threading.Thread(target=_play_worker, name="cloud-tts-play", daemon=True).start()
        _pipeline_started = True


def wait_until_idle(timeout: float = 300) -> bool:
    _ensure_pipeline()
    return _idle_event.wait(timeout)


def speak(text: str, wait: bool = False) -> dict:
    text = _sanitize_tts_text(text)
    if not text:
        return {"ok": True, "skipped": True}
    if not cloud_tts_configured():
        raise CloudTtsError("请先在 .env 中配置 DASHSCOPE_API_KEY")

    if wait:
        _mark_job_started()
        try:
            if _stop_requested.is_set():
                return {"ok": True, "skipped": True, "stopped": True}
            audio = _fetch_audio_bytes(text)
            if _stop_requested.is_set():
                return {"ok": True, "skipped": True, "stopped": True}
            _play_audio_bytes(audio)
        except Exception as exc:
            if _stop_requested.is_set():
                return {"ok": True, "skipped": True, "stopped": True}
            logger.warning("cloud TTS sync speak failed: %s", exc)
            raise
        finally:
            _mark_job_finished()
        return {"ok": True, "source": "cosyvoice", "async": False}

    _ensure_pipeline()
    done_event = None
    _mark_job_started()
    _text_queue.put((text, done_event))
    return {"ok": True, "source": "cosyvoice", "async": True}


def synthesize_bytes(text: str) -> bytes:
    if not cloud_tts_configured():
        raise CloudTtsError("请先在 .env 中配置 DASHSCOPE_API_KEY")
    return _fetch_audio_bytes(text)


def _prompt_cache_key(text: str) -> str:
    settings = get_settings()
    fingerprint = "|".join(
        str(x)
        for x in (
            text,
            settings.get("cosyvoice_model"),
            settings.get("cosyvoice_voice"),
            settings.get("cosyvoice_format"),
            settings.get("cosyvoice_sample_rate"),
            settings.get("cosyvoice_speech_rate"),
        )
    )
    return hashlib.md5(fingerprint.encode("utf-8")).hexdigest()


def _load_prompt_from_disk(key: str) -> bytes | None:
    path = os.path.join(_PROMPT_CACHE_DIR, f"{key}.wav")
    try:
        with open(path, "rb") as handle:
            data = handle.read()
        return data or None
    except OSError:
        return None


def _store_prompt_to_disk(key: str, data: bytes) -> None:
    try:
        os.makedirs(_PROMPT_CACHE_DIR, exist_ok=True)
        path = os.path.join(_PROMPT_CACHE_DIR, f"{key}.wav")
        tmp = path + ".tmp"
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except OSError as exc:
        logger.debug("prompt cache write failed: %s", exc)


def prewarm_prompt(text: str) -> bytes | None:
    """预生成固定短语（如「我在」）音频并缓存，供 speak_prompt 秒播。"""
    text = _sanitize_tts_text(text)
    if not text or not cloud_tts_configured():
        return None
    key = _prompt_cache_key(text)
    with _prompt_cache_lock:
        cached = _prompt_cache.get(key)
    if cached:
        return cached

    data = _load_prompt_from_disk(key)
    if not data:
        try:
            data = _fetch_audio_bytes(text)
        except Exception as exc:
            logger.warning("prewarm prompt '%s' failed: %s", text, exc)
            return None
        if data:
            _store_prompt_to_disk(key, data)
    if data:
        with _prompt_cache_lock:
            _prompt_cache[key] = data
        logger.info("prompt cached: '%s' (%d bytes)", text, len(data))
    return data


def speak_prompt(text: str, wait: bool = False) -> dict:
    """播放固定短语：命中缓存则直接入播放队列，绕过云端合成。未命中回退 speak。"""
    sanitized = _sanitize_tts_text(text)
    if not sanitized:
        return {"ok": True, "skipped": True}

    key = _prompt_cache_key(sanitized)
    with _prompt_cache_lock:
        data = _prompt_cache.get(key)
    if not data:
        data = _load_prompt_from_disk(key)
        if data:
            with _prompt_cache_lock:
                _prompt_cache[key] = data

    if not data:
        # 未命中：后台补缓存，本次回退到常规合成播放
        threading.Thread(
            target=prewarm_prompt, args=(sanitized,), name="tts-prompt-cache", daemon=True
        ).start()
        return speak(sanitized, wait=wait)

    _ensure_pipeline()
    if _stop_requested.is_set():
        return {"ok": True, "skipped": True, "stopped": True}
    done_event = threading.Event() if wait else None
    _mark_job_started()
    _audio_queue.put(("audio", data, done_event))
    if wait and done_event is not None:
        done_event.wait(timeout=15)
    return {"ok": True, "source": "prompt-cache", "async": not wait}
