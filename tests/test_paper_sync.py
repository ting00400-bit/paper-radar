# -*- coding: utf-8 -*-
"""paper_sync 純函數測試。跑法：python -X utf8 -m pytest tests/ -v"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paper_sync import sanitize_filename, short_title, first_author_surname, note_filename

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
