"""口语化回答：prompt 规范、RAG 片段整理、回答后清洗。"""

import re

# 默认：简短口语（语音播报）
SPOKEN_STYLE_BRIEF = """
回答风格（必须遵守）：
- 这是语音播报，像跟自家老人面对面聊天，语气亲切温暖。
- 总共 2～4 句，80～100 字以内。
- 开头可以简短共情（如"嗯，我理解""别担心""这个情况挺常见的"），再给建议。
- 不要一上来就"建议您..."，那像医院公告，要自然地说。
- 适当使用"您""啊""呢""哦"等语气词，让语音听起来自然。
- 禁止 markdown、星号、方括号标题、编号列表、冒号小标题。
- 只用逗号和句号；剂量用口语，例如「每天一次，一次一片」。
- 知识库只提炼一句要点，不要照搬「定义」「注意事项」等标签。
""".strip()

# 用户明确要求「详细介绍」时使用
SPOKEN_STYLE_DETAILED = """
回答风格（必须遵守）：
- 这是语音播报，患者要求详细介绍，可以多说一些，但语气要像跟长辈聊天。
- 用 4～6 句、150～220 字；按顺序说清药名、主要作用、怎么吃、注意什么。
- 开头先简短回应患者的关切，再展开说明。
- 禁止 markdown、星号、方括号标题、编号列表；只用逗号和句号。
- 可结合知识库与包装信息，但不要堆砌术语，用老人听得懂的话说。
- 最后一句温暖提醒，如"有什么不放心的，随时问我，或者跟医生确认一下"。
""".strip()

# 兼容旧引用
SPOKEN_STYLE_RULES = SPOKEN_STYLE_BRIEF

_DETAIL_HINTS = (
    "详细介绍",
    "详细说明",
    "详细讲",
    "详细说",
    "详细解释",
    "仔细介绍",
    "展开说",
    "展开讲",
    "多说一点",
    "多说几句",
    "多说一些",
    "讲详细",
    "说详细",
    "全面介绍",
    "具体介绍",
    "具体说说",
    "完整介绍",
)


def is_detail_request(question: str) -> bool:
    normalized = (question or "").strip()
    if not normalized:
        return False
    return any(hint in normalized for hint in _DETAIL_HINTS)


def get_spoken_style_rules(question: str) -> str:
    return SPOKEN_STYLE_DETAILED if is_detail_request(question) else SPOKEN_STYLE_BRIEF

_RAG_LABEL_RE = re.compile(
    r"^(定义|症状相关|注意事项|建议|用法相关|用法|禁忌|副作用)[：:]\s*"
)
_MD_HEADING_RE = re.compile(r"^#+\s*")


def flatten_rag_text(text: str) -> str:
    """把 RAG 段落压成一句口语素材，去掉 markdown 与小标题标签。"""
    parts: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        line = _MD_HEADING_RE.sub("", line)
        line = _RAG_LABEL_RE.sub("", line)
        line = line.strip("·-•* ")
        if line:
            parts.append(line)
    merged = " ".join(parts)
    merged = re.sub(r"\s+", " ", merged).strip()
    return merged


def format_knowledge_snippets(
    knowledge: list[dict],
    *,
    max_items: int = 2,
    max_chars: int = 96,
    detailed: bool = False,
) -> str:
    """注入 prompt 的 RAG 摘要：条数少、每条短、无 markdown。"""
    if detailed:
        max_items = max(max_items, 3)
        max_chars = max(max_chars, 180)
    if not knowledge:
        return ""
    lines: list[str] = []
    for item in knowledge[:max_items]:
        title = (item.get("title") or "").strip()
        body = flatten_rag_text(item.get("content") or "")
        if not body:
            continue
        if len(body) > max_chars:
            body = body[: max_chars - 1].rstrip() + "…"
        if title:
            lines.append(f"{title}：{body}")
        else:
            lines.append(body)
    return "\n".join(lines)


def sanitize_spoken_answer(text: str) -> str:
    """清洗模型输出，便于显示和 TTS。"""
    cleaned = (text or "").strip()
    if not cleaned:
        return cleaned

    cleaned = cleaned.replace("**", "").replace("*", "")
    cleaned = cleaned.replace("【", "").replace("】", "")
    cleaned = cleaned.replace("《", "").replace("》", "")
    cleaned = re.sub(r"`+", "", cleaned)
    cleaned = re.sub(r"^#+\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*[-*•·]\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*\d+[.)、）]\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"(?<=[，。；])\s*\d+[.)、）]\s*", "，", cleaned)
    cleaned = cleaned.replace("；", "，").replace(";", "，")
    cleaned = re.sub(r"(\S)[：:](?=\S)", r"\1，", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"，{2,}", "，", cleaned)
    cleaned = re.sub(r"。{2,}", "。", cleaned)
    cleaned = cleaned.strip("，。、 ")

    if cleaned and cleaned[-1] not in "。！？":
        cleaned += "。"

    return cleaned
