CREATE TABLE IF NOT EXISTS participant_domain_knowledge (
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  canonical_key TEXT NOT NULL,
  term TEXT NOT NULL,
  meaning TEXT NOT NULL,
  scope TEXT NOT NULL DEFAULT '',
  source_session_id TEXT NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
  evidence_json TEXT NOT NULL DEFAULT '[]',
  updated_at TEXT NOT NULL,
  PRIMARY KEY (account_id, canonical_key)
);
