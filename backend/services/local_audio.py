"""
本地麦克风录音模块（不依赖 demo）

使用 arecord 命令行录制 WAV
"""

import subprocess
import time
from pathlib import Path
from typing import Dict, Any

import logging
logger = logging.getLogger(__name__)


def _ensure_audio_dir() -> Path:
    audio_dir = Path("/tmp/ai_doctor_audio")
    audio_dir.mkdir(parents=True, exist_ok=True)
    return audio_dir


def record_wav(
    duration_sec: float = 8.0,
    sample_rate: int = 16000,
    channels: int = 2,
    alsa_device: str = "plughw:1,0",
    timeout_sec: float = 12.0,
    *,
    prefer_stereo: bool = True,
) -> Dict[str, Any]:
    """
    使用 arecord 录制 WAV 文件。

    RK3588 nau8822 麦克风：立体声右声道有效，单声道往往几乎无声，故默认先录立体声。
    """
    audio_dir = _ensure_audio_dir()
    wav_path = audio_dir / f"input_{int(time.time())}.wav"
    timeout_sec = max(timeout_sec, duration_sec + 4.0)

    def _try_record(dev: str, ch: int):
        cmd = [
            "arecord",
            "-D", dev,
            "-f", "S16_LE",
            "-r", str(sample_rate),
            "-c", str(ch),
            "-d", str(max(1, int(duration_sec))),
            str(wav_path),
        ]
        try:
            subprocess.run(cmd, check=True, timeout=timeout_sec, capture_output=True)
            if wav_path.exists() and wav_path.stat().st_size > 1000:
                logger.info("local_audio: recorded %s (%.1fs, ch=%d)", wav_path, duration_sec, ch)
                return {"ok": True, "path": str(wav_path), "duration": duration_sec, "error": ""}
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
        return None

    order = (2, 1) if prefer_stereo else (channels, 3 - channels)
    for ch in order:
        res = _try_record(alsa_device, ch)
        if res:
            return res

    if alsa_device.startswith("hw:"):
        plug_dev = alsa_device.replace("hw:", "plughw:", 1)
        for ch in order:
            res = _try_record(plug_dev, ch)
            if res:
                return res

    return {"ok": False, "error": "arecord 失败：设备不支持录音", "path": "", "duration": 0}
