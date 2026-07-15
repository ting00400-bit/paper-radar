import pytest

from fetch_and_score import pub_date_sort


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-Jul-10", "2026-07-10"),
        ("2026-May", "2026-05-01"),
        ("2026", "2026-01-01"),
        ("2026-07-10", "2026-07-10"),
        ("", ""),
        ("not-a-date", ""),
    ],
)
def test_pub_date_sort(raw, expected):
    assert pub_date_sort(raw) == expected
