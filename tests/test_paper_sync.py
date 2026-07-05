# -*- coding: utf-8 -*-
"""paper_sync 純函數測試。跑法：python -X utf8 -m pytest tests/ -v"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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

def test_build_worklist_default_both_when_no_flags():
    wl = build_worklist(rows(content=0, deepread=0), PAPERS)
    assert wl[0]['content'] is True and wl[0]['deepread'] is True   # 只按筆記沒分類 → 兩段都寫

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
