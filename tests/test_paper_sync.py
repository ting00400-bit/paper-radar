# -*- coding: utf-8 -*-
"""paper_sync 純函數測試。跑法：python -X utf8 -m pytest tests/ -v"""
import errno
import hashlib
import importlib.util
import json
import socket
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
    assert not valid_item_id('anything')
    assert not valid_item_id('manual:1751700000\n')


def test_cache_filename_hashes_full_item_id_to_avoid_sanitize_collisions():
    first = 'doi:10.1000/a/bc'
    second = 'doi:10.1000/ab/c'
    assert sanitize_filename(first) == sanitize_filename(second)

    first_name = paper_sync.cache_filename(first)
    second_name = paper_sync.cache_filename(second)

    assert first_name != second_name
    assert hashlib.sha256(first.encode('utf-8')).hexdigest() in first_name
    assert hashlib.sha256(second.encode('utf-8')).hexdigest() in second_name


def test_wrangler_failure_preserves_bounded_stdout_and_stderr(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_sync, '_runner_dir', lambda: tmp_path)

    def failed_run(*args, **kwargs):
        return CompletedProcess(
            args[0], 7, stdout=('stdout detail\n' * 1000),
            stderr=('stderr detail\n' * 1000))

    monkeypatch.setattr(paper_sync.subprocess, 'run', failed_run)
    with pytest.raises(RuntimeError) as exc_info:
        paper_sync._wrangler(['d1', 'execute', 'x' * 5000])

    message = str(exc_info.value)
    assert 'exit 7' in message
    assert 'stdout: stdout detail' in message
    assert 'stderr: stderr detail' in message
    assert len(message) < 1000


@pytest.mark.parametrize('url', [
    'http://example.test/paper.pdf',
    'https://127.0.0.1/paper.pdf',
    'https://10.0.0.1/paper.pdf',
    'https://169.254.1.1/paper.pdf',
    'https://224.0.0.1/paper.pdf',
    'https://[::1]/paper.pdf',
])
def test_validate_oa_url_rejects_non_https_and_non_global_ips(url):
    with pytest.raises(ValueError):
        paper_sync._validate_oa_url(url)


def test_validate_oa_url_rejects_hostname_resolving_to_private_ip(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.168.1.5', 443)),
    ])
    with pytest.raises(ValueError):
        paper_sync._validate_oa_url('https://papers.example.test/article.pdf')


def test_validate_oa_url_accepts_hostname_resolving_to_global_ip(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443)),
    ])
    url = 'https://papers.example.test/article.pdf'
    assert paper_sync._validate_oa_url(url) == url


def test_pinned_https_connection_uses_verified_ip_and_hostname_sni(monkeypatch):
    calls = {}
    raw_socket = object()
    wrapped_socket = object()

    class Context:
        verify_mode = paper_sync.ssl.CERT_REQUIRED
        check_hostname = True

        def wrap_socket(self, sock, server_hostname):
            calls['sni'] = server_hostname
            assert sock is raw_socket
            return wrapped_socket

    def fake_create_connection(address, timeout, source_address):
        calls['address'] = address
        calls['timeout'] = timeout
        calls['source_address'] = source_address
        return raw_socket

    monkeypatch.setattr(socket, 'create_connection', fake_create_connection)
    connection = paper_sync._PinnedHTTPSConnection(
        'papers.example.test', 8443, '93.184.216.34',
        context=Context(), timeout=12)
    connection.connect()

    assert calls['address'] == ('93.184.216.34', 8443)
    assert calls['sni'] == 'papers.example.test'
    assert connection.sock is wrapped_socket


def test_manual_redirect_closes_without_reading_body_and_revalidates_each_hop(
        tmp_path, monkeypatch):
    seen_urls = []
    requests = []
    connections = []

    class Response:
        headers = {}

        def __init__(self, status, location=None, payload=None):
            self.status = status
            self.location = location
            self.payload = payload
            self.closed = False
            self.read_calls = 0

        def getheader(self, name):
            return self.location if name == 'Location' else None

        def read(self, size):
            self.read_calls += 1
            if 300 <= self.status < 400:
                raise AssertionError('redirect body must not be read')
            return self.payload

        def close(self):
            self.closed = True

    responses = [
        Response(302, location='/final.pdf'),
        Response(200, payload=b'%PDF' + b'x' * 3000),
    ]

    class Connection:
        def __init__(self, host, port, pinned_ip, *, context, timeout):
            self.response = responses[len(connections)]
            connections.append(self)

        def request(self, method, path, headers):
            requests.append((method, path, headers))

        def getresponse(self):
            return self.response

        def close(self):
            pass

    def resolve(url):
        seen_urls.append(url)
        return paper_sync.urlsplit(url), '93.184.216.34'

    monkeypatch.setattr(paper_sync, '_resolve_public_https', resolve, raising=False)
    part = tmp_path / 'download.part'
    paper_sync._download_oa_pdf(
        'https://example.test:8443/start.pdf', part,
        context=object(), connection_factory=Connection)

    assert seen_urls == [
        'https://example.test:8443/start.pdf',
        'https://example.test:8443/final.pdf',
    ]
    assert responses[0].read_calls == 0
    assert all(response.closed for response in responses)
    assert [request[2]['Host'] for request in requests] == [
        'example.test:8443', 'example.test:8443']
    assert paper_sync.is_valid_pdf(part)


@pytest.mark.parametrize(('status', 'expected'), [
    (400, False), (401, False), (403, False), (404, False),
    (429, True), (500, True), (503, True),
])
def test_http_status_retryability_is_typed(status, expected):
    assert paper_sync._retryable_error(
        paper_sync._HttpStatusError(status)) is expected


def test_dns_and_network_retryability_is_typed():
    assert paper_sync._retryable_error(
        socket.gaierror(socket.EAI_AGAIN, 'try again')) is True
    assert paper_sync._retryable_error(
        socket.gaierror(socket.EAI_NONAME, 'not found')) is False
    assert paper_sync._retryable_error(
        ConnectionResetError(errno.ECONNRESET, 'reset')) is True
    assert paper_sync._retryable_error(OSError('unknown os error')) is False


@pytest.mark.parametrize(('message', 'expected'), [
    ('request timeout', True),
    ('HTTP 429 rate limited', True),
    ('503 service unavailable', True),
    ('unauthorized API token', False),
    ('invalid wrangler config', False),
    ('R2 object not found', False),
    ('unexpected wrangler failure', False),
])
def test_wrangler_runtime_retryability_requires_explicit_evidence(message, expected):
    assert paper_sync._retryable_error(RuntimeError(message)) is expected


def test_read_limited_rejects_payload_over_limit():
    class Response:
        headers = {}

        def read(self, size):
            assert size == 9
            return b'x' * size

    with pytest.raises(ValueError, match='maximum size'):
        paper_sync._read_limited(Response(), limit=8)


@pytest.mark.parametrize('key', [
    '../secret.pdf',
    'pdf/../secret.pdf',
    r'pdf\secret.pdf',
    'pdf/paper.pdf & whoami',
    '/absolute/paper.pdf',
    'pdf//paper.pdf',
])
def test_valid_pdf_key_rejects_path_escape_and_shell_metacharacters(key):
    assert paper_sync.valid_pdf_key(key) is False


def test_valid_pdf_key_accepts_conservative_r2_path():
    assert paper_sync.valid_pdf_key('pdf/2026/paper-123_v2.pdf') is True


def test_valid_pdf_key_accepts_worker_generated_doi_key():
    assert paper_sync.valid_pdf_key('pdf/doi:10_7759_cureus_109501.pdf') is True


def test_acquire_pdf_rejects_unsafe_pdf_key_before_wrangler(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_sync, 'WORK_DIR', tmp_path)
    monkeypatch.setattr(
        paper_sync, '_wrangler',
        lambda args: (_ for _ in ()).throw(AssertionError('wrangler must not run')))

    result = paper_sync.acquire_pdf({
        'item_id': 'manual:unsafe-key', 'pdf_key': 'pdf/x.pdf & whoami',
        'oa_pdf_url': None, 'doi': '',
    })

    assert result['pdf'] is None
    assert result['retryable'] is False
    assert 'invalid pdf_key' in result['fetch_error']

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


@pytest.mark.parametrize('error', [
    'invalid resolver template: missing doi',
    'invalid DOI: not-a-doi',
    'invalid output path',
    'resolver request timeout',
    'HTTP 429 too many requests',
    'HTTP 503 service unavailable',
    'temporary network failure',
    'unknown route failure',
])
def test_run_paper_fetch_exit_two_without_typed_retryability_fails_closed(
        tmp_path, error):
    dest = tmp_path / 'paper.pdf'

    def failed_runner(cmd, **kwargs):
        return CompletedProcess(
            cmd, 2, stdout=json.dumps({'ok': False, 'error': error}), stderr='')

    result = paper_sync.run_paper_fetch('10.1234/test', dest, runner=failed_runner)
    assert result['retryable'] is False


@pytest.mark.parametrize(('typed', 'error'), [
    (True, 'permanent child wording'),
    (False, 'request timeout'),
])
def test_run_paper_fetch_prefers_typed_child_retryability(tmp_path, typed, error):
    dest = tmp_path / 'paper.pdf'

    def failed_runner(cmd, **kwargs):
        return CompletedProcess(cmd, 2, stdout=json.dumps({
            'ok': False, 'error': error, 'retryable': typed,
        }), stderr='')

    result = paper_sync.run_paper_fetch('10.1234/test', dest, runner=failed_runner)
    assert result['retryable'] is typed


@pytest.mark.parametrize('typed', [None, 0, 1, 'true', [], {}])
def test_run_paper_fetch_rejects_non_boolean_child_retryability(tmp_path, typed):
    dest = tmp_path / 'paper.pdf'

    def failed_runner(cmd, **kwargs):
        return CompletedProcess(cmd, 2, stdout=json.dumps({
            'ok': False, 'error': 'request timeout', 'retryable': typed,
        }), stderr='')

    result = paper_sync.run_paper_fetch('10.1234/test', dest, runner=failed_runner)
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
    dest = tmp_path / paper_sync.cache_filename('doi:10.1234/test')
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
    dest = tmp_path / paper_sync.cache_filename('doi:10.1234/test')
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
    dest = tmp_path / paper_sync.cache_filename('doi:10.1234/test')
    calls = []

    def fake_wrangler(args):
        calls.append('r2')
        part = Path(args[args.index('--file') + 1])
        assert part != dest
        part.write_bytes(b'<html>' + b'x' * 3000)

    monkeypatch.setattr(paper_sync, '_wrangler', fake_wrangler)
    def fake_download(url, part):
        calls.append('oa')
        Path(part).write_bytes(b'%PDF' + b'x' * 3000)
    monkeypatch.setattr(paper_sync, '_download_oa_pdf', fake_download, raising=False)
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
    monkeypatch.setattr(
        paper_sync, '_download_oa_pdf',
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError('OA unavailable')))

    def failed_runner(cmd, **kwargs):
        return CompletedProcess(
            cmd, 2, stdout=(
                '{"ok": false, "error": "routes exhausted", "retryable": true}'),
            stderr='')

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
    monkeypatch.setattr(
        paper_sync, '_download_oa_pdf',
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


def test_acquire_pdf_unknown_wrangler_runtime_error_is_not_retryable(
        tmp_path, monkeypatch):
    monkeypatch.setattr(paper_sync, 'WORK_DIR', tmp_path)
    monkeypatch.setattr(
        paper_sync, '_wrangler',
        lambda args: (_ for _ in ()).throw(RuntimeError('unexpected failure')))

    result = paper_sync.acquire_pdf({
        'item_id': 'manual:unknown-r2', 'pdf_key': 'pdf/test.pdf',
        'oa_pdf_url': None, 'doi': '',
    })

    assert result['pdf'] is None
    assert result['retryable'] is False


@pytest.mark.parametrize(('status', 'expected'), [(404, False), (503, True)])
def test_acquire_pdf_http_status_retryability(status, expected, tmp_path, monkeypatch):
    monkeypatch.setattr(paper_sync, 'WORK_DIR', tmp_path)
    monkeypatch.setattr(
        paper_sync, '_download_oa_pdf',
        lambda *args, **kwargs: (_ for _ in ()).throw(
            paper_sync._HttpStatusError(status)))

    result = paper_sync.acquire_pdf({
        'item_id': f'manual:http-{status}', 'pdf_key': None,
        'oa_pdf_url': 'https://example.test/paper.pdf', 'doi': '',
    })

    assert result['pdf'] is None
    assert result['retryable'] is expected


@pytest.fixture
def identity_dirs(tmp_path, monkeypatch):
    work_dir = tmp_path / 'work'
    quarantine_dir = tmp_path / 'quarantine'
    work_dir.mkdir()
    monkeypatch.setattr(paper_sync, 'WORK_DIR', work_dir)
    monkeypatch.setattr(paper_sync, 'QUARANTINE_DIR', quarantine_dir, raising=False)
    return work_dir, quarantine_dir


def test_record_identity_rejection_writes_atomic_marker_and_only_quarantines_expected_cache(
        identity_dirs):
    work_dir, quarantine_dir = identity_dirs
    item_id = 'manual:identity-1'
    expected_cache = work_dir / paper_sync.cache_filename(item_id)
    expected_cache.write_bytes(b'%PDF' + b'x' * 3000)
    old_unhashed = work_dir / 'manualidentity-1.pdf'
    old_unhashed.write_bytes(b'%PDF' + b'o' * 3000)
    unrelated = work_dir / 'unrelated.pdf'
    unrelated.write_bytes(b'%PDF' + b'u' * 3000)

    state = paper_sync.record_identity_rejection(
        item_id, source='r2', route='r2', reason='DOI mismatch')

    assert state['item_id'] == item_id
    assert state['attempts'] == 1
    assert state['rejected_sources'] == ['r2']
    assert state['rejected_routes'] == ['r2']
    assert state['reason'] == 'DOI mismatch'
    assert not expected_cache.exists()
    assert old_unhashed.exists() and unrelated.exists()
    markers = list(quarantine_dir.glob('*.json'))
    quarantined = list(quarantine_dir.glob('*.pdf'))
    assert len(markers) == 1 and len(quarantined) == 1
    assert json.loads(markers[0].read_text(encoding='utf-8')) == state
    assert not list(quarantine_dir.glob('*.part'))


def test_repeated_identity_rejections_use_unique_quarantine_names(identity_dirs):
    work_dir, quarantine_dir = identity_dirs
    item_id = 'manual:identity-unique'
    cache = work_dir / paper_sync.cache_filename(item_id)
    cache.write_bytes(b'%PDF' + b'a' * 3000)
    first = paper_sync.record_identity_rejection(
        item_id, source='r2', route='r2', reason='first mismatch')
    assert first['attempts'] == 1
    assert paper_sync.load_identity_rejection(item_id)['attempts'] == 1
    cache.write_bytes(b'%PDF' + b'b' * 3000)

    state = paper_sync.record_identity_rejection(
        item_id, source='oa-url', route='oa-url', reason='second mismatch')

    names = [path.name for path in quarantine_dir.glob('*.pdf')]
    assert len(names) == 2 and len(set(names)) == 2
    assert state['attempts'] == 2
    assert state['rejected_sources'] == ['r2', 'oa-url']


def test_identity_marker_survives_fresh_module_session_and_blocks_network(
        identity_dirs, monkeypatch):
    work_dir, quarantine_dir = identity_dirs
    item_id = 'manual:identity-session'
    paper_sync.record_identity_rejection(
        item_id, source='r2', route='r2', reason='first mismatch')
    paper_sync.record_identity_rejection(
        item_id, source='oa-url', route='oa-url', reason='second mismatch')

    spec = importlib.util.spec_from_file_location('paper_sync_session2', paper_sync.__file__)
    session2 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(session2)
    session2.WORK_DIR = work_dir
    session2.QUARANTINE_DIR = quarantine_dir
    session2._wrangler = lambda args: (_ for _ in ()).throw(
        AssertionError('network must not run'))
    session2._download_oa_pdf = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError('network must not run'))

    result = session2.acquire_pdf({
        'item_id': item_id, 'pdf_key': 'pdf/test.pdf',
        'oa_pdf_url': 'https://example.test/paper.pdf', 'doi': '10.1000/test',
    }, runner=lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError('network must not run')))

    assert result == {
        'pdf': None, 'pdf_source': 'missing', 'fetch_route': None,
        'fetch_error': 'source_identity_mismatch', 'retryable': False,
    }


def test_first_identity_rejection_skips_rejected_source_without_counting_reacquire(
        identity_dirs, monkeypatch):
    work_dir, _ = identity_dirs
    item_id = 'manual:identity-skip'
    paper_sync.record_identity_rejection(
        item_id, source='r2', route='r2', reason='R2 DOI mismatch')
    monkeypatch.setattr(
        paper_sync, '_wrangler',
        lambda args: (_ for _ in ()).throw(AssertionError('rejected R2 must be skipped')))

    def download(url, part):
        Path(part).write_bytes(b'%PDF' + b'x' * 3000)

    monkeypatch.setattr(paper_sync, '_download_oa_pdf', download)
    result = paper_sync.acquire_pdf({
        'item_id': item_id, 'pdf_key': 'pdf/test.pdf',
        'oa_pdf_url': 'https://example.test/paper.pdf', 'doi': '',
    })

    assert result['pdf_source'] == 'oa-url'
    assert paper_sync.load_identity_rejection(item_id)['attempts'] == 1
    assert Path(result['pdf']) == work_dir / paper_sync.cache_filename(item_id)

    monkeypatch.setattr(
        paper_sync, '_download_oa_pdf',
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError('replacement cache must be returned before network')))
    cached = paper_sync.acquire_pdf({
        'item_id': item_id, 'pdf_key': 'pdf/test.pdf',
        'oa_pdf_url': 'https://example.test/paper.pdf', 'doi': '',
    })
    assert cached['pdf_source'] == 'cache'
    assert cached['pdf'] == result['pdf']
    assert paper_sync.load_identity_rejection(item_id)['attempts'] == 1


def test_transient_reacquire_failure_keeps_attempt_one_and_can_retry_remaining_source(
        identity_dirs, monkeypatch):
    item_id = 'manual:identity-once'
    paper_sync.record_identity_rejection(
        item_id, source='r2', route='r2', reason='R2 mismatch')
    monkeypatch.setattr(
        paper_sync, '_download_oa_pdf',
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError('OA timeout')))
    item = {
        'item_id': item_id, 'pdf_key': 'pdf/test.pdf',
        'oa_pdf_url': 'https://example.test/paper.pdf', 'doi': '',
    }
    first = paper_sync.acquire_pdf(item)
    assert first['retryable'] is True
    assert paper_sync.load_identity_rejection(item_id)['attempts'] == 1

    def download(url, part):
        Path(part).write_bytes(b'%PDF' + b'x' * 3000)

    monkeypatch.setattr(paper_sync, '_download_oa_pdf', download)
    second = paper_sync.acquire_pdf(item)
    assert second['pdf_source'] == 'oa-url'
    assert paper_sync.load_identity_rejection(item_id)['attempts'] == 1


def test_accept_and_reset_clear_identity_marker(identity_dirs):
    item_id = 'manual:identity-clear'
    paper_sync.record_identity_rejection(
        item_id, source='cache', route='cache', reason='mismatch')
    paper_sync.accept_identity(item_id)
    assert paper_sync.load_identity_rejection(item_id) is None

    paper_sync.record_identity_rejection(
        item_id, source='cache', route='cache', reason='replacement needed')
    paper_sync.reset_identity_rejection(item_id)
    assert paper_sync.load_identity_rejection(item_id) is None


def test_legacy_unhashed_cache_is_left_as_orphan_and_never_hits(identity_dirs):
    work_dir, _ = identity_dirs
    item_id = 'manual:legacy-cache'
    legacy = work_dir / (sanitize_filename(item_id).replace(' ', '_') + '.pdf')
    legacy.write_bytes(b'%PDF' + b'x' * 3000)

    result = paper_sync.acquire_pdf({
        'item_id': item_id, 'pdf_key': None, 'oa_pdf_url': None, 'doi': '',
    })

    assert result['pdf'] is None
    assert legacy.exists()


@pytest.mark.parametrize('argv', [
    ['paper_sync.py', 'reject', 'anything', 'r2', 'r2', 'reason'],
    ['paper_sync.py', 'accept', 'anything'],
    ['paper_sync.py', 'reset-rejection', 'anything'],
    ['paper_sync.py', 'reject', 'manual:1', 'bad-source', 'r2', 'reason'],
    ['paper_sync.py', 'reject', 'manual:1', 'r2', 'bad&route', 'reason'],
])
def test_local_identity_cli_rejects_non_allowlisted_arguments(
        argv, identity_dirs, monkeypatch):
    monkeypatch.setattr(sys, 'argv', argv)
    with pytest.raises(ValueError):
        paper_sync.main()


def test_reject_cli_records_marker_and_blocked_status(identity_dirs, monkeypatch):
    item_id = 'manual:cli-local'
    calls = []
    monkeypatch.setattr(paper_sync, '_wrangler', lambda args: calls.append(args) or '')
    monkeypatch.setattr(sys, 'argv', [
        'paper_sync.py', 'reject', item_id, 'r2', 'r2', 'DOI mismatch'])

    paper_sync.main()

    state = paper_sync.load_identity_rejection(item_id)
    assert state['attempts'] == 1
    assert state['reason'] == 'DOI mismatch'
    sql = calls[0][-1]
    assert "sync_status='blocked'" in sql
    assert "pdf_status='identity_mismatch'" in sql
    assert "pdf_source='r2'" in sql
    assert "sync_error='DOI mismatch'" in sql


def test_update_sync_status_validates_item_id_and_escapes_error(monkeypatch):
    calls = []
    monkeypatch.setattr(paper_sync, '_wrangler', lambda args: calls.append(args) or '')

    paper_sync.update_sync_status(
        'doi:10.1234/example', sync_status='pending', pdf_status='missing',
        pdf_source='paper-fetch', sync_error="author's PDF unavailable")

    sql = calls[0][-1]
    assert "sync_status='pending'" in sql
    assert "pdf_status='missing'" in sql
    assert "pdf_source='paper-fetch'" in sql
    assert "author''s PDF unavailable" in sql
    assert 'sync_updated_at=' in sql
    with pytest.raises(ValueError):
        paper_sync.update_sync_status("x'; DROP TABLE actions;--", sync_status='pending')


@pytest.mark.parametrize(('result', 'expected'), [
    ({'pdf': 'paper.pdf', 'pdf_source': 'r2', 'fetch_error': None, 'retryable': False},
     ('pending', 'available', 'r2', None)),
    ({'pdf': None, 'pdf_source': 'missing', 'fetch_error': 'source_identity_mismatch', 'retryable': False},
     ('blocked', 'identity_mismatch', 'missing', '全文身分核對失敗')),
    ({'pdf': None, 'pdf_source': 'missing', 'fetch_error': 'HTTP 503', 'retryable': True},
     ('pending', 'fetch_failed', 'missing', '全文取得暫時失敗，請稍後重試')),
    ({'pdf': None, 'pdf_source': 'missing', 'fetch_error': 'no route', 'retryable': False},
     ('pending', 'missing', 'missing', '找不到可用全文來源')),
])
def test_acquisition_sync_state(result, expected):
    assert paper_sync.acquisition_sync_state(result) == expected


def test_acquisition_sync_state_preserves_identity_marker_source_and_reason():
    result = {
        'pdf': None, 'pdf_source': 'missing', 'fetch_error': 'routes exhausted',
        'retryable': False,
    }
    rejection = {
        'rejected_sources': ['r2'], 'reason': 'R2 PDF belongs to another DOI',
    }

    assert paper_sync.acquisition_sync_state(result, rejection) == (
        'blocked', 'identity_mismatch', 'r2', 'R2 PDF belongs to another DOI')


def test_public_sync_error_removes_paths_urls_and_wrangler_details():
    assert paper_sync.public_sync_error(
        r'filesystem: C:\Users\ting\secret.pdf') == '本機暫存區無法使用'
    assert paper_sync.public_sync_error(
        'r2: wrangler command failed; stderr: token detail') == '雲端全文讀取失敗'
    safe = paper_sync.public_sync_error(
        'DOI mismatch at C:\\Users\\Ting\\My Project\\wrong.pdf https://resolver.test/item')
    assert 'C:\\' not in safe
    assert 'Project\\wrong.pdf' not in safe
    assert 'https://' not in safe


def test_accept_cli_marks_pdf_verified_and_clears_error(identity_dirs, monkeypatch):
    item_id = 'manual:accept-status'
    paper_sync.record_identity_rejection(
        item_id, source='r2', route='r2', reason='wrong DOI')
    calls = []
    monkeypatch.setattr(paper_sync, '_wrangler', lambda args: calls.append(args) or '')
    monkeypatch.setattr(sys, 'argv', ['paper_sync.py', 'accept', item_id])

    paper_sync.main()

    sql = calls[0][-1]
    assert "sync_status='pending'" in sql
    assert "pdf_status='verified'" in sql
    assert 'sync_error=NULL' in sql


def test_accept_cli_does_not_update_d1_when_marker_clear_fails(
        identity_dirs, monkeypatch):
    calls = []
    monkeypatch.setattr(
        paper_sync, 'accept_identity',
        lambda _item_id: (_ for _ in ()).throw(PermissionError('locked')))
    monkeypatch.setattr(paper_sync, '_wrangler', lambda args: calls.append(args) or '')
    monkeypatch.setattr(sys, 'argv', ['paper_sync.py', 'accept', 'manual:locked'])

    with pytest.raises(PermissionError):
        paper_sync.main()

    assert calls == []


def test_mark_synced_sets_dashboard_status(monkeypatch):
    calls = []
    monkeypatch.setattr(paper_sync, '_wrangler', lambda args: calls.append(args) or '')

    paper_sync.mark_synced(['doi:10.1234/example'])

    sql = calls[0][-1]
    assert 'synced=1' in sql
    assert "sync_status='synced'" in sql
    assert "pdf_status='verified'" in sql
    assert 'sync_error=NULL' in sql


def test_cmd_pending_writes_all_acquisition_result_keys(tmp_path, monkeypatch):
    papers_json = tmp_path / 'papers.json'
    papers_json.write_text(json.dumps(PAPERS), encoding='utf-8')
    monkeypatch.setattr(paper_sync, 'PAPERS_JSON', papers_json)
    monkeypatch.setattr(paper_sync, 'WORK_DIR', tmp_path)
    monkeypatch.setattr(paper_sync, 'query_pending', lambda: rows())
    expected = {'pdf': None, 'pdf_source': 'missing', 'fetch_route': None,
                'fetch_error': 'fixture', 'retryable': False}
    monkeypatch.setattr(paper_sync, 'acquire_pdf', lambda item: expected)
    statuses = []
    monkeypatch.setattr(
        paper_sync, 'update_sync_status',
        lambda item_id, **fields: statuses.append((item_id, fields)))

    paper_sync.cmd_pending()

    item = json.loads((tmp_path / 'worklist.json').read_text(encoding='utf-8'))[0]
    assert {key: item[key] for key in expected} == expected
    assert statuses == [(rows()[0]['item_id'], {
        'sync_status': 'pending', 'pdf_status': 'missing',
        'pdf_source': 'missing', 'sync_error': '找不到可用全文來源',
    })]


def test_cmd_pending_preserves_rejection_status_when_other_routes_fail(
        tmp_path, monkeypatch):
    papers_json = tmp_path / 'papers.json'
    papers_json.write_text(json.dumps(PAPERS), encoding='utf-8')
    monkeypatch.setattr(paper_sync, 'PAPERS_JSON', papers_json)
    monkeypatch.setattr(paper_sync, 'WORK_DIR', tmp_path)
    monkeypatch.setattr(paper_sync, 'query_pending', lambda: rows())
    monkeypatch.setattr(paper_sync, 'acquire_pdf', lambda _item: {
        'pdf': None, 'pdf_source': 'missing', 'fetch_route': None,
        'fetch_error': 'routes exhausted', 'retryable': False,
    })
    monkeypatch.setattr(paper_sync, 'load_identity_rejection', lambda _item_id: {
        'rejected_sources': ['r2'], 'reason': 'DOI mismatch', 'attempts': 1,
    })
    statuses = []
    monkeypatch.setattr(
        paper_sync, 'update_sync_status',
        lambda item_id, **fields: statuses.append((item_id, fields)))

    paper_sync.cmd_pending()

    assert statuses[0][1] == {
        'sync_status': 'blocked', 'pdf_status': 'identity_mismatch',
        'pdf_source': 'r2', 'sync_error': 'DOI mismatch',
    }
