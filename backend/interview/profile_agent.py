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
    prompt = f"初対面の参加者と自己紹介のように話し始める、短く自然な発話を{language_name}で1〜2文生成してください。{INTERVIEWER_STANCE}\n{domain_knowledge_context(domain_knowledge)}\nこの初回面談は、その人の仕事の全体像を知り、安心して話せる関係を作るためのものです。まずは差し支えない範囲で、普段どんな仕事をしているかを一つだけ尋ねてください。役職・経験年数などを一度に並べて尋ねず、会話の入口を作ります。発話だけを返してください。"
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
目的は、自己紹介を通してその人の仕事の全体像と人柄を知り、安心して話せる関係を作ること（ラポール形成）です。
会話の中で知りたいのは、役職や立場、今の仕事の経験年数、業務内容の概要、日頃担当している業務や責任の範囲、よく一緒に仕事をする関係者がどんな人たちか、など，仕事内容や1日の業務の流れ，どれくらいその仕事をしているのか，などの基本的なその人の仕事を把握するために必要なプロフィールです．一日の流れは普段の仕事を知るための話題として扱えます。
この一覧は質問の台本ではありません。回答を短く自然に受け止め、その話に沿って、まだ分からない話題を一つだけ尋ねてください。回答から既に分かったことは聞き直さず、順番に項目を埋めるような聞き方や、一度に複数の質問を並べる聞き方は避けます。
その理由や価値観の形成背景を追及せず、具体的な作業手順や判断の根拠も深掘りしません。
話しづらそうな話題は追わず、別の話しやすい話題に移ってください。評価や大げさな称賛はせず、相手の言葉に合わせて関心を示します。
面談はおおむね{CONFIG['min_turns']}往復を目安とし、長くても{CONFIG['max_turns']}往復までです。現在、本人から{state['turn_count']}回の回答を受けています。残りの会話で全項目を無理に聞き切ろうとせず、短い会話で大まかな人物像をつかんでください。この発話では質問を一つ返し、終了の挨拶や次回の約束はしません。
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
            "extracted": empty_extraction(), "guide": {"guidance": "自己紹介のように日々の仕事の全体像や役職，関係者などを聞き、ラポールを形成する。"},
            "profileExtraction": extracted}
