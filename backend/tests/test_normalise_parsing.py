from __future__ import annotations

import pytest

from arp.normalise.parsing import (
    detect_decimal_comma,
    is_blank,
    load_table,
    parse_delimited,
    sniff_delimiter,
    to_bool,
    to_number,
)


def test_semicolon_and_german_decimals_parse_without_cleaning():
    text = "Firma;Intensitaet;Abdeckung\nAlpha;1.234,5;91,4\nBeta;887,25;88,0\n"
    assert sniff_delimiter(text) == ";"
    rows = parse_delimited(text)
    assert rows[0] == ["Firma", "Intensitaet", "Abdeckung"]
    assert detect_decimal_comma([r[1] for r in rows[1:]]) is True
    assert to_number("1.234,5", True) == pytest.approx(1234.5)
    assert to_number("91,4", True) == pytest.approx(91.4)


def test_thousands_separated_dot_locale():
    assert to_number("1,234.5") == pytest.approx(1234.5)
    assert to_number("91.4") == pytest.approx(91.4)
    assert detect_decimal_comma(["1.234,5", "88,2"]) is True
    assert detect_decimal_comma(["1,234.5", "88.2"]) is False


def test_bilingual_booleans():
    assert to_bool("Ja") == 1 and to_bool("wahr") == 1 and to_bool("Yes") == 1
    assert to_bool("Nein") == 0 and to_bool("No") == 0
    assert to_bool("maybe") is None


def test_blank_conventions_are_missing_not_zero():
    assert is_blank(None) is True
    assert is_blank("") is True
    assert is_blank("n/a") is True
    assert is_blank("N.A.") is True
    assert is_blank("42") is False
    assert to_number("n/a") is None
    assert to_number("N.A.") is None
    assert to_number("") is None
    assert to_number("12 apples") is None


def test_load_table_csv_pads_short_rows(tmp_path):
    p = tmp_path / "sample.csv"
    p.write_text("\ufeffA,B,C\n1,2\n3,4,5\n", encoding="utf-8")
    assert load_table(p) == [["A", "B", "C"], ["1", "2", ""], ["3", "4", "5"]]
