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
            content = True                      # 只按筆記沒分類 → 預設內容整理
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
        item['note_filename'] = note_filename(item)
        item['pdf_source'] = 'r2' if item['pdf_key'] else ('oa' if item['oa_pdf_url'] else 'missing')
        wl.append(item)
    return wl
