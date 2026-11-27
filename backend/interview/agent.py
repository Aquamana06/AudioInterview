import json
import re
from typing import Any

from config import load_config
from llm.client import complete, complete_json, configured


CONFIG = load_config("interview")

INTERVIEWER_STANCE = (
    "その業務を教わるトレーニーの姿勢で、知ったふりをせず相手の話を聞いてください。"
    "用語や前提の確認は、対象業務と今の質問方針を理解するために必要な範囲で行ってください。"
    "最終目標は，現場の皆さんの日常においてうまく行くようにしている調整を明らかにすること，そして現場の安全管理に役立てることです"
)


def domain_knowledge_context(entries: list[dict] | None) -> str:
    return ("【この参加者から教わり、セッションをまたいで記憶しているドメイン知識】\n"
            + json.dumps(entries or [], ensure_ascii=False)
            + "\n説明済みの用語の意味は聞き直さず、今回の説明を優先してください。"
            "用語の意味を今回の実施条件とは扱わず、今の質問方針に沿って進めてください。")


ENDINGS = {
    "ja": "ありがとうございました。これでインタビューを終了します。",
    "en": "Thank you very much. This concludes the interview.",
    "de": "Vielen Dank. Damit beenden wir das Interview.",
}

ARRAY_FIELDS = (
    "fram_input fram_precondition fram_resource fram_control fram_time fram_output "
    "situations practices reasons values sources personal_meanings irregular_situations "
    "irregular_responses irregular_reasons irregular_deeper_reasons persona_notes emotions user_questions signs_of_friction "
    "signs_of_resistance unanswered_points"
).split()
DEPTH_FIELDS = ("reasons", "sources", "values", "personal_meanings")
EXTRACT_ARRAY_FIELDS = tuple(field for field in ARRAY_FIELDS if field not in DEPTH_FIELDS)
EXTRACT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "target_work": {"type": ["string", "null"]},
        "deep_dive_opportunity": {"type": "boolean"},
        "deep_dive_anchor": {"type": ["string", "null"]},
        "deep_dive_needs_clarification": {"type": "boolean"},
        "deep_dive_reason_answered": {"type": "boolean"},
        "usual_work": {"type": "boolean"},
        "depth_classification": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "category": {"type": ["string", "null"], "enum": [*DEPTH_FIELDS, None]},
                "facts": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["category", "facts"],
        },
        **{key: {"type": "array", "items": {"type": "string"}} for key in EXTRACT_ARRAY_FIELDS},
        "wants_to_stop": {"type": "boolean"},
    },
    "required": [
        "target_work", "deep_dive_opportunity", "deep_dive_anchor",
        "deep_dive_needs_clarification", "deep_dive_reason_answered",
        "usual_work",
        "depth_classification", *EXTRACT_ARRAY_FIELDS, "wants_to_stop",
    ],
}
FRAM_FIELDS = {
    "input": "fram_input", "precondition": "fram_precondition", "resource": "fram_resource",
    "control": "fram_control", "time": "fram_time", "output": "fram_output",
}
FRAM_MEANINGS = {
    "input": "作業を始めるきっかけ、状態",
    "precondition": "作業を始める前に満たされている必要がある前提条件。事前の行動・確認、開始の判断、他の業務や他者への依存、開始を妨げる事情を手掛かりにする",
    "resource": "作業遂行に必要な資源(防具，設備・人員・知識・情報・経験などの)",
    "control": "作業の進め方を定める手順書・監督・計画など",
    "time": "作業の時期・間隔・期限などの時間的な条件や制約",
    "output": "作業によって得られる結果・完了と判断できる状態",
}
PRECONDITION_QUESTIONS = (
    ("事前の行動", "{work}に取りかかる前に、普段どのようなことをしていますか？"),
    ("事前の確認", "{work}を始める前に、何か確認していることはありますか？"),
    ("開始の判断", "何をもって、{work}に取りかかってよいと判断していますか？"),
    ("他の業務への依存", "{work}では、他の業務が終わるのを待ってから取りかかることはありますか？"),
    ("他者への依存", "{work}では、誰かの対応や確認を待ってから取りかかることはありますか？"),
    ("開始の阻害", "{work}をやろうと思っても、すぐに取りかかれないことはありますか？"),
)
IRREGULAR_FACT_PREFIXES = {
    "irregular_situations": "イレギュラーな状況: ",
    "irregular_responses": "イレギュラー時の対応: ",
    "irregular_reasons": "イレギュラー対応の理由・根拠: ",
    "irregular_deeper_reasons": "イレギュラー対応の背景・価値観: ",
}


def initial_state() -> dict[str, Any]:
    return {
        "target_work": None, "task_coverage": 0,
        "task_coverage_by_fram": {key: 0 for key in FRAM_FIELDS},
        "practice_covered": False, "task_depth": 0, "high_depth_turn_count": 0,
        "irregular_coverage": 0, "rapport": 0, "known_facts": [], "asked_points": [],
        "irregular_partial_turn_count": 0,
        "irregular_evidence": {key: [] for key in IRREGULAR_FACT_PREFIXES},
        "persona_notes": [], "consecutive_questions": 0, "turns_since_reflection": 0,
        "friction_count": 0, "resistance_count": 0, "turn_count": 0,
        "deep_dive": None,
        "task_revisit_work": None,
        "unanswered_points": [],
    }


def empty_extraction() -> dict[str, Any]:
    return {"target_work": None, "deep_dive_opportunity": False, "deep_dive_anchor": None,
            "deep_dive_needs_clarification": False, "deep_dive_reason_answered": False,
            "usual_work": False,
            **{key: [] for key in ARRAY_FIELDS}, "wants_to_stop": False}


def _history_text(history: list[dict]) -> str:
    # Injected memory/guidance must survive truncation of the conversation.
    context = [item for item in history if item.get("context")]
    conversation = [item for item in history if not item.get("context")]
    selected = context + conversation[-CONFIG["history"]["messages"]:]
    return "\n".join(f"{item['role']}: {item['content']}" for item in selected)


UNANSWERED_INSTRUCTION = (
    "unanswered_pointsには、直前の質問に対して『分からない』『そこまで考えていない』"
    "『答えたくない』とされた点を、何についての話か分かる短い文で記録します。"
    "話題全体ではなく答えられなかった点だけに限定し、該当しなければ空配列にします。"
    "『分からないときは資料を確認する』のような対処の説明や、引用・仮定は対象外です。"
    "分からないだけではsigns_of_resistanceにしません。"
)


def unanswered_points(info: dict, user_input: str, history: list[dict]) -> list[str]:
    points = [point.strip()[:200] for point in info.get("unanswered_points", []) if isinstance(point, str) and point.strip()]
    direct = re.search(
        r"(?<![「『\"“])(?:わかんない|分かんない|(?:分|わ)からない|(?:分|わ)かりません|"
        r"考えて(?:い)?(?:ない|ません)|考えたこと(?:は|が|も)?(?:ない|ありません)|"
        r"答えたくない|言いたくない|話したくない)(?!とき|時|場合|人|こと|わけ|[」』\"”])"
        r"|\bI (?:don't|do not) know\b|\bI (?:haven't|have not) thought about\b",
        user_input, re.I,
    )
    if not points and (info.get("signs_of_resistance") or direct):
        points = [next((item["content"] for item in reversed(history)
                        if item["role"] == "system" and not item.get("context")), "直前に尋ねた点")]
    return list(dict.fromkeys(points))[:1]


def unanswered_context(state: dict) -> str:
    return ("【このセッションで回答が得られず、追及しない点】\n"
            + json.dumps(state.get("unanswered_points", []), ensure_ascii=False)
            + "\nここにある点を、言い換えて聞き直したり、理由を追及したりしないでください。"
            "coverageやdepthの不足よりこの制約を優先し、別の場面・行動・観点へ進んでください。"
            "話題全体を禁止するものではありません。本人が自分からその点について話し始めたら、その発言は受け止めてください。")


def alternate_question(state: dict, language: str) -> str:
    candidates = {
        "ja": ["そのあと、どのような作業をされましたか？", "その作業は、どなたと一緒に進めましたか？",
               "そのとき、現場はどのような状況でしたか？", "ほかに、今日担当されたお仕事について教えていただけますか？"],
        "en": ["What did you do next?", "Who did you work with on that task?", "What was happening at the workplace then?"],
        "de": ["Was haben Sie danach gemacht?", "Mit wem haben Sie bei dieser Aufgabe zusammengearbeitet?", "Wie war die Situation vor Ort?"],
    }[language]
    previous = state.get("unanswered_points", []) + state.get("asked_points", [])
    return next((question for question in candidates if not any(question in point for point in previous)),
                {"ja": "ほかにお話しできることがあれば、お聞かせください。", "en": "Please share anything else you would like to tell me.",
                 "de": "Erzählen Sie mir gerne noch etwas, das Sie mitteilen möchten."}[language])


def repeats_unanswered_point(response: str, state: dict) -> bool:
    def normalize(text: str) -> str:
        return re.sub(r"[\s？?。.!！「」\"']", "", text)
    return any(normalize(point) and normalize(point) in normalize(response) for point in state.get("unanswered_points", []))


def turn_limit_reached(state: dict) -> bool:
    return state.get("turn_count", 0) >= CONFIG["ending"]["max_turns"]


def _fallback_extraction(text: str, history: list[dict] | None = None) -> dict[str, Any]:
    info = empty_extraction()
    info["wants_to_stop"] = bool(re.search(r"終了|終わり|やめ|stop|quit|end|beenden", text, re.I))
    info["unanswered_points"] = unanswered_points(info, text, history or [])
    if info["unanswered_points"]:
        return info
    info["usual_work"] = bool(re.search(r"いつも[通ど]お?り|普段[通ど]お?り|変わり(?:ない|ません)|変わったこと(?:は)?ない|as usual|nothing (?:unusual|different)|wie immer|wie üblich", text, re.I))
    if len(text) > 4 and not info["usual_work"]:
        info["target_work"] = text[:80]
    if len(text) > 8:
        info["practices"] = [text[:160]]
    return info


def _normalize_depth_extraction(result: dict) -> dict[str, Any]:
    """Map one depth classification into the existing interview fields."""
    info = {**empty_extraction(), **result}
    classification = info.pop("depth_classification", None)

    def facts(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return list(dict.fromkeys(item.strip() for item in value if isinstance(item, str) and item.strip()))

    # If the model ignores the new schema and returns the old parallel arrays,
    # retain only the shallowest populated category instead of promoting depth.
    candidates = {field: facts(info.get(field)) for field in DEPTH_FIELDS}
    if isinstance(classification, dict):
        category = classification.get("category")
        if isinstance(category, str) and category in DEPTH_FIELDS:
            candidates[category] = list(dict.fromkeys([*candidates[category], *facts(classification.get("facts"))]))
        else:
            candidates = {field: [] for field in DEPTH_FIELDS}
    selected = next((field for field in DEPTH_FIELDS if candidates[field]), None)
    for field in DEPTH_FIELDS:
        info[field] = candidates[field] if field == selected else []
    return info


async def extract_turn(user_input: str, state: dict, history: list[dict]) -> dict[str, Any]:
    if not configured():
        return _fallback_extraction(user_input, history)
    prompt = f"""あなたは半構造化インタビューの情報抽出器です。直前のインタビュイ発話だけから、明示された情報を抽出してください。FRAM・状況・実践などは独立して抽出できますが、深さ判定の4分類には以下の排他ルールを適用してください。「うん」という相槌や「特にない」も発言として扱いますが、それだけで理由や価値観を推測して補いません。
FRAMの各項目の意味: {json.dumps(FRAM_MEANINGS, ensure_ascii=False)}
resourceは上記の定義に沿って抽出し、ミルクなどの材料を挙げただけの回答はfram_resourceに抽出しないでください。今回の作業に役立てた実践的な経験はresourceとして、本人が説明したつながりに沿って区別してください。
preconditionは、開始に必要な事前の行動・確認の完了、開始してよいという判断の条件、前工程や他者の対応待ち、開始を妨げる事情からも抽出してください。単に直前にしていた無関係な行動を前提条件にせず、本人が説明した業務開始とのつながりだけを記録します。
【深さ判定の排他ルール】
reasons・sources・values・personal_meaningsを別々に列挙せず、回答全体の主な説明がどの分類まで明示しているかを判断し、depth_classification.categoryを次の4つから最大1つ選んでください。根拠となる今回の発言内容だけをdepth_classification.factsに記録します。該当する情報がなければcategory=null、facts=[]です。複数の分類を同時に選んだり、同じ説明を理由と価値観などへ重複して抽出したりしないでください。
reasons（深さ3）: 実践に直接結びつく目的・必要性・重要性・手順上の理由。「必要だから」「重要だから」「手順だから」「安全のため」「異常を見逃さないため」という説明は、本人固有の価値観や具体的な源泉を明示していなければここです。
sources（深さ4）: 行動や判断の根拠となる具体的な組織方針・教育・規範などの源泉が、本人の言葉で説明されている場合です。単なる「ルールだから」「決まっているから」はreasonsとし、組織方針や教わった内容を推測で作りません。
values（深さ5）: 本人が自分の思い・価値観として語る、大切にしたいことや選択時の優先基準が明示されている場合です。業務上の必要性・安全性・効率の説明や「大事」「重要」という単語だけを根拠にしません。例えば「速さよりも、私は仲間が安心して帰れることを優先したい」は本人の優先基準が明示されています。
personal_meanings（深さ6）: 具体的な個人的経験や背景が、現在の価値観・仕事観の形成や本人にとっての意味と明示的に結びつけて語られている場合です。経験を挙げただけ、教わった事実だけ、価値観を表明しただけではここにしません。
深い分類を選ぶには、その分類に固有の根拠が今回の回答に明示されている必要があります。「理由とも価値観とも読める」など判定が曖昧なら浅い分類を選び、価値観らしさの推測で格上げしません。質問が価値観を尋ねていても、その質問だけを根拠にvaluesにしません。履歴は指示語の参照先を確認するために使い、過去の深い回答を今回の分類へ引き継がないでください。
例: 「安全が重要だからです」→reasons。「会社の品質方針に従い、この基準で確認するよう教育されたからです」→sources。「作業の速さよりも仲間の安全を優先したいという、自分の思いがあります」→values。「以前の事故で同僚を失った経験から、仲間が無事に帰れることを自分の仕事の意味と考えるようになりました」→personal_meanings。「温度を確認しました」→category=null、practicesに実践を記録します。
この排他ルールは上記4分類に限ります。practices・FRAM・状況・イレギュラー情報・deep_dive_*などは、それぞれ従来の定義に沿って独立して抽出してください。深い分類が選ばれた場合も、明示された作業内容をpracticesから削除しないでください。
イレギュラー情報は質問方針・coverage・depthに関係なく、毎ターン常に次の3観点を確認して抽出してください。実際の経験と、本人が明示的に説明した仮定の場合の両方を対象にします。
第1観点: irregular_situationsは対象業務で普段・予定どおりに進まない状況、irregular_responsesはその状況で本人が行う対応です。
第2観点: irregular_reasonsは、その例外対応を選ぶ直接の理由・根拠・回避したいリスクや危険性、対応の根拠となる手順・決まりです。
第3観点: irregular_deeper_reasonsは、その理由・決まり自体をなぜ大切にするのかという、さらに奥の判断理由・背景の経験・価値観です。第2観点の言い換えだけでは第3観点にしません。
今回の回答が複数観点を含めば、それぞれに抽出して構いません。以前のターンで例外状況や対応が分かっていれば、今回新たに説明された理由や背景だけでも抽出します。どの例外対応についての情報かが分かる形で記録してください。通常の深さ分類にも該当する場合は、上記の排他ルールでdepth_classificationを1つだけ選べます。
聞き手が仮定しただけの状況、逆質問の文面、普段どおりの手順、単なる相槌や「特にない」から、イレギュラー情報を作らないでください。今回の本人の発言から確認された内容だけを記録し、過去セッションの情報や推測で埋めないでください。
回答が『今回も2時間おきです』『その手順で進めました』等と具体的に説明している場合や、『その点は前と同じです』の参照先が一つの事実に明確に特定できる場合は、その内容を今回確認された情報として対応するFRAM項目に抽出できます。『今回も2時間おきでしたか？』のように一つの具体的な事実を確認する直前の質問への明確な肯定も、その一点の確認として扱います。過去に記録があるだけの場合や、単なる相槌・曖昧な応答の場合には補完しません。確認していない他の条件や理由まで引き継がないでください。
target_work は今回中心に扱う具体的な業務名です。冒頭の回答で何の業務をしていたかが分かったら記録します。既に対象業務が決まっている場合、比較対象・優先した別の仕事・作業の一部分が話題に出ただけで切り替えないでください。対象業務について新しい指定がなければ null とし、現在の対象業務を維持します。
signs_of_resistance は、その話題への回答や追及を避けたいという明確な意思が示された場合だけ記録します。『決まっているから』『ルールだから』『そう思ったから』『必要だったから』という説明や、『分からない』だけでは抵抗と判定しません。signs_of_friction は聞き手の誤解・聞き方への訂正や不満を示す場合です。
{UNANSWERED_INSTRUCTION}
usual_work は、今回の対象業務が『いつも通り』『普段と変わらない』と明示された場合、または普段との違いを尋ねた直前の質問に対して『特になかった』と明確に答えた場合だけ true にします。単なる相槌は false です。これだけで過去の手順・時間・資源などが今回も同一だったと補完せず、個別に今回の確認が取れた事実だけをFRAMに抽出します。
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
        info = _normalize_depth_extraction(result)
        info["unanswered_points"] = unanswered_points(info, user_input, history)
        return info
    except Exception:
        return _fallback_extraction(user_input, history)


def _add_facts(state: dict, prefix: str, values: list[str]) -> None:
    state["known_facts"].extend(f"{prefix}{value}" for value in values)


def _update_irregular_evidence(state: dict, info: dict) -> None:
    evidence = state.setdefault("irregular_evidence", {})
    for field, prefix in IRREGULAR_FACT_PREFIXES.items():
        # Legacy state has only factual text and the old, incompatible numeric score.
        previous = evidence.get(field, [fact[len(prefix):] for fact in state["known_facts"] if fact.startswith(prefix)])
        evidence[field] = list(dict.fromkeys([*previous, *info.get(field, [])]))
    stages = (
        bool(evidence["irregular_situations"] or evidence["irregular_responses"]),
        bool(evidence["irregular_reasons"]),
        bool(evidence["irregular_deeper_reasons"]),
    )
    completed = 0
    for present in stages:
        if not present:
            break
        completed += 1
    state["irregular_coverage"] = round(completed * CONFIG["scoring"]["irregular_stage_increment"], 2)
    state["irregular_partial_turn_count"] = (
        state.get("irregular_partial_turn_count", 0) + 1
        if state["irregular_coverage"] == CONFIG["ending"]["partial_irregular_coverage"] else 0
    )


def update_state(state: dict, info: dict) -> dict:
    state["turn_count"] += 1
    state["unanswered_points"] = list(dict.fromkeys([*state.get("unanswered_points", []), *info.get("unanswered_points", [])]))
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
        *IRREGULAR_FACT_PREFIXES.items(),
        ("emotions", "感情・状態: "), ("user_questions", "相手からの確認: "),
    ):
        _add_facts(state, prefix, info.get(field, []))
    state["persona_notes"].extend(info.get("persona_notes", []))
    _update_irregular_evidence(state, info)
    if info.get("signs_of_friction"):
        state["friction_count"] += 1
        state["rapport"] = max(0, state["rapport"] - CONFIG["scoring"]["friction_penalty"])
        state["asked_points"].extend(info["signs_of_friction"])
    if info.get("signs_of_resistance"):
        state["resistance_count"] += 1
        state["rapport"] = max(0, state["rapport"] - CONFIG["scoring"]["resistance_penalty"])
        state["asked_points"].extend(info["signs_of_resistance"])
    state["rapport"] = min(1, state["rapport"] + (CONFIG["scoring"]["information_rapport_increment"] if any(info.get(k) for k in ARRAY_FIELDS if k != "unanswered_points") else 0))
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
    if turn_limit_reached(state):
        return True
    irregular_ready = (
        state["irregular_coverage"] >= CONFIG["ending"]["min_irregular_coverage"]
        or (state["irregular_coverage"] == CONFIG["ending"]["partial_irregular_coverage"]
            and state.get("irregular_partial_turn_count", 0) >= CONFIG["ending"]["partial_irregular_turns"])
    )
    return bool(state["target_work"] and state["practice_covered"] and state["task_coverage"] >= CONFIG["ending"]["min_task_coverage"] and state["task_depth"] >= CONFIG["ending"]["high_depth"] and irregular_ready and (
        state["high_depth_turn_count"] >= CONFIG["ending"]["high_depth_turns"] or
        (state["task_coverage"] >= CONFIG["ending"]["complete_task_coverage"] and state["task_depth"] >= CONFIG["ending"]["complete_depth"] and state["irregular_coverage"] >= CONFIG["ending"]["complete_irregular_coverage"])
    ))


def _fram_question(state: dict, language: str) -> tuple[str, str]:
    scores = state.get("task_coverage_by_fram", {})
    focus = min(FRAM_FIELDS, key=lambda key: scores.get(key, 0))
    work = state.get("target_work") or {"ja": "その作業", "en": "that task", "de": "diese Arbeit"}[language]
    questions = {
        "ja": {
            "input": f"{work}が必要になったのは、何がきっかけでしたか？",
            "precondition": PRECONDITION_QUESTIONS[0][1].format(work=work),
            "resource": f"{work}では、どんな知識が必要でしたか？",
            "control": f"{work}の進め方は、何をもとに決めていますか？",
            "time": f"{work}は、いつまでに終える必要がありますか？",
            "output": f"{work}が終わったとき、何がどうなっていれば完了と判断しますか？",
        },
        "en": {
            "input": f"What happened that made {work} necessary?",
            "precondition": f"What do you usually do before starting {work}?",
            "resource": f"What knowledge did you need to carry out {work}?",
            "control": f"What do you base your way of carrying out {work} on?",
            "time": f"When does {work} need to be finished?",
            "output": f"What needs to have changed for you to consider {work} complete?",
        },
        "de": {
            "input": f"Was war der Anlass für {work}?",
            "precondition": f"Was machen Sie normalerweise, bevor Sie mit {work} beginnen?",
            "resource": f"Welches Wissen brauchten Sie für {work}?",
            "control": f"Woran orientieren Sie sich beim Vorgehen für {work}?",
            "time": f"Bis wann muss {work} abgeschlossen sein?",
            "output": f"Woran erkennen Sie, dass {work} abgeschlossen ist?",
        },
    }
    return focus, questions[language][focus]


def _irregular_question(state: dict, language: str) -> tuple[str, str]:
    work = state.get("target_work") or {"ja": "その作業", "en": "that task", "de": "diese Arbeit"}[language]
    score = state["irregular_coverage"]
    increment = CONFIG["scoring"]["irregular_stage_increment"]
    if score < increment:
        guide = ("対象業務で予定どおりに進まない時の状況や対応のうち、まだ分かっていない点を一つ尋ねる。"
                 "今回語られた平常時の条件や手順を起点にし、実際の経験がなければ現実的な範囲で仮定してよい。")
        question = {"ja": f"{work}で、普段どおりに進まないときはどう対応していますか？",
                    "en": f"How do you respond when {work} does not go as usual?",
                    "de": f"Wie reagieren Sie, wenn {work} nicht wie gewohnt verläuft?"}[language]
    elif score < round(2 * increment, 2):
        guide = ("既に語られたイレギュラーな状況・対応を起点に、その対応を選ぶ理由・根拠、"
                 "避けたいリスクや危険性、根拠となる手順や決まりのうち、まだ分からない点を一つ尋ねる。"
                 "別の例外の列挙や対応の聞き直しに戻らない。")
        question = {"ja": "そのようなときに、その対応を選ぶのはどうしてですか？",
                    "en": "What makes you choose that response in that situation?",
                    "de": "Warum entscheiden Sie sich in dieser Situation für dieses Vorgehen?"}[language]
    else:
        guide = ("イレギュラーな状況・対応と直接の理由は分かっているため、その理由や決まりをなぜ大切にするのか、"
                 "さらに奥の判断理由・背景の経験・価値観のうち、まだ分からない点を一つ尋ねる。"
                 "既に説明された直接の理由を聞き直さず、今回の対象業務と例外対応に結びつける。")
        question = {"ja": "今お話しされた理由を大切にするようになったのは、どんな背景があるのでしょうか？",
                    "en": "What led you to place importance on the reason you just described?",
                    "de": "Was hat Sie dazu gebracht, den gerade genannten Grund so wichtig zu nehmen?"}[language]
    guide += " 今回の会話と取得済みのイレギュラー情報に沿って自然に尋ね、理由や価値観を決めつけない。"
    return guide, question


def fallback_question(state: dict, language: str) -> str:
    if state.get("target_work") and state["task_coverage"] < CONFIG["ending"]["min_task_coverage"]:
        return _fram_question(state, language)[1]
    if state.get("target_work") and state["task_depth"] >= CONFIG["ending"]["high_depth"] and state["irregular_coverage"] < CONFIG["ending"]["min_irregular_coverage"]:
        return _irregular_question(state, language)[1]
    if language == "en":
        if not state["target_work"]: return "What kind of work were you doing earlier?"
        if state["task_depth"] < CONFIG["ending"]["high_depth"]: return f"What matters most to you when doing {state['target_work']}?"
        return f"What do you do when something unexpected happens during {state['target_work']}?"
    if language == "de":
        if not state["target_work"]: return "Welche Arbeit haben Sie vorhin gemacht?"
        if state["task_depth"] < CONFIG["ending"]["high_depth"]: return f"Was ist Ihnen bei {state['target_work']} besonders wichtig?"
        return f"Was tun Sie, wenn bei {state['target_work']} etwas Unerwartetes passiert?"
    if not state["target_work"]: return "先ほどの業務について、その時の状況も含めてもう少し聞かせてください。"
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
                 "理由を一問だけ尋ねる。既に説明された理由は聞き直さず、"
                 "まだ説明されていない判断の背景に沿って尋ねる。対象の種類や作業手順の具体化だけで終えない。"
                 "理由を決めつけず、責める聞き方にしない。この一問への回答後は元の業務の話へ戻る。")
        fallback = {
            "ja": f"「{anchor}」と判断されたのは、どういった理由からですか？",
            "en": f'What led you to make that decision when you said “{anchor}”?',
            "de": f'Was hat Sie zu der Entscheidung „{anchor}“ bewogen?',
        }[language]
    return guide, fallback, False


def _revisit_opening(state: dict, previous_work: str | None, info: dict,
                     past_sessions: list[dict], language: str) -> tuple[str | None, str | None]:
    work = state.get("target_work")
    if not work or not past_sessions:
        return None, None
    first = state.get("task_revisit_work") != work and previous_work != work
    state["task_revisit_work"] = work
    if first and not info.get("usual_work") and not (info.get("irregular_situations") or info.get("irregular_responses")):
        return (
            "過去に同じ対象業務のセッションがあるため、まず今回いつもと違うことが起きたかを一問で尋ねる。"
            "過去の詳しい情報は持ち出さず、業務名だけに沿って自然に聞く。違いがあったと決めつけない。",
            {"ja": f"今回の{work}では、いつもと違うことはありましたか？",
             "en": f"Was there anything different from usual during {work} this time?",
             "de": f"Gab es bei {work} diesmal etwas anders als sonst?"}[language],
        )
    return None, None


async def run_interview_turn(state: dict, user_input: str, history: list[dict], language: str,
                             *, extracted: dict | None = None, task_memory: dict | None = None) -> dict:
    info = dict(extracted if extracted is not None else await extract_turn(user_input, state, history))
    info["unanswered_points"] = unanswered_points(info, user_input, history)
    previous_work = state.get("target_work")
    task_memory = task_memory or {}
    current_session_id = task_memory.get("current_session_id")
    past_sessions = [
        {key: session[key] for key in ("session_id", "target_work", "ended_at", "summary", "info") if key in session}
        for session in task_memory.get("sessions", [])
        if session.get("session_id") and session["session_id"] != current_session_id
    ]
    active = state.get("deep_dive")
    next_state = update_state(state, {**info, "target_work": None} if active else info)
    if turn_limit_reached(next_state):
        next_state["deep_dive"] = None
        return {"text": ENDINGS[language], "state": next_state, "stateLabel": "end", "extracted": info,
                "guide": {"should_end": True, "end_reason": "turn_limit"}}
    if active:
        # An example about a competing task must not replace the interview's main task.
        next_state["target_work"] = active["return_target_work"]
    needs_irregular = bool(
        next_state["target_work"] and next_state["practice_covered"]
        and next_state["task_coverage"] >= CONFIG["ending"]["min_task_coverage"]
        and next_state["task_depth"] >= CONFIG["ending"]["high_depth"]
        and next_state["irregular_coverage"] < CONFIG["ending"]["min_irregular_coverage"]
    )
    interrupted = bool(info.get("user_questions") or info.get("signs_of_resistance") or info["unanswered_points"])
    revisit_guide, revisit_fallback = (None, None)
    if not interrupted and not active and not needs_irregular and not info.get("wants_to_stop"):
        revisit_guide, revisit_fallback = _revisit_opening(next_state, previous_work, info, past_sessions, language)
    if interrupted or info.get("wants_to_stop"):
        next_state["deep_dive"] = None
        dive_guide, dive_fallback, returning = None, None, False
    elif revisit_guide or (needs_irregular and not active):
        # Finish any pending anchor, then prioritize the missing exception topic.
        dive_guide, dive_fallback, returning = None, None, False
    else:
        dive_guide, dive_fallback, returning = _deep_dive_guidance(next_state, info, language)
    if info.get("wants_to_stop") or (
        not info.get("user_questions") and not dive_guide and not revisit_guide and should_end(next_state)
    ):
        next_state["deep_dive"] = None
        return {"text": ENDINGS[language], "state": next_state, "stateLabel": "end", "extracted": info,
                "guide": {"should_end": True}}

    fram_focus = None
    question_fallback = None
    depth_question = False
    if info.get("user_questions"):
        guide = "相手の質問に対して短く答え、必要なら答えやすい確認を一つする。質問の意図についてなどの質問じゃなく，あなたの1意見を聞かれているなら，素直に思ったことを想像で答える．"
    elif info["unanswered_points"]:
        guide = "無理に深掘りせず、同様の質問はそれ以降しないようにし，圧を下げて答えやすい形で会話を進める。"
        guide += "今回答えられなかった点の言い換えや理由の追及はせず、別の場面・行動・観点を一つ尋ねる。"
        question_fallback = alternate_question(next_state, language)
    elif revisit_guide:
        guide, question_fallback = revisit_guide, revisit_fallback
    elif dive_guide:
        guide = dive_guide
    elif next_state["task_coverage"] < CONFIG["ending"]["min_task_coverage"] and any(
        next_state.get("task_coverage_by_fram", {}).get(key, 0) < CONFIG["scoring"]["fram_cap"] for key in FRAM_FIELDS
    ):
        fram_focus, question_fallback = _fram_question(next_state, language)
        guide = (f"対象業務『{next_state.get('target_work')}』について、未取得・不足が最も大きい FRAM 項目"
                 f" {fram_focus} についてを重点的に確認する。質問例: {question_fallback} "
                 "会話で分かっている具体的な作業や現場の言葉に合わせ、既に答えた内容は聞き直さない。"
                 "環境や設備の状態を推測で決めつけない。別の観点を付け足さない。また，ここでも，framの6要素については，きっかけはなんですかとか処理対象はとか知識や情報はとかそういうダイレクトな聞き方を絶対しないでください．対話履歴の文脈の中で，自然にそれらに関することを引き出すイメージです．")
        if fram_focus == "precondition":
            guide += (" preconditionを『現場がどんな状態になっている必要がありますか』のように抽象的には尋ねない。"
                      "次の6つを切り口の候補とし、今回の会話に自然につながり、まだ確認していないものを一つだけ選ぶ。"
                      "既に答えた点や追及しない点は避ける。一度に並べたり、この順に全項目を埋めるように聞いたりしない。\n"
                      + "\n".join(f"{angle}: {question.format(work=next_state.get('target_work') or 'その作業')}"
                                  for angle, question in PRECONDITION_QUESTIONS))
        elif fram_focus == "resource":
            guide += (f" resourceは{FRAM_MEANINGS['resource']}。"
                      "今回の話と過去の情報を踏まえ、文脈に合う観点を一つだけ尋ね、材料の種類や一覧は尋ねない。")
    elif next_state["task_depth"] < CONFIG["ending"]["high_depth"]:
        depth_question = True
        guide = ("今回の対象業務について、それまでに語られた具体的な実践や判断を一つ選び、その人の仕事の内容や役職など過去に得た情報をふまえて深い情報を引き出す"
                 "まだ得られていない段階へ一段掘り下げる。『決まっているから』『ルールだから』など手順の説明で止まっているなら、"
                 "その決まりがなぜ大事なのか、現場でどう守られているか、組織として何を大切にしているのかのうち一つを尋ねる。"
                 "方針やその必要性まで分かっているなら、それを本人が大切にする背景の経験や価値観、仕事や会社への想いを尋ねる。"
                 "既に得られた説明を聞き直さず、今回の発言と対象業務を起点にし、一般論や無関係な人生相談へ広げない。"
                 "手順・方針・価値観のどこまで分かったかは取得済みの事実とdepthを踏まえ、質問は一度に一つにする。ただし，上べだけのことを聞かないできちんと相手に寄り添うこと")
    elif next_state["irregular_coverage"] < CONFIG["ending"]["min_irregular_coverage"]:
        guide, question_fallback = _irregular_question(next_state, language)
    else:
        guide = "ここまでの理解を短く返し、必要なら自然に終了へ向かう。"
    if returning:
        guide = (f"今の判断・調整の深掘りはここで終え、元の対象業務『{next_state.get('target_work')}』の話へ自然に戻る。"
                 "回答を短く受け止め、同じ理由を聞き直したり、回答中の別の語をさらに追いかけたりしない。" + guide)

    if dive_guide and next_state["task_coverage"] >= CONFIG["ending"]["min_task_coverage"] and next_state["task_depth"] < CONFIG["ending"]["high_depth"]:
        depth_question = True
    if info.get("signs_of_friction"):
        guide = ("誤解や聞き方の問題にはまず短く謝り、訂正された内容を反映する。"
                 "そのうえで次の方針に沿って質問を一つ続ける。" + guide)

    past_ids = {session["session_id"] for session in past_sessions}
    past_nodes = [node for node in task_memory.get("nodes", []) if past_ids.intersection(node.get("source_session_ids", []))]
    past_node_ids = {node["id"] for node in past_nodes}
    profile = task_memory.get("profile", {})
    use_past_memory = bool((past_sessions or any(profile.values())) and (fram_focus or depth_question or revisit_guide))
    if use_past_memory:
        memory_context = ("【過去セッションからの参照情報。下記の別セッションIDの情報だけが以前のインタビューの根拠】\n" +
                          json.dumps({"sessions": past_sessions, "nodes": past_nodes,
                                      "edges": [edge for edge in task_memory.get("edges", [])
                                                if edge["from_node_id"] in past_node_ids and edge["to_node_id"] in past_node_ids]}, ensure_ascii=False) +
                          "\n【参加者の長期プロフィール。特定セッションの発言の引用ではない】\n" +
                          json.dumps(profile, ensure_ascii=False) +
                          "\n過去の同じ業務の情報と今回の会話を踏まえ、同じことを聞き直さず、今の質問方針に沿って進めてください。"
                          "過去の情報を質問文に入れる必要はありません。今回の会話を別セッションの発言として引用せず、過去の事実を今回の回答として補わないでください。")
    else:
        memory_context = ("このターンは過去セッションとの比較を行いません。"
                          "今回の発話・今回の会話履歴と今の方針に沿って、通常どおり進めてください。")

    language_name = {"ja": "日本語", "en": "English", "de": "Deutsch"}[language]
    focus_context = f"今回尋ねるFRAM項目: {fram_focus} = {FRAM_MEANINGS[fram_focus]}。" if fram_focus else ""
    prompt = f"""あなたはインタビュアーの業務について教えてもらう，トレーナーの立場兼半構造化インタビューを行う自然な聞き手です。最終的な目的は，safety-IIのレジリエンスエンジニアリングの文脈で，現場の皆さんの日常においてうまく行くようにしている調整を明らかにすること，そして現場の安全管理に役立てるために行っています．{language_name}で次の発話だけを作ってください。
{INTERVIEWER_STANCE}
{domain_knowledge_context(task_memory.get('domain_knowledge'))}
短い1〜2文にし、質問は一度に一つ。監査や尋問のようにせず、相手の実際の仕事とその背景にある理由や仕事に関する価値観を理解してください。
トレーニーとして，対象者の人はすごいんだ，日々難しい仕事をしていて，尊敬するべきものだ，という心づもり，姿勢でいてください．
質問は原則として、今回の具体的な状況・行動・考え方を本人の言葉で説明できるオープンエンドな形にします。同じだったことや違いがあったことは決めつけないでください。
一つの疑問文でも、尋ねる内容は一つに絞ります。「手順や必要な知識・経験」のように複数の抽象的な項目をまとめて尋ねないでください。
対象業務の名前や会話に出た言葉を使って、その場面を思い出して答えられる短い質問にします。「改めて業務そのものについて」のような長い前置きは省きます。
framの6要素については，きっかけはなんですかとか処理対象はとか知識や情報はとかそういうダイレクトな聞き方を絶対しないでください．対話履歴の文脈の中で，自然にそれらに関することを引き出すイメージです．
{memory_context}
対象業務: {next_state.get('target_work')}
【今回のセッションで分かったこと。別セッションの記憶ではない】
{json.dumps(next_state['known_facts'][-CONFIG['history']['prompt_facts']:], ensure_ascii=False)}
【今回のセッションで取得済みのイレギュラー情報】
{json.dumps(next_state['irregular_evidence'], ensure_ascii=False)}
【今回のセッション内の既出質問】
{json.dumps([point.replace('過去の質問:', '今回の質問:', 1) for point in next_state['asked_points'][-CONFIG['history']['prompt_questions']:]], ensure_ascii=False)}
【今回のセッション内の会話履歴。別セッションの記憶ではない】
{_history_text(history)}
{unanswered_context(next_state)}
今回の履歴を振り返るときは『先ほど』と表現し、『以前のインタビューでは』と言い換えないでください。別セッションの根拠がないときは『以前〜と伺いましたが』という引用を作らないでください。
直前の回答: {user_input}

今の方針: {guide}
{focus_context}
会話履歴と過去の情報は文脈として参照し、次の発話は今の方針に沿って作ってください。
"""
    try:
        response = (await complete(prompt)).strip() if configured() else ""
    except Exception:
        response = ""
    if not response:
        response = dive_fallback or question_fallback or fallback_question(next_state, language)
        if info.get("signs_of_friction"):
            response = {"ja": "失礼しました。", "en": "Sorry about that. ", "de": "Entschuldigung. "}[language] + response
    if repeats_unanswered_point(response, next_state):
        response = alternate_question(next_state, language)
    is_question = "?" in response or "？" in response or (
        language == "ja" and bool(re.search(r"(?:か|教えてください)[。！!]?\s*$", response))
    )
    if is_question:
        next_state["consecutive_questions"] += 1
        next_state["turns_since_reflection"] += 1
        next_state["asked_points"].append(f"今回の質問: {response}")
    else:
        next_state["consecutive_questions"] = 0
        next_state["turns_since_reflection"] = 0
        next_state["rapport"] = min(1, next_state["rapport"] + CONFIG["scoring"]["reflection_rapport_increment"])
    return {"text": response, "state": next_state, "stateLabel": "running", "extracted": info,
            "guide": {"guidance": guide, "past_memory_used": use_past_memory,
                      **({"fram_focus": fram_focus} if fram_focus else {})}}
