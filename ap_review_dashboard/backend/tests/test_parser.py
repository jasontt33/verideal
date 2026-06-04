"""Tests for the xlsx ingest parser."""
from datetime import datetime
import pytest

from app.parser import parse_xlsx
from .conftest import (
    AP_HEADER, HOLD_HEADER, standard_ap_rows, standard_hold_rows, write_xlsx,
    _entity_header, _invoice,
)


def test_parse_basic(tmp_path):
    path = write_xlsx(tmp_path, standard_ap_rows())
    out = parse_xlsx(str(path))
    assert len(out["invoices"]) == 3
    assert out["holds"] == []
    orgs = [i["org"] for i in out["invoices"]]
    assert orgs == [
        "Americans for Prosperity",
        "Americans for Prosperity",
        "Stand Together, Inc.",
    ]


def test_invoice_fields_populated(tmp_path):
    path = write_xlsx(tmp_path, [
        _entity_header("ACME"),
        _invoice("Vendor X", "B-100", 999.99,
                 date="2026-04-15", due="2026-05-15",
                 ref="Description here", w9="LLC - C"),
    ])
    out = parse_xlsx(str(path))
    inv = out["invoices"][0]
    assert inv["org"] == "ACME"
    assert inv["vendor"] == "Vendor X"
    assert inv["bill"] == "B-100"
    assert inv["amount"] == pytest.approx(999.99)
    assert inv["ref"] == "Description here"
    assert inv["w9"] == "LLC - C"
    assert inv["on_hold"] is False
    # Date strings come through formatted MM/DD/YYYY when parsed as Excel dates
    assert inv["date"]
    assert inv["due_date"]


def test_skip_sum_and_grand_total_rows(tmp_path):
    rows = [
        _entity_header("Org A"),
        _invoice("V1", "B1", 100),
        ["Sum for Org A", None, None, None, None, None, None, None, None, 100, None],
        _entity_header("Org B"),
        _invoice("V2", "B2", 200),
        ["Sum Total", None, None, None, None, None, None, None, None, 200, None],
        ["Grand Total", None, None, None, None, None, None, None, None, 300, None],
    ]
    out = parse_xlsx(str(write_xlsx(tmp_path, rows)))
    vendors = [i["vendor"] for i in out["invoices"]]
    assert vendors == ["V1", "V2"]


def test_skip_blank_and_invalid_amounts(tmp_path):
    rows = [
        _entity_header("Org A"),
        _invoice("Has amount", "B1", 100),
        _invoice("Blank amount", "B2", None),
        _invoice("Zero amount", "B3", 0),
        _invoice("Negative amount", "B4", -50),
    ]
    out = parse_xlsx(str(write_xlsx(tmp_path, rows)))
    vendors = [i["vendor"] for i in out["invoices"]]
    assert vendors == ["Has amount"]


def test_amount_string_with_dollar_and_commas(tmp_path):
    rows = [
        _entity_header("Org A"),
        _invoice("V1", "B1", "$1,234.56"),
    ]
    out = parse_xlsx(str(write_xlsx(tmp_path, rows)))
    assert out["invoices"][0]["amount"] == pytest.approx(1234.56)


def test_alternative_column_headers(tmp_path):
    """Parser should accept "Bill #", "Vendor", etc. as alternative headers."""
    alt_header = [
        "Org", "Bank", "Vendor", "Bill #", "Date", "Due",
        "GL", "Due in", "Memo", "Amount", "W9",
    ]
    rows = [
        _entity_header("Org A"),
        _invoice("V1", "B-Alt", 500, ref="memo text"),
    ]
    path = write_xlsx(tmp_path, rows, ap_header=alt_header)
    out = parse_xlsx(str(path))
    inv = out["invoices"][0]
    assert inv["bill"] == "B-Alt"
    assert inv["vendor"] == "V1"
    assert inv["amount"] == pytest.approx(500)
    assert inv["ref"] == "memo text"


def test_excel_date_object_formatted_as_iso(tmp_path):
    """openpyxl returns Date cells as datetime; parser should format YYYY-MM-DD."""
    dt = datetime(2026, 4, 15)
    rows = [
        _entity_header("Org A"),
        _invoice("V1", "B1", 100, date=dt, due=datetime(2026, 5, 15)),
    ]
    out = parse_xlsx(str(write_xlsx(tmp_path, rows)))
    assert out["invoices"][0]["date"] == "2026-04-15"
    assert out["invoices"][0]["due_date"] == "2026-05-15"


def test_no_hold_sheet_returns_empty_holds(tmp_path):
    out = parse_xlsx(str(write_xlsx(tmp_path, standard_ap_rows())))
    assert out["holds"] == []
    assert all(i["on_hold"] is False for i in out["invoices"])


def test_hold_sheet_parsed(tmp_path):
    out = parse_xlsx(str(write_xlsx(
        tmp_path, standard_ap_rows(), hold_rows=standard_hold_rows()
    )))
    assert len(out["holds"]) == 1
    h = out["holds"][0]
    assert h["vendor"] == "Vendor One"
    assert h["reason"] == "ACH Return"
    assert h["ticket"] == "P2P-1"


def test_hold_cross_referenced_to_invoices(tmp_path):
    """An invoice whose vendor matches a hold-list vendor (12-char prefix)
    should have on_hold=True."""
    out = parse_xlsx(str(write_xlsx(
        tmp_path, standard_ap_rows(), hold_rows=standard_hold_rows()
    )))
    by_vendor = {i["vendor"]: i for i in out["invoices"]}
    assert by_vendor["Vendor One"]["on_hold"] is True
    assert by_vendor["Vendor Two"]["on_hold"] is False
    assert by_vendor["Vendor Three"]["on_hold"] is False


def test_hold_amount_filled_from_matched_invoice(tmp_path):
    out = parse_xlsx(str(write_xlsx(
        tmp_path, standard_ap_rows(), hold_rows=standard_hold_rows()
    )))
    assert out["holds"][0]["amount"] == pytest.approx(1000.00)


def test_missing_vendor_or_amount_raises(tmp_path):
    """If neither Vendor nor Amount columns can be detected, raise."""
    bogus = ["X", "Y", "Z"]
    rows = [["a", "b", "c"]]
    path = write_xlsx(tmp_path, rows, ap_header=bogus)
    with pytest.raises(ValueError, match="Vendor or Amount"):
        parse_xlsx(str(path))


def test_empty_sheet_raises(tmp_path):
    """A workbook whose AP sheet has only a header row should raise."""
    path = write_xlsx(tmp_path, [])  # header only, no data rows
    with pytest.raises(ValueError, match="empty|No invoice rows"):
        parse_xlsx(str(path))


def test_no_data_rows_raises(tmp_path):
    """A sheet that has columns but no real invoice rows."""
    rows = [
        _entity_header("Org A"),  # entity-header row only
    ]
    path = write_xlsx(tmp_path, rows)
    with pytest.raises(ValueError, match="No invoice rows"):
        parse_xlsx(str(path))


def test_invoice_inherits_current_org(tmp_path):
    """Invoice rows with blank Org column inherit from the latest entity header."""
    rows = [
        _entity_header("Entity Alpha"),
        _invoice("V1", "B1", 100),
        _invoice("V2", "B2", 200),
        _entity_header("Entity Beta"),
        _invoice("V3", "B3", 300),
    ]
    out = parse_xlsx(str(write_xlsx(tmp_path, rows)))
    assert [i["org"] for i in out["invoices"]] == [
        "Entity Alpha", "Entity Alpha", "Entity Beta",
    ]
