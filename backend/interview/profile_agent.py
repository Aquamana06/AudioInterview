import json

from config import load_config
from llm.client import complete, complete_json, configured
from interview.agent import ENDINGS, INTERVIEWER_STANCE, _history_text, domain_knowledge_context, empty_extraction


CONFIG = load_config("interview")["profile"]


PROFILE_FIELDS = (
    "role position_or_seniority experience responsibilities typical_day collaborators "
    "workplace_context personally_important_topics other_personal_context signs_of_discomfort"
).split()
PROFILE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        **{field: {"type": "array", "items": {"type": "string"}} for field in PROFILE_FIELDS},
        "wants_to_stop": {"type": "boolean"},
    },
    "required": [*PROFILE_FIELDS, "wants_to_stop"],
}
OPENINGS = {
    "ja": "最初に、普段どんな立場でお仕事をされているのか、差し支えない範囲で教えていただけますか？",
    "en": "To start, could you tell me a little about your usual role at work, as far as you are comfortable sharing?",
    "de": "Erzählen Sie mir zu Beginn bitte, soweit es für Sie in Ordnung ist, etwas über Ihre übliche Rolle bei der Arbeit.",
}


async def starter(language: str, *, domain_knowledge: list[dict] | None = None) -> str:
    if not configured():
        return OPENINGS[language]
    language_name = {"ja": "日本語", "en": "English", "de": "Deutsch"}[language]
    prompt = f"初対面の参加者とのインタビューを始める、短く自然な発話を{language_name}で1〜2文生成してください。{INTERVIEWER_STANCE}\n{domain_knowledge_context(domain_knowledge)}\n安心して話せる雰囲気を作り、差し支えない範囲で現在の担当や立場を一つ尋ねます。発話だけを返してください。"
    try:
        return (await complete(prompt)).strip() or OPENINGS[language]
    except Exception:
        return OPENINGS[language]


async def run_profile_turn(state: dict, user_input: str, history: list[dict], language: str, known_profile: dict,
                           *, domain_knowledge: list[dict] | None = None) -> dict:
    if configured():
        prompt = f"""初回の仕事プロフィール抽出器です。直前の発話から明示された内容だけを記録してください。推測しないこと。
保存済みプロフィール: {json.dumps(known_profile, ensure_ascii=False)}
会話履歴: {_history_text(history)}
直前の回答: {user_input}"""
        try:
            extracted = await complete_json(prompt, PROFILE_SCHEMA)
        except Exception:
            extracted = {**{field: [] for field in PROFILE_FIELDS}, "wants_to_stop": False}
    else:
        extracted = {**{field: [] for field in PROFILE_FIELDS}, "wants_to_stop": False}

    state = {**state, "turn_count": state.get("turn_count", 0) + 1}
    for key in PROFILE_FIELDS:
        state["persona_notes"].extend(f"初回プロフィール/{key}: {item}" for item in extracted.get(key, []))
    groups = {note.split("/", 1)[1].split(":", 1)[0] for note in state["persona_notes"] if note.startswith("初回プロフィール/")}
    wants_to_stop = extracted.get("wants_to_stop", False) or any(word in user_input.lower() for word in ("終了", "終わり", "やめ", "stop", "quit", "end", "beenden"))
    should_end = wants_to_stop or state["turn_count"] >= CONFIG["max_turns"] or (state["turn_count"] >= CONFIG["min_turns"] and len(groups) >= CONFIG["min_covered_fields"])
    if should_end:
        return {"text": ENDINGS[language], "state": state, "stateLabel": "end",
                "extracted": {**empty_extraction(), "wants_to_stop": wants_to_stop},
                "guide": {"should_end": True}, "profileExtraction": extracted}

    language_name = {"ja": "日本語", "en": "English", "de": "Deutsch"}[language]
    prompt = f"""初回インタビューの親しみやすい聞き手として、{language_name}で次の発話を1〜2文作ってください。
{INTERVIEWER_STANCE}
{domain_knowledge_context(domain_knowledge)}
回答を短く受け止め、まだ十分に分からない基本情報を一つだけ自然に尋ねます。質問票のように列挙せず、差し支えない範囲で話せるようにします。深い理由や価値観の追及はせず、既に聞いたことは尋ね直しません。
分かっているプロフィール: {json.dumps(state['persona_notes'], ensure_ascii=False)}
会話履歴: {_history_text(history)}
直前の回答: {user_input}
"""
    try:
        text = (await complete(prompt)).strip() if configured() else ""
    except Exception:
        text = ""
    if not text:
        text = "普段は、どのくらいの期間そのお仕事をされているんですか？" if language == "ja" else OPENINGS[language]
    state["consecutive_questions"] = state.get("consecutive_questions", 0) + 1
    state["turns_since_reflection"] = state.get("turns_since_reflection", 0) + 1
    return {"text": text, "state": state, "stateLabel": "running",
            "extracted": empty_extraction(), "guide": {"guidance": "初回のプロフィール形成を雑談的に進める。"},
            "profileExtraction": extracted}
