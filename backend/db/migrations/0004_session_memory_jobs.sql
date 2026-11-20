CREATE TABLE IF NOT EXISTS session_memory_jobs (
  session_id TEXT PRIMARY KEY REFERENCES interview_sessions(id) ON DELETE CASCADE,
  status TEXT NOT NULL CHECK (status IN ('pending', 'ready', 'fallback')),
  updated_at TEXT NOT NULL
);
