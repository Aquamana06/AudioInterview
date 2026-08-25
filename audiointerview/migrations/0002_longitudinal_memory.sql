CREATE TABLE IF NOT EXISTS participant_profiles (
  account_id TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
  profile_json TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS longitudinal_session_summaries (
  session_id TEXT PRIMARY KEY REFERENCES interview_sessions(id) ON DELETE CASCADE,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  summary TEXT NOT NULL,
  ended_at TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS memory_nodes (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  canonical_key TEXT NOT NULL,
  kind TEXT NOT NULL,
  text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'observed',
  confidence REAL NOT NULL DEFAULT 0.5,
  first_session_id TEXT NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
  last_session_id TEXT NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
  evidence_json TEXT NOT NULL DEFAULT '[]',
  last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(account_id, canonical_key)
);

CREATE TABLE IF NOT EXISTS memory_edges (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  canonical_key TEXT NOT NULL,
  from_node_id TEXT NOT NULL REFERENCES memory_nodes(id) ON DELETE CASCADE,
  to_node_id TEXT NOT NULL REFERENCES memory_nodes(id) ON DELETE CASCADE,
  relation TEXT NOT NULL,
  explicitness TEXT NOT NULL DEFAULT 'explicit',
  confidence REAL NOT NULL DEFAULT 0.5,
  first_session_id TEXT NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
  last_session_id TEXT NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
  evidence_json TEXT NOT NULL DEFAULT '[]',
  last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(account_id, canonical_key)
);

CREATE INDEX IF NOT EXISTS idx_longitudinal_summaries_account_ended ON longitudinal_session_summaries(account_id, ended_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_nodes_account_seen ON memory_nodes(account_id, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_edges_account_seen ON memory_edges(account_id, last_seen_at DESC);
