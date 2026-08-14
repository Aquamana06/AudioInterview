CREATE TABLE IF NOT EXISTS worker_profiles (
  worker_id TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
  role TEXT,
  department TEXT,
  total_experience_years REAL,
  current_role_experience_years REAL,
  assigned_processes_json TEXT NOT NULL DEFAULT '[]',
  assigned_equipment_json TEXT NOT NULL DEFAULT '[]',
  responsibilities_json TEXT NOT NULL DEFAULT '[]',
  qualifications_json TEXT NOT NULL DEFAULT '[]',
  expertise_json TEXT NOT NULL DEFAULT '[]',
  education_experience_json TEXT NOT NULL DEFAULT '[]',
  evidence_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS long_term_memories (
  id TEXT PRIMARY KEY,
  worker_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  type TEXT NOT NULL CHECK (type IN (
    'work_knowledge', 'tacit_knowledge', 'decision_criterion',
    'work_philosophy', 'value', 'trouble_experience', 'unexplored_theme'
  )),
  content TEXT NOT NULL,
  source_session_id TEXT REFERENCES interview_sessions(id) ON DELETE SET NULL,
  evidence_message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
  confidence REAL NOT NULL DEFAULT 1.0,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'resolved', 'superseded')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS session_summaries (
  session_id TEXT PRIMARY KEY REFERENCES interview_sessions(id) ON DELETE CASCADE,
  worker_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  summary TEXT NOT NULL,
  topics_json TEXT NOT NULL DEFAULT '[]',
  unresolved_topics_json TEXT NOT NULL DEFAULT '[]',
  final_state_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE interview_sessions ADD COLUMN phase TEXT NOT NULL DEFAULT 'interview';
ALTER TABLE interview_sessions ADD COLUMN profile_turn_count INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_long_term_memories_worker ON long_term_memories(worker_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_session_summaries_worker ON session_summaries(worker_id, created_at);
