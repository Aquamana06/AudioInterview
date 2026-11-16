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
        "deep_dive_needs_clarification": {"type": "boolean"},
        "deep_dive_reason_answered": {"type": "boolean"},
        **{key: {"type": "array", "items": {"type": "string"}} for key in ARRAY_FIELDS},
        "wants_to_stop": {"type": "boolean"},
    },
    "required": [
        "target_work", "deep_dive_opportunity", "deep_dive_anchor",
        "deep_dive_needs_clarification", "deep_dive_reason_answered",
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
        "deep_dive": None,
    }


def empty_extraction() -> dict[str, Any]:
    return {"target_work": None, "deep_dive_opportunity": False, "deep_dive_anchor": None,
            "deep_dive_needs_clarification": False, "deep_dive_reason_answered": False,
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
deep_dive_opportunity は、直前の回答に、業務上の選択・優先順位・必要性・重要性・状況に応じた工夫や調整を示す語句や追加情報があり、「なぜそうするのか」「何を手掛かりにそう判断するのか」という、まだ語られていない理由・判断基準・暗黙の前提を尋ねる余地があるときだけ true にしてください。単に詳しく説明できそうな名詞があるだけでは true にしません。理由や判断基準が既に会話で十分説明されている話題も false にします。暗黙知が存在すると断定したり、理由を推測して抽出したりしないでください。
deep_dive_anchor には、その判断や調整を示す直前発話の短い原文を記録します。例えば「他のタスクの方が優先だから」は候補ですが、「他のタスク」という名詞だけに切り縮めないでください。候補がなければ null にします。
deep_dive_needs_clarification は、候補の判断や調整の対象が曖昧で、その理由を自然に尋ねる前に「何を優先したのか」等の確認を一問だけ挟む必要がある場合に true にします。既に対象が分かる場合は false にします。
現在の state.deep_dive がある場合は、新しい話題へ乗り換えず、その anchor について今回の回答で理由・判断基準が明示されたかを deep_dive_reason_answered に記録します。対象の名称や作業内容を説明しただけでは true にしません。この間 deep_dive_opportunity は false にしてください。深掘り中でなければ deep_dive_reason_answered は false にします。
例: 「他のタスクの方が優先だから」は、何を優先したか不明なら opportunity=true、needs_clarification=true。その確認への「故障対応です」という回答は reason_answered=false。「放置するとラインが止まるためです」という回答は reason_answered=true です。
wants_to_stop は明確な終了意思だけ true です。

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


def _deep_dive_guidance(state: dict, info: dict, language: str) -> tuple[str | None, str | None, bool]:
    """Ask at most one clarification and one reason question, then return."""
    active = state.get("deep_dive")
    if active and (active["stage"] == "reason" or info.get("deep_dive_reason_answered")):
        state["deep_dive"] = None
        return None, None, True
    if active:
        stage = "reason"
    elif info.get("deep_dive_opportunity") and info.get("deep_dive_anchor"):
        active = {"anchor": info["deep_dive_anchor"], "return_target_work": state.get("target_work")}
        stage = "clarify" if info.get("deep_dive_needs_clarification") else "reason"
    else:
        return None, None, False
    state["deep_dive"] = {**active, "stage": stage}
    anchor = active["anchor"]
    if stage == "clarify":
        guide = (f"『{anchor}』という判断・調整について、理由を尋ねる前提となる対象を一問だけ確認する。"
                 "例えば『他のタスクの方が優先』なら、何を優先したのかを尋ねる。"
                 "作業内容の詳細を掘り続けず、次のターンでその判断の理由・必要性を尋ねる。")
        fallback = {
            "ja": f"「{anchor}」とのことですが、具体的には何を指していますか？",
            "en": f'When you say “{anchor}”, what specifically are you referring to?',
            "de": f'Was meinen Sie konkret mit „{anchor}“?',
        }[language]
    else:
        guide = (f"『{anchor}』という判断・調整と、直前に確認できた対象について、"
                 "なぜそれを優先する／必要・重要と考える／そのように対応するのか、"
                 "理由または判断の手掛かりを一問だけ尋ねる。既に説明された理由は聞き直さず、"
                 "まだ説明されていない判断の背景に沿って尋ねる。対象の種類や作業手順の具体化だけで終えない。"
                 "理由を決めつけず、責める聞き方にしない。この一問への回答後は元の業務の話へ戻る。")
        fallback = {
            "ja": f"「{anchor}」と判断されたのは、どういった理由からですか？",
            "en": f'What led you to make that decision when you said “{anchor}”?',
            "de": f'Was hat Sie zu der Entscheidung „{anchor}“ bewogen?',
        }[language]
    return guide, fallback, False


async def run_interview_turn(state: dict, user_input: str, history: list[dict], language: str) -> dict:
    info = await extract_turn(user_input, state, history)
    active = state.get("deep_dive")
    next_state = update_state(state, {**info, "target_work": None} if active else info)
    if active:
        # An example about a competing task must not replace the interview's main task.
        next_state["target_work"] = active["return_target_work"]
    interrupted = any(info.get(key) for key in (
        "signs_of_friction", "user_questions", "signs_of_resistance", "signs_of_no_information",
    ))
    if interrupted or info.get("wants_to_stop"):
        next_state["deep_dive"] = None
        dive_guide, dive_fallback, returning = None, None, False
    else:
        dive_guide, dive_fallback, returning = _deep_dive_guidance(next_state, info, language)
    if info.get("wants_to_stop") or (not dive_guide and should_end(next_state)):
        next_state["deep_dive"] = None
        return {"text": ENDINGS[language], "state": next_state, "stateLabel": "end", "extracted": info,
                "guide": {"should_end": True}}

    if info.get("signs_of_friction"):
        guide = "まず短く謝り、分かった内容を正しく言い直す。このターンでは質問しない。"
    elif info.get("user_questions"):
        guide = "相手の質問に短く答え、必要なら答えやすい確認を一つする。"
    elif info.get("signs_of_resistance") or info.get("signs_of_no_information"):
        guide = "無理に深掘りせず、圧を下げて答えやすい形で会話を進める。"
    elif dive_guide:
        guide = dive_guide
    elif next_state["task_coverage"] < CONFIG["ending"]["min_task_coverage"]:
        guide = "業務のきっかけ・条件・資源（知識や経験）・手順・時間制約(優先順位）・結果の観点でを確認する。"
    elif next_state["task_depth"] < CONFIG["ending"]["high_depth"]:
        guide = "具体的な実践や判断を一つ選び、理由や判断基準を一段掘り下げる。"
    elif next_state["irregular_coverage"] < CONFIG["guidance"]["irregular_coverage"]:
        guide = "対象業務で予定どおりに進まない時の状況や対応を一つ尋ねる。"
    else:
        guide = "ここまでの理解を短く返し、必要なら自然に終了へ向かう。"
    if returning:
        guide = (f"今の判断・調整の深掘りはここで終え、元の対象業務『{next_state.get('target_work')}』の話へ自然に戻る。"
                 "回答を短く受け止め、同じ理由を聞き直したり、回答中の別の語をさらに追いかけたりしない。" + guide)

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
    response = response or dive_fallback or fallback_question(next_state, language)
    if "?" in response or "？" in response:
        next_state["consecutive_questions"] += 1
        next_state["turns_since_reflection"] += 1
        next_state["asked_points"].append(f"過去の質問: {response}")
    else:
        next_state["consecutive_questions"] = 0
        next_state["turns_since_reflection"] = 0
        next_state["rapport"] = min(1, next_state["rapport"] + CONFIG["scoring"]["reflection_rapport_increment"])
    return {"text": response, "state": next_state, "stateLabel": "running", "extracted": info, "guide": {"guidance": guide}}
