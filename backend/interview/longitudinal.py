import json

from config import load_config
from llm.client import complete, configured


CONFIG = load_config("interview")["retrieval"]


FALLBACK_STARTERS = {
    "ja": ["先ほどはどんな業務をしていましたか？", "今日は直前まで、どんなお仕事をされていたんですか？",
           "さっき取り組んでいた業務について教えてもらえますか？"],
    "en": ["What kind of work were you doing earlier?", "What were you working on just before this interview?"],
    "de": ["Welche Arbeit haben Sie vorhin gemacht?", "Woran haben Sie unmittelbar vor diesem Gespräch gearbeitet?"],
}


async def starter(language: str, session_count: int, profile: dict, recent_starters: list[str] | None = None) -> str:
    candidates = FALLBACK_STARTERS[language]
    recent_starters = recent_starters or []
    available = [item for item in candidates if item not in recent_starters] or candidates
    fallback = available[session_count % len(available)]
    if not configured():
        return fallback
    language_name = {"ja": "日本語", "en": "English", "de": "Deutsch"}[language]
    prompt = f"""反復型インタビューの開始発話を{language_name}で一文だけ作ってください。参加者が「先ほどしていた具体的な業務」を話し始められる短い質問にします。過去の価値観は持ち出さず、今日の経験を起点にします。分析用語や挨拶は不要です。最近の開始発話: {json.dumps(recent_starters, ensure_ascii=False)}"""
    try:
        text = (await complete(prompt)).strip().strip("「」\"'")
        if text and text not in recent_starters and len(text) <= CONFIG["starter_max_chars"]:
            return text
    except Exception:
        pass
    return fallback


def select_relevant(memory: dict, user_input: str, limit: int | None = None) -> dict:
    limit = CONFIG["items"] if limit is None else limit
    terms = {term for term in __import__("re").split(r"[\s、。,.!?！？]+", user_input.lower()) if len(term) >= 2}
    nodes = sorted(
        memory.get("nodes", []),
        key=lambda node: sum(term in node["text"].lower() for term in terms) + float(node.get("confidence", 0)) * CONFIG["confidence_weight"],
        reverse=True,
    )
    nodes = [node for node in nodes if any(term in node["text"].lower() for term in terms)][:limit]
    ids = {node["id"] for node in nodes}
    summaries = sorted(
        memory.get("recent_summaries", []),
        key=lambda item: sum(term in item["summary"].lower() for term in terms),
        reverse=True,
    )
    summaries = [item for item in summaries if any(term in item["summary"].lower() for term in terms)][:CONFIG["summaries"]]
    return {
        "profile": memory.get("profile", {}),
        "summaries": summaries,
        "nodes": nodes,
        "edges": [edge for edge in memory.get("edges", []) if edge["from_node_id"] in ids or edge["to_node_id"] in ids][:limit],
    }
