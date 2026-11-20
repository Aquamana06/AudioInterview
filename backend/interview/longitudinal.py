import json
import re
import unicodedata

from config import load_config
from llm.client import complete, configured
from interview.agent import INTERVIEWER_STANCE, domain_knowledge_context


CONFIG = load_config("interview")["retrieval"]


FALLBACK_STARTERS = {
    "ja": ["先ほどはどんな業務をしていましたか？", "今日は直前まで、どんなお仕事をされていたんですか？",
           "さっき取り組んでいた業務について教えてもらえますか？"],
    "en": ["What kind of work were you doing earlier?", "What were you working on just before this interview?"],
    "de": ["Welche Arbeit haben Sie vorhin gemacht?", "Woran haben Sie unmittelbar vor diesem Gespräch gearbeitet?"],
}


def task_match_score(target_work: str, previous_work: str) -> float:
    """Match task names across particles/spacing without matching '交換' alone."""
    def words(text: str) -> list[str]:
        return re.findall(r"[a-zäöüß0-9]+|[一-龯々]+|[ァ-ヴー]+", unicodedata.normalize("NFKC", text).lower())

    query = words(target_work)
    key = "".join(query)
    candidate = "".join(words(previous_work))
    if not key or not candidate:
        return 0
    if key == candidate:
        return 1
    if len(key) < 3:
        return 0
    score = sum(len(word) for word in query if word in candidate) / len(key)
    return score if score >= 0.8 else 0


async def starter(language: str, session_count: int, profile: dict, recent_starters: list[str] | None = None,
                  *, domain_knowledge: list[dict] | None = None) -> str:
    candidates = FALLBACK_STARTERS[language]
    recent_starters = recent_starters or []
    available = [item for item in candidates if item not in recent_starters] or candidates
    fallback = available[session_count % len(available)]
    if not configured():
        return fallback
    language_name = {"ja": "日本語", "en": "English", "de": "Deutsch"}[language]
    prompt = f"""反復型インタビューの開始発話を{language_name}で一文だけ作ってください。{INTERVIEWER_STANCE}
{domain_knowledge_context(domain_knowledge)}
参加者が「先ほどしていた具体的な業務」を話し始められる短い質問にします。過去の価値観は持ち出さず、今日の経験を起点にします。分析用語や挨拶は不要です。最近の開始発話: {json.dumps(recent_starters, ensure_ascii=False)}"""
    try:
        text = (await complete(prompt)).strip().strip("「」\"'")
        if text and text not in recent_starters and len(text) <= CONFIG["starter_max_chars"]:
            return text
    except Exception:
        pass
    return fallback


def select_relevant(memory: dict, user_input: str, limit: int | None = None) -> dict:
    limit = CONFIG["items"] if limit is None else limit
    def terms(text: str) -> set[str]:
        text = unicodedata.normalize("NFKC", text).lower()
        words = set(re.findall(r"[a-zäöüß0-9]+|[一-龯々]+|[ァ-ヴー]+", text))
        # Japanese answers contain no spaces: retain content words and substrings,
        # rather than requiring an entire conjugated sentence to match memory.
        return {word for word in words if len(word) >= 2} | {
            word[index:index + 2] for word in words if re.search(r"[一-龯々ァ-ヴー]", word)
            for index in range(len(word) - 1)
        }

    query_terms = terms(user_input)

    def relevance(text: str) -> int:
        return len(query_terms & terms(text))

    nodes = sorted(
        memory.get("nodes", []),
        key=lambda node: relevance(node["text"]) + float(node.get("confidence", 0)) * CONFIG["confidence_weight"],
        reverse=True,
    )
    nodes = [node for node in nodes if relevance(node["text"]) > 0][:limit]
    ids = {node["id"] for node in nodes}
    summaries = sorted(
        memory.get("recent_summaries", []),
        key=lambda item: relevance(item["summary"]),
        reverse=True,
    )
    summaries = [item for item in summaries if relevance(item["summary"]) > 0][:CONFIG["summaries"]]
    return {
        "profile": memory.get("profile", {}),
        "summaries": summaries,
        "nodes": nodes,
        "edges": [edge for edge in memory.get("edges", []) if edge["from_node_id"] in ids or edge["to_node_id"] in ids][:limit],
    }
