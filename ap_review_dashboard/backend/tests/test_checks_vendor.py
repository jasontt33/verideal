"""Tests for _extract_vendor_from_invoice."""
from app.checks import _extract_vendor_from_invoice


def test_vendor_full_legal_name_in_text():
    text = "Invoice from Acme Consulting LLC\nTotal: $500.00"
    extracted, result = _extract_vendor_from_invoice(text, "Acme Consulting LLC")
    assert result == "match"


def test_vendor_dba_match():
    text = "Invoice\nRemit to FBT Gibbons LLP\n123 Main St\nTotal: $500"
    extracted, result = _extract_vendor_from_invoice(
        text, "Frost Brown Todd LLC dba FBT Gibbons LLP"
    )
    assert result == "dba_match"


def test_vendor_prf_blank_empty_field():
    text = "PAYMENT REQUEST FORM\nVendor Name:\n\nDate: 2026-01-15"
    extracted, result = _extract_vendor_from_invoice(text, "Whatever LLC")
    assert result == "prf_blank"


def test_vendor_prf_blank_new_keyword():
    text = "PAYMENT REQUEST FORM\nVendor Name:\nNEW\nDate: 2026-01-15"
    extracted, result = _extract_vendor_from_invoice(text, "Whatever LLC")
    assert result == "prf_blank"


def test_vendor_prf_filled_matches_sage():
    text = "PAYMENT REQUEST FORM\nVendor Name:\nAcme Reimbursement Vendor\nDate:"
    extracted, result = _extract_vendor_from_invoice(text, "Acme Reimbursement Vendor")
    assert result == "match"


def test_vendor_prf_filled_mismatches_sage():
    text = "PAYMENT REQUEST FORM\nVendor Name:\nSomeone Else\nDate:"
    extracted, result = _extract_vendor_from_invoice(text, "Acme Reimbursement Vendor")
    assert result == "mismatch"


def test_vendor_remit_to_section():
    text = "Invoice 1234\n\nRemit payment to:\nAcme Corp\n123 Main"
    extracted, result = _extract_vendor_from_invoice(text, "Acme Corp")
    assert result == "match"


def test_vendor_make_checks_payable_section():
    text = "Invoice\n\nMake checks payable to: Acme Corp\n"
    extracted, result = _extract_vendor_from_invoice(text, "Acme Corp")
    assert result == "match"


def test_vendor_fuzzy_word_match():
    text = (
        "INVOICE\nProvider: Frost Brown Todd\nCase Reference: 2026-XX\n"
        "Total Due: $1,200.00\nGibbons Office\n"
    )
    extracted, result = _extract_vendor_from_invoice(
        text, "Frost Brown Todd LLC dba FBT Gibbons LLP"
    )
    assert result in ("match", "dba_match")


def test_vendor_mismatch():
    text = "Invoice from Unknown Corp\nTotal: $100"
    extracted, result = _extract_vendor_from_invoice(text, "Acme Consulting LLC")
    assert result == "mismatch"


def test_vendor_no_text():
    extracted, result = _extract_vendor_from_invoice("", "Acme")
    assert result == "no_text"
    extracted, result = _extract_vendor_from_invoice("short", "Acme")
    assert result == "no_text"
