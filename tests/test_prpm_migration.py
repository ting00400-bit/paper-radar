import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_action_log_migration_is_idempotent_for_retried_event():
    db = sqlite3.connect(':memory:')
    migration = (ROOT / 'migrations' / '2026-07-15-action-log.sql').read_text(encoding='utf-8')
    db.executescript(migration)
    sql = (
        'INSERT OR IGNORE INTO action_log '
        '(event_id, item_id, action, value, ctx_json, created_at) '
        'VALUES (?, ?, ?, NULL, NULL, ?)'
    )

    db.execute(sql, ('evt-one', 'doi:one', 'content_on', '2026-07-15T00:00:00Z'))
    db.execute(sql, ('evt-one', 'doi:one', 'content_on', '2026-07-15T00:00:01Z'))

    assert db.execute('SELECT COUNT(*) FROM action_log').fetchone()[0] == 1
