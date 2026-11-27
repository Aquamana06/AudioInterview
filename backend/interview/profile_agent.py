import json
import re

from config import load_config
from llm.client import complete, complete_json, configured
from interview.agent import ENDINGS, INTERVIEWER_STANCE, _history_text, domain_knowledge_context, empty_extraction


CONFIG = load_config("interview")["profile"]
EXPERIENCE_DECLINED = "回答を希望しない"
EXPERIENCE_DECLINED_NOTE = f"初回プロフィール/experience: {EXPERIENCE_DECLINED}"
EXPERIENCE_REFUSAL = re.compile(
    r"回答を希望しない|答えたくない|回答したくない|言いたくない|話したくない|教えたくない|非公開|回答拒否"
    r"|prefer not to|rather not|(?:do not|don't) want to (?:answer|say|share|disclose)"
    r"|möchte.*nicht|keine Angabe", re.I,
)


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
PROFILE_SCHEMA["properties"]["experience"]["description"] = (
    "現在の仕事を何年・何か月続けているか。本人が明示した期間、または経験年数を答えたくないという意思を記録する。"
    "以前の別の仕事の経験や『ベテラン』など期間の分からない表現は含めない。"
)
OPENINGS = {
    "ja": "最初に、普段どんな立場でお仕事をされているのか、差し支えない範囲で教えていただけますか？",
    "en": "To start, could you tell me a little about your usual role at work, as far as you are comfortable sharing?",
    "de": "Erzählen Sie mir zu Beginn bitte, soweit es für Sie in Ordnung ist, etwas über Ihre übliche Rolle bei der Arbeit.",
}
EXPERIENCE_QUESTIONS = {
    "ja": "そのお仕事は、今年で何年目になりますか？ おおよその年数や月数でも構いません。",
    "en": "How many years have you been doing that kind of work? An approximate number of years or months is fine.",
    "de": "Seit wie vielen Jahren machen Sie diese Arbeit? Eine ungefähre Angabe in Jahren oder Monaten reicht aus.",
}


def _has_experience_response(state: dict) -> bool:
    duration = (
        r"(?:\d+(?:[.,]\d+)?|[〇零一二三四五六七八九十百]+)\s*"
        r"(?:年|[かヶヵ箇]?月|years?\b|months?\b|Jahr\w*\b|Monat\w*\b)"
        r"|半年|(?:less than|under) (?:a|one) year"
    )
    return any(note.startswith("初回プロフィール/experience:")
               and (re.search(duration, note, re.I) or EXPERIENCE_REFUSAL.search(note))
               for note in state.get("persona_notes", []))


def meets_completion_criteria(state: dict) -> bool:
    notes = state.get("persona_notes", [])
    groups = {note.split("/", 1)[1].split(":", 1)[0] for note in notes
              if note.startswith("初回プロフィール/") and note.partition(":")[2].strip()}
    # General experience (e.g. "veteran") must not satisfy the required tenure.
    return (state.get("turn_count", 0) >= CONFIG["min_turns"]
            and len(groups) >= CONFIG["min_covered_fields"] and _has_experience_response(state))


async def starter(language: str, *, domain_knowledge: list[dict] | None = None) -> str:
    if not configured():
        return OPENINGS[language]
    language_name = {"ja": "日本語", "en": "English", "de": "Deutsch"}[language]
    prompt = f"初対面の参加者と自己紹介のように話し始める、短く自然な発話を{language_name}で1〜2文生成してください。{INTERVIEWER_STANCE}\n{domain_knowledge_context(domain_knowledge)}\nこの初回面談は、その人の仕事の全体像を知り、安心して話せる関係を作るためのものです。まずは差し支えない範囲で、普段どんな仕事をしているかを一つだけ尋ねてください。冒頭では経験年数を尋ねません。役職・経験年数などを一度に並べて尋ねず、会話の入口を作ります。発話だけを返してください。"
    try:
        return (await complete(prompt)).strip() or OPENINGS[language]
    except Exception:
        return OPENINGS[language]


async def run_profile_turn(state: dict, user_input: str, history: list[dict], language: str, known_profile: dict,
                           *, domain_knowledge: list[dict] | None = None) -> dict:
    if configured():
        prompt = f"""初回の仕事プロフィール抽出器です。直前の発話から明示された内容だけを記録してください。推測しないこと。
experienceには、今の仕事を続けている年数・月数を、数値と単位を含めて記録します（例: 「3年目」「半年」「2 years」）。経験年数について「答えたくない」「言いたくない」などと答えた場合も、その意思をexperienceに記録してください。職位や熟練度、以前の別の仕事の年数は含めません。経験年数への回答拒否だけでは面談全体の終了希望にはせず、wants_to_stopはfalseにします。本人が面談自体の終了も希望している場合だけtrueにします。
保存済みプロフィール: {json.dumps(known_profile, ensure_ascii=False)}
会話履歴: {_history_text(history)}
直前の回答: {user_input}"""
        try:
            extracted = await complete_json(prompt, PROFILE_SCHEMA)
        except Exception:
            extracted = {**{field: [] for field in PROFILE_FIELDS}, "wants_to_stop": False}
    else:
        extracted = {**{field: [] for field in PROFILE_FIELDS}, "wants_to_stop": False}

    state = {**state, "turn_count": state.get("turn_count", 0) + 1, "interview_mode": "profile",
             "persona_notes": list(state.get("persona_notes", []))}
    for key in PROFILE_FIELDS:
        state["persona_notes"].extend(f"初回プロフィール/{key}: {item}" for item in extracted.get(key, []))
    if any(EXPERIENCE_REFUSAL.search(item) for item in extracted.get("experience", [])):
        if EXPERIENCE_DECLINED_NOTE not in state["persona_notes"]:
            state["persona_notes"].append(EXPERIENCE_DECLINED_NOTE)
    wants_to_stop = extracted.get("wants_to_stop", False) or bool(re.search(r"終了|終わり|やめ|\b(?:stop|quit|end|beenden)\b", user_input, re.I))
    state["profile_completed"] = not wants_to_stop and meets_completion_criteria(state)
    should_end = wants_to_stop or state["turn_count"] >= CONFIG["max_turns"] or state["profile_completed"]
    if should_end:
        state["profile_end_reason"] = "participant_stop" if wants_to_stop else "completed" if state["profile_completed"] else "turn_limit"
        return {"text": ENDINGS[language], "state": state, "stateLabel": "end",
                "extracted": {**empty_extraction(), "wants_to_stop": wants_to_stop},
                "guide": {"should_end": True, "profile_completed": state["profile_completed"],
                          "end_reason": state["profile_end_reason"]}, "profileExtraction": extracted}

    language_name = {"ja": "日本語", "en": "English", "de": "Deutsch"}[language]
    prompt = f"""初回インタビューの親しみやすい聞き手として、{language_name}で次の発話を1〜2文作ってください。
{INTERVIEWER_STANCE}
{domain_knowledge_context(domain_knowledge)}
目的は、自己紹介を通してその人の仕事の全体像と人柄を知り、安心して話せる関係を作ること（ラポール形成）です。
会話の中で知りたいのは、役職や立場、今の仕事の経験年数、業務内容の概要、日頃担当している業務や責任の範囲、よく一緒に仕事をする関係者がどんな人たちか、など，仕事内容や1日の業務の流れ，どれくらいその仕事をしているのか，などの基本的なその人の仕事を把握するために必要なプロフィールです．一日の流れは普段の仕事を知るための話題として扱えます。
この一覧は質問の台本ではありません。回答を短く自然に受け止め、その話に沿って、まだ分からない話題を一つだけ尋ねてください。回答から既に分かったことは聞き直さず、順番に項目を埋めるような聞き方や、一度に複数の質問を並べる聞き方は避けます。
その理由や価値観の形成背景を追及せず、具体的な作業手順や判断の根拠も深掘りしません。気をつけていることや大切にしていることは聞かない．
今の仕事を何年・何か月続けているかは必ず一度は確認しますが、冒頭からは尋ねません。最初の2回の回答までは仕事内容や立場の話を自然に続けてください。その後、まだ期間も回答拒否の意思も分からない場合は会話の途中で確認します。experienceに「答えたくない」「回答を希望しない」などの記録があれば確認済みとして扱い、年数や月数を聞き直したり、理由を尋ねたりせず、他の話題に移ってください。
話しづらそうな話題は追わず、別の話しやすい話題に移ってください。評価や大げさな称賛はせず、相手の言葉に合わせて関心を示します。
面談はおおむね{CONFIG['min_turns']}往復を目安とし、長くても{CONFIG['max_turns']}往復までです。現在、本人から{state['turn_count']}回の回答を受けています。残りの会話で全項目を無理に聞き切ろうとせず、短い会話で大まかな人物像をつかんでください。この発話では質問を一つ返し、終了の挨拶や次回の約束はしません。
分かっているプロフィール: {json.dumps(state['persona_notes'], ensure_ascii=False)}
会話履歴: {_history_text(history)}
直前の回答: {user_input}
"""
    if state["turn_count"] >= 2 and not _has_experience_response(state) and not state.get("profile_experience_asked"):
        # Guarantee the required question after the participant has described their work.
        text = EXPERIENCE_QUESTIONS[language]
        state["profile_experience_asked"] = True
    else:
        try:
            text = (await complete(prompt)).strip() if configured() else ""
        except Exception:
            text = ""
    if not text:
        text = OPENINGS[language]
    state["consecutive_questions"] = state.get("consecutive_questions", 0) + 1
    state["turns_since_reflection"] = state.get("turns_since_reflection", 0) + 1
    return {"text": text, "state": state, "stateLabel": "running",
            "extracted": empty_extraction(), "guide": {"guidance": "自己紹介のように日々の仕事の全体像や役職，関係者などを聞き、ラポールを形成する。"},
            "profileExtraction": extracted}
