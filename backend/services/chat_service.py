import logging
import re
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..config import get_settings
from .cloud_llm_service import CloudLlmError, cloud_configured, stream_chat, stream_vision
from .medication_intent import build_verify_vision_question, is_medication_verify_question
from .prompt_builder import build_chat_prompt
from .rag_service import get_rag_service
from .reminder_service import (
    build_intake_log_summary,
    get_pending_reminder_for_verify,
    try_ack_from_verify_answer,
)
from .spoken_response import (
    format_knowledge_snippets,
    get_spoken_style_rules,
    is_detail_request,
    sanitize_spoken_answer,
)
from .tts_service import speak as tts_speak, tts_enabled as tts_is_enabled

logger = logging.getLogger(__name__)

_HISTORY_MAX_TURNS = 6
_HISTORY_MSG_MAX_CHARS = 220


def _truncate_history_text(text: str, limit: int = _HISTORY_MSG_MAX_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _build_session_history_text(db: Session, session_id: int, *, max_turns: int = _HISTORY_MAX_TURNS) -> str:
    rows = get_chat_history(db, session_id)
    if not rows:
        return ""
    recent = rows[-(max_turns * 2) :]
    lines: list[str] = []
    for row in recent:
        role = "患者" if row.role == "user" else "助手"
        lines.append(f"{role}：{_truncate_history_text(row.content)}")
    return "\n".join(lines)


def create_chat_session(db: Session, user_id: int):
    if not db.get(models.User, user_id):
        raise HTTPException(status_code=404, detail="User not found")

    session = models.ChatSession(user_id=user_id, title="新问诊", updated_at=datetime.now())
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def list_chat_sessions(db: Session, user_id: int):
    return (
        db.query(models.ChatSession)
        .filter(models.ChatSession.user_id == user_id)
        .order_by(models.ChatSession.updated_at.desc(), models.ChatSession.id.desc())
        .all()
    )


def update_chat_session_title(db: Session, session_id: int, title: str):
    session = db.get(models.ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.title = build_session_title(title)
    session.updated_at = datetime.now()
    db.commit()
    db.refresh(session)
    return session


def delete_chat_session(db: Session, session_id: int):
    session = db.get(models.ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    db.delete(session)
    db.commit()


def get_chat_history(db: Session, session_id: int):
    return (
        db.query(models.ChatHistory)
        .filter(models.ChatHistory.session_id == session_id)
        .order_by(models.ChatHistory.created_at.asc(), models.ChatHistory.id.asc())
        .all()
    )


def get_recent_sessions(db: Session, limit: int = 5):
    return (
        db.query(models.ChatSession)
        .order_by(models.ChatSession.updated_at.desc(), models.ChatSession.id.desc())
        .limit(limit)
        .all()
    )


def answer_question(db: Session, session_id: int, user_id: int, question: str, speak: bool = False):
    user, session, question, knowledge, prompt, context = _prepare_chat(
        db, session_id, user_id, question
    )
    answer, llm_source = generate_answer(prompt, question, context, speak=speak)
    _save_chat_turn(db, user_id, session_id, session, question, answer)
    return {"answer": answer, "references": knowledge, "prompt": prompt, "source": llm_source}


def stream_answer_question(db: Session, session_id: int, user_id: int, question: str, speak: bool = False):
    user, session, question, knowledge, prompt, context = _prepare_chat(
        db, session_id, user_id, question
    )
    yield {"type": "meta", "references": knowledge}

    answer_parts: list[str] = []
    source = "mock"
    settings = get_settings()

    if settings["chat_use_cloud_llm"] and cloud_configured():
        try:
            for text in stream_chat(prompt, speak=speak):
                answer_parts.append(text)
                yield {"type": "delta", "text": text}
            source = settings["dashscope_model"]
        except CloudLlmError as exc:
            logger.warning("cloud chat stream failed: %s", exc)
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not answer_parts:
        mock = mock_ai_answer(question, context)
        yield {"type": "delta", "text": mock}
        answer = mock
    else:
        answer = sanitize_spoken_answer("".join(answer_parts).strip())

    _save_chat_turn(db, user_id, session_id, session, question, answer)
    yield {"type": "done", "answer": answer, "references": knowledge, "source": source}


DEFAULT_VISION_QUESTION = (
    "请读取药盒包装上的药名，用两三句口语说明怎么吃和注意什么，60字以内。"
)


def _vision_uses_rag(question: str) -> bool:
    q = (question or "").strip()
    if q == DEFAULT_VISION_QUESTION:
        return False
    identify_hints = ("识别", "什么药", "哪种药", "叫什么", "看看", "读一下", "图片中", "包装上")
    if any(h in q for h in identify_hints) and len(q) <= 48:
        return False
    return True


def _prepare_vision_chat(db: Session, session_id: int, user_id: int, question: str):
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    session = db.get(models.ChatSession, session_id)
    if not session or session.user_id != user_id:
        raise HTTPException(status_code=404, detail="Session not found")

    question = (question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    medications = db.query(models.Medication).filter(models.Medication.user_id == user_id).all()
    is_verify = is_medication_verify_question(question)
    detailed = not is_verify and is_detail_request(question)
    knowledge = []
    if not is_verify and _vision_uses_rag(question):
        knowledge = get_rag_service().search(question, top_k=3 if detailed else 2)
    context = build_vision_patient_context(
        user, medications, question, db, user_id, detailed=detailed
    )

    vision_question = question
    if is_verify:
        pending = get_pending_reminder_for_verify(db, user_id)
        if pending:
            vision_question = build_verify_vision_question(question, pending)
        else:
            vision_question = (
                f"{question}\n"
                "请读取<image>药盒包装上的药名，并对照患者长期用药清单，"
                "第一句明确回答是不是该吃的药；若不是，说明包装上的药名。"
            )

    history_text = "" if is_verify else _build_session_history_text(db, session_id)
    prompt = build_vision_prompt(context, knowledge, vision_question, history_text, detailed=detailed)
    return user, session, question, knowledge, prompt, context


def stream_vision_answer_question(
    db: Session, session_id: int, user_id: int, question: str, speak: bool = False
):
    settings = get_settings()
    use_cloud = settings["chat_use_cloud_llm"] and cloud_configured()

    if not use_cloud:
        raise HTTPException(status_code=503, detail="未配置云端模型，请设置 DASHSCOPE_API_KEY")
    if use_cloud and speak and not tts_is_enabled():
        logger.warning("TTS unavailable: answer will be text only")

    question = (question or "").strip() or DEFAULT_VISION_QUESTION
    user, session, question, knowledge, prompt, context = _prepare_vision_chat(
        db, session_id, user_id, question
    )
    yield {"type": "meta", "references": knowledge}

    answer_parts: list[str] = []
    source = "mock"

    if use_cloud:
        try:
            # 从本地拍照目录读取最新照片
            capture_dir = Path("/tmp/ai_doctor_captures")
            files = sorted(capture_dir.glob("capture_*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not files:
                raise HTTPException(status_code=400, detail="请先拍照再进行视觉问答")
            image_jpeg = files[0].read_bytes()

            for text in stream_vision(prompt, image_jpeg, speak=speak and tts_is_enabled()):
                answer_parts.append(text)
                yield {"type": "delta", "text": text}
            source = settings["dashscope_vision_model"]
        except CloudLlmError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not answer_parts:
        mock = "抱歉，未能识别图片中的药品，请对准药盒正面再拍一次。"
        yield {"type": "delta", "text": mock}
        answer = mock
    else:
        answer = sanitize_spoken_answer("".join(answer_parts).strip())

    user_note = f"[拍照问药] {question}"
    _save_chat_turn(db, user_id, session_id, session, user_note, answer)
    reminder_ack = None
    if is_medication_verify_question(question):
        reminder_ack = try_ack_from_verify_answer(db, user_id, answer)
    yield {
        "type": "done",
        "answer": answer,
        "references": knowledge,
        "source": source,
        "reminder_ack": reminder_ack,
    }


def _prepare_chat(db: Session, session_id: int, user_id: int, question: str):
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    session = db.get(models.ChatSession, session_id)
    if not session or session.user_id != user_id:
        raise HTTPException(status_code=404, detail="Session not found")

    question = (question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    history_text = _build_session_history_text(db, session_id)
    prompt, knowledge, case_refs = build_chat_prompt(db, user, user_id, question, history_text)
    # context 保留给 mock_ai_answer 兜底用
    context = prompt
    return user, session, question, knowledge, prompt, context


def _save_chat_turn(db: Session, user_id: int, session_id: int, session, question: str, answer: str):
    db.add(models.ChatHistory(user_id=user_id, session_id=session_id, role="user", content=question))
    db.add(models.ChatHistory(user_id=user_id, session_id=session_id, role="assistant", content=answer))
    if session.title == "新问诊":
        session.title = build_session_title(question)
    session.updated_at = datetime.now()
    db.commit()


def voice_question(db: Session, session_id: int, user_id: int, speak: bool = True):
    """
    云端化版本：使用本地麦克风录音（后续接 DashScope ASR）
    """
    from .local_audio import record_wav as local_record_wav

    record_result = local_record_wav(duration_sec=6.0)
    if not record_result.get("ok"):
        raise HTTPException(status_code=503, detail=record_result.get("error", "录音失败"))

    # TODO: 调用 DashScope ASR 将 WAV 转为文字
    # 临时返回空问题，提示用户使用按钮输入
    raise HTTPException(status_code=501, detail="语音输入功能正在迁移到云端 ASR，请使用文字输入")


def generate_answer(prompt: str, question: str, context: str, speak: bool = False):
    settings = get_settings()
    if settings["chat_use_cloud_llm"] and cloud_configured():
        try:
            from .cloud_llm_service import chat_once

            answer = sanitize_spoken_answer(chat_once(prompt))
            if answer:
                if speak and tts_is_enabled():
                    tts_speak(answer, wait=True)
                return answer, settings["dashscope_model"]
        except CloudLlmError as exc:
            logger.warning("cloud chat failed: %s", exc)

    return mock_ai_answer(question, context), "mock"


def build_session_title(content):
    title = (content or "").strip()[:20]
    return title or "新问诊"


def build_vision_patient_context(
    user,
    medications,
    question: str = "",
    db=None,
    user_id: int | None = None,
    *,
    detailed: bool = False,
):
    chronic_diseases = extract_chronic_diseases(user.chronic_diseases)
    medicine_names = [item.name for item in medications if item.name]
    intake_block = ""
    if db is not None and user_id is not None:
        intake_block = build_intake_log_summary(db, user_id)
    style_rules = get_spoken_style_rules(question)
    context_lines = [
        "你是一名经验丰富的家庭医生，名叫小医，正在帮老人看药盒照片，回答会语音播报。",
        '你说话温暖耐心，像家人帮忙核对药品。确认是对的药可以说"对的，这就是您该吃的"。',
        style_rules,
        "识别规则：必须以药盒包装上可见的文字为准；先报药名，再说明。",
        "若包装文字模糊或看不清，请明确说「包装文字不清晰，无法确认」，不要猜测常见药名。",
        "验药时对照长期用药清单与服药记录，判断是不是该吃的药、是否已在该时间点服过。",
        "",
        "患者信息：",
        f"姓名：{user.name}",
        f"年龄：{user.age or '未知'}岁",
        f"性别：{user.gender or '未知'}",
        f"过敏史：{user.allergy or '暂无'}",
        f"慢性疾病：{'、'.join(chronic_diseases) if chronic_diseases else '暂无记录'}",
        f"长期用药：{'、'.join(medicine_names) if medicine_names else '暂无记录'}",
    ]
    if intake_block:
        context_lines.extend(["", intake_block])
    return "\n".join(context_lines)


def build_vision_prompt(
    context, knowledge, question, history_text: str = "", *, detailed: bool = False
):
    knowledge_text = format_knowledge_snippets(knowledge, detailed=detailed)
    rag_block = ""
    if knowledge_text:
        rag_hint = "可综合多条要点" if detailed else "只提炼一句"
        rag_block = (
            f"知识库参考（仅作补充，与包装冲突以包装为准，{rag_hint}）：\n"
            f"{knowledge_text}\n\n"
        )
    history_block = ""
    if (history_text or "").strip():
        history_block = f"本会话此前对话：\n{history_text.strip()}\n\n"
    answer_hint = "请按患者要求结合包装详细介绍" if detailed else "请结合包装口语回答"
    return (
        f"{context}\n\n"
        f"{rag_block}"
        f"{history_block}"
        f"{answer_hint}：{question}"
    )


def mock_ai_answer(question, context):
    if "头晕" in question:
        if "高血压" in context:
            return "结合您的高血压情况，建议先测血压、休息，若持续不适请尽快就医。"
        return "建议先测血压并休息，若持续不适请就医。"
    if "血糖" in question:
        return "建议监测血糖并保持规律饮食，异常时请咨询医生。"
    if "失眠" in question:
        return "建议固定作息时间，睡前少喝茶和咖啡。"
    return "根据现有信息，建议您注意休息并按医嘱用药，如有加重请及时就医。"


def extract_chronic_diseases(chronic_text):
    diseases = []
    for item in re.split(r"[、,，;；\n\s]+", chronic_text or ""):
        disease = item.strip()
        if disease and disease not in diseases:
            diseases.append(disease)
    return diseases
