"""
本地关键词唤醒：持久化 sherpa_kws_worker + 长连接 arecord 流式 PCM
"""

from __future__ import annotations

import logging
import os
import struct
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)

_worker_proc: Optional[subprocess.Popen] = None
_worker_lock = threading.Lock()
_listener_lock = threading.Lock()
_listener_running = False

_KWS_SCORE = float(os.getenv("KWS_KEYWORDS_SCORE", "4.5"))
_KWS_THRESHOLD = float(os.getenv("KWS_KEYWORDS_THRESHOLD", "0.25"))
_DEMO_KEYWORD_LINE = f"x iǎo y ī :{_KWS_SCORE} #{_KWS_THRESHOLD} @小医"

# RMS 能量门控：低于此值的音频块视为静音，不送入 KWS（防止背景噪音误触发）
_RMS_GATE_THRESHOLD = int(os.getenv("KWS_RMS_GATE", "80"))


def _get_kws_dir() -> Optional[Path]:
    env_dir = os.getenv("SHERPA_KWS_DIR")
    if env_dir and Path(env_dir).exists():
        return Path(env_dir)
    for path in (
        Path("/home/elf/Qwen_test/sherpa/kws"),
        Path.home() / "Qwen_test" / "sherpa" / "kws",
    ):
        if (path / "tokens.txt").exists():
            return path
    return None


def _get_worker_bin() -> Optional[Path]:
    env_bin = os.getenv("SHERPA_KWS_WORKER_BIN")
    if env_bin and Path(env_bin).exists():
        return Path(env_bin)
    for path in (
        Path("/home/elf/Qwen_test/sherpa/bin/sherpa_kws_worker"),
        Path.home() / "Qwen_test" / "sherpa" / "bin" / "sherpa_kws_worker",
    ):
        if path.exists():
            return path
    return None


def _ensure_keywords_file(kws_dir: Path) -> None:
    keywords_path = kws_dir / "keywords.txt"
    keywords_path.write_text(f"{_DEMO_KEYWORD_LINE}\n", encoding="utf-8")


def _worker_env(kws_dir: Path) -> dict:
    env = os.environ.copy()
    env["SHERPA_KWS_DIR"] = str(kws_dir)
    env["SHERPA_KWS_ENCODER"] = "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
    env["SHERPA_KWS_DECODER"] = "decoder-epoch-12-avg-2-chunk-16-left-64.onnx"
    env["SHERPA_KWS_JOINER"] = "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
    env["KWS_KEYWORDS_SCORE"] = str(_KWS_SCORE)
    env["KWS_KEYWORDS_THRESHOLD"] = str(_KWS_THRESHOLD)
    env["SHERPA_NUM_THREADS"] = os.getenv("SHERPA_NUM_THREADS", "2")
    return env


def _stereo_to_mono(raw: np.ndarray, channels: int) -> np.ndarray:
    """取右声道喂 KWS。

    板载 nau8822 麦克风右声道有效、左声道几乎无声（实测右声道 RMS 约为左的 5×）。
    流式 KWS 必须用固定声道：若按每块 RMS 动态选择，静音间隙会在左右之间来回
    切换，破坏流式特征、导致漏检。故固定取右声道。
    """
    if channels <= 1:
        return raw.astype(np.int16, copy=False)
    n = (raw.shape[0] // channels) * channels
    frames = raw[:n].reshape(-1, channels)
    right_index = 1 if channels >= 2 else 0
    return frames[:, right_index].astype(np.int16, copy=False)


def _stop_worker_unlocked() -> None:
    global _worker_proc
    proc = _worker_proc
    _worker_proc = None
    if proc is None:
        return
    try:
        if proc.stdin:
            proc.stdin.write(struct.pack(">I", 0))
            proc.stdin.flush()
    except Exception:
        pass
    try:
        proc.terminate()
        proc.wait(timeout=2.0)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _start_worker_unlocked() -> bool:
    global _worker_proc
    kws_dir = _get_kws_dir()
    worker_bin = _get_worker_bin()
    if not kws_dir or not worker_bin:
        return False
    _ensure_keywords_file(kws_dir)
    _stop_worker_unlocked()
    try:
        proc = subprocess.Popen(
            [str(worker_bin)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_worker_env(kws_dir),
            bufsize=0,
        )
        ready_line = proc.stdout.readline()
        if b"READY" not in ready_line:
            proc.kill()
            return False
    except Exception as exc:
        logger.error("start KWS worker failed: %s", exc)
        return False
    _worker_proc = proc
    logger.info("KWS worker ready")
    return True


def _ensure_worker() -> bool:
    with _worker_lock:
        if _worker_proc is not None and _worker_proc.poll() is None:
            return True
        return _start_worker_unlocked()


def _worker_reset() -> bool:
    with _worker_lock:
        if _worker_proc is None or _worker_proc.poll() is not None:
            if not _start_worker_unlocked():
                return False
        try:
            _worker_proc.stdin.write(struct.pack(">I", 1))
            _worker_proc.stdin.flush()
            return _worker_proc.stdout.read(1) == b"\x00"
        except Exception:
            _stop_worker_unlocked()
            return False


def _worker_feed(samples: np.ndarray) -> int:
    with _worker_lock:
        if _worker_proc is None or _worker_proc.poll() is not None:
            return -1
        try:
            pcm = samples.astype(np.int16, copy=False)
            n = int(pcm.shape[0])
            _worker_proc.stdin.write(struct.pack(">I", 2))
            _worker_proc.stdin.write(struct.pack(">I", n))
            _worker_proc.stdin.write(pcm.tobytes())
            _worker_proc.stdin.flush()
            event = _worker_proc.stdout.read(1)
            return int(event[0]) if event else -1
        except Exception:
            _stop_worker_unlocked()
            return -1


def run_persistent_listener(
    wake_word: str,
    on_detected: Callable[[], None],
    should_stop: Callable[[], bool],
    *,
    alsa_device: str = "plughw:1,0",
    channels: int = 2,
) -> None:
    """长连接麦克风 + KWS，检测到关键词即回调（不重启 arecord）。"""
    global _listener_running
    with _listener_lock:
        if _listener_running:
            return
        _listener_running = True

    if not _worker_reset():
        _listener_running = False
        return

    chunk_samples = 512
    chunk_bytes = chunk_samples * 2 * channels

    proc = subprocess.Popen(
        ["arecord", "-D", alsa_device, "-f", "S16_LE", "-r", "16000", "-c", str(channels), "-t", "raw", "-"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    logger.info("KWS persistent listener started for %r", wake_word)
    try:
        while not should_stop():
            if proc.poll() is not None:
                break
            data = proc.stdout.read(chunk_bytes)
            if not data:
                time.sleep(0.01)
                continue
            mono = _stereo_to_mono(np.frombuffer(data, dtype=np.int16), channels)

            # RMS 能量门控：静音帧直接跳过，不送入 KWS，防止背景噪音误触发
            rms = int(np.sqrt(np.mean(mono.astype(np.int32) ** 2)))
            if rms < _RMS_GATE_THRESHOLD:
                continue

            if _worker_feed(mono) == 1:
                logger.info("KWS hit %r", wake_word)
                on_detected()
                _worker_reset()
                continue

    finally:
        if proc.poll() is None:
            proc.terminate()
        with _listener_lock:
            _listener_running = False
        logger.info("KWS persistent listener stopped")


def kws_prewarm(wake_word: str = "小医") -> threading.Thread:
    def _run():
        _ensure_worker()

    t = threading.Thread(target=_run, daemon=True, name="kws-prewarm")
    t.start()
    return t


def is_kws_available() -> bool:
    return _get_kws_dir() is not None and _get_worker_bin() is not None


def listener_running() -> bool:
    """常驻监听是否仍持有麦克风（arecord 未退出）。"""
    return _listener_running


def wait_for_keyword(
    wake_word: str = "小医",
    timeout_sec: float = 120.0,
    *,
    should_stop: Optional[Callable[[], bool]] = None,
    alsa_device: str = "plughw:1,0",
    channels: int = 2,
) -> bool:
    """兼容旧接口：单次超时监听。"""
    hit = threading.Event()

    def on_hit():
        hit.set()

    def stop():
        if should_stop and should_stop():
            return True
        if hit.is_set():
            return True
        return False

    listener = threading.Thread(
        target=run_persistent_listener,
        args=(wake_word, on_hit, stop),
        kwargs={"alsa_device": alsa_device, "channels": channels},
        daemon=True,
    )
    listener.start()
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if hit.wait(timeout=0.15):
            return True
        if should_stop and should_stop():
            return False
    return False
