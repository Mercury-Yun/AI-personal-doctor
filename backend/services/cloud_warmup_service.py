import logging
import threading

from ..config import get_settings

logger = logging.getLogger(__name__)
_warmup_started = False


def warm_cloud_services() -> None:
    global _warmup_started
    if _warmup_started:
        return
    _warmup_started = True

    settings = get_settings()
    if not settings.get("cloud_warmup", True):
        return

    def _run() -> None:
        try:
            from .cloud_llm_service import cloud_configured
            from .cloud_tts_service import (
                cloud_tts_configured,
                _ensure_pipeline,
                prewarm_prompt,
                synthesize_bytes,
            )
            from .rag_service import get_rag_service

            rag = get_rag_service()
            if not rag.initialized:
                rag.initialize()

            if cloud_configured():
                from openai import OpenAI

                client = OpenAI(
                    api_key=settings["dashscope_api_key"],
                    base_url=settings["dashscope_base_url"],
                )
                client.chat.completions.create(
                    model=settings["dashscope_model"],
                    messages=[{"role": "user", "content": "回复一个字：好"}],
                    stream=False,
                    extra_body={"enable_thinking": False},
                )
                logger.info("cloud warmup: llm ok")

            if cloud_tts_configured():
                _ensure_pipeline()
                synthesize_bytes("好")
                logger.info("cloud warmup: tts ok")
                for prompt in ("我在呢", "哎，我在", "来了", "嗯，怎么了", "您说，我听着呢"):
                    prewarm_prompt(prompt)
        except Exception as exc:
            logger.warning("cloud warmup failed: %s", exc)

    threading.Thread(target=_run, name="cloud-warmup", daemon=True).start()
