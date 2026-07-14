# -*- coding: utf-8 -*-
"""paper_sync 純函數測試。跑法：python -X utf8 -m pytest tests/ -v"""
import json
import sys, os
import urllib.request
from pathlib import Path
from subprocess import CompletedProcess
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paper_sync
from paper_sync import sanitize_filename, short_title, first_author_surname, note_filename, build_worklist, valid_item_id

def test_sanitize_removes_windows_illegal_chars():
    assert sanitize_filename('a/b\\c:d*e?f"g<h>i|j') == 'abcdefghij'

def test_sanitize_collapses_spaces_and_strips_edges():
    assert sanitize_filename('  a   b .') == 'a b'

def test_short_title_cuts_at_word_boundary():
    t = 'Adjunctive Electrolytic Implant Surface Decontamination in the Reconstructive Surgical Treatment of Peri-Implantitis'
    out = short_title(t, limit=60)
    assert len(out) <= 60
    assert not out.endswith((' ', '-', ',', ':', ';', '.'))
    assert out.startswith('Adjunctive Electrolytic')

def test_short_title_short_passthrough():
    assert short_title('Short title.') == 'Short title'

def test_first_author_surname():
    assert first_author_surname('Regidor E, Ortiz-Vigón A, Berglundh J') == 'Regidor'
    assert first_author_surname('Wang T') == 'Wang'
    assert first_author_surname('') == 'Unknown'

def test_note_filename():
    meta = {'pub_date': '2026-06-28', 'authors': 'Regidor E, Ortiz-Vigón A',
            'title': 'Adjunctive Electrolytic Implant Surface Decontamination in the Reconstructive Surgical Treatment'}
    fn = note_filename(meta)
    assert fn.startswith('2026-06-28 Regidor - Adjunctive')
    assert fn.endswith('.md')
    assert '/' not in fn and ':' not in fn

def test_note_filename_no_date_falls_back():
    meta = {'pub_date': '', 'first_seen': '2026-07-01', 'authors': 'Wang T', 'title': 'X'}
    assert note_filename(meta).startswith('2026-07-01 Wang - X')

def test_note_filename_missing_keys_does_not_raise():
    assert note_filename({}) == 'Unknown -.md'
    assert note_filename({'title': 'Some Paper'}) == 'Unknown - Some Paper.md'

PAPERS = {'papers': [
    {'item_id': 'doi:10.1/abc', 'title': 'Paper A', 'authors': 'Regidor E, Ortiz-Vigón A',
     'source_name': 'J Clin Periodontol', 'pub_date': '2026-06-28', 'doi': '10.1/abc',
     'abstract': 'Abs A', 'oa_pdf_url': 'https://x/a.pdf', 'tags': ['peri-implantitis']},
    {'item_id': 'doi:10.2/def', 'title': 'Paper B', 'authors': 'Wang T',
     'source_name': 'COIR', 'pub_date': '', 'first_seen': '2026-07-01', 'doi': '10.2/def',
     'abstract': 'Abs B', 'oa_pdf_url': None, 'tags': []},
]}

def rows(**over):
    base = {'item_id': 'doi:10.1/abc', 'doi': '10.1/abc', 'title': 'Paper A',
            'star': 1, 'deepread': 0, 'content': 1, 'pdf_key': None}
    base.update(over)
    return [base]

def test_build_worklist_merges_metadata():
    wl = build_worklist(rows(), PAPERS)
    assert wl[0]['journal'] == 'J Clin Periodontol'
    assert wl[0]['abstract'] == 'Abs A'
    assert wl[0]['content'] is True and wl[0]['deepread'] is False
    assert wl[0]['note_filename'].startswith('2026-06-28 Regidor - Paper A')

def test_build_worklist_legacy_star_only_maps_to_content():
    wl = build_worklist(rows(star=1, content=0, deepread=0), PAPERS)
    assert wl[0]['content'] is True
    assert wl[0]['deepread'] is False

def test_build_worklist_deepread_only_stays_deepread_only():
    wl = build_worklist(rows(star=0, content=0, deepread=1), PAPERS)
    assert wl[0]['content'] is False
    assert wl[0]['deepread'] is True

def test_query_pending_selects_typed_and_legacy_requests(monkeypatch):
    captured = {}
    def fake_wrangler(args):
        captured['sql'] = args[-1]
        return json.dumps([{'results': []}])
    monkeypatch.setattr(paper_sync, '_wrangler', fake_wrangler)
    assert paper_sync.query_pending() == []
    assert '(deepread=1 OR content=1 OR star=1)' in captured['sql']
    assert 'synced=0' in captured['sql']

def test_build_worklist_respects_explicit_content_only():
    wl = build_worklist(rows(content=1, deepread=0), PAPERS)
    assert wl[0]['content'] is True and wl[0]['deepread'] is False   # 明確只勾內容 → 不強加品質

def test_build_worklist_unknown_item_uses_d1_title():
    wl = build_worklist(rows(item_id='manual:123', doi='', title='Uploaded paper'), PAPERS)
    assert wl[0]['title'] == 'Uploaded paper'
    assert wl[0]['journal'] == ''
    assert wl[0]['note_filename'].endswith('Unknown - Uploaded paper.md') is True  # 日期可空，仍組得出檔名（無日期/作者則用 Unknown）
    assert wl[0]['note_filename'].endswith('.md')

def test_valid_item_id_allowlist():
    assert valid_item_id('doi:10.1155/ijod/6556335')
    assert valid_item_id('h:a1b2c3')
    assert valid_item_id('manual:1751700000')
    assert not valid_item_id("x'); DROP TABLE actions;--")
    assert not valid_item_id('')
    assert not valid_item_id('a' * 65)

def test_build_worklist_pdf_source_priority():
    assert build_worklist(rows(pdf_key='pdf/x.pdf'), PAPERS)[0]['pdf_source'] == 'r2'  # 這篇 meta 也有 oa_pdf_url → 驗證 r2 優先
    assert build_worklist(rows(), PAPERS)[0]['pdf_source'] == 'oa'          # 有 oa_pdf_url
    wl = build_worklist(rows(item_id='doi:10.2/def', title='Paper B'), PAPERS)
    assert wl[0]['pdf_source'] == 'missing'                                  # 都沒有


def test_is_valid_pdf_rejects_html(tmp_path):
    p = tmp_path / 'fake.pdf'
    p.write_bytes(b'<html>' + b'x' * 3000)
    assert paper_sync.is_valid_pdf(p) is False


def test_run_paper_fetch_installs_unique_valid_result(tmp_path):
    dest = tmp_path / 'paper.pdf'

    def fake_runner(cmd, **kwargs):
        assert cmd[1:3] == ['-X', 'utf8']
        part = Path(cmd[-1])
        assert part != dest
        assert part.suffix == '.part'
        part.write_bytes(b'%PDF' + b'x' * 3000)
        env = {'schema': 1, 'doi': '10.1234/test', 'ok': True, 'route': 'unpaywall',
               'tried': ['unpaywall'], 'bytes': part.stat().st_size,
               'sha256': 'fixture', 'path': str(part), 'elapsed_s': 0.1}
        return CompletedProcess(cmd, 0, stdout=json.dumps(env), stderr='')

    result = paper_sync.run_paper_fetch('10.1234/test', dest, runner=fake_runner)
    assert result['pdf'] == str(dest)
    assert result['fetch_route'] == 'unpaywall'
    assert paper_sync.is_valid_pdf(dest)


def test_run_paper_fetch_uses_unique_part_for_each_attempt(tmp_path):
    dest = tmp_path / 'paper.pdf'
    parts = []

    def fake_runner(cmd, **kwargs):
        part = Path(cmd[-1])
        parts.append(part)
        part.write_bytes(b'%PDF' + b'x' * 3000)
        return CompletedProcess(
            cmd, 0, stdout='{"ok": true, "route": "unpaywall"}', stderr='')

    assert paper_sync.run_paper_fetch('10.1234/test', dest, runner=fake_runner)['pdf']
    assert paper_sync.run_paper_fetch('10.1234/test', dest, runner=fake_runner)['pdf']
    assert len(set(parts)) == 2
    assert all(part != dest and part.suffix == '.part' for part in parts)
    assert not list(tmp_path.glob('*.part'))


@pytest.mark.parametrize('stdout', ['null', '[]'])
def test_run_paper_fetch_rejects_non_mapping_json_envelope(tmp_path, stdout):
    dest = tmp_path / 'paper.pdf'

    def fake_runner(cmd, **kwargs):
        return CompletedProcess(cmd, 0, stdout=stdout, stderr='')

    result = paper_sync.run_paper_fetch('10.1234/test', dest, runner=fake_runner)
    assert set(result) == {'pdf', 'pdf_source', 'fetch_route', 'fetch_error', 'retryable'}
    assert result['pdf'] is None
    assert 'JSON envelope' in result['fetch_error']


def test_run_paper_fetch_cleanup_permission_error_does_not_mask_success(
        tmp_path, monkeypatch):
    dest = tmp_path / 'paper.pdf'
    original_unlink = Path.unlink

    def locked_part_cleanup(path, *args, **kwargs):
        if path.suffix == '.part':
            raise PermissionError('part is locked')
        return original_unlink(path, *args, **kwargs)

    def fake_runner(cmd, **kwargs):
        part = Path(cmd[-1])
        part.write_bytes(b'%PDF' + b'x' * 3000)
        return CompletedProcess(
            cmd, 0, stdout='{"ok": true, "route": "unpaywall"}', stderr='')

    monkeypatch.setattr(Path, 'unlink', locked_part_cleanup)
    result = paper_sync.run_paper_fetch('10.1234/test', dest, runner=fake_runner)
    assert result['pdf'] == str(dest)
    assert paper_sync.is_valid_pdf(dest)


def test_run_paper_fetch_replace_failure_preserves_destination(tmp_path, monkeypatch):
    dest = tmp_path / 'paper.pdf'
    old = b'<html>old stale destination'
    dest.write_bytes(old)
    original_replace = Path.replace

    def failed_replace(path, target):
        if path.suffix == '.part':
            raise PermissionError('destination is locked')
        return original_replace(path, target)

    def fake_runner(cmd, **kwargs):
        part = Path(cmd[-1])
        part.write_bytes(b'%PDF' + b'x' * 3000)
        return CompletedProcess(
            cmd, 0, stdout='{"ok": true, "route": "unpaywall"}', stderr='')

    monkeypatch.setattr(Path, 'replace', failed_replace)
    result = paper_sync.run_paper_fetch('10.1234/test', dest, runner=fake_runner)
    assert set(result) == {'pdf', 'pdf_source', 'fetch_route', 'fetch_error', 'retryable'}
    assert result['pdf'] is None
    assert result['retryable'] is True
    assert dest.read_bytes() == old
    assert not list(tmp_path.glob('*.part'))


def test_run_paper_fetch_does_not_accept_stale_destination(tmp_path):
    dest = tmp_path / 'paper.pdf'
    dest.write_bytes(b'%PDF' + b'old' * 1000)

    def failed_runner(cmd, **kwargs):
        return CompletedProcess(cmd, 2, stdout='{"ok": false}', stderr='no route')

    result = paper_sync.run_paper_fetch('10.1234/test', dest, runner=failed_runner)
    assert result['pdf'] is None
    assert result['fetch_error']


def test_run_paper_fetch_route_exhausted_does_not_dump_multiline_stderr(tmp_path):
    dest = tmp_path / 'paper.pdf'

    def failed_runner(cmd, **kwargs):
        return CompletedProcess(
            cmd, 2, stdout='{"ok": false}', stderr=('diagnostic line\n' * 1000))

    result = paper_sync.run_paper_fetch('10.1234/test', dest, runner=failed_runner)
    assert result['fetch_error'] == 'no route'
    assert result['retryable'] is False


def test_run_paper_fetch_bounds_unexpected_multiline_stderr(tmp_path):
    dest = tmp_path / 'paper.pdf'

    def failed_runner(cmd, **kwargs):
        return CompletedProcess(
            cmd, 3, stdout='{"ok": false}', stderr=('diagnostic line\n' * 1000))

    result = paper_sync.run_paper_fetch('10.1234/test', dest, runner=failed_runner)
    assert '\n' not in result['fetch_error']
    assert len(result['fetch_error']) <= 300
    assert result['retryable'] is True


def test_run_paper_fetch_rejects_html_even_when_json_says_ok(tmp_path):
    dest = tmp_path / 'paper.pdf'

    def fake_runner(cmd, **kwargs):
        part = Path(cmd[-1])
        part.write_bytes(b'<html>' + b'x' * 3000)
        return CompletedProcess(cmd, 0, stdout='{"ok": true, "route": "unpaywall"}', stderr='')

    result = paper_sync.run_paper_fetch('10.1234/test', dest, runner=fake_runner)
    assert result['pdf'] is None


def test_acquire_pdf_uses_valid_cache_before_other_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_sync, 'WORK_DIR', tmp_path)
    dest = tmp_path / 'doi10.1234test.pdf'
    dest.write_bytes(b'%PDF' + b'x' * 3000)
    monkeypatch.setattr(paper_sync, '_wrangler',
                        lambda args: (_ for _ in ()).throw(AssertionError('R2 called')))

    def runner(cmd, **kwargs):
        raise AssertionError('paper-fetch called')

    result = paper_sync.acquire_pdf({
        'item_id': 'doi:10.1234/test', 'pdf_key': 'pdf/test.pdf',
        'oa_pdf_url': 'https://example.test/test.pdf', 'doi': '10.1234/test',
    }, runner=runner)
    assert result == {
        'pdf': str(dest), 'pdf_source': 'cache', 'fetch_route': 'cache',
        'fetch_error': None, 'retryable': False,
    }


def test_acquire_pdf_replace_failure_preserves_stale_destination(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_sync, 'WORK_DIR', tmp_path)
    dest = tmp_path / 'doi10.1234test.pdf'
    old = b'<html>old stale destination'
    dest.write_bytes(old)
    original_replace = Path.replace

    def fake_wrangler(args):
        assert dest.read_bytes() == old
        Path(args[args.index('--file') + 1]).write_bytes(b'%PDF' + b'x' * 3000)

    def failed_replace(path, target):
        if path.suffix == '.part':
            raise PermissionError('destination is locked')
        return original_replace(path, target)

    monkeypatch.setattr(paper_sync, '_wrangler', fake_wrangler)
    monkeypatch.setattr(Path, 'replace', failed_replace)
    result = paper_sync.acquire_pdf({
        'item_id': 'doi:10.1234/test', 'pdf_key': 'pdf/test.pdf',
        'oa_pdf_url': None, 'doi': '',
    })
    assert set(result) == {'pdf', 'pdf_source', 'fetch_route', 'fetch_error', 'retryable'}
    assert result['pdf'] is None
    assert result['retryable'] is True
    assert dest.read_bytes() == old
    assert not list(tmp_path.glob('*.part'))


def test_acquire_pdf_returns_typed_result_when_work_dir_creation_fails(
        tmp_path, monkeypatch):
    work_dir = tmp_path / 'locked'
    monkeypatch.setattr(paper_sync, 'WORK_DIR', work_dir)
    original_mkdir = Path.mkdir

    def failed_mkdir(path, *args, **kwargs):
        if path == work_dir:
            raise PermissionError('work dir is locked')
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'mkdir', failed_mkdir)
    result = paper_sync.acquire_pdf({
        'item_id': 'manual:locked', 'pdf_key': None, 'oa_pdf_url': None, 'doi': '',
    })
    assert set(result) == {'pdf', 'pdf_source', 'fetch_route', 'fetch_error', 'retryable'}
    assert result['pdf'] is None
    assert 'work dir is locked' in result['fetch_error']
    assert result['retryable'] is True


def test_acquire_pdf_cleanup_permission_error_does_not_abort(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_sync, 'WORK_DIR', tmp_path)
    original_unlink = Path.unlink

    def fake_wrangler(args):
        Path(args[args.index('--file') + 1]).write_bytes(b'<html>' + b'x' * 3000)

    def locked_part_cleanup(path, *args, **kwargs):
        if path.suffix == '.part':
            raise PermissionError('part is locked')
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(paper_sync, '_wrangler', fake_wrangler)
    monkeypatch.setattr(Path, 'unlink', locked_part_cleanup)
    result = paper_sync.acquire_pdf({
        'item_id': 'manual:locked', 'pdf_key': 'pdf/test.pdf',
        'oa_pdf_url': None, 'doi': '',
    })
    assert set(result) == {'pdf', 'pdf_source', 'fetch_route', 'fetch_error', 'retryable'}
    assert result['pdf'] is None
    assert 'valid PDF' in result['fetch_error']


def test_acquire_pdf_falls_back_from_invalid_r2_to_oa(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_sync, 'WORK_DIR', tmp_path)
    dest = tmp_path / 'doi10.1234test.pdf'
    calls = []

    def fake_wrangler(args):
        calls.append('r2')
        part = Path(args[args.index('--file') + 1])
        assert part != dest
        part.write_bytes(b'<html>' + b'x' * 3000)

    class Response:
        def __enter__(self):
            calls.append('oa')
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'%PDF' + b'x' * 3000

    monkeypatch.setattr(paper_sync, '_wrangler', fake_wrangler)
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *args, **kwargs: Response())
    result = paper_sync.acquire_pdf({
        'item_id': 'doi:10.1234/test', 'pdf_key': 'pdf/test.pdf',
        'oa_pdf_url': 'https://example.test/test.pdf', 'doi': '10.1234/test',
    })
    assert calls == ['r2', 'oa']
    assert result['pdf_source'] == 'oa-url'
    assert result['fetch_route'] == 'oa-url'
    assert paper_sync.is_valid_pdf(result['pdf'])
    assert not list(tmp_path.glob('*.part'))


def test_acquire_pdf_accumulates_failures_before_paper_fetch(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_sync, 'WORK_DIR', tmp_path)
    monkeypatch.setattr(paper_sync, '_wrangler',
                        lambda args: (_ for _ in ()).throw(RuntimeError('R2 unavailable')))
    monkeypatch.setattr(urllib.request, 'urlopen',
                        lambda *args, **kwargs: (_ for _ in ()).throw(OSError('OA unavailable')))

    def failed_runner(cmd, **kwargs):
        return CompletedProcess(
            cmd, 2, stdout='{"ok": false, "error": "routes exhausted"}', stderr='')

    result = paper_sync.acquire_pdf({
        'item_id': 'doi:10.1234/test', 'pdf_key': 'pdf/test.pdf',
        'oa_pdf_url': 'https://example.test/test.pdf', 'doi': '10.1234/test',
    }, runner=failed_runner)
    assert result['pdf'] is None
    assert result['pdf_source'] == 'missing'
    assert 'r2: R2 unavailable' in result['fetch_error']
    assert 'oa-url: OA unavailable' in result['fetch_error']
    assert 'paper-fetch: routes exhausted' in result['fetch_error']
    assert result['retryable'] is True
    assert not list(tmp_path.glob('*.part'))


def test_acquire_pdf_marks_r2_and_oa_only_transient_failures_retryable(
        tmp_path, monkeypatch):
    monkeypatch.setattr(paper_sync, 'WORK_DIR', tmp_path)
    monkeypatch.setattr(paper_sync, '_wrangler',
                        lambda args: (_ for _ in ()).throw(OSError('R2 timeout')))
    monkeypatch.setattr(urllib.request, 'urlopen',
                        lambda *args, **kwargs: (_ for _ in ()).throw(OSError('OA timeout')))
    result = paper_sync.acquire_pdf({
        'item_id': 'manual:transient', 'pdf_key': 'pdf/test.pdf',
        'oa_pdf_url': 'https://example.test/test.pdf', 'doi': '',
    })
    assert result['pdf'] is None
    assert result['retryable'] is True
    assert 'r2: R2 timeout' in result['fetch_error']
    assert 'oa-url: OA timeout' in result['fetch_error']


def test_acquire_pdf_preserves_prior_retryable_when_fetch_routes_exhausted(
        tmp_path, monkeypatch):
    monkeypatch.setattr(paper_sync, 'WORK_DIR', tmp_path)
    monkeypatch.setattr(paper_sync, '_wrangler',
                        lambda args: (_ for _ in ()).throw(OSError('R2 timeout')))

    def route_exhausted(cmd, **kwargs):
        return CompletedProcess(
            cmd, 2, stdout='{"ok": false, "resolver_url": "https://resolver.test"}',
            stderr='diagnostics')

    result = paper_sync.acquire_pdf({
        'item_id': 'doi:10.1234/test', 'pdf_key': 'pdf/test.pdf',
        'oa_pdf_url': None, 'doi': '10.1234/test',
    }, runner=route_exhausted)
    assert result['pdf'] is None
    assert result['retryable'] is True
    assert 'r2: R2 timeout' in result['fetch_error']
    assert 'paper-fetch: https://resolver.test' in result['fetch_error']


def test_cmd_pending_writes_all_acquisition_result_keys(tmp_path, monkeypatch):
    papers_json = tmp_path / 'papers.json'
    papers_json.write_text(json.dumps(PAPERS), encoding='utf-8')
    monkeypatch.setattr(paper_sync, 'PAPERS_JSON', papers_json)
    monkeypatch.setattr(paper_sync, 'WORK_DIR', tmp_path)
    monkeypatch.setattr(paper_sync, 'query_pending', lambda: rows())
    expected = {'pdf': None, 'pdf_source': 'missing', 'fetch_route': None,
                'fetch_error': 'fixture', 'retryable': False}
    monkeypatch.setattr(paper_sync, 'acquire_pdf', lambda item: expected)

    paper_sync.cmd_pending()

    item = json.loads((tmp_path / 'worklist.json').read_text(encoding='utf-8'))[0]
    assert {key: item[key] for key in expected} == expected
