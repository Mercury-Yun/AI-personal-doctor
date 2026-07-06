PHOTO_HINTS = (
    "拍照",
    "问药",
    "识药",
    "药盒",
    "看看药",
    "拍药",
    "识别药",
    "拍张照",
    "拍一个",
    "这是什么药",
    "什么药",
    "哪种药",
    "药名",
    "包装上",
    "生产日期",
    "有效期",
    "保质期",
    "批号",
)

# "这是什么/那是什么"只有跟"药"搭配才算拍照意图
_POINTER_WHAT_DRUG_ONLY = ("这是什么", "这是啥", "那是什么", "那是啥")

# 健康对话排除词——含这些词时不应触发拍照
_HEALTH_CONTEXT_WORDS = (
    "症状", "病", "原因", "情况", "指标", "问题", "怎么办",
    "治疗", "为什么", "怎么回事", "疼", "痛", "检查", "报告",
    "血压", "血糖", "心脏", "头晕", "发烧", "咳嗽",
)

VERIFY_HINTS = (
    "是不是这个药",
    "是这个药",
    "该吃这个",
    "该吃吗",
    "拿对了",
    "拿错",
    "核实",
    "比对",
)

POINTER_WORDS = ("这个", "那个", "这盒", "那盒", "它", "这边", "上面", "包装上")
VISUAL_VERBS = ("看", "瞧", "认", "读", "拍", "识别")
DATE_WORDS = ("什么时候", "啥时", "几时", "日期", "年月", "到期")


def is_medication_verify_question(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    if any(hint in normalized for hint in VERIFY_HINTS):
        return True
    if "药" in normalized and any(p in normalized for p in POINTER_WORDS):
        if normalized.endswith("吗") or normalized.endswith("嘛"):
            return True
        if any(w in normalized for w in ("是不是", "对不对", "是不是这个")):
            return True
    return False


def is_drug_usage_question(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    usage_hints = (
        "怎么吃",
        "如何用",
        "用法",
        "用量",
        "一天",
        "几次",
        "饭前",
        "饭后",
        "间隔",
        "副作用",
        "禁忌",
        "注意",
        "能吃吗",
        "要不要吃",
    )
    return any(h in normalized for h in usage_hints)


def is_explicit_photo_request(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    explicit = (
        "拍照",
        "问药",
        "识药",
        "药盒",
        "看看药",
        "拍药",
        "识别药",
        "什么药",
        "这是什么药",
        "包装上",
    )
    if any(h in normalized for h in explicit):
        return True
    # "这是什么" + 药相关上下文 → photo
    if any(p in normalized for p in _POINTER_WHAT_DRUG_ONLY):
        if "药" in normalized:
            return True
        if not any(w in normalized for w in _HEALTH_CONTEXT_WORDS):
            return True  # 没有明确健康上下文时倾向拍照
    return False


def classify_intent(text: str) -> str:
    normalized = (text or "").strip()
    if not normalized:
        return "chat"

    # 健康上下文检测——含这些词优先走 chat
    has_health_context = any(w in normalized for w in _HEALTH_CONTEXT_WORDS)

    if is_drug_usage_question(normalized) and not is_explicit_photo_request(normalized):
        # 「这个药怎么吃」需先看药盒 → 问药拍照
        if any(p in normalized for p in POINTER_WORDS) or normalized.startswith(("这", "那")):
            return "photo"
        return "chat"

    if is_medication_verify_question(normalized):
        return "photo"

    if any(hint in normalized for hint in PHOTO_HINTS):
        # "吃什么药好/该吃什么药" 是用药咨询，不是拍照
        if "什么药" in normalized and any(w in normalized for w in ("吃", "用", "服", "该")):
            return "chat"
        return "photo"

    # "这是什么/那是什么" 需要药上下文才触发
    if any(p in normalized for p in _POINTER_WHAT_DRUG_ONLY):
        if "药" in normalized:
            return "photo"
        if has_health_context:
            return "chat"
        # 无明确上下文时，独立短句倾向拍照，长句倾向聊天
        return "photo" if len(normalized) <= 6 else "chat"

    has_pointer = any(word in normalized for word in POINTER_WORDS)
    has_visual = any(verb in normalized for verb in VISUAL_VERBS)
    has_date = any(word in normalized for word in DATE_WORDS)
    asks_what = "什么" in normalized or "啥" in normalized or "哪个" in normalized

    # 组合规则：必须含"药"相关词才触发，否则走 chat
    has_drug_context = "药" in normalized or any(
        w in normalized for w in ("药盒", "包装", "生产日期", "保质期", "有效期", "批号")
    )

    if has_health_context:
        return "chat"

    if has_visual and has_drug_context and (has_pointer or has_date or asks_what):
        return "photo"
    if has_pointer and has_drug_context and (has_date or asks_what):
        return "photo"
    if has_date and any(word in normalized for word in ("生产", "保质", "有效", "过期", "包装", "药盒")):
        return "photo"

    return "chat"


DOCTOR_SWITCH_HINTS = (
    "切换问诊",
    "去问医",
    "转到问诊",
    "换问诊",
    "改成问诊",
    "不想问药",
    "不问药",
    "别问药",
    "不问这个药",
    "问个别的问题",
    "问别的",
    "别的健康",
    "换个话题",
    "健康咨询",
    "一般问诊",
)

DRUG_FOLLOWUP_HINTS = (
    "这个药",
    "这药",
    "那个药",
    "该药",
    "此药",
    "副作用",
    "怎么吃",
    "用法",
    "用量",
    "一天",
    "几次",
    "饭前",
    "饭后",
    "间隔",
    "禁忌",
    "注意",
    "成分",
    "过期",
    "生产日期",
    "保质期",
    "包装",
    "药盒",
)

GENERAL_HEALTH_HINTS = (
    "为什么",
    "怎么回事",
    "原因",
    "症状",
    "疼",
    "痛",
    "病",
    "怎么办",
    "治疗",
    "发烧",
    "咳嗽",
    "头晕",
    "头痛",
    "睡眠",
    "血压",
    "血糖",
    "心脏",
    "胃",
    "肚子",
    "恶心",
    "呕吐",
    "胸闷",
    "乏力",
)


def wants_doctor_consult(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    if any(hint in normalized for hint in DOCTOR_SWITCH_HINTS):
        return True
    if "问诊" in normalized and "问药" not in normalized:
        if any(w in normalized for w in ("切换", "转", "去", "要", "开始", "改成", "进入")):
            return True
    if classify_intent(normalized) != "chat":
        return False
    has_health = any(w in normalized for w in GENERAL_HEALTH_HINTS)
    drug_ctx = any(w in normalized for w in DRUG_FOLLOWUP_HINTS) or "药" in normalized
    return has_health and not drug_ctx


RECAPTURE_HINTS = (
    "换一个",
    "换一盒",
    "换盒",
    "另一盒",
    "另一包",
    "另一个",
    "下一盒",
    "重新拍",
    "再拍",
    "拍一下",
    "拍一张",
    "再拍一张",
    "这个药呢",
    "那个药呢",
    "那盒呢",
    "这盒呢",
    "还有这个",
    "还有一个",
    "再看一盒",
    "再看一个",
    "换个药",
    "新药盒",
)


def wants_new_capture(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    if any(hint in normalized for hint in RECAPTURE_HINTS):
        return True
    # 已有照片时：只有明确「再拍/换盒」才重拍，避免「还要拍照吗」误触发
    if any(hint in normalized for hint in ("重新拍", "再拍", "再拍一张", "重新拍照", "换一盒", "换盒拍")):
        return True
    if "呢" in normalized and any(p in normalized for p in ("这个药", "那个药", "这盒", "那盒")):
        return True
    if normalized in {"再看看", "重新看", "再看一下", "再看一盒", "再看一个"}:
        return True
    return False


def classify_photo_session_action(text: str, has_photo: bool) -> str:
    """拍照问药会话内：capture | followup | recapture | doctor（切换问诊）。"""
    normalized = (text or "").strip()
    if not has_photo:
        return "capture"
    if wants_doctor_consult(normalized):
        return "doctor"
    if wants_new_capture(normalized):
        return "recapture"
    return "followup"


VERIFY_WRONG_MARKERS = (
    "不是该吃",
    "不是这个药",
    "不是今天",
    "不是提醒",
    "别吃",
    "不要服",
    "先别吃",
    "不能服",
    "请勿服用",
    "请勿",
    "不对，应该",
)

VERIFY_RIGHT_MARKERS = (
    "是该吃",
    "是这个药",
    "可以服用",
    "请按时",
    "没问题",
    "药品正确",
    "确认无误",
    "是的，是该",
    "对的，是该",
    "是，是该",
    "是正确的",
    "可以按时",
)


def _normalize_medicine_core(name: str) -> str:
    text = (name or "").strip()
    for suffix in ("缓释片", "软胶囊", "胶囊", "颗粒", "注射液", "片"):
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
            break
    return text.strip()


def medicine_name_matches(answer: str, expected_name: str) -> bool:
    expected = (expected_name or "").strip()
    if not expected:
        return False
    normalized = (answer or "").strip()
    if expected in normalized:
        return True
    core = _normalize_medicine_core(expected)
    return len(core) >= 2 and core in normalized


def classify_verify_answer(answer: str, expected_name: str) -> str:
    """Return 'correct', 'wrong', or 'unknown' for medication verify replies."""
    normalized = (answer or "").strip()
    if not normalized:
        return "unknown"

    if any(marker in normalized for marker in VERIFY_WRONG_MARKERS):
        return "wrong"

    if medicine_name_matches(normalized, expected_name):
        return "correct"

    if any(marker in normalized for marker in VERIFY_RIGHT_MARKERS):
        return "correct"

    if normalized.startswith("不是"):
        return "wrong"

    return "unknown"


def build_verify_vision_question(user_question: str, pending: dict) -> str:
    name = pending.get("name") or "该药物"
    dosage = (pending.get("dosage") or "").strip()
    take_time = (pending.get("take_time") or "").strip()
    expected = name if not dosage else f"{name}（{dosage}）"
    time_hint = f"，提醒时间 {take_time}" if take_time else ""
    return (
        f"系统刚提醒患者按时服用「{expected}」{time_hint}。"
        f"患者问：{user_question}\n"
        "请读取<image>药盒包装上的药品名称（通用名或商品名均可）。"
        f"若包装药名与应服「{name}」一致（规格后缀如片/胶囊可省略），"
        "第一句必须答「是，是该吃的药」。"
        "仅当包装药名明显不是该药时，第一句答「不是，包装上是XXX」，并提醒先别吃、核对后再服用。"
        "只回答一句话，不超过30字，不要展开说明。"
    )
