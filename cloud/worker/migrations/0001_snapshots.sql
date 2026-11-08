-- Latest snapshot files of the Python engine (the same JSON the phone app reads), one row per file.
-- The PC uploads a file only when its SHA-256 changed, so a day costs a few hundred writes (D1 free: 100 000).
CREATE TABLE IF NOT EXISTS snapshots (
  name TEXT PRIMARY KEY,
  body TEXT NOT NULL,
  sha TEXT NOT NULL,
  computed_at TEXT,
  synced_at TEXT NOT NULL
);

-- One row per finished sync from the PC (kept 30 days): when the PC last delivered results.
CREATE TABLE IF NOT EXISTS sync_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  uploaded INTEGER NOT NULL DEFAULT 0,
  unchanged INTEGER NOT NULL DEFAULT 0,
  bytes INTEGER NOT NULL DEFAULT 0,
  problems INTEGER NOT NULL DEFAULT 0,
  computed_at TEXT
);
CREATE INDEX IF NOT EXISTS sync_log_at ON sync_log (at);
