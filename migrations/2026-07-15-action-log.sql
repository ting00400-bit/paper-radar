-- Run against production only after explicit confirmation from Ting.
CREATE TABLE IF NOT EXISTS action_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT,
  item_id TEXT NOT NULL,
  action TEXT NOT NULL,
  value TEXT,
  ctx_json TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_action_log_created ON action_log(created_at);
CREATE INDEX IF NOT EXISTS idx_action_log_item ON action_log(item_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_action_log_event ON action_log(event_id);
