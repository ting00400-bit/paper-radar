# -*- coding: utf-8 -*-
"""paper-radar 回流筆記 helper（/paper-sync 的機械部分）。

用法（都在 repo 根目錄跑、python -X utf8）：
  python -X utf8 paper_sync.py pending   # 查 D1 待辦→補 metadata→下載 PDF→輸出 worklist JSON
  python -X utf8 paper_sync.py done ID…  # 逐篇標 synced=1

注意：wrangler 走本機 OAuth（有 D1 寫入權）。subprocess 會拿掉 CLOUDFLARE_API_TOKEN，
避免誤吃 .env 的 NAS 唯讀 token。
"""
import json, os, re, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
PAPERS_JSON = Path(r'Z:/docker/paper-radar/papers.json')   # NAS canonical
WORK_DIR = REPO / '_sync_tmp'                               # PDF 暫存＋worklist
D1_NAME = 'paper-radar-db'
R2_BUCKET = 'paper-radar-pdfs'

_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

def sanitize_filename(s):
    s = _ILLEGAL.sub('', s or '')
    s = re.sub(r'\s+', ' ', s).strip()
    return s.rstrip(' .')

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
        if not content and not deepread:
            content = True                      # 只按筆記沒分類 → 預設兩段都寫
            deepread = True
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
        raise RuntimeError(f'wrangler {" ".join(args)} failed:\n{r.stderr}')
    return r.stdout

def _sql_quote(s):
    return "'" + str(s).replace("'", "''") + "'"

# item_id 白名單：實際格式只有 doi:*/h:*/manual:*（字元含 \w : . / ( ) -）。
# D1 的 item_id 是網站寫入的，這裡擋掉任何長相可疑的值，避免流進 SQL 拼接。
_ID_OK = re.compile(r'^[\w:./()\-]{1,64}$')

def valid_item_id(s):
    return bool(_ID_OK.match(s or ''))

def query_pending():
    out = _wrangler(['d1', 'execute', D1_NAME, '--remote', '--json', '--command',
                     'SELECT item_id, doi, title, star, deepread, content, pdf_key '
                     'FROM actions WHERE synced=0 AND star=1'])
    data = json.loads(out[out.index('['):])       # wrangler 前面可能有雜訊行
    return data[0]['results']

def mark_synced(item_ids):
    bad = [i for i in item_ids if not valid_item_id(i)]
    if bad:
        raise ValueError(f'可疑 item_id，拒絕執行: {bad}')
    ids = ','.join(_sql_quote(i) for i in item_ids)
    _wrangler(['d1', 'execute', D1_NAME, '--remote', '--command',
               f'UPDATE actions SET synced=1 WHERE item_id IN ({ids})'])

def fetch_pdf(item):
    """依 pdf_source 抓 PDF 到 WORK_DIR。成功回傳路徑字串，失敗回 None。"""
    WORK_DIR.mkdir(exist_ok=True)
    dest = WORK_DIR / (sanitize_filename(item['item_id']).replace(' ', '_') + '.pdf')
    if dest.exists() and dest.stat().st_size > 0:
        return str(dest)
    try:
        if item['pdf_source'] == 'r2':
            _wrangler(['r2', 'object', 'get', f"{R2_BUCKET}/{item['pdf_key']}",
                       '--file', str(dest), '--remote'])
        elif item['pdf_source'] == 'oa':
            import urllib.request, ssl
            try:                                    # Windows 的 Python 不吃系統憑證庫，改用 certifi
                import certifi
                ctx = ssl.create_default_context(cafile=certifi.where())
            except Exception:
                ctx = ssl.create_default_context()
            req = urllib.request.Request(item['oa_pdf_url'],
                                         headers={'User-Agent': 'paper-radar-sync/1.0'})
            with urllib.request.urlopen(req, timeout=60, context=ctx) as resp, open(dest, 'wb') as f:
                f.write(resp.read())
        else:
            return None
        return str(dest) if dest.exists() and dest.stat().st_size > 0 else None
    except Exception as e:
        print(f'  [warn] PDF 下載失敗 {item["item_id"]}: {e}')
        return None

def cmd_pending():
    rows = query_pending()
    if not rows:
        print('沒有待整理的論文（star=1 且 synced=0）。')
        return
    papers = json.loads(PAPERS_JSON.read_text(encoding='utf-8'))
    wl = build_worklist(rows, papers)
    for item in wl:
        item['pdf'] = fetch_pdf(item)
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
