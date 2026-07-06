import re

LISTEN_PROMPT_ECHOES = (
    "请说出您的问题",
    "拍照完成请说出您的问题",
    "拍照完成，请说出您的问题",
    "拍好了请说出您想问的问题",
    "拍好了，请说出您想问的问题",
    "请对准药盒",
    "请对准药盒我来拍照识别",
    "请说",
)

# 会出现在 speak_first 提示语里的短指令，不能因「是提示语子串」就被当成回声丢弃。
LISTEN_COMMAND_WORDS = frozenset(
    {
        "换一个",
        "换一盒",
        "换盒",
        "这个药呢",
        "那个药呢",
        "这盒呢",
        "那盒呢",
        "切换问诊",
        "去问医",
        "退出",
        "结束",
        "不问了",
        "再见",
        "没有了",
        "不用了",
        "停止",
        "算了",
    }
)

FOLLOWUP_LISTEN_HINT = "您还可以继续问这个药。换一盒请说换一个，说退出可以结束"


def normalize_listen_text(text: str) -> str:
    return re.sub(r"[\s，,。．.！!？?；;：:、]", "", (text or "").strip())


def is_listen_prompt_echo(text: str, speak_first: str = "") -> bool:
    heard = normalize_listen_text(text)
    if not heard:
        return True

    if heard in LISTEN_COMMAND_WORDS:
        return False

    for cand in LISTEN_PROMPT_ECHOES:
        prompt = normalize_listen_text(cand)
        if not prompt:
            continue
        if heard == prompt:
            return True
        if len(heard) >= 8 and prompt in heard:
            return True
        if len(heard) >= 8 and len(heard) <= len(prompt) + 2 and heard in prompt:
            return True

    prompt = normalize_listen_text(speak_first)
    if not prompt:
        return False
    if heard == prompt:
        return True
    # 只有复述了较长一段提示语时才视为 TTS 回声
    min_echo_len = max(10, len(prompt) * 2 // 3)
    if len(heard) >= min_echo_len and heard in prompt:
        return True
    if len(heard) >= min_echo_len and prompt in heard:
        return True
    return False
