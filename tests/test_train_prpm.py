import json
from datetime import datetime, timedelta, timezone

import pytest

import train_prpm


NOW = datetime(2026, 7, 15, tzinfo=timezone.utc)


def paper(item_id, group, tag, score=4, source='Journal'):
    return {
        'item_id': item_id, 'title': f'{tag} clinical study', 'group': group,
        'tags': [tag], 'source_name': source, 'pub_date': '2026-Jul-01',
        'oa_pdf_url': None, 'isNew': False, 'score': score,
    }


def snapshot(events=None, actions=None):
    return {'events': events or [], 'actions': actions or []}


def event(item_id, action, days=0, ctx=None):
    return {
        'item_id': item_id, 'action': action, 'ctx': ctx,
        'created_at': (NOW - timedelta(days=days)).isoformat(),
    }


def by_id(papers):
    return {p['item_id']: p for p in papers}


def test_positive_event_raises_matching_feature_and_downvote_lowers_it():
    papers = [
        paper('a', 'implant', 'peri-implantitis', 4),
        paper('b', 'implant', 'peri-implantitis', 4),
        paper('c', 'ortho', 'aligner', 4),
    ]
    positive, _ = train_prpm.train_model(
        papers, snapshot([event('a', 'content_on')]), now=NOW)
    negative, _ = train_prpm.train_model(
        papers, snapshot([event('a', 'vote_down')]), now=NOW)

    assert by_id(positive)['b']['score'] > by_id(positive)['c']['score']
    assert by_id(negative)['b']['score'] < by_id(negative)['c']['score']


def test_90_day_half_life_makes_old_events_weaker():
    recent = train_prpm.decayed_weight(event('a', 'vote_up', days=0), now=NOW)
    old = train_prpm.decayed_weight(event('a', 'vote_up', days=90), now=NOW)

    assert recent == pytest.approx(1.0)
    assert old == pytest.approx(0.5)


def test_training_preserves_keyword_score_and_adds_contract_and_profile():
    papers = [paper('a', 'implant', 'peri-implantitis', 6), paper('b', 'ortho', 'aligner', 3)]
    ranked, profile = train_prpm.train_model(
        papers, snapshot([event('a', 'vote_up')]), now=NOW)

    first = by_id(ranked)['a']
    assert first['kw_score'] == 6
    assert isinstance(first['score'], (int, float))
    assert isinstance(first['rank'], int)
    assert isinstance(first['why'], list)
    assert {'label', 'weight'} <= first['why'][0].keys()
    assert profile['events']['total'] == 1
    assert profile['top_liked']
    assert 'item_id' not in json.dumps(profile)


def test_explanations_and_profile_merge_duplicate_human_labels():
    papers = [
        paper('a', 'implant', 'Journal', source='Journal'),
        paper('b', 'ortho', 'aligner', source='Other'),
    ]
    ranked, profile = train_prpm.train_model(
        papers, snapshot([event('a', 'vote_up')]), now=NOW)

    why_labels = [row['label'] for row in ranked[0]['why']]
    liked_labels = [row['feature'] for row in profile['top_liked']]
    assert len(why_labels) == len(set(why_labels))
    assert len(liked_labels) == len(set(liked_labels))
    assert max(abs(row['weight']) for row in ranked[0]['why']) <= 2
    assert max(abs(row['weight']) for row in profile['top_liked']) <= 2


def test_single_event_strength_order_survives_score_normalization():
    papers = [
        paper('a', 'implant', 'peri-implantitis', 4),
        paper('b', 'implant', 'peri-implantitis', 4),
        paper('c', 'ortho', 'aligner', 4),
    ]

    def score(action=None):
        data = snapshot([event('a', action)]) if action else snapshot()
        return by_id(train_prpm.train_model(papers, data, now=NOW)[0])['b']['score']

    baseline = score()
    negative_impacts = [baseline - score(name) for name in ('seen_only', 'vote_mid', 'vote_down')]
    positive_impacts = [score(name) - baseline for name in ('vote_up', 'content_on')]

    assert 0 < negative_impacts[0] < negative_impacts[1] < negative_impacts[2]
    assert 0 < positive_impacts[0] < positive_impacts[1]


def test_seen_only_survives_distribution_across_many_features():
    rich_tags = [f'tag{i}' for i in range(20)]
    papers = [
        {**paper('a', 'implant', 'base'), 'tags': rich_tags},
        {**paper('b', 'implant', 'base'), 'tags': rich_tags},
        paper('c', 'ortho', 'aligner'),
    ]
    baseline = by_id(train_prpm.train_model(papers, snapshot(), now=NOW)[0])['b']['score']
    with_seen = by_id(train_prpm.train_model(
        papers, snapshot([event('a', 'seen_only')]), now=NOW)[0])['b']['score']

    assert with_seen < baseline


def test_actions_snapshot_backfills_only_missing_event_signals():
    papers = [paper('a', 'implant', 'peri-implantitis'), paper('b', 'implant', 'peri-implantitis')]
    data = snapshot(
        [event('a', 'vote_up')],
        [{'item_id': 'a', 'vote': 'up', 'content': 1, 'deepread': 0, 'star': 0,
          'seen': 1, 'pdf_key': None, 'updated': NOW.isoformat()}],
    )
    events = train_prpm.training_events(data)

    assert [e['action'] for e in events].count('vote_up') == 1
    assert [e['action'] for e in events].count('content_on') == 1


def test_explore_is_deterministic_and_excludes_downvoted_paper():
    papers = [paper(f'p{i}', f'g{i % 4}', f'tag{i}', score=12-i) for i in range(10)]
    data = snapshot([event('p8', 'vote_down')])

    first, _ = train_prpm.train_model(papers, data, now=NOW)
    second, _ = train_prpm.train_model(papers, data, now=NOW)

    assert [(p['item_id'], p['rank'], p['explore']) for p in first] == [
        (p['item_id'], p['rank'], p['explore']) for p in second]
    assert any(p['explore'] for p in first)
    assert by_id(first)['p8']['explore'] is False


def test_explore_excludes_recently_seen_current_state_even_with_positive_action():
    papers = [paper(f'p{i}', 'same-group', 'same-tag', score=12-i) for i in range(10)]
    data = snapshot(actions=[{
        'item_id': 'p3', 'content': 1, 'deepread': 0, 'star': 0,
        'vote': None, 'seen': 1, 'pdf_key': None, 'updated': NOW.isoformat(),
    }])

    events = train_prpm.training_events(data)
    assert train_prpm.recent_seen_items(data, events, now=NOW) == {'p3'}

    ranked, _ = train_prpm.train_model(papers, data, now=NOW)
    unseen = json.loads(json.dumps(data))
    unseen['actions'][0]['seen'] = 0
    baseline, _ = train_prpm.train_model(papers, unseen, now=NOW)

    assert by_id(baseline)['p3']['explore'] is True
    assert by_id(ranked)['p3']['explore'] is False


def test_explore_excludes_current_downvote_even_when_content_signal_offsets_it():
    papers = [paper(f'p{i}', 'same-group', 'same-tag', score=12-i) for i in range(10)]
    data = snapshot(actions=[{
        'item_id': 'p3', 'content': 1, 'deepread': 0, 'star': 0,
        'vote': 'down', 'seen': 0, 'pdf_key': None, 'updated': NOW.isoformat(),
    }])

    ranked, _ = train_prpm.train_model(papers, data, now=NOW)

    assert by_id(ranked)['p3']['explore'] is False


def test_pdf_upload_counts_as_recently_seen_for_explore():
    data = snapshot([event('p3', 'pdf_upload')])

    assert train_prpm.recent_seen_items(
        data, train_prpm.training_events(data), now=NOW) == {'p3'}


def test_many_historical_signals_do_not_saturate_the_entire_feed():
    papers = [
        paper(f'p{i}', f'g{i % 4}', f'tag{i}', score=4, source=f'J{i % 5}')
        for i in range(20)
    ]
    actions = [{
        'item_id': f'p{i}', 'content': 1, 'deepread': 0, 'star': 0,
        'vote': None, 'seen': 1, 'pdf_key': None, 'updated': NOW.isoformat(),
    } for i in range(20)]

    ranked, _ = train_prpm.train_model(papers, snapshot(actions=actions), now=NOW)

    assert sum(row['score'] == 12 for row in ranked) < len(ranked)


def test_invalid_input_does_not_overwrite_serving_files(tmp_path):
    papers_path = tmp_path / 'papers.json'
    events_path = tmp_path / 'events.json'
    profile_path = tmp_path / 'profile.json'
    papers_path.write_text('{"last":"good"}', encoding='utf-8')
    events_path.write_text('{}', encoding='utf-8')
    profile_path.write_text('{"profile":"good"}', encoding='utf-8')

    with pytest.raises(ValueError):
        train_prpm.run_training(papers_path, events_path, profile_path, now=NOW)

    assert papers_path.read_text(encoding='utf-8') == '{"last":"good"}'
    assert profile_path.read_text(encoding='utf-8') == '{"profile":"good"}'
