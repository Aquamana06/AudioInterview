CREATE TABLE IF NOT EXISTS interview_archives (
  session_id TEXT PRIMARY KEY REFERENCES interview_sessions(id) ON DELETE CASCADE,
  user_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'ready')),
  exported_at TEXT,
  last_error TEXT
);

CREATE TABLE IF NOT EXISTS interview_recordings (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
  message_id TEXT UNIQUE REFERENCES messages(id) ON DELETE SET NULL,
  audio_file TEXT NOT NULL,
  content_type TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_recordings_session ON interview_recordings(session_id);

-- A separate table keeps this migration repeatable without ALTER TABLE.
CREATE TRIGGER IF NOT EXISTS archive_session_created
AFTER INSERT ON interview_sessions
BEGIN
  INSERT INTO interview_archives (session_id, user_name)
  SELECT NEW.id, display_name FROM accounts WHERE id=NEW.account_id;
END;

CREATE TRIGGER IF NOT EXISTS archive_session_ended
AFTER UPDATE OF status ON interview_sessions
WHEN NEW.status='ended'
BEGIN
  UPDATE interview_archives SET status='pending', last_error=NULL WHERE session_id=NEW.id;
END;

-- Older sessions have no historical display name; use the current one once.
INSERT OR IGNORE INTO interview_archives (session_id, user_name)
SELECT s.id, a.display_name FROM interview_sessions s JOIN accounts a ON a.id=s.account_id;
