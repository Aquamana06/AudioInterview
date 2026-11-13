import json
import sqlite3
from typing import Any

from config import load_config
from db.database import database, new_id, now_iso
from llm.client import complete_json, configured


CONFIG = load_config("db")["memory"]


def empty_profile() -> dict[str, Any]:
    return {
        "role": None, "years_of_experience": None, "typical_day": [],
        "responsibilities": [], "collaborators": [],
    }


def load_participant_memory(account_id: str) -> dict[str, Any]:
    with database() as connection:
        profile_row = connection.execute(
            "SELECT profile_json FROM participant_profiles WHERE account_id=?", (account_id,)
        ).fetchone()
        session_count = connection.execute(
            "SELECT COUNT(*) FROM interview_sessions WHERE account_id=? AND status='ended'", (account_id,)
        ).fetchone()[0]
        summaries = [dict(row) for row in connection.execute(
            "SELECT session_id, summary, ended_at FROM longitudinal_session_summaries WHERE account_id=? ORDER BY ended_at DESC LIMIT ?",
            (account_id, CONFIG["recent_summaries"]),
        )]
        nodes = [dict(row) for row in connection.execute(
            """SELECT id, kind, canonical_key AS key, text, status, confidence,
                      first_session_id, last_session_id, evidence_json
               FROM memory_nodes WHERE account_id=? AND status!='superseded'
               ORDER BY last_seen_at DESC LIMIT ?""",
            (account_id, CONFIG["nodes"]),
        )]
        edges = [dict(row) for row in connection.execute(
            """SELECT id, from_node_id, to_node_id, relation, explicitness, confidence,
                      first_session_id, last_session_id, evidence_json
               FROM memory_edges WHERE account_id=? ORDER BY last_seen_at DESC LIMIT ?""",
            (account_id, CONFIG["edges"]),
        )]
        keys_by_id = {node["id"]: node["key"] for node in nodes}
    for node in nodes:
        node["evidence_message_ids"] = json.loads(node.pop("evidence_json") or "[]")
    for edge in edges:
        edge["evidence_message_ids"] = json.loads(edge.pop("evidence_json") or "[]")
        edge["from_key"] = keys_by_id.get(edge["from_node_id"], "")
        edge["to_key"] = keys_by_id.get(edge["to_node_id"], "")
    profile = {**empty_profile(), **(json.loads(profile_row["profile_json"]) if profile_row else {})}
    return {
        "account_id": account_id, "session_count": int(session_count), "profile": profile,
        "recent_summaries": summaries, "nodes": nodes, "edges": edges,
    }


def select_relevant_memory(memory: dict, user_input: str, limit: int | None = None) -> dict:
    from interview.longitudinal import select_relevant

    return select_relevant(memory, user_input, limit)


def _merge_unique(current: list[str], incoming: list[str]) -> list[str]:
    return list(dict.fromkeys([value.strip() for value in [*current, *incoming] if value.strip()]))


def _merge_profile(current: dict, patch: dict) -> dict:
    result = dict(current)
    for key in ("role", "years_of_experience"):
        result[key] = patch.get(key) or current.get(key)
    for key in ("typical_day", "responsibilities", "collaborators"):
        result[key] = _merge_unique(current.get(key, []), patch.get(key, []))
    return result


def save_session_memory(account_id: str, session_id: str, current_profile: dict, update: dict) -> None:
    stamp = now_iso()
    with database() as connection:
        profile = _merge_profile(current_profile, update.get("profile_patch", {}))
        connection.execute(
            """INSERT INTO participant_profiles (account_id, profile_json, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(account_id) DO UPDATE SET profile_json=excluded.profile_json, updated_at=excluded.updated_at""",
            (account_id, json.dumps(profile, ensure_ascii=False), stamp),
        )
        connection.execute(
            """INSERT INTO longitudinal_session_summaries (session_id, account_id, summary, ended_at)
               VALUES (?, ?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET summary=excluded.summary, ended_at=excluded.ended_at""",
            (session_id, account_id, update.get("summary", ""), stamp),
        )
        node_ids: dict[str, str] = {}
        for node in update.get("nodes", []):
            kind, text = node.get("kind", "situation"), node.get("text", "").strip()
            if not text:
                continue
            canonical = f"{kind}:{text}"
            existing = connection.execute(
                "SELECT id, evidence_json FROM memory_nodes WHERE account_id=? AND canonical_key=?",
                (account_id, canonical),
            ).fetchone()
            node_id = existing["id"] if existing else new_id("mem")
            evidence = _merge_unique(json.loads(existing["evidence_json"]) if existing else [], node.get("evidence_message_ids", []))
            connection.execute(
                """INSERT INTO memory_nodes
                   (id, account_id, canonical_key, kind, text, status, confidence, first_session_id,
                    last_session_id, evidence_json, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(account_id, canonical_key) DO UPDATE SET status=excluded.status,
                   confidence=MAX(memory_nodes.confidence, excluded.confidence),
                   last_session_id=excluded.last_session_id, evidence_json=excluded.evidence_json,
                   last_seen_at=excluded.last_seen_at""",
                (node_id, account_id, canonical, kind, text, node.get("status", "observed"),
                 float(node.get("confidence", 0.5)), session_id, session_id,
                 json.dumps(evidence), stamp),
            )
            node_ids[node.get("key", canonical)] = node_id
        for edge in update.get("edges", []):
            from_id, to_id = node_ids.get(edge.get("from_key")), node_ids.get(edge.get("to_key"))
            if not from_id or not to_id:
                continue
            relation = edge.get("relation", "related_to")
            canonical = f"{from_id}:{relation}:{to_id}"
            existing = connection.execute(
                "SELECT id, evidence_json FROM memory_edges WHERE account_id=? AND canonical_key=?",
                (account_id, canonical),
            ).fetchone()
            evidence = _merge_unique(json.loads(existing["evidence_json"]) if existing else [], edge.get("evidence_message_ids", []))
            connection.execute(
                """INSERT INTO memory_edges
                   (id, account_id, canonical_key, from_node_id, to_node_id, relation, explicitness,
                    confidence, first_session_id, last_session_id, evidence_json, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(account_id, canonical_key) DO UPDATE SET
                   explicitness=CASE WHEN memory_edges.explicitness='explicit' OR excluded.explicitness='explicit'
                                     THEN 'explicit' ELSE 'inferred' END,
                   confidence=MAX(memory_edges.confidence, excluded.confidence),
                   last_session_id=excluded.last_session_id, evidence_json=excluded.evidence_json,
                   last_seen_at=excluded.last_seen_at""",
                (existing["id"] if existing else new_id("edge"), account_id, canonical,
                 from_id, to_id, relation, edge.get("explicitness", "explicit"),
                 float(edge.get("confidence", 0.5)), session_id, session_id,
                 json.dumps(evidence), stamp),
            )


MEMORY_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "profile_patch": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "role": {"type": ["string", "null"]},
                "years_of_experience": {"type": ["string", "null"]},
                "typical_day": {"type": "array", "items": {"type": "string"}},
                "responsibilities": {"type": "array", "items": {"type": "string"}},
                "collaborators": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["role", "years_of_experience", "typical_day", "responsibilities", "collaborators"],
        },
        "nodes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "key": {"type": "string"}, "kind": {"type": "string"}, "text": {"type": "string"},
                "status": {"type": "string"}, "confidence": {"type": "number"},
                "evidence_message_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["key", "kind", "text", "status", "confidence", "evidence_message_ids"],
        }},
        "edges": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "from_key": {"type": "string"}, "to_key": {"type": "string"}, "relation": {"type": "string"},
                "explicitness": {"type": "string"}, "confidence": {"type": "number"},
                "evidence_message_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["from_key", "to_key", "relation", "explicitness", "confidence", "evidence_message_ids"],
        }},
    },
    "required": ["summary", "profile_patch", "nodes", "edges"],
}


async def finalize_session(account_id: str, session_id: str, language: str, messages: list[dict]) -> None:
    if not configured():
        return
    memory = load_participant_memory(account_id)
    transcript = "\n".join(f"[{item['id']}] {item['role']}: {item['content']}" for item in messages)
    prompt = f"""次のインタビュー記録を、参加者の将来の会話で参照するために整理してください。書かれていない事実は作らず、profile_patchは新しく明示された情報だけにしてください。nodesは具体的な業務、状況、調整行動、理由、判断基準、価値観、経験源、個人的意味を含めます。edgesは明示された因果や関係だけにします。evidence_message_idsは根拠のメッセージIDを使います。
言語: {language}
既存プロフィール: {json.dumps(memory['profile'], ensure_ascii=False)}
既存要約: {json.dumps(memory['recent_summaries'][:CONFIG['prompt_summaries']], ensure_ascii=False)}
会話: {transcript}"""
    try:
        update = await complete_json(prompt, MEMORY_SCHEMA)
    except Exception:
        return
    save_session_memory(account_id, session_id, memory["profile"], update)
