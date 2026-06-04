"""Tests for PRF detection and brand-field example rejection in checks.py."""
from app.checks import _is_prf, _looks_like_brand_example


def test_is_prf_detects_form():
    assert _is_prf("PAYMENT REQUEST FORM\nVendor Name: Foo")


def test_is_prf_case_insensitive_and_whitespace_tolerant():
    assert _is_prf("payment   request   form")


def test_is_prf_negative():
    assert not _is_prf("Invoice #1234\nTotal: $500")
    assert not _is_prf("")


def test_brand_example_ex_prefix():
    assert _looks_like_brand_example("ex. STCC, AFP, STF, ST-")
    assert _looks_like_brand_example("Ex STCC")


def test_brand_example_multi_abbrev_short():
    # 3+ comma-separated abbreviations under 40 chars looks like template text
    assert _looks_like_brand_example("STCC, AFP, STF")


def test_brand_example_trailing_dash():
    assert _looks_like_brand_example("ST-")


def test_brand_example_all_abbrev_pattern():
    assert _looks_like_brand_example("STCC, AFP")
    assert _looks_like_brand_example("ABCDE, FGHIJ")


def test_brand_legit_value_not_flagged():
    assert not _looks_like_brand_example("Charles Koch Foundation")
    assert not _looks_like_brand_example("STCC Music")
    assert not _looks_like_brand_example("Americans for Prosperity")
