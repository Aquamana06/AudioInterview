import json
import sqlite3
import unicodedata
from typing import Any

from config import load_config
from db.database import database, list_messages, new_id, now_iso
from llm.client import complete_json, configured
from interview.diagnostics import log_event, logger


CONFIG = load_config("db")["memory"]


def get_session_memory(connection: sqlite3.Connection, session_id: str) -> dict:
    row = connection.execute(
        "SELECT summary FROM longitudinal_session_summaries WHERE session_id=?", (session_id,),
    ).fetchone()
    job = connection.execute("SELECT status FROM session_memory_jobs WHERE session_id=?", (session_id,)).fetchone()
    return {"summary": row["summary"] if row else None,
            "status": job["status"] if job else ("ready" if row else "not_started")}


def ensure_session_memory(account_id: str, session_id: str, messages: list[dict]) -> None:
    """Persist a bounded, verbatim record before returning the end response."""
    answers = [item["content"] for item in messages if item["role"] == "user"]
    count = CONFIG["fallback_answers"]
    selected = answers if len(answers) <= count else answers[:count // 2] + answers[-(count - count // 2):]
    excerpts = "\n".join(f"- {answer[:CONFIG['fallback_answer_chars']]}" for answer in selected)
    summary = "【発話抜粋】\n" + (excerpts or "回答は記録されていません。")
    with database() as connection:
        existing = get_session_memory(connection, session_id)
        if existing["summary"]:
            return
        session = connection.execute("SELECT ended_at FROM interview_sessions WHERE id=?", (session_id,)).fetchone()
        connection.execute(
            """INSERT INTO longitudinal_session_summaries (session_id, account_id, summary, ended_at)
               VALUES (?, ?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET
               summary=excluded.summary, ended_at=excluded.ended_at
               WHERE longitudinal_session_summaries.summary=''""",
            (session_id, account_id, summary, session["ended_at"] or now_iso()),
        )
        connection.execute(
            """INSERT INTO session_memory_jobs (session_id, status, updated_at) VALUES (?, 'pending', ?)
               ON CONFLICT(session_id) DO UPDATE SET status='pending', updated_at=excluded.updated_at""",
            (session_id, now_iso()),
        )
    log_event("memory_record_saved", session_id, summary=summary)


async def recover_session_memories() -> None:
    """Resume interrupted/failed jobs and legacy ended sessions without summaries."""
    with database() as connection:
        sessions = [dict(row) for row in connection.execute(
            """SELECT s.* FROM interview_sessions s
               LEFT JOIN longitudinal_session_summaries m ON m.session_id=s.id
               LEFT JOIN session_memory_jobs j ON j.session_id=s.id
               WHERE s.status='ended' AND (m.summary IS NULL OR m.summary='' OR j.status IN ('pending', 'fallback'))
               ORDER BY s.ended_at""",
        )]
    # Save excerpts for every pending session before starting model inference.
    for session in sessions:
        with database() as connection:
            messages = list_messages(connection, session["id"])
        ensure_session_memory(session["account_id"], session["id"], messages)
        with database() as connection:
            connection.execute(
                "UPDATE session_memory_jobs SET status='pending', updated_at=? WHERE session_id=? AND status='fallback'",
                (now_iso(), session["id"]),
            )
    for session in sessions:
        try:
            with database() as connection:
                messages = list_messages(connection, session["id"])
            await finalize_session(session["account_id"], session["id"], session["language"], messages)
        except Exception:
            logger.exception("[interview] session_id=%s 記憶の復旧に失敗しました", session["id"])
            with database() as connection:
                connection.execute(
                    "UPDATE session_memory_jobs SET status='fallback', updated_at=? WHERE session_id=? AND status='pending'",
                    (now_iso(), session["id"]),
                )


def empty_profile() -> dict[str, Any]:
    return {
        "role": None, "years_of_experience": None, "typical_day": [],
        "responsibilities": [], "collaborators": [],
    }


def load_participant_profile(account_id: str) -> dict[str, Any]:
    """Load the long-term profile and learned vocabulary, without past conversations."""
    with database() as connection:
        profile_row = connection.execute(
            "SELECT profile_json FROM participant_profiles WHERE account_id=?", (account_id,)
        ).fetchone()
        session_count = connection.execute(
            "SELECT COUNT(*) FROM interview_sessions WHERE account_id=? AND status='ended'", (account_id,)
        ).fetchone()[0]
        domain_knowledge = [dict(row) for row in connection.execute(
            """SELECT term, meaning, scope, source_session_id FROM participant_domain_knowledge
               WHERE account_id=? ORDER BY updated_at DESC, canonical_key""", (account_id,),
        )]
    profile = {**empty_profile(), **(json.loads(profile_row["profile_json"]) if profile_row else {})}
    return {"account_id": account_id, "session_count": int(session_count), "profile": profile,
            "domain_knowledge": domain_knowledge}


def load_participant_memory(account_id: str) -> dict[str, Any]:
    participant = load_participant_profile(account_id)
    with database() as connection:
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
    return {
        **participant,
        "recent_summaries": summaries, "nodes": nodes, "edges": edges,
    }


def select_relevant_memory(memory: dict, user_input: str, limit: int | None = None) -> dict:
    from interview.longitudinal import select_relevant

    return select_relevant(memory, user_input, limit)


def load_task_memory(account_id: str, target_work: str | None, *, exclude_session_id: str,
                     profile: dict) -> dict:
    """Load summaries and structured facts from other completed sessions only."""
    from interview.longitudinal import task_match_score

    retrieval = load_config("interview")["retrieval"]
    result = {"target_work": target_work, "current_session_id": exclude_session_id,
              "profile": profile, "sessions": [],
              "summaries": [], "nodes": [], "edges": []}
    if not target_work:
        return result
    with database() as connection:
        candidates = []
        for row in connection.execute(
            """SELECT s.id, s.ended_at, m.summary, i.state_json
               FROM interview_sessions s
               LEFT JOIN longitudinal_session_summaries m ON m.session_id=s.id
               LEFT JOIN interview_states i ON i.session_id=s.id
               WHERE s.account_id=? AND s.status='ended' AND s.id!=?
               ORDER BY s.ended_at DESC""", (account_id, exclude_session_id),
        ):
            state = json.loads(row["state_json"] or "{}")
            previous_work = state.get("target_work")
            # Legacy/profile sessions may have no task state; their summary is searchable.
            score = task_match_score(target_work, previous_work or row["summary"] or "")
            if score:
                candidates.append((score, dict(row), previous_work))
        candidates.sort(key=lambda item: item[0], reverse=True)
        selected = candidates[:retrieval["task_sessions"]]
        per_session_budget = retrieval["task_context_chars"] // max(1, len(selected))
        for _, row, previous_work in selected:
            summary = (row["summary"] or "")[:min(retrieval["summary_chars"], per_session_budget)]
            budget = per_session_budget - len(summary)
            state = json.loads(row["state_json"] or "{}")
            info = {}
            for field in ("known_facts", "persona_notes"):
                info[field] = []
                for value in state.get(field, []):
                    content = value[:min(retrieval["message_chars"], budget)]
                    if not content:
                        break
                    info[field].append(content)
                    budget -= len(content)
            result["sessions"].append({"session_id": row["id"], "target_work": previous_work,
                                       "ended_at": row["ended_at"], "summary": summary, "info": info})
            if summary:
                result["summaries"].append({"session_id": row["id"], "summary": summary, "ended_at": row["ended_at"]})
        ids = [row["session_id"] for row in result["sessions"]]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            result["nodes"] = [dict(row) for row in connection.execute(
                f"""SELECT id, kind, text, confidence, first_session_id, last_session_id FROM memory_nodes
                    WHERE account_id=? AND status!='superseded'
                    AND (first_session_id IN ({placeholders}) OR last_session_id IN ({placeholders}))
                    ORDER BY confidence DESC LIMIT ?""",
                (account_id, *ids, *ids, retrieval["items"]),
            )]
            for node in result["nodes"]:
                node["text"] = node["text"][:retrieval["message_chars"]]
                node["source_session_ids"] = list(dict.fromkeys(
                    session_id for session_id in (node.pop("first_session_id"), node.pop("last_session_id"))
                    if session_id in ids
                ))
            node_ids = {node["id"] for node in result["nodes"]}
            result["edges"] = [dict(row) for row in connection.execute(
                f"""SELECT from_node_id, to_node_id, relation FROM memory_edges
                    WHERE account_id=? AND (first_session_id IN ({placeholders}) OR last_session_id IN ({placeholders}))
                    ORDER BY confidence DESC LIMIT ?""",
                (account_id, *ids, *ids, retrieval["items"]),
            ) if row["from_node_id"] in node_ids and row["to_node_id"] in node_ids]
    return result


def _merge_unique(current: list[str], incoming: list[str]) -> list[str]:
    return list(dict.fromkeys([value.strip() for value in [*current, *incoming] if value.strip()]))


def _merge_profile(current: dict, patch: dict) -> dict:
    result = dict(current)
    for key in ("role", "years_of_experience"):
        result[key] = patch.get(key) or current.get(key)
    for key in ("typical_day", "responsibilities", "collaborators"):
        result[key] = _merge_unique(current.get(key, []), patch.get(key, []))
    return result


def _save_domain_knowledge(connection: sqlite3.Connection, account_id: str, session_id: str,
                           entries: list[dict], stamp: str) -> None:
    if not entries:
        return
    # Only the respondent's own explanations in this session can support a definition.
    user_ids = {row["id"] for row in connection.execute(
        """SELECT m.id FROM messages m JOIN interview_sessions s ON s.id=m.session_id
           WHERE m.session_id=? AND s.account_id=? AND m.role='user'""", (session_id, account_id),
    )}
    for entry in entries:
        term, meaning = entry.get("term", "").strip(), entry.get("meaning", "").strip()
        scope = entry.get("scope", "").strip()
        evidence = list(dict.fromkeys(value for value in entry.get("evidence_message_ids", []) if value in user_ids))
        if not term or not meaning or not evidence:
            continue
        key = json.dumps([unicodedata.normalize("NFKC", value).casefold().strip()
                          for value in (scope, term)], ensure_ascii=False)
        connection.execute(
            """INSERT INTO participant_domain_knowledge
               (account_id, canonical_key, term, meaning, scope, source_session_id, evidence_json, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(account_id, canonical_key) DO UPDATE SET
               term=excluded.term, meaning=excluded.meaning, source_session_id=excluded.source_session_id,
               evidence_json=excluded.evidence_json, updated_at=excluded.updated_at""",
            (account_id, key, term, meaning, scope, session_id, json.dumps(evidence), stamp),
        )


def save_session_memory(account_id: str, session_id: str, current_profile: dict, update: dict) -> None:
    stamp = now_iso()
    with database() as connection:
        session = connection.execute("SELECT ended_at FROM interview_sessions WHERE id=?", (session_id,)).fetchone()
        profile = _merge_profile(current_profile, update.get("profile_patch", {}))
        connection.execute(
            """INSERT INTO participant_profiles (account_id, profile_json, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(account_id) DO UPDATE SET profile_json=excluded.profile_json, updated_at=excluded.updated_at""",
            (account_id, json.dumps(profile, ensure_ascii=False), stamp),
        )
        connection.execute(
            """INSERT INTO longitudinal_session_summaries (session_id, account_id, summary, ended_at)
               VALUES (?, ?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET summary=excluded.summary, ended_at=excluded.ended_at""",
            (session_id, account_id, update.get("summary", ""), session["ended_at"] or stamp),
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
        connection.execute(
            """INSERT INTO session_memory_jobs (session_id, status, updated_at) VALUES (?, 'ready', ?)
               ON CONFLICT(session_id) DO UPDATE SET status='ready', updated_at=excluded.updated_at""",
            (session_id, stamp),
        )
        _save_domain_knowledge(connection, account_id, session_id, update.get("domain_knowledge", []), stamp)


MEMORY_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "domain_knowledge": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "term": {"type": "string"}, "meaning": {"type": "string"},
                "scope": {"type": "string"},
                "evidence_message_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["term", "meaning", "scope", "evidence_message_ids"],
        }},
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
    "required": ["summary", "profile_patch", "nodes", "edges", "domain_knowledge"],
}


async def finalize_session(account_id: str, session_id: str, language: str, messages: list[dict]) -> None:
    ensure_session_memory(account_id, session_id, messages)
    if not configured():
        with database() as connection:
            connection.execute("UPDATE session_memory_jobs SET status='fallback', updated_at=? WHERE session_id=? AND status!='ready'",
                               (now_iso(), session_id))
        log_event("memory_fallback", session_id, reason="LLM が未設定のため発話抜粋を保持します。")
        return
    log_event("memory_finalizing", session_id)
    memory = load_participant_memory(account_id)
    transcript = "\n".join(f"[{item['id']}] {item['role']}: {item['content']}" for item in messages)
    prompt = f"""次のインタビュー記録を、参加者の将来の会話で参照するために整理してください。書かれていない事実は作らず、profile_patchは新しく明示された情報だけにしてください。nodesは具体的な業務、状況、調整行動、理由、判断基準、価値観、経験源、個人的意味を含めます。edgesは明示された因果や関係だけにします。evidence_message_idsは根拠のメッセージIDを使います。
言語: {language}
既存プロフィール: {json.dumps(memory['profile'], ensure_ascii=False)}
domain_knowledgeは、参加者が明示的に教えた作業名・略語・現場用語の意味や、業務を理解するための定義だけを別の用語集として保存します。例えば『全交換とはカラフェとピッチャーを交換する作業』です。termは本人の用語、meaningは説明された意味、scopeはその意味が通用する職場・業務の範囲（特定できなければ空文字）にします。今回の実施間隔や一時的な状態、本人の判断・価値観は用語の定義に混ぜません。聞き手だけの推測や未回答の確認質問を採用せず、evidence_message_idsには今回その意味を説明・訂正したuserのIDを付けます。既存の同じ意味は再出力せず、説明が訂正された場合は同じtermとscopeで新しいmeaningを出してください。新しく説明された用語は省略せず保存し、なければ空配列にします。
既存のドメイン知識: {json.dumps(memory['domain_knowledge'], ensure_ascii=False)}
要約は300字程度、nodesは重要なものを最大6件、edgesは最大6件、各 evidence_message_ids は最大2件に絞り、JSONを最後まで出力してください。既存の記憶の再出力は不要です。
既存要約: {json.dumps([item for item in memory['recent_summaries'] if item['session_id'] != session_id][:CONFIG['prompt_summaries']], ensure_ascii=False)}
会話: {transcript}"""
    try:
        update = await complete_json(prompt, MEMORY_SCHEMA)
        if not isinstance(update.get("summary"), str) or not update["summary"].strip():
            raise ValueError("LLM returned an empty session summary")
        save_session_memory(account_id, session_id, memory["profile"], update)
    except Exception:
        logger.exception("[interview] session_id=%s 要約・記憶の生成に失敗しました", session_id)
        with database() as connection:
            connection.execute("UPDATE session_memory_jobs SET status='fallback', updated_at=? WHERE session_id=? AND status!='ready'",
                               (now_iso(), session_id))
        log_event("memory_fallback", session_id, reason="要約生成に失敗したため発話抜粋を保持します。再起動時に再試行します。")
        return
    log_event("memory_saved", session_id, summary=update.get("summary", ""),
              profile=_merge_profile(memory["profile"], update.get("profile_patch", {})),
              nodes=update.get("nodes", []), edges=update.get("edges", []),
              domain_knowledge=load_participant_profile(account_id)["domain_knowledge"])
