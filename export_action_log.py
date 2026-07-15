#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Read-only D1 export for lightweight PRPM training."""
import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
D1_NAME = 'paper-radar-db'
DEFAULT_OUT = SCRIPT_DIR / '_prpm_cache' / 'events.json'

EVENT_SQL = (
    'SELECT id, event_id, item_id, action, value, ctx_json, created_at '
    'FROM action_log ORDER BY id'
)
ACTION_SQL = (
    'SELECT item_id, content, deepread, star, vote, seen, pdf_key, updated '
    'FROM actions ORDER BY item_id'
)


def query_d1(sql, *, runner=subprocess.run):
    proc = runner(
        ['npx', '--yes', 'wrangler', 'd1', 'execute', D1_NAME, '--remote',
         '--json', '--command', sql],
        cwd=SCRIPT_DIR, env=dict(os.environ), capture_output=True, text=True,
        encoding='utf-8', shell=(os.name == 'nt'))
    if proc.returncode != 0:
        raise RuntimeError('D1 action export failed')
    try:
        data = json.loads(proc.stdout[proc.stdout.index('['):])
        return data[0]['results']
    except (ValueError, KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError('D1 action export returned invalid JSON') from exc


def export_snapshot(destination=DEFAULT_OUT, *, runner=subprocess.run):
    destination = Path(destination)
    events = query_d1(EVENT_SQL, runner=runner)
    actions = query_d1(ACTION_SQL, runner=runner)
    clean_events = []
    for event in events:
        ctx = None
        try:
            parsed = json.loads(event.get('ctx_json') or 'null')
            if isinstance(parsed, dict):
                ctx = parsed
        except json.JSONDecodeError:
            pass
        clean_events.append({
            'id': event.get('id'),
            'event_id': event.get('event_id'),
            'item_id': event.get('item_id'),
            'action': event.get('action'),
            'value': event.get('value'),
            'ctx': ctx,
            'created_at': event.get('created_at'),
        })
    snapshot = {
        'exported_at': datetime.now(timezone.utc).isoformat(),
        'events': clean_events,
        'actions': actions,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + '.tmp')
    try:
        tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(destination)
    finally:
        tmp.unlink(missing_ok=True)
    return snapshot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default=str(DEFAULT_OUT))
    args = parser.parse_args()
    snapshot = export_snapshot(args.out)
    print(f"PRPM export: {len(snapshot['events'])} events, {len(snapshot['actions'])} actions")


if __name__ == '__main__':
    main()
