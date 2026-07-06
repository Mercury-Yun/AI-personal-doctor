"""拍照识药：VLM 只识别药名+规格，再用本地结构化知识库补齐结构化字段。"""

import json
import logging
import re
from pathlib import Path

from fastapi import HTTPException

from ..config import get_settings
from .cloud_llm_service import CloudLlmError, cloud_configured, stream_vision
from .medicine_kb import get_medicine_kb

logger = logging.getLogger(__name__)

CAPTURE_DIR = Path("/tmp/ai_doctor_captures")

IDENTIFY_PROMPT = (
    "你是药盒识别助手。请仔细观察图片中的药品包装盒或说明书，只识别药品名称与规格，"
    "不要给出用法或说明。只返回一个 JSON 对象，不要包含任何多余文字、解释或代码块标记。\n"
    "JSON 格式：{\"name\": \"药品通用名（尽量去掉商品名和厂家，如苯磺酸氨氯地平片写氨氯地平）\", "
    "\"spec\": \"规格，如 5mg、0.3g、10ml，看不清则填空字符串\", "
    "\"raw\": \"包装上完整可见的药品名称文字\"}\n"
    "如果图中没有药盒或完全无法辨认药名，name 与 raw 都返回空字符串。"
)


def _latest_capture() -> bytes:
    if not CAPTURE_DIR.exists():
        raise HTTPException(status_code=400, detail="请先拍照再识别药品")
    files = sorted(
        CAPTURE_DIR.glob("capture_*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not files:
        raise HTTPException(status_code=400, detail="请先拍照再识别药品")
    return files[0].read_bytes()


def _parse_vision_json(text: str) -> dict:
    if not text:
        return {}
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def identify_medicine() -> dict:
    settings = get_settings()
    if not (settings["chat_use_cloud_llm"] and cloud_configured()):
        raise HTTPException(status_code=503, detail="未配置云端模型，请设置 DASHSCOPE_API_KEY")

    image = _latest_capture()
    try:
        parts = list(stream_vision(IDENTIFY_PROMPT, image, speak=False))
    except CloudLlmError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    parsed = _parse_vision_json("".join(parts).strip())
    recognized_name = (parsed.get("name") or "").strip()
    recognized_raw = (parsed.get("raw") or "").strip()
    recognized_spec = (parsed.get("spec") or "").strip()

    if not recognized_name and not recognized_raw:
        return {
            "ok": True,
            "matched": False,
            "recognized_name": "",
            "spec": recognized_spec,
            "name": "",
            "category": "",
            "uses": "",
            "usage": "",
            "cautions": [],
            "source": "",
            "note": "没能看清药名，请把药盒正面（印有药品名称的一面）对准摄像头重新拍照。",
        }

    display_recognized = recognized_name or recognized_raw
    record = get_medicine_kb().match(recognized_name, recognized_raw)
    if record:
        return {
            "ok": True,
            "matched": True,
            "recognized_name": display_recognized,
            "spec": recognized_spec or record.get("spec", ""),
            "name": record.get("name", display_recognized),
            "category": record.get("category", ""),
            "uses": record.get("uses", ""),
            "usage": record.get("usage", ""),
            "cautions": record.get("cautions", []),
            "source": "本地用药知识库",
            "note": "以下信息仅供参考，具体请遵医嘱或参照药品说明书。",
        }

    return {
        "ok": True,
        "matched": False,
        "recognized_name": display_recognized,
        "spec": recognized_spec,
        "name": display_recognized,
        "category": "",
        "uses": "",
        "usage": "",
        "cautions": [],
        "source": "",
        "note": "本地知识库暂未收录该药品。可点击「继续问药」向 AI 详细询问，或咨询医生、药师。",
    }
