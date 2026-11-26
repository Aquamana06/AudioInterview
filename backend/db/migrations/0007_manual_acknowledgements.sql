CREATE TABLE IF NOT EXISTS manual_acknowledgements (
  account_id TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
  acknowledged_at TEXT NOT NULL
);
