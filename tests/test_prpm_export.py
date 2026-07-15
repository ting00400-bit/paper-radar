import json
from types import SimpleNamespace

import pytest

import export_action_log


def wrangler_result(rows):
    return json.dumps([{'results': rows, 'success': True}])


def test_export_snapshot_writes_events_and_actions_atomically(tmp_path):
    destination = tmp_path / 'events.json'
    outputs = iter([
        wrangler_result([{
            'id': 1, 'event_id': 'evt-one', 'item_id': 'doi:one',
            'action': 'vote_up', 'value': None,
            'ctx_json': '{"rank":2}', 'created_at': '2026-07-15T00:00:00Z',
        }]),
        wrangler_result([{
            'item_id': 'doi:one', 'content': 1, 'deepread': 0, 'star': 0,
            'vote': 'up', 'seen': 1, 'pdf_key': None,
            'updated': '2026-07-15T00:00:00Z',
        }]),
    ])

    def runner(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout=next(outputs), stderr='')

    snapshot = export_action_log.export_snapshot(destination, runner=runner)

    assert snapshot['events'][0]['action'] == 'vote_up'
    assert snapshot['events'][0]['event_id'] == 'evt-one'
    assert snapshot['events'][0]['ctx'] == {'rank': 2}
    assert snapshot['actions'][0]['content'] == 1
    assert json.loads(destination.read_text(encoding='utf-8')) == snapshot
    assert not destination.with_suffix('.json.tmp').exists()


def test_failed_export_preserves_last_good_cache(tmp_path):
    destination = tmp_path / 'events.json'
    destination.write_text('{"last":"good"}', encoding='utf-8')

    def runner(*_args, **_kwargs):
        return SimpleNamespace(returncode=1, stdout='', stderr='token detail')

    with pytest.raises(RuntimeError, match='D1 action export failed'):
        export_action_log.export_snapshot(destination, runner=runner)

    assert destination.read_text(encoding='utf-8') == '{"last":"good"}'
