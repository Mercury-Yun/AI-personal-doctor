"""Prompt Builder：意图路由 + 查询改写 + 结构化 prompt 组装。

只负责文本问诊链路的 prompt 构建。Vision 链路保持在 chat_service.py 不动。
chat_service._prepare_chat 调用 build_chat_prompt() 即可，接口兼容。
"""

import re
from enum import Enum

from sqlalchemy.orm import Session

from .. import models
from .case_rag_service import get_case_rag_service
from .case_service import build_case_digest
from .rag_service import get_rag_service
from .reminder_service import build_intake_log_summary
from .spoken_response import format_knowledge_snippets, get_spoken_style_rules, is_detail_request

import logging

logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════
# 一、Intent 检测（关键词规则，3 类）
# ════════════════════════════════════════════════════════


class Intent(str, Enum):
    MEDICAL = "medical"  # 疾病/症状/检查/病例/急症 → 全上下文
    MEDICATION = "medication"  # 药物相关 → 强化药物+服药记录
    CASUAL = "casual"  # 闲聊/简单追问 → 仅基本信息+历史


_MEDICATION_HINTS = (
    "药", "吃药", "服药", "用药", "停药", "换药", "漏服", "漏吃",
    "剂量", "副作用", "不良反应", "药片", "胶囊", "片剂",
    "氨氯地平", "美托洛尔", "阿司匹林", "二甲双胍", "降压", "降糖",
)

_MEDICAL_HINTS = (
    "头晕", "头疼", "头痛", "胸闷", "胸痛", "心慌", "心悸",
    "血压", "血糖", "血脂", "血氧", "心率",
    "呼吸困难", "喘不过气", "恶心", "呕吐", "腹痛", "腹泻",
    "失眠", "睡不着", "乏力", "疲劳", "水肿", "浮肿",
    "高血压", "糖尿病", "冠心病", "心脏", "肾",
    "检查", "化验", "报告", "指标", "异常",
    "病例", "病历", "诊断", "就诊", "手术",
    "过敏", "发烧", "发热", "咳嗽", "感冒",
)

_EMERGENCY_HINTS = (
    "胸痛", "呼吸困难", "喘不过气", "昏迷", "晕倒", "大出血",
    "中风", "口角歪斜", "半身不遂", "剧烈头痛", "意识不清",
)


def detect_intent(question: str) -> Intent:
    """基于关键词的轻量意图分类，不引入模型。"""
    q = (question or "").strip()
    if not q:
        return Intent.CASUAL

    # 优先检查药物意图（更窄更确定）
    if any(h in q for h in _MEDICATION_HINTS):
        return Intent.MEDICATION

    # 再检查医学/疾病意图
    if any(h in q for h in _MEDICAL_HINTS):
        return Intent.MEDICAL

    # 短句且无明确关键词 → 可能是追问，归 CASUAL
    if len(q) <= 6:
        return Intent.CASUAL

    # 默认归 MEDICAL（宁可多给上下文也不遗漏）
    return Intent.MEDICAL


def is_emergency(question: str) -> bool:
    """检测紧急情况关键词。"""
    return any(h in (question or "") for h in _EMERGENCY_HINTS)


# ════════════════════════════════════════════════════════
# 二、Query Rewrite（指代消解）
# ════════════════════════════════════════════════════════

# 常见指代词
_PRONOUN_PATTERNS = re.compile(
    r"(这个药|那个药|这药|那药|它|这个|那个|刚才说的|上次说的|之前说的|前面提到的)"
)

# 从历史对话中提取药名/疾病名的简易正则
_ENTITY_RE = re.compile(
    r"([\u4e00-\u9fff]{2,8}(?:片|胶囊|颗粒|口服液|滴丸|缓释片|控释片))"  # 药名
    r"|"
    r"(高血压|糖尿病|冠心病|高脂血症|心律失常|哮喘|痛风|贫血|甲亢|甲减)"  # 常见病名
)


def rewrite_query(question: str, history_text: str) -> str:
    """基于最近对话历史做简易指代消解，改善 RAG 命中率。"""
    q = (question or "").strip()
    if not q or not _PRONOUN_PATTERNS.search(q):
        return q

    # 从历史中提取最近提到的实体
    entities = _ENTITY_RE.findall(history_text or "")
    if not entities:
        return q

    # 取最近出现的实体（flatten tuple groups）
    flat = [e for group in reversed(entities) for e in group if e]
    if not flat:
        return q

    latest_entity = flat[0]
    rewritten = _PRONOUN_PATTERNS.sub(latest_entity, q, count=1)
    if rewritten != q:
        logger.debug("query rewrite: '%s' → '%s'", q, rewritten)
    return rewritten


# ════════════════════════════════════════════════════════
# 三、各 Context Block 构建
# ════════════════════════════════════════════════════════

def _extract_chronic_diseases(chronic_text: str) -> list[str]:
    """拆分慢病字段为列表。"""
    diseases = []
    for item in re.split(r"[、,，;；\n\s]+", chronic_text or ""):
        d = item.strip()
        if d and d not in diseases:
            diseases.append(d)
    return diseases


def _short(text: str, limit: int = 90) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) > limit:
        return f"{text[: limit - 1]}…"
    return text


def _build_patient_block(user, medications) -> str:
    """【患者信息】+ 【长期用药】，始终注入。"""
    chronic = _extract_chronic_diseases(user.chronic_diseases)
    med_names = [m.name for m in medications if m.name]
    lines = [
        "【患者信息】",
        f"姓名：{user.name}",
        f"年龄：{user.age or '未知'}岁",
        f"性别：{user.gender or '未知'}",
        f"过敏史：{user.allergy or '暂无'}",
        f"慢性疾病：{'、'.join(chronic) if chronic else '暂无记录'}",
    ]
    if med_names:
        lines.append(f"\n【长期用药】\n{'、'.join(med_names)}")
    else:
        lines.append(f"\n【长期用药】\n暂无记录")
    return "\n".join(lines)


def _build_intake_block(db: Session, user_id: int) -> str:
    """【服药记录】，仅 MEDICATION intent 或有记录时注入。"""
    text = build_intake_log_summary(db, user_id)
    if not text or "暂无记录" in text:
        return ""
    return f"\n【服药记录】\n{text}"


def _build_case_block(db: Session, user_id: int) -> str:
    """【病例摘要】，MEDICAL intent 时注入。"""
    digest = build_case_digest(db, user_id)
    if not digest:
        return ""
    return f"\n{digest}"


def _build_knowledge_block(snippets: list[dict], detailed: bool) -> str:
    """【知识库参考】。"""
    text = format_knowledge_snippets(snippets, detailed=detailed)
    if not text:
        return ""
    hint = "可综合多条要点" if detailed else "只提炼一句，勿照搬"
    return f"\n【知识库参考】（{hint}）\n{text}"


def _build_case_rag_block(refs: list[dict]) -> str:
    """【病例参考】。"""
    if not refs:
        return ""
    lines = [f"- {_short(r.get('content', ''))}" for r in refs if r.get("content")]
    if not lines:
        return ""
    return "\n【本人历史病例参考】（仅供结合，勿照搬）\n" + "\n".join(lines)


def _build_history_block(history_text: str) -> str:
    """【历史对话】。"""
    text = (history_text or "").strip()
    if not text:
        return ""
    return f"\n【历史对话】\n{text}"


# ════════════════════════════════════════════════════════
# 四、Medical Constraints & System Role
# ════════════════════════════════════════════════════════

_SYSTEM_ROLE = """你是一名经验丰富的家庭医生，名叫小医，正在通过语音陪一位老人聊健康。
你说话温暖、耐心，像跟自家长辈聊天。
先简短表达对老人的理解或关心，再给建议。
老人焦虑或害怕时，先安抚情绪再分析病情。
称呼用"您"，可以说"放心""不用太担心""我帮您看看"。"""

_MEDICAL_GOAL = """你的任务：
1. 先关心患者感受，再结合画像（年龄、慢病、用药）分析问题。
2. 结合病例与检查结果给出针对性建议。
3. 结合长期药物判断用药安全性。
4. 结合医学知识回答，不确定的不要编造。
5. 高风险情况优先提醒及时就医，但语气要安抚而非吓唬。"""

_MEDICAL_CONSTRAINTS = """注意限制：
- 如遇紧急情况（胸痛、呼吸困难、意识不清等），先说"别慌"，再建议拨打120或就近就医。
- 信息不足时温和追问，如"您能跟我说说持续多久了吗""有没有量过血压"。
- 不替代医生做诊断或开处方，可以说"建议您跟医生确认一下"。
- 不猜测检查结果，不确定时诚实说"这个需要看具体报告"。"""

_EMERGENCY_EXTRA = '\n⚠️ 患者描述涉及紧急情况。先安抚"别慌"，再果断建议立即就医或拨打120。'

_FOLLOWUP_HINT = "若患者在追问，请结合此前对话理解指代（如「它」「刚才说的」「那个药」）。"

_MEDICATION_HINT = "判断该不该吃某个药时，务必参考服药记录，避免重复提醒已服过的剂量或忽略漏服。"


# ════════════════════════════════════════════════════════
# 五、Prompt Composer（核心对外接口）
# ════════════════════════════════════════════════════════

# Intent → RAG top_k 映射
_INTENT_RAG_K = {
    Intent.CASUAL: 0,
    Intent.MEDICATION: 2,
    Intent.MEDICAL: 3,
}

_INTENT_CASE_RAG_K = {
    Intent.CASUAL: 0,
    Intent.MEDICATION: 0,
    Intent.MEDICAL: 2,
}


def build_chat_prompt(
    db: Session,
    user,
    user_id: int,
    question: str,
    history_text: str,
) -> tuple[str, list[dict], list[dict]]:
    """构建文本问诊 prompt，返回 (prompt, knowledge, case_refs)。

    替代原 chat_service 中 build_patient_context + build_prompt 的组合。
    """
    detailed = is_detail_request(question)
    intent = detect_intent(question)

    # Query Rewrite（用原始 question 做意图检测，改写后用于检索）
    search_query = rewrite_query(question, history_text)

    # 药物
    medications = db.query(models.Medication).filter(models.Medication.user_id == user_id).all()

    # RAG 检索（按 intent 调 top_k）
    rag_k = _INTENT_RAG_K.get(intent, 2)
    if detailed:
        rag_k = max(rag_k, 3)
    knowledge = get_rag_service().search(search_query, top_k=rag_k) if rag_k > 0 else []

    # Case RAG（仅 MEDICAL）
    case_rag_k = _INTENT_CASE_RAG_K.get(intent, 0)
    case_refs = []
    if case_rag_k > 0:
        try:
            case_refs = get_case_rag_service().search(db, search_query, user_id=user_id, top_k=case_rag_k)
        except Exception as exc:
            logger.warning("case rag search failed: %s", exc)

    # ── 组装 prompt ──
    parts: list[str] = []

    # 1. 系统角色
    parts.append(f"【系统角色】\n{_SYSTEM_ROLE}")

    # 2. 回答风格
    style_rules = get_spoken_style_rules(question)
    parts.append(style_rules)

    # 3. Medical Goal + Constraints（MEDICAL/MEDICATION 注入）
    if intent in (Intent.MEDICAL, Intent.MEDICATION):
        parts.append(_MEDICAL_GOAL)
        parts.append(_MEDICAL_CONSTRAINTS)
        if is_emergency(question):
            parts.append(_EMERGENCY_EXTRA)

    # 4. 行为提示
    parts.append(_FOLLOWUP_HINT)
    if intent == Intent.MEDICATION:
        parts.append(_MEDICATION_HINT)

    # 5. 患者信息 + 长期用药（始终注入）
    parts.append(_build_patient_block(user, medications))

    # 6. 服药记录（MEDICATION 始终注入；MEDICAL 有记录也注入）
    if intent in (Intent.MEDICATION, Intent.MEDICAL):
        intake = _build_intake_block(db, user_id)
        if intake:
            parts.append(intake)

    # 7. 病例摘要（MEDICAL 注入）
    if intent == Intent.MEDICAL:
        case_block = _build_case_block(db, user_id)
        if case_block:
            parts.append(case_block)

    # 8. 知识库参考
    kb_block = _build_knowledge_block(knowledge, detailed)
    if kb_block:
        parts.append(kb_block)

    # 9. 病例 RAG 参考
    cr_block = _build_case_rag_block(case_refs)
    if cr_block:
        parts.append(cr_block)

    # 10. 历史对话
    hist_block = _build_history_block(history_text)
    if hist_block:
        parts.append(hist_block)

    # 11. 当前问题 + 回答要求
    answer_hint = "请按患者要求详细介绍" if detailed else "请直接口语回答"
    parts.append(f"\n【当前问题】\n{answer_hint}患者当前问题：{question}")

    prompt = "\n\n".join(parts)
    return prompt, knowledge, case_refs
