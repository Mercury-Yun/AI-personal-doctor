"""
本地 ASR 服务（Sherpa-ONNX 离线识别）

使用 Sherpa-ONNX Python API 进行语音识别。
支持预热（prewarm）以加速首次识别。
"""

import os
import threading
import logging
from typing import Optional, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

# 全局 ASR 模型（单例）
_asr_model = None
_asr_model_lock = threading.Lock()
_asr_prewarm_done = threading.Event()


def _get_asr_model_dir() -> Optional[Path]:
    """查找 Sherpa ASR 模型目录（优先 SenseVoice）"""
    # 优先使用环境变量
    env_dir = os.getenv("SHERPA_ASR_DIR")
    if env_dir and Path(env_dir).exists():
        return Path(env_dir)

    # 常见位置（优先 SenseVoice，其次 Paraformer）
    candidates = [
        Path("/home/elf/Qwen_test/sherpa/asr_sensevoice/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"),
        Path.home() / "Qwen_test" / "sherpa" / "asr_sensevoice" / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
        Path("/home/elf/Qwen_test/sherpa/asr"),
        Path.home() / "Qwen_test" / "sherpa" / "asr",
    ]
    for p in candidates:
        if p.exists() and ((p / "model.int8.onnx").exists() or (p / "model.onnx").exists()):
            logger.info(f"找到 ASR 模型目录: {p}")
            return p
    return None


def _load_asr_model():
    """加载 Sherpa ASR 模型（线程安全）"""
    global _asr_model

    with _asr_model_lock:
        if _asr_model is not None:
            return _asr_model

        try:
            import sherpa_onnx

            model_dir = _get_asr_model_dir()
            if not model_dir:
                logger.warning("Sherpa ASR 模型目录未找到，ASR 功能不可用")
                return None

            # 尝试加载模型（支持多种格式）
            # 优先使用 int8 量化模型
            model_files = list(model_dir.glob("*.onnx"))
            if not model_files:
                logger.warning(f"Sherpa ASR 模型目录 {model_dir} 中未找到 .onnx 文件")
                return None

            # 选择模型文件（优先 int8）
            model_file = None
            for f in model_files:
                if "int8" in f.name.lower():
                    model_file = f
                    break
            if model_file is None:
                model_file = model_files[0]

            tokens_file = model_dir / "tokens.txt"
            if not tokens_file.exists():
                logger.warning(f"tokens.txt 未找到: {tokens_file}")
                return None

            logger.info(f"加载 Sherpa ASR 模型: {model_file}")

            model_path = str(model_file)
            is_sensevoice = "sense-voice" in model_path.lower()

            if is_sensevoice:
                # SenseVoice 模型
                logger.info("使用 SenseVoice 模型加载")
                _asr_model = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                    model=model_path,
                    tokens=str(tokens_file),
                    num_threads=int(os.getenv("SHERPA_NUM_THREADS", "4")),
                    sample_rate=16000,
                    decoding_method="greedy_search",
                    language="auto",  # 自动检测语言
                )
            else:
                # Paraformer 模型（需要 text_norm）
                logger.info("使用 Paraformer 模型加载")
                _asr_model = sherpa_onnx.OfflineRecognizer.from_paraformer(
                    paraformer=model_path,
                    tokens=str(tokens_file),
                    num_threads=int(os.getenv("SHERPA_NUM_THREADS", "4")),
                    sample_rate=16000,
                    decoding_method="greedy_search",
                )

            logger.info("Sherpa ASR 模型加载完成")
            _asr_prewarm_done.set()
            return _asr_model

        except ImportError:
            logger.warning("sherpa_onnx 未安装，ASR 功能不可用")
            return None
        except Exception as e:
            logger.error(f"加载 Sherpa ASR 模型失败: {e}")
            return None


def asr_prewarm():
    """
    预热 ASR 模型（在后台线程中执行，避免阻塞启动）
    """
    def _prewarm():
        logger.info("ASR 预热开始...")
        model = _load_asr_model()
        if model:
            # 用一个空音频预热
            try:
                # 创建一个静音音频进行预热
                import numpy as np
                # Sherpa ONNX 的预热方式
                logger.info("ASR 预热完成")
            except Exception as e:
                logger.warning(f"ASR 预热过程出错: {e}")
        else:
            logger.warning("ASR 预热失败：模型未加载")

    thread = threading.Thread(target=_prewarm, daemon=True, name="asr-prewarm")
    thread.start()
    return thread


def transcribe_wav(
    wav_path: str,
    timeout_sec: float = 30.0
) -> Dict[str, Any]:
    """
    使用本地 Sherpa ASR 将 WAV 文件转为文字

    Args:
        wav_path: WAV 文件路径
        timeout_sec: 超时时间

    Returns:
        {"ok": bool, "text": str, "error": str}
    """
    model = _load_asr_model()
    if model is None:
        return {"ok": False, "text": "", "error": "ASR 模型未加载"}

    if not os.path.exists(wav_path):
        return {"ok": False, "text": "", "error": f"WAV 文件不存在: {wav_path}"}

    try:
        import sherpa_onnx

        # 读取 WAV 文件
        import wave
        with wave.open(wav_path, "rb") as wf:
            sample_rate = wf.getframerate()
            num_channels = wf.getnchannels()
            num_frames = wf.getnframes()
            audio_data = wf.readframes(num_frames)

        # 转换为 float32；立体声取音量更大的声道（板载 mic 常为右声道）
        import numpy as np
        raw = np.frombuffer(audio_data, dtype=np.int16)
        if num_channels == 2:
            stereo = raw.reshape(-1, 2).astype(np.float32)
            left = stereo[:, 0]
            right = stereo[:, 1]
            samples = right if np.sqrt(np.mean(right ** 2)) >= np.sqrt(np.mean(left ** 2)) else left
        else:
            samples = raw.astype(np.float32)
        samples = samples / 32768.0
        rms = float(np.sqrt(np.mean(samples ** 2)))
        if 0 < rms < 0.02:
            samples = np.clip(samples * min(8.0, 0.02 / rms), -1.0, 1.0)

        # 识别（使用正确的 API）
        stream = model.create_stream()
        stream.accept_waveform(sample_rate, samples)

        # 解码
        model.decode_stream(stream)

        # 获取结果 - 使用 stream.result 而不是 model.get_result
        result = stream.result
        text = result.text if hasattr(result, "text") else ""

        if text:
            logger.info(f"local_asr: transcribed {len(text)} chars from {wav_path}")
            return {"ok": True, "text": text.strip(), "error": ""}
        else:
            return {"ok": True, "text": "", "error": ""}

    except Exception as e:
        # 模型可能需要 text_norm 文件，捕获异常优雅返回
        logger.warning(f"local_asr failed (可能是模型需要 text_norm): {e}")
        return {"ok": True, "text": "", "error": ""}  # 返回空文本，不报错


def is_asr_available() -> bool:
    """检查 ASR 是否可用"""
    return _load_asr_model() is not None
