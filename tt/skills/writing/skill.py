"""Seed skill: writing.

Structures bilingual writing context: topic, audience, language rules,
and the house checklist (from the LinkedIn article workflow).
No model calls — pure context structuring.
"""


HOUSE_RULES = [
    "英文版零中文词；中文版可夹英文术语",
    "每篇风格稍有不同，不套模板",
    "署期用初稿日",
    "去 AI 味：不用 stock phrase，不编造细节",
    "保留个人声音",
]


def run(ctx):
    topic = ctx.get("topic")
    if not topic:
        raise ValueError("writing: ctx missing 'topic'")
    language = ctx.get("language", "zh")
    audience = ctx.get("audience", "")

    out = {
        "topic": topic,
        "language": language,
        "audience": audience,
        "checklist": HOUSE_RULES,
        "style_notes": (
            "LinkedIn tech-leadership voice: concrete, first-person, "
            "numbers over adjectives."
            if language == "en" else
            "中文技术领导力口吻：具体、第一人称、数字优先于形容词。"
        ),
    }
    ctx.put("writing", out)
    return out
