"""AI 病例摘要：把单个病例压成结构化文本喂给云端 LLM，实时生成 8 键 JSON，不落库。

形态照 medicine_service.py：固定 prompt → chat_once → 正则截取 JSON + json.loads
防御性解析；cloud_configured() 守卫，未配置抛 503。输出恒为 CaseSummary 的 8 键。
"""

import json
import logging
import re

from fastapi import HTTPException

from .. import models
from ..config import get_settings
from .case_service import build_case_document
from .cloud_llm_service import CloudLlmError, chat_once, cloud_configured

logger = logging.getLogger(__name__)

_TEXT_KEYS = (
    "main_disease",
    "history",
    "recent_visit",
    "recent_exam",
    "current_treatment",
    "doctor_advice",
    "follow_up",
)

SUMMARY_PROMPT = (
    "你是一名严谨的病历分析助手。请阅读下面的病例内容，提炼结构化摘要。"
    "只返回一个 JSON 对象，不要包含任何多余文字、解释或代码块标记。\n"
    "JSON 必须且只能包含以下键：\n"
    "{\"main_disease\": \"主要疾病/诊断，一句话\", "
    "\"history\": \"病史与既往史概述\", "
    "\"recent_visit\": \"最近一次就诊情况（时间/医院/科室/主诉）\", "
    "\"recent_exam\": \"关键检查及其结果\", "
    "\"current_treatment\": \"当前治疗与用药\", "
    "\"doctor_advice\": \"医生建议要点\", "
    "\"follow_up\": \"随访与复诊安排\", "
    "\"risk\": [\"风险提示1\", \"风险提示2\"]}\n"
    "无对应信息的字段填空字符串（risk 填空数组）。所有内容必须基于病例，不要编造。"
)


def _parse_summary_json(text: str) -> dict:
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


def _normalize(parsed: dict) -> dict:
    result = {key: str(parsed.get(key) or "").strip() for key in _TEXT_KEYS}
    risk = parsed.get("risk", [])
    if isinstance(risk, str):
        risk = [x.strip() for x in re.split(r"[、,，;；\n]+", risk) if x.strip()]
    elif isinstance(risk, list):
        risk = [str(x).strip() for x in risk if str(x).strip()]
    else:
        risk = []
    result["risk"] = risk
    return result


def _require_cloud() -> None:
    settings = get_settings()
    if not (settings["chat_use_cloud_llm"] and cloud_configured()):
        raise HTTPException(status_code=503, detail="未配置云端模型，请设置 DASHSCOPE_API_KEY")


def summarize_case(db, case_id: int) -> dict:
    _require_cloud()
    case = db.get(models.MedicalCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    document = build_case_document(case)
    if not document.strip():
        return _normalize({})

    prompt = f"{SUMMARY_PROMPT}\n\n病例内容：\n{document}"
    try:
        text = chat_once(prompt)
    except CloudLlmError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return _normalize(_parse_summary_json(text))
