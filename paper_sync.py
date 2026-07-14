# -*- coding: utf-8 -*-
"""paper-radar 回流筆記 helper（/paper-sync 的機械部分）。

用法（都在 repo 根目錄跑、python -X utf8）：
  python -X utf8 paper_sync.py pending   # 查 D1 待辦→補 metadata→下載 PDF→輸出 worklist JSON
  python -X utf8 paper_sync.py done ID…  # 逐篇標 synced=1

注意：wrangler 走本機 OAuth（有 D1 寫入權）。subprocess 會拿掉 CLOUDFLARE_API_TOKEN，
避免誤吃 .env 的 NAS 唯讀 token。
"""
import hashlib, ipaddress, json, os, re, socket, ssl, subprocess, sys, uuid
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parent
PAPER_FETCH = REPO.parents[1] / '700_Scripts' / 'paper-fetch' / 'paper_fetch.py'
PAPERS_JSON = Path(r'Z:/docker/paper-radar/papers.json')   # NAS canonical
WORK_DIR = REPO / '_sync_tmp'                               # PDF 暫存＋worklist
D1_NAME = 'paper-radar-db'
R2_BUCKET = 'paper-radar-pdfs'
MIN_PDF_BYTES = 1000
MAX_PDF_BYTES = 100 * 1024 * 1024
MAX_ERROR_CHARS = 300
MAX_R2_KEY_CHARS = 512
PENDING_SQL = (
    'SELECT item_id, doi, title, star, deepread, content, pdf_key '
    'FROM actions WHERE synced=0 '
    'AND (deepread=1 OR content=1 OR star=1)'
)

_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

def sanitize_filename(s):
    s = _ILLEGAL.sub('', s or '')
    s = re.sub(r'\s+', ' ', s).strip()
    return s.rstrip(' .')

def cache_filename(item_id):
    raw = str(item_id or '')
    label = sanitize_filename(raw).replace(' ', '_')[:80] or 'item'
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    return f'{label}-{digest}.pdf'

def short_title(title, limit=60):
    t = sanitize_filename(title)
    if len(t) > limit:
        t = t[:limit].rsplit(' ', 1)[0]
    return t.rstrip(' -,:;.')

def first_author_surname(authors):
    first = (authors or '').split(',')[0].strip()
    return first.split(' ')[0] if first else 'Unknown'

def note_filename(meta):
    date = meta.get('pub_date') or meta.get('first_seen') or ''
    parts = [p for p in (date, first_author_surname(meta.get('authors', ''))) if p]
    return sanitize_filename(f"{' '.join(parts)} - {short_title(meta.get('title', ''))}") + '.md'

def build_worklist(pending_rows, papers_data):
    """D1 待辦列 × papers.json metadata → worklist。找不到 metadata（外部上傳）用 D1 的 title。"""
    by_id = {p['item_id']: p for p in papers_data.get('papers', [])}
    wl = []
    for r in pending_rows:
        meta = by_id.get(r['item_id'], {})
        content = bool(r.get('content'))
        deepread = bool(r.get('deepread'))
        if not content and not deepread and bool(r.get('star')):
            content = True
        item = {
            'item_id': r['item_id'],
            'title': meta.get('title') or r.get('title') or '',
            'authors': meta.get('authors', ''),
            'journal': meta.get('source_name', ''),
            'pub_date': meta.get('pub_date') or meta.get('first_seen') or '',
            'doi': meta.get('doi') or r.get('doi') or '',
            'tags': meta.get('tags', []),
            'abstract': meta.get('abstract', ''),
            'content': content,
            'deepread': deepread,
            'pdf_key': r.get('pdf_key'),
            'oa_pdf_url': meta.get('oa_pdf_url'),
        }
        # item['pub_date'] 已在上面合併過 first_seen，note_filename 只會走 pub_date 分支
        item['note_filename'] = note_filename(item)
        item['pdf_source'] = 'r2' if item['pdf_key'] else ('oa' if item['oa_pdf_url'] else 'missing')
        wl.append(item)
    return wl

def _env_val(key):
    """只從 REPO/.env 讀單一 key（不經 shell、不外洩其他值）。找不到回 None。"""
    envf = REPO / '.env'
    if not envf.exists():
        return None
    for line in envf.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line.startswith(key + '='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    return None

def _runner_dir():
    """回傳一個「有 wrangler.toml、無 .env」的乾淨執行目錄，逼 wrangler 走本機 OAuth。
    坑：repo 的 .env 存的是唯讀 token（Pages:Edit + D1:Read），新版 wrangler 會自動
    載入 cwd 的 .env 並覆蓋 OAuth → 只能讀不能寫。在沒有 .env 的目錄執行即可回退到
    有 D1 寫入權的 OAuth。複製 wrangler.toml 過去（而非寫死 id）以免 database_id 進 git。"""
    d = WORK_DIR / '_wrunner'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'wrangler.toml').write_text((REPO / 'wrangler.toml').read_text(encoding='utf-8'),
                                     encoding='utf-8')
    return d

def _wrangler(args):
    """在乾淨 runner 目錄跑 wrangler（本機 OAuth，有 D1 寫入權）。回傳 stdout。見 _runner_dir。"""
    env = {k: v for k, v in os.environ.items() if k != 'CLOUDFLARE_API_TOKEN'}
    acct = _env_val('CLOUDFLARE_ACCOUNT_ID')
    if acct:
        env['CLOUDFLARE_ACCOUNT_ID'] = acct
    r = subprocess.run(['npx', '--yes', 'wrangler'] + args, cwd=_runner_dir(), env=env,
                       capture_output=True, text=True, encoding='utf-8', shell=(os.name == 'nt'))
    if r.returncode != 0:
        command = _short_error(' '.join(args), '(empty)')
        raise RuntimeError(
            f'wrangler {command} failed (exit {r.returncode}); '
            f'stdout: {_short_error(r.stdout, "(empty)")}; '
            f'stderr: {_short_error(r.stderr, "(empty)")}')
    return r.stdout

def _sql_quote(s):
    return "'" + str(s).replace("'", "''") + "'"

# item_id 白名單：實際格式只有 doi:*/h:*/manual:*（字元含 \w : . / ( ) -）。
# D1 的 item_id 是網站寫入的，這裡擋掉任何長相可疑的值，避免流進 SQL 拼接。
_ID_OK = re.compile(r'(?=.{1,64}\Z)(?:doi|h|manual):[A-Za-z0-9_:./()\-]+', re.ASCII)
_PDF_KEY_PART = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*', re.ASCII)

def valid_item_id(s):
    return isinstance(s, str) and bool(_ID_OK.fullmatch(s))

def valid_pdf_key(key):
    if not isinstance(key, str) or not key or len(key) > MAX_R2_KEY_CHARS:
        return False
    return all(_PDF_KEY_PART.fullmatch(part) for part in key.split('/'))

def is_valid_pdf(path):
    p = Path(path)
    try:
        return p.stat().st_size > MIN_PDF_BYTES and p.read_bytes()[:4] == b'%PDF'
    except OSError:
        return False

def _cleanup_part(part):
    try:
        part.unlink(missing_ok=True)
    except OSError:
        pass

def _short_error(value, default='no route'):
    text = ' '.join(str(value or '').split()) or default
    return text[:MAX_ERROR_CHARS]

def run_paper_fetch(doi, dest, runner=subprocess.run):
    dest = Path(dest)
    part = dest.with_name(f'{dest.stem}.{uuid.uuid4().hex}.part')
    result = {'pdf': None, 'pdf_source': 'paper-fetch', 'fetch_route': None,
              'fetch_error': None, 'retryable': False}
    try:
        proc = runner(
            [sys.executable, '-X', 'utf8', str(PAPER_FETCH), '--json', doi, str(part)],
            capture_output=True, text=True, encoding='utf-8', timeout=240,
        )
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        envelope = json.loads(lines[-1]) if lines else {}
        if not isinstance(envelope, Mapping):
            raise ValueError('paper-fetch returned invalid JSON envelope')
        if proc.returncode != 0 or not envelope.get('ok'):
            error = envelope.get('error') or envelope.get('resolver_url')
            if not error and proc.returncode != 2:
                error = proc.stderr
            result['fetch_error'] = _short_error(
                error, 'no route' if proc.returncode == 2 else 'paper-fetch failed')
            result['retryable'] = (
                proc.returncode not in (1, 2)
                or (proc.returncode == 2 and bool(envelope.get('error')))
            )
            return result
        if not is_valid_pdf(part):
            result['fetch_error'] = 'fetcher returned a non-PDF payload'
            return result
        part.replace(dest)
        result.update(pdf=str(dest), fetch_route=envelope.get('route'))
        return result
    except subprocess.TimeoutExpired:
        result.update(fetch_error='paper-fetch timeout', retryable=True)
        return result
    except OSError as exc:
        result.update(fetch_error=_short_error(exc), retryable=True)
        return result
    except (ValueError, json.JSONDecodeError) as exc:
        result['fetch_error'] = _short_error(exc)
        return result
    finally:
        _cleanup_part(part)

def query_pending():
    out = _wrangler([
        'd1', 'execute', D1_NAME, '--remote', '--json', '--command', PENDING_SQL
    ])
    data = json.loads(out[out.index('['):])       # wrangler 前面可能有雜訊行
    return data[0]['results']

def mark_synced(item_ids):
    bad = [i for i in item_ids if not valid_item_id(i)]
    if bad:
        raise ValueError(f'可疑 item_id，拒絕執行: {bad}')
    ids = ','.join(_sql_quote(i) for i in item_ids)
    _wrangler(['d1', 'execute', D1_NAME, '--remote', '--command',
               f'UPDATE actions SET synced=1 WHERE item_id IN ({ids})'])

def _result(pdf=None, source='missing', route=None, error=None, retryable=False):
    return {
        'pdf': str(pdf) if pdf else None,
        'pdf_source': source,
        'fetch_route': route,
        'fetch_error': error,
        'retryable': retryable,
    }

def _part_for(dest):
    return dest.with_name(f'{dest.stem}.{uuid.uuid4().hex}.part')

def _promote_pdf(part, dest):
    if not is_valid_pdf(part):
        raise ValueError('downloaded payload is not a valid PDF')
    part.replace(dest)

def _validate_oa_url(url):
    parsed = urlsplit(str(url or ''))
    if parsed.scheme.lower() != 'https' or not parsed.hostname:
        raise ValueError('oa_pdf_url must use HTTPS with a hostname')
    if parsed.username is not None or parsed.password is not None:
        raise ValueError('oa_pdf_url must not contain credentials')
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise ValueError('oa_pdf_url has an invalid port') from exc

    host = parsed.hostname
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        resolved = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = {
            ipaddress.ip_address(info[4][0].split('%', 1)[0]) for info in resolved
        }
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError('oa_pdf_url resolved to a non-public address')
    return url

class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_oa_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def _read_limited(response, limit=MAX_PDF_BYTES):
    raw_length = response.headers.get('Content-Length')
    if raw_length:
        try:
            declared = int(raw_length)
        except ValueError as exc:
            raise ValueError('invalid Content-Length') from exc
        if declared < 0 or declared > limit:
            raise ValueError('PDF exceeds maximum size')
    data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('PDF exceeds maximum size')
    return data

def _download_oa_pdf(url, part):
    _validate_oa_url(url)
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ctx), _ValidatingRedirectHandler())
    request = urllib.request.Request(
        url, headers={'User-Agent': 'paper-radar-sync/1.0'})
    with opener.open(request, timeout=60) as response:
        final_url = response.geturl() if hasattr(response, 'geturl') else url
        _validate_oa_url(final_url)
        part.write_bytes(_read_limited(response))

def acquire_pdf(item, runner=subprocess.run):
    try:
        WORK_DIR.mkdir(exist_ok=True)
    except OSError as exc:
        return _result(error=f'filesystem: {exc}', retryable=True)
    dest = WORK_DIR / cache_filename(item['item_id'])
    if is_valid_pdf(dest):
        return _result(dest, 'cache', 'cache')
    errors = []
    retryable = False

    if item.get('pdf_key'):
        if not valid_pdf_key(item['pdf_key']):
            errors.append('r2: invalid pdf_key')
        else:
            part = _part_for(dest)
            try:
                _wrangler(['r2', 'object', 'get', f"{R2_BUCKET}/{item['pdf_key']}",
                           '--file', str(part), '--remote'])
                _promote_pdf(part, dest)
                return _result(dest, 'r2', 'r2')
            except Exception as exc:
                errors.append(f'r2: {_short_error(exc, exc.__class__.__name__)}')
                retryable = retryable or isinstance(
                    exc, (OSError, RuntimeError, subprocess.TimeoutExpired))
            finally:
                _cleanup_part(part)

    if item.get('oa_pdf_url'):
        part = _part_for(dest)
        try:
            _download_oa_pdf(item['oa_pdf_url'], part)
            _promote_pdf(part, dest)
            return _result(dest, 'oa-url', 'oa-url')
        except Exception as exc:
            errors.append(f'oa-url: {_short_error(exc, exc.__class__.__name__)}')
            retryable = retryable or isinstance(
                exc, (OSError, RuntimeError, subprocess.TimeoutExpired))
        finally:
            _cleanup_part(part)

    if item.get('doi'):
        fetched = run_paper_fetch(item['doi'], dest, runner=runner)
        if fetched['pdf']:
            return fetched
        errors.append(f"paper-fetch: {fetched['fetch_error'] or 'no route'}")
        return _result(
            None, 'missing', None, '; '.join(errors), retryable or fetched['retryable'])

    errors.append('no DOI available for fallback fetch')
    return _result(None, 'missing', None, '; '.join(errors), retryable)

def cmd_pending():
    rows = query_pending()
    if not rows:
        print('沒有待整理的論文（content/deepread/legacy star 均為 0，或已 synced）')
        return
    papers = json.loads(PAPERS_JSON.read_text(encoding='utf-8'))
    wl = build_worklist(rows, papers)
    for item in wl:
        item.update(acquire_pdf(item))
    out = WORK_DIR / 'worklist.json'
    out.write_text(json.dumps(wl, ensure_ascii=False, indent=2), encoding='utf-8')
    ok = [w for w in wl if w['pdf']]
    miss = [w for w in wl if not w['pdf']]
    print(f'worklist: {out}')
    print(f'可處理 {len(ok)} 篇；缺全文 {len(miss)} 篇:')
    for w in miss:
        print(f'  - {w["title"][:70]}  ({w["item_id"]})')

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('pending', 'done'):
        print(__doc__); sys.exit(1)
    if sys.argv[1] == 'pending':
        cmd_pending()
    else:
        if len(sys.argv) < 3:
            print('用法: paper_sync.py done <item_id> [...]'); sys.exit(1)
        mark_synced(sys.argv[2:])
        print(f'已標 synced: {len(sys.argv) - 2} 篇')

if __name__ == '__main__':
    main()
