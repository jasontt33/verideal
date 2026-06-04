"""Tests for _extract_billto address-block detection."""
from app.checks import _extract_billto


def test_billto_address_block():
    text = """Invoice

Bill To:
Stand Together Trust
1310 N Courthouse Rd
Arlington VA 22201

Service rendered."""
    result = _extract_billto(text)
    assert "Stand Together Trust" in result


def test_billto_skips_attn_line():
    text = """Invoice
Attn: John Smith
Stand Together
1310 N Courthouse Rd
Arlington VA 22201
"""
    result = _extract_billto(text)
    assert "Stand Together" in result
    assert "Attn" not in result
    assert "John Smith" not in result


def test_billto_skips_title_line():
    text = """Invoice
Controller
Stand Together Foundation
1310 N Courthouse Rd
Arlington VA 22201
"""
    result = _extract_billto(text)
    assert "Stand Together Foundation" in result
    assert "Controller" not in result


def test_billto_po_box_recognized_as_street():
    text = """Bill To:
Stand Together Trust
P.O. Box 12345
Arlington VA 22201
"""
    result = _extract_billto(text)
    assert "Stand Together Trust" in result


def test_billto_fallback_regex():
    text = "Bill To: Acme Corp"
    result = _extract_billto(text)
    assert "Acme Corp" in result


def test_billto_to_colon_fallback():
    text = "Invoice\nTo: Acme Corporation"
    result = _extract_billto(text)
    assert "Acme Corporation" in result


def test_billto_no_address_block_no_regex_returns_text_head():
    text = "Random invoice text without bill-to information at all."
    result = _extract_billto(text)
    assert result.startswith("Random invoice text")
