import json
import re
from typing import Any

from config import load_config
from llm.client import complete, complete_json, configured


CONFIG = load_config("interview")


ENDINGS = {
    "ja": "ありがとうございました。これでインタビューを終了します。",
    "en": "Thank you very much. This concludes the interview.",
    "de": "Vielen Dank. Damit beenden wir das Interview.",
}

ARRAY_FIELDS = (
    "fram_input fram_precondition fram_resource fram_control fram_time fram_output "
    "situations practices reasons values sources personal_meanings irregular_situations "
    "irregular_responses persona_notes emotions user_questions signs_of_friction "
    "signs_of_resistance signs_of_no_information"
).split()
EXTRACT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "target_work": {"type": ["string", "null"]},
        "deep_dive_opportunity": {"type": "boolean"},
        "deep_dive_anchor": {"type": ["string", "null"]},
        **{key: {"type": "array", "items": {"type": "string"}} for key in ARRAY_FIELDS},
        "wants_to_stop": {"type": "boolean"},
    },
    "required": [
        "target_work", "deep_dive_opportunity", "deep_dive_anchor",
        *ARRAY_FIELDS, "wants_to_stop",
    ],
}
FRAM_FIELDS = {
    "input": "fram_input", "precondition": "fram_precondition", "resource": "fram_resource",
    "control": "fram_control", "time": "fram_time", "output": "fram_output",
}


def initial_state() -> dict[str, Any]:
    return {
        "target_work": None, "task_coverage": 0,
        "task_coverage_by_fram": {key: 0 for key in FRAM_FIELDS},
        "practice_covered": False, "task_depth": 0, "high_depth_turn_count": 0,
        "irregular_coverage": 0, "rapport": 0, "known_facts": [], "asked_points": [],
        "persona_notes": [], "consecutive_questions": 0, "turns_since_reflection": 0,
        "friction_count": 0, "resistance_count": 0, "turn_count": 0,
    }


def empty_extraction() -> dict[str, Any]:
    return {"target_work": None, "deep_dive_opportunity": False, "deep_dive_anchor": None,
            **{key: [] for key in ARRAY_FIELDS}, "wants_to_stop": False}


def _history_text(history: list[dict]) -> str:
    # Injected memory/guidance must survive truncation of the conversation.
    context = [item for item in history if item.get("context")]
    conversation = [item for item in history if not item.get("context")]
    selected = context + conversation[-CONFIG["history"]["messages"]:]
    return "\n".join(f"{item['role']}: {item['content']}" for item in selected)


def _fallback_extraction(text: str) -> dict[str, Any]:
    info = empty_extraction()
    if len(text) > 4:
        info["target_work"] = text[:80]
    if len(text) > 8:
        info["practices"] = [text[:160]]
    if re.search(r"特になし|わからない|分からない|nothing|none|weiß nicht", text, re.I):
        info["signs_of_no_information"] = [text]
    info["wants_to_stop"] = bool(re.search(r"終了|終わり|やめ|stop|quit|end|beenden", text, re.I))
    return info


async def extract_turn(user_input: str, state: dict, history: list[dict]) -> dict[str, Any]:
    if not configured():
        return _fallback_extraction(user_input)
    prompt = f"""あなたは半構造化インタビューの情報抽出器です。直前のインタビュイ発話だけから、明示された情報を抽出してください。想像で補わず、同じ事実を複数項目に重複させず、相槌は情報なしとします。
FRAMは input=作業のきっかけ/処理対象、precondition=実行前の条件、resource=資源、control=手順書/監督/計画、time=時間/制約、output=結果です。reasons は実践に明示的に結びつく理由だけ、values は業務上の判断基準、sources は考え方の形成源、personal_meanings は個人的経験と仕事観のつながりだけを記録してください。
deep_dive_opportunity は直前の回答に関してxxのときだけ true にし、その根拠を短く deep_dive_anchor に記録します。wants_to_stop は明確な終了意思だけ true です。

現在の state: {json.dumps(state, ensure_ascii=False)}
対話履歴: {_history_text(history)}
直前のインタビュイ発話: {user_input}
"""
    try:
        result = await complete_json(prompt, EXTRACT_SCHEMA)
        return {**empty_extraction(), **result}
    except Exception:
        return _fallback_extraction(user_input)


def _add_facts(state: dict, prefix: str, values: list[str]) -> None:
    state["known_facts"].extend(f"{prefix}{value}" for value in values)


def update_state(state: dict, info: dict) -> dict:
    state["turn_count"] += 1
    state.setdefault("task_coverage_by_fram", {key: 0 for key in FRAM_FIELDS})
    for key in FRAM_FIELDS:
        state["task_coverage_by_fram"].setdefault(key, 0)
        values = info.get(FRAM_FIELDS[key], [])
        if values:
            state["task_coverage_by_fram"][key] = min(CONFIG["scoring"]["fram_cap"], state["task_coverage_by_fram"][key] + CONFIG["scoring"]["fram_increment"])
            _add_facts(state, f"FRAM {key}: ", values)
    covered = sum(value > 0 for value in state["task_coverage_by_fram"].values())
    coverage = sum(state["task_coverage_by_fram"].values())
    coverage += max((bonus for count, bonus in CONFIG["scoring"]["fram_bonuses"].items() if covered >= count), default=0)
    state["task_coverage"] = min(1, round(coverage, 2))
    if info.get("target_work"):
        state["target_work"] = info["target_work"]
        _add_facts(state, "対象業務: ", [info["target_work"]])
    if info.get("practices"):
        state["practice_covered"] = True
    for field, prefix in (
        ("situations", "状況: "), ("practices", "業務上の実践: "), ("reasons", "理由: "),
        ("sources", "源泉: "), ("values", "価値観: "),
        ("personal_meanings", "個人的意味・価値観の形成背景・真髄: "),
        ("irregular_situations", "イレギュラーな状況: "), ("irregular_responses", "イレギュラー時の対応: "),
        ("emotions", "感情・状態: "), ("user_questions", "相手からの確認: "),
    ):
        _add_facts(state, prefix, info.get(field, []))
    state["persona_notes"].extend(info.get("persona_notes", []))
    if info.get("irregular_situations"):
        state["irregular_coverage"] = min(1, state["irregular_coverage"] + CONFIG["scoring"]["irregular_situation_increment"])
    if info.get("irregular_responses"):
        state["irregular_coverage"] = min(1, state["irregular_coverage"] + CONFIG["scoring"]["irregular_response_increment"])
    if info.get("signs_of_friction"):
        state["friction_count"] += 1
        state["rapport"] = max(0, state["rapport"] - CONFIG["scoring"]["friction_penalty"])
        state["asked_points"].extend(info["signs_of_friction"])
    if info.get("signs_of_resistance"):
        state["resistance_count"] += 1
        state["rapport"] = max(0, state["rapport"] - CONFIG["scoring"]["resistance_penalty"])
        state["asked_points"].extend(info["signs_of_resistance"])
    state["asked_points"].extend(info.get("signs_of_no_information", []))
    state["rapport"] = min(1, state["rapport"] + (CONFIG["scoring"]["information_rapport_increment"] if any(info.get(k) for k in ARRAY_FIELDS) else 0))
    facts = state["known_facts"]
    depth = 0 if not state["target_work"] else 1
    for prefix, depth_level in (
        ("業務上の実践:", 2), ("理由:", 3), ("源泉:", 4), ("価値観:", 5),
        ("個人的意味・価値観の形成背景・真髄:", 6),
    ):
        if any(item.startswith(prefix) for item in facts):
            depth = depth_level
    state["task_depth"] = max(state.get("task_depth", 0), depth)
    if state["task_depth"] >= CONFIG["ending"]["high_depth"]:
        state["high_depth_turn_count"] += 1
    state["known_facts"] = list(dict.fromkeys(state["known_facts"]))[-CONFIG["history"]["known_facts"]:]
    state["asked_points"] = state["asked_points"][-CONFIG["history"]["asked_points"]:]
    state["persona_notes"] = state["persona_notes"][-CONFIG["history"]["persona_notes"]:]
    return state


def should_end(state: dict) -> bool:
    return bool(state["target_work"] and state["practice_covered"] and state["task_coverage"] >= CONFIG["ending"]["min_task_coverage"] and (
        state["high_depth_turn_count"] >= CONFIG["ending"]["high_depth_turns"] or
        (state["task_coverage"] >= CONFIG["ending"]["complete_task_coverage"] and state["task_depth"] >= CONFIG["ending"]["complete_depth"] and state["irregular_coverage"] >= CONFIG["ending"]["complete_irregular_coverage"])
    ))


def fallback_question(state: dict, language: str) -> str:
    if language == "en":
        if not state["target_work"]: return "What kind of work were you doing earlier?"
        if state["task_coverage"] < CONFIG["guidance"]["fallback_task_coverage"]: return f"What is the usual flow for {state['target_work']}?"
        if state["task_depth"] < CONFIG["ending"]["high_depth"]: return f"What matters most to you when doing {state['target_work']}?"
        return f"What do you do when something unexpected happens during {state['target_work']}?"
    if language == "de":
        if not state["target_work"]: return "Welche Arbeit haben Sie vorhin gemacht?"
        if state["task_coverage"] < CONFIG["guidance"]["fallback_task_coverage"]: return f"Wie läuft {state['target_work']} normalerweise ab?"
        if state["task_depth"] < CONFIG["ending"]["high_depth"]: return f"Was ist Ihnen bei {state['target_work']} besonders wichtig?"
        return f"Was tun Sie, wenn bei {state['target_work']} etwas Unerwartetes passiert?"
    if not state["target_work"]: return "先ほどの業務について、その時の状況も含めてもう少し聞かせてください。"
    if state["task_coverage"] < CONFIG["guidance"]["fallback_task_coverage"]: return f"{state['target_work']} の場面では、普段どんな流れで進めていますか？"
    if state["task_depth"] < CONFIG["ending"]["high_depth"]: return f"その {state['target_work']} で大事にしている判断や考え方はありますか？"
    return f"{state['target_work']} で想定外のことが起きた時は、どのように対応しますか？"


async def run_interview_turn(state: dict, user_input: str, history: list[dict], language: str) -> dict:
    info = await extract_turn(user_input, state, history)
    next_state = update_state(state, info)
    if info.get("wants_to_stop") or should_end(next_state):
        return {"text": ENDINGS[language], "state": next_state, "stateLabel": "end", "extracted": info,
                "guide": {"should_end": True}}

    if info.get("signs_of_friction"):
        guide = "まず短く謝り、分かった内容を正しく言い直す。このターンでは質問しない。"
    elif info.get("user_questions"):
        guide = "相手の質問に短く答え、必要なら答えやすい確認を一つする。"
    elif info.get("signs_of_resistance") or info.get("signs_of_no_information"):
        guide = "無理に深掘りせず、圧を下げて答えやすい形で会話を進める。"
    elif info.get("deep_dive_opportunity") and info.get("deep_dive_anchor"):
        guide = f"直前の具体的な話『{info['deep_dive_anchor']}』に続く一問をする。"
    elif next_state["task_coverage"] < CONFIG["ending"]["min_task_coverage"]:
        guide = "業務のきっかけ・条件・資源（知識や経験）・手順・時間制約(優先順位）・結果の観点でを確認する。"
    elif next_state["task_depth"] < CONFIG["ending"]["high_depth"]:
        guide = "具体的な実践や判断を一つ選び、理由や判断基準を一段掘り下げる。"
    elif next_state["irregular_coverage"] < CONFIG["guidance"]["irregular_coverage"]:
        guide = "対象業務で予定どおりに進まない時の状況や対応を一つ尋ねる。"
    else:
        guide = "ここまでの理解を短く返し、必要なら自然に終了へ向かう。"

    language_name = {"ja": "日本語", "en": "English", "de": "Deutsch"}[language]
    prompt = f"""あなたは半構造化インタビューを行う自然な聞き手です。{language_name}で次の発話だけを作ってください。
短い1〜2文にし、質問は一度に一つ。監査や尋問のようにせず、相手の実際の仕事と判断を理解してください。
今の方針: {guide}
対象業務: {next_state.get('target_work')}
これまでに分かったこと: {json.dumps(next_state['known_facts'][-CONFIG['history']['prompt_facts']:], ensure_ascii=False)}
既出の質問: {json.dumps(next_state['asked_points'][-CONFIG['history']['prompt_questions']:], ensure_ascii=False)}
会話履歴: {_history_text(history)}
直前の回答: {user_input}
"""
    try:
        response = (await complete(prompt)).strip() if configured() else ""
    except Exception:
        response = ""
    response = response or fallback_question(next_state, language)
    if "?" in response or "？" in response:
        next_state["consecutive_questions"] += 1
        next_state["turns_since_reflection"] += 1
        next_state["asked_points"].append(f"過去の質問: {response}")
    else:
        next_state["consecutive_questions"] = 0
        next_state["turns_since_reflection"] = 0
        next_state["rapport"] = min(1, next_state["rapport"] + CONFIG["scoring"]["reflection_rapport_increment"])
    return {"text": response, "state": next_state, "stateLabel": "running", "extracted": info, "guide": {"guidance": guide}}
