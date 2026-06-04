"""Tests for backend/app/sharepoint.py — matching + dispatch."""
import pytest

from app import sharepoint
from app.sharepoint import (
    _normalize_for_match,
    _matches_invoice,
    search_supporting_docs,
)


def test_normalize_for_match_strips_punct():
    assert _normalize_for_match("BP-12345_inv.pdf") == "bp12345invpdf"
    assert _normalize_for_match("STT 0042") == "stt0042"
    assert _normalize_for_match("") == ""


def test_matches_invoice_p_number():
    matched, reason = _matches_invoice(
        "BP-12345_inv.pdf", "Vendor", "INV-9999", "P-12345"
    )
    assert matched and reason == "P-number"


def test_matches_invoice_bill_number():
    matched, reason = _matches_invoice(
        "inv_9999_signed.pdf", "Vendor", "INV-9999", ""
    )
    assert matched and reason == "Bill number"


def test_matches_invoice_p_number_preferred_over_bill():
    matched, reason = _matches_invoice(
        "P-12345_INV-9999.pdf", "Vendor", "INV-9999", "P-12345"
    )
    assert matched and reason == "P-number"


def test_matches_invoice_no_match():
    matched, _ = _matches_invoice(
        "unrelated.pdf", "Vendor", "INV-12345", "P-67890"
    )
    assert not matched


def test_matches_invoice_min_length_p_below_floor():
    matched, _ = _matches_invoice("p12.pdf", "Vendor", "", "P-12")
    assert not matched


def test_matches_invoice_min_length_bill_below_floor():
    matched, _ = _matches_invoice("ab_doc.pdf", "Vendor", "AB", "")
    assert not matched


def test_search_no_creds_no_map_returns_empty(monkeypatch):
    monkeypatch.delenv("AZURE_TENANT_ID", raising=False)
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
    monkeypatch.delenv("AZURE_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(sharepoint, "_load_sp_map", lambda: {})
    result = search_supporting_docs([
        {"vendor": "V", "bill": "B", "p_number": "P-12345"}
    ])
    assert result == {}


def test_search_via_sp_map_new_format_filename_keys(monkeypatch):
    monkeypatch.delenv("AZURE_TENANT_ID", raising=False)
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
    monkeypatch.delenv("AZURE_CLIENT_SECRET", raising=False)
    sp_map = {
        "BP-12345_invoice.pdf": "https://sp/url-1",
        "unrelated.pdf": "https://sp/url-2",
    }
    monkeypatch.setattr(sharepoint, "_load_sp_map", lambda: sp_map)
    result = search_supporting_docs([
        {"vendor": "V", "bill": "INV", "p_number": "P-12345"}
    ])
    docs = result.get("V||INV") or []
    assert len(docs) == 1
    assert docs[0]["name"] == "BP-12345_invoice.pdf"
    assert docs[0]["url"] == "https://sp/url-1"
    assert docs[0]["reason"] == "P-number"


def test_search_via_sp_map_legacy_p_number_keys(monkeypatch):
    monkeypatch.delenv("AZURE_TENANT_ID", raising=False)
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
    monkeypatch.delenv("AZURE_CLIENT_SECRET", raising=False)
    sp_map = {"P-12345": "https://sp/url-1"}
    monkeypatch.setattr(sharepoint, "_load_sp_map", lambda: sp_map)
    result = search_supporting_docs([
        {"vendor": "V", "bill": "INV", "p_number": "P-12345"}
    ])
    docs = result.get("V||INV") or []
    assert len(docs) == 1
    assert docs[0]["url"] == "https://sp/url-1"
    assert docs[0]["reason"] == "P-number"


def test_search_tier_disabled_skips_bill_matching(monkeypatch):
    monkeypatch.delenv("AZURE_TENANT_ID", raising=False)
    monkeypatch.setenv("SP_BILL_TIER_ENABLED", "false")
    sp_map = {"inv_9999_signed.pdf": "https://sp/url"}
    monkeypatch.setattr(sharepoint, "_load_sp_map", lambda: sp_map)
    result = search_supporting_docs([
        {"vendor": "V", "bill": "INV-9999", "p_number": ""}
    ])
    assert result == {}
