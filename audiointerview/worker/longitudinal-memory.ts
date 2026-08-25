import { nowIso, randomId } from './db.js';
import type { RuntimeEnv } from './types.js';
import type { ContextualMemory, ParticipantMemory, ParticipantProfile, SessionMemoryUpdate, StoredMemoryEdge, StoredMemoryNode } from './longitudinal-types.js';
import { emptyProfile } from './longitudinal-types.js';

function mergeUnique(current: string[], incoming: string[]) {
  return [...new Set([...current, ...incoming].map((item) => item.trim()).filter(Boolean))];
}

function mergeProfile(current: ParticipantProfile, patch: ParticipantProfile): ParticipantProfile {
  return {
    role: patch.role ?? current.role,
    years_of_experience: patch.years_of_experience ?? current.years_of_experience,
    typical_day: mergeUnique(current.typical_day, patch.typical_day),
    responsibilities: mergeUnique(current.responsibilities, patch.responsibilities),
    collaborators: mergeUnique(current.collaborators, patch.collaborators),
  };
}

export async function loadParticipantMemory(env: RuntimeEnv, accountId: string): Promise<ParticipantMemory> {
  const profileRow = await env.RI_db.prepare('SELECT profile_json FROM participant_profiles WHERE account_id = ?').bind(accountId).first<{ profile_json: string }>();
  const countRow = await env.RI_db.prepare("SELECT COUNT(*) AS count FROM interview_sessions WHERE account_id = ? AND status = 'ended'").bind(accountId).first<{ count: number }>();
  const summaries = await env.RI_db.prepare('SELECT session_id, summary, ended_at FROM session_summaries WHERE account_id = ? ORDER BY ended_at DESC LIMIT 5').bind(accountId).all<ParticipantMemory['recent_summaries'][number]>();
  const nodeRows = await env.RI_db.prepare("SELECT id, kind, canonical_key AS key, text, status, confidence, first_session_id, last_session_id, evidence_json FROM memory_nodes WHERE account_id = ? AND status NOT IN ('superseded') ORDER BY last_seen_at DESC LIMIT 80").bind(accountId).all<Omit<StoredMemoryNode, 'evidence_message_ids'> & { evidence_json: string }>();
  const edgeRows = await env.RI_db.prepare('SELECT id, from_node_id, to_node_id, relation, explicitness, confidence, first_session_id, last_session_id, evidence_json FROM memory_edges WHERE account_id = ? ORDER BY last_seen_at DESC LIMIT 120').bind(accountId).all<Omit<StoredMemoryEdge, 'from_key' | 'to_key' | 'evidence_message_ids'> & { evidence_json: string }>();
  const nodes = nodeRows.results.map(({ evidence_json, ...node }) => ({ ...node, evidence_message_ids: JSON.parse(evidence_json) as string[] }));
  const byId = new Map(nodes.map((node) => [node.id, node.key]));
  const edges = edgeRows.results.map(({ evidence_json, ...edge }) => ({ ...edge, from_key: byId.get(edge.from_node_id) ?? '', to_key: byId.get(edge.to_node_id) ?? '', evidence_message_ids: JSON.parse(evidence_json) as string[] }));
  return {
    account_id: accountId,
    session_count: Number(countRow?.count ?? 0),
    profile: profileRow ? { ...emptyProfile(), ...JSON.parse(profileRow.profile_json) } : emptyProfile(),
    recent_summaries: summaries.results,
    nodes,
    edges,
  };
}

export function selectRelevantMemory(memory: ParticipantMemory, userInput: string, limit = 12): ContextualMemory {
  const terms = new Set(userInput.toLowerCase().split(/[\s、。,.!?！？]+/).filter((term) => term.length >= 2));
  const scored = memory.nodes.map((node) => ({
    node,
    score: [...terms].reduce((score, term) => score + (node.text.toLowerCase().includes(term) ? 1 : 0), 0) + node.confidence * 0.25,
  })).sort((a, b) => b.score - a.score).slice(0, limit).map(({ node }) => node);
  const ids = new Set(scored.map((node) => node.id));
  const summaries = memory.recent_summaries
    .map((summary, index) => ({
      summary,
      score: [...terms].reduce((score, term) => score + (summary.summary.toLowerCase().includes(term) ? 1 : 0), 0) + (index === 0 ? 0.5 : 0),
    }))
    .sort((a, b) => b.score - a.score)
    .slice(0, 6)
    .map(({ summary }) => summary);
  return {
    profile: memory.profile,
    summaries,
    nodes: scored,
    edges: memory.edges.filter((edge) => ids.has(edge.from_node_id) || ids.has(edge.to_node_id)).slice(0, limit),
  };
}

export async function saveSessionMemory(env: RuntimeEnv, accountId: string, sessionId: string, currentProfile: ParticipantProfile, update: SessionMemoryUpdate) {
  const merged = mergeProfile(currentProfile, update.profile_patch);
  await env.RI_db.prepare(`INSERT INTO participant_profiles (account_id, profile_json, updated_at) VALUES (?, ?, ?) ON CONFLICT(account_id) DO UPDATE SET profile_json = excluded.profile_json, updated_at = excluded.updated_at`).bind(accountId, JSON.stringify(merged), nowIso()).run();
  await env.RI_db.prepare(`INSERT INTO session_summaries (session_id, account_id, summary, ended_at) VALUES (?, ?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET summary = excluded.summary, ended_at = excluded.ended_at`).bind(sessionId, accountId, update.summary, nowIso()).run();

  const nodeIds = new Map<string, string>();
  for (const node of update.nodes) {
    const existing = await env.RI_db.prepare('SELECT id, evidence_json FROM memory_nodes WHERE account_id = ? AND canonical_key = ?').bind(accountId, `${node.kind}:${node.text}`).first<{ id: string; evidence_json: string }>();
    const id = existing?.id ?? randomId('mem');
    const evidence = mergeUnique(existing ? JSON.parse(existing.evidence_json) : [], node.evidence_message_ids);
    await env.RI_db.prepare(`INSERT INTO memory_nodes (id, account_id, canonical_key, kind, text, status, confidence, first_session_id, last_session_id, evidence_json, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(account_id, canonical_key) DO UPDATE SET status = excluded.status, confidence = MAX(memory_nodes.confidence, excluded.confidence), last_session_id = excluded.last_session_id, evidence_json = excluded.evidence_json, last_seen_at = excluded.last_seen_at`).bind(id, accountId, `${node.kind}:${node.text}`, node.kind, node.text, node.status, node.confidence, sessionId, sessionId, JSON.stringify(evidence), nowIso()).run();
    nodeIds.set(node.key, id);
  }
  for (const edge of update.edges) {
    const fromId = nodeIds.get(edge.from_key);
    const toId = nodeIds.get(edge.to_key);
    if (!fromId || !toId) continue;
    const key = `${fromId}:${edge.relation}:${toId}`;
    const existing = await env.RI_db.prepare('SELECT id, evidence_json FROM memory_edges WHERE account_id = ? AND canonical_key = ?').bind(accountId, key).first<{ id: string; evidence_json: string }>();
    const evidence = mergeUnique(existing ? JSON.parse(existing.evidence_json) : [], edge.evidence_message_ids);
    await env.RI_db.prepare(`INSERT INTO memory_edges (id, account_id, canonical_key, from_node_id, to_node_id, relation, explicitness, confidence, first_session_id, last_session_id, evidence_json, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(account_id, canonical_key) DO UPDATE SET explicitness = CASE WHEN memory_edges.explicitness = 'explicit' OR excluded.explicitness = 'explicit' THEN 'explicit' ELSE 'inferred' END, confidence = MAX(memory_edges.confidence, excluded.confidence), last_session_id = excluded.last_session_id, evidence_json = excluded.evidence_json, last_seen_at = excluded.last_seen_at`).bind(existing?.id ?? randomId('edge'), accountId, key, fromId, toId, edge.relation, edge.explicitness, edge.confidence, sessionId, sessionId, JSON.stringify(evidence), nowIso()).run();
  }
}
