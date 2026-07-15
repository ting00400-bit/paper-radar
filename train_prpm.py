#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Deterministic, standard-library lightweight PRPM trainer."""
import argparse
import copy
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

EVENT_WEIGHTS = {
    'content_on': 2.0,
    'deepread_on': 2.0,
    'pdf_upload': 2.0,
    'vote_up': 1.0,
    'vote_mid': -0.3,
    'vote_down': -1.5,
    'seen_only': -0.1,
}
STOPWORDS = {
    'about', 'after', 'among', 'analysis', 'association', 'clinical', 'dental',
    'effects', 'from', 'into', 'patients', 'study', 'their', 'this', 'using',
    'with', 'without', 'between', 'randomized', 'review',
}


def parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone(timezone.utc)
    except ValueError:
        return None


def decayed_weight(event, *, now=None):
    weight = EVENT_WEIGHTS.get(event.get('action'), 0.0)
    now = now or datetime.now(timezone.utc)
    created = parse_time(event.get('created_at')) or now
    age_days = max(0.0, (now - created).total_seconds() / 86400)
    return weight * 0.5 ** (age_days / 90.0)


def paper_features(paper):
    out = set()
    if paper.get('group'):
        out.add('group:' + str(paper['group']).strip().lower())
    for tag in paper.get('tags') or []:
        tag = str(tag).strip().lower()
        if tag and not tag.startswith(('author:', 'penalty:')):
            out.add('tag:' + tag)
    if paper.get('source_name'):
        out.add('journal:' + str(paper['source_name']).strip().lower())
    year = re.search(r'\b(19|20)\d{2}\b', str(paper.get('pub_date') or ''))
    if year:
        out.add('year:' + year.group(0)[:3] + '0s')
    out.add('access:' + ('oa' if paper.get('oa_pdf_url') else 'non-oa'))
    if paper.get('isNew'):
        out.add('badge:new')
    tokens = re.findall(r"[a-z][a-z'-]{3,}", str(paper.get('title') or '').lower())
    for token in sorted(set(tokens) - STOPWORDS)[:8]:
        out.add('title:' + token)
    return sorted(out)


def training_events(snapshot):
    events = [dict(event) for event in snapshot.get('events') or []
              if event.get('action') in EVENT_WEIGHTS and event.get('item_id')]
    present = {(event['item_id'], event['action']) for event in events}
    for action in snapshot.get('actions') or []:
        item_id = action.get('item_id')
        if not item_id:
            continue
        created = action.get('updated')
        candidates = []
        if action.get('content') or action.get('star'):
            candidates.append('content_on')
        if action.get('deepread'):
            candidates.append('deepread_on')
        vote = {'up': 'vote_up', 'neutral': 'vote_mid', 'down': 'vote_down'}.get(action.get('vote'))
        if vote:
            candidates.append(vote)
        if action.get('pdf_key'):
            candidates.append('pdf_upload')
        if action.get('seen') and not candidates:
            candidates.append('seen_only')
        for name in candidates:
            if (item_id, name) not in present:
                events.append({
                    'item_id': item_id, 'action': name, 'created_at': created,
                    'ctx': {'fallback': True},
                })
                present.add((item_id, name))
    return events


def recent_seen_items(snapshot, events, *, now=None):
    now = now or datetime.now(timezone.utc)
    seen = set()
    for event in events:
        created = parse_time(event.get('created_at'))
        if event.get('action') in {'seen_only', 'pdf_upload'} and created and (now - created).days <= 30:
            seen.add(event.get('item_id'))
    for action in snapshot.get('actions') or []:
        updated = parse_time(action.get('updated'))
        if action.get('seen') and updated and (now - updated).days <= 30:
            seen.add(action.get('item_id'))
    return {item_id for item_id in seen if item_id}


def downvoted_items(snapshot, events, *, now=None):
    now = now or datetime.now(timezone.utc)
    current_down = {
        action.get('item_id') for action in snapshot.get('actions') or []
        if action.get('item_id') and action.get('vote') == 'down'
    }
    vote_signals = defaultdict(float)
    for event in events:
        if event.get('action') in {'vote_up', 'vote_mid', 'vote_down'}:
            vote_signals[event.get('item_id')] += decayed_weight(event, now=now)
    return current_down | {
        item_id for item_id, signal in vote_signals.items()
        if item_id and signal <= -0.5
    }


def feature_label(feature):
    return feature.split(':', 1)[-1]


def _merge_labels(rows):
    merged = defaultdict(float)
    for feature, value in rows:
        merged[feature_label(feature)] += value
    return list(merged.items())


def _cap_labeled(rows, limit=2.0):
    rows = list(rows)
    largest = max((abs(value) for _, value in rows), default=0.0)
    scale = max(1.0, largest / limit)
    return [(label, value / scale) for label, value in rows]


def _profile_features(weights):
    allowed = _cap_labeled(_merge_labels(
        (feature, value) for feature, value in weights.items()
        if feature.startswith(('tag:', 'group:', 'journal:'))))
    liked = sorted((x for x in allowed if x[1] > 0), key=lambda x: (-x[1], x[0]))[:10]
    avoided = sorted((x for x in allowed if x[1] < 0), key=lambda x: (x[1], x[0]))[:10]
    encode = lambda rows: [
        {'feature': label, 'weight': round(value, 3)} for label, value in rows]
    return encode(liked), encode(avoided)


def train_model(papers, snapshot, *, now=None):
    now = now or datetime.now(timezone.utc)
    items = copy.deepcopy(papers)
    by_id = {paper.get('item_id'): paper for paper in items if paper.get('item_id')}
    features = {item_id: paper_features(paper) for item_id, paper in by_id.items()}
    feature_frequency = Counter(feature for values in features.values() for feature in values)
    discriminative = {
        feature for feature, count in feature_frequency.items()
        if count / max(1, len(features)) <= 0.8
    }
    events = training_events(snapshot)
    feature_weights = defaultdict(float)
    item_signals = defaultdict(float)
    recent_seen = recent_seen_items(snapshot, events, now=now)
    downvoted = downvoted_items(snapshot, events, now=now)
    for event in events:
        item_id = event.get('item_id')
        if item_id not in features:
            continue
        signal = decayed_weight(event, now=now)
        item_signals[item_id] += signal
        learned = [feature for feature in features[item_id] if feature in discriminative]
        feature_count = max(1, len(learned))
        for feature in learned:
            feature_weights[feature] += signal / feature_count

    contributions_by_id = {}
    preferences = {}
    for paper in items:
        item_id = paper.get('item_id')
        kw_score = paper.get('kw_score', paper.get('score', 0))
        kw_score = float(kw_score) if isinstance(kw_score, (int, float)) else 0.0
        paper['kw_score'] = kw_score
        contributions = [(feature, feature_weights[feature]) for feature in features.get(item_id, [])
                         if feature_weights[feature]]
        contributions_by_id[item_id] = contributions
        preferences[item_id] = sum(value for _, value in contributions)

    preference_scale = max(
        2.5, max((abs(value) for value in preferences.values()), default=0.0))
    for paper in items:
        item_id = paper.get('item_id')
        boost = preferences.get(item_id, 0.0) / preference_scale * 4.0
        paper['score'] = round(max(0.0, min(12.0, paper['kw_score'] * 0.55 + boost)), 1)
        visible = [
            row for row in contributions_by_id.get(item_id, []) if abs(row[1]) >= 0.01
        ]
        strongest = sorted(
            _cap_labeled(_merge_labels(visible)),
            key=lambda row: (-abs(row[1]), row[0]))[:3]
        paper['why'] = [
            {'label': label, 'weight': round(value, 2)} for label, value in strongest]
        paper['explore'] = False

    ranked = sorted(items, key=lambda p: (-p['score'], -p['kw_score'], str(p.get('item_id') or '')))
    if len(ranked) >= 6:
        top_groups = Counter(str(p.get('group') or '') for p in ranked[:5])
        median_kw = sorted(p['kw_score'] for p in ranked)[len(ranked) // 2]
        candidates = [p for p in ranked[3:] if item_signals[p.get('item_id')] > -0.5
                      and p.get('item_id') not in downvoted
                      and p.get('item_id') not in recent_seen and p['kw_score'] >= median_kw]
        candidates.sort(key=lambda p: (
            top_groups[str(p.get('group') or '')], -p['kw_score'], str(p.get('item_id') or '')))
        explore_count = min(3, max(1, len(ranked) // 20))
        chosen = candidates[:explore_count]
        for index, paper in enumerate(chosen):
            ranked.remove(paper)
            ranked.insert(min(5 + index * 7, len(ranked)), paper)
            paper['explore'] = True
            paper['why'].append({'label': '探索：不同主題但仍符合牙科範圍', 'weight': 0.0})
    for rank, paper in enumerate(ranked, 1):
        paper['rank'] = rank

    positive = sum(1 for event in events if EVENT_WEIGHTS[event['action']] > 0)
    negative = sum(1 for event in events if EVENT_WEIGHTS[event['action']] < 0)
    liked, avoided = _profile_features(feature_weights)
    profile = {
        'updated_at': now.isoformat(),
        'events': {'total': len(events), 'positive': positive, 'negative': negative},
        'top_liked': liked,
        'top_avoided': avoided,
        'explore': {
            'shown': sum(1 for paper in ranked if paper['explore']),
            'engaged': sum(1 for event in events
                           if (event.get('ctx') or {}).get('explore')
                           and EVENT_WEIGHTS[event['action']] > 0),
        },
    }
    return ranked, profile


def _atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def run_training(papers_path, events_path, profile_path, *, now=None):
    papers_path, events_path, profile_path = map(Path, (papers_path, events_path, profile_path))
    papers_doc = json.loads(papers_path.read_text(encoding='utf-8'))
    snapshot = json.loads(events_path.read_text(encoding='utf-8'))
    if not isinstance(papers_doc, dict) or not isinstance(papers_doc.get('papers'), list):
        raise ValueError('papers.json must contain a papers list')
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('events'), list):
        raise ValueError('events.json must contain an events list')
    ranked, profile = train_model(papers_doc['papers'], snapshot, now=now)
    output = dict(papers_doc)
    output['papers'] = ranked
    _atomic_json(profile_path, profile)
    _atomic_json(papers_path, output)
    return output, profile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--papers', default='site/papers.json')
    parser.add_argument('--events', default='_prpm_cache/events.json')
    parser.add_argument('--profile', default='site/profile.json')
    args = parser.parse_args()
    output, profile = run_training(args.papers, args.events, args.profile)
    print(f"PRPM trained: {len(output['papers'])} papers, {profile['events']['total']} events")


if __name__ == '__main__':
    main()
