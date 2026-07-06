import base64
import logging

from ..config import get_settings
from .tts_service import speak as tts_speak, tts_enabled as tts_is_enabled

logger = logging.getLogger(__name__)

_SENTENCE_END = "。！？!?\n"


class CloudLlmError(Exception):
    pass


def cloud_configured() -> bool:
    settings = get_settings()
    key = (settings.get("dashscope_api_key") or "").strip()
    return bool(key) and not key.startswith("REPLACE_")


def _require_client():
    if not cloud_configured():
        raise CloudLlmError("请先在 .env 或环境变量中配置 DASHSCOPE_API_KEY")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise CloudLlmError("缺少 openai 依赖，请执行 pip install openai") from exc

    settings = get_settings()
    return OpenAI(
        api_key=settings["dashscope_api_key"],
        base_url=settings["dashscope_base_url"],
    )


class _StreamTtsFeeder:
    """流式合并播报：首段尽早开口，后续尽量按整句合并减少 API 调用。"""

    def __init__(self, enabled: bool):
        self.enabled = enabled
        self._accum = ""
        self._first_spoken = False
        settings = get_settings()
        self._batch_max = max(60, int(settings.get("cosyvoice_batch_max_chars", 160)))
        self._first_batch = max(16, int(settings.get("cosyvoice_first_batch_chars", 36)))

    def push(self, text: str) -> None:
        if not self.enabled or not text:
            return
        self._accum += text
        if not self._first_spoken:
            self._try_first_batch()
            return
        while True:
            chunk = self._take_sentence_chunk(force=False)
            if not chunk:
                break
            self._speak(chunk)

    def flush(self) -> None:
        if self.enabled and self._accum.strip():
            if not self._first_spoken:
                self._try_first_batch(force=True)
            while True:
                chunk = self._take_sentence_chunk(force=True)
                if not chunk:
                    break
                self._speak(chunk)
        self._accum = ""
        if self.enabled:
            from .tts_service import wait_for_tts_idle

            wait_for_tts_idle()

    def _try_first_batch(self, force: bool = False) -> None:
        text = self._accum
        if not text.strip():
            return
        cut = _last_sentence_end(text)
        if cut >= 0 and cut + 1 >= 8:
            chunk = text[: cut + 1].strip()
            self._accum = text[cut + 1 :].lstrip()
            if chunk:
                self._speak(chunk)
                self._first_spoken = True
            return
        if force or len(text) >= self._first_batch:
            chunk = text[: self._first_batch].strip()
            self._accum = text[self._first_batch :].lstrip()
            if chunk:
                self._speak(chunk)
                self._first_spoken = True

    def _take_sentence_chunk(self, force: bool) -> str:
        text = self._accum
        if not text.strip():
            return ""
        if len(text) <= self._batch_max:
            cut = _last_sentence_end(text)
            if cut < 0:
                return text.strip() if force else ""
            end = cut + 1
            chunk = text[:end].strip()
            self._accum = text[end:].lstrip()
            return chunk
        chunk, rest = _take_speech_chunk(text, self._batch_max)
        self._accum = rest
        return chunk

    def _speak(self, text: str) -> None:
        try:
            tts_speak(text, wait=False)
        except Exception as exc:
            logger.warning("cloud TTS feed failed: %s", exc)


def _last_sentence_end(text: str) -> int:
    cut_at = -1
    for mark in _SENTENCE_END:
        pos = text.rfind(mark)
        if pos > cut_at:
            cut_at = pos
    return cut_at


def _take_speech_chunk(text: str, max_chars: int) -> tuple[str, str]:
    if len(text) <= max_chars:
        return text.strip(), ""
    window = text[:max_chars]
    cut_at = _last_sentence_end(window)
    if cut_at >= max(24, max_chars // 3):
        end = cut_at + 1
        return text[:end].strip(), text[end:].lstrip()
    return window.strip(), text[max_chars:].lstrip()


def _extra_body(settings) -> dict | None:
    if settings.get("dashscope_enable_thinking"):
        return {"enable_thinking": True}
    return {"enable_thinking": False}


def stream_chat(prompt: str, speak: bool = False):
    settings = get_settings()
    client = _require_client()
    feeder = _StreamTtsFeeder(speak)

    stream = client.chat.completions.create(
        model=settings["dashscope_model"],
        messages=[{"role": "user", "content": prompt}],
        stream=True,
        extra_body=_extra_body(settings),
    )

    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content or ""
        if not delta:
            continue
        feeder.push(delta)
        yield delta

    feeder.flush()


def stream_vision(prompt: str, image_jpeg: bytes, speak: bool = False):
    if not image_jpeg:
        raise CloudLlmError("没有可用的药盒照片，请先拍照")
    settings = get_settings()
    client = _require_client()
    feeder = _StreamTtsFeeder(speak)

    data_url = "data:image/jpeg;base64," + base64.b64encode(image_jpeg).decode("ascii")
    stream = client.chat.completions.create(
        model=settings["dashscope_vision_model"],
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        stream=True,
        extra_body=_extra_body(settings),
    )

    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content or ""
        if not delta:
            continue
        feeder.push(delta)
        yield delta

    feeder.flush()


def chat_once(prompt: str) -> str:
    parts = list(stream_chat(prompt, speak=False))
    return "".join(parts).strip()
