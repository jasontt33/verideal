"""Tests for the HTTP API."""
import io

import pytest

from .conftest import build_xlsx_bytes, standard_ap_rows, standard_hold_rows


def _upload(client, name="AP_Test.xlsx", ap_rows=None, hold_rows=None):
    data = build_xlsx_bytes(
        ap_rows if ap_rows is not None else standard_ap_rows(),
        hold_rows=hold_rows,
    )
    files = {"file": (name, data,
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    return client.post("/api/upload", files=files)


# ──────────────────────────────────────────────────────────────────────
# Health + empty state
# ──────────────────────────────────────────────────────────────────────
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_me_returns_dev_user_when_no_alb_header(client):
    r = client.get("/api/me")
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "tester@example.com"
    assert body["name"] == "Test User"


def test_invoices_empty_when_no_uploads(client):
    r = client.get("/api/invoices")
    assert r.status_code == 200
    body = r.json()
    assert body["upload"] is None
    assert body["invoices"] == []


def test_holds_empty_when_no_uploads(client):
    r = client.get("/api/holds")
    assert r.status_code == 200
    assert r.json() == {"holds": []}


# ──────────────────────────────────────────────────────────────────────
# Upload
# ──────────────────────────────────────────────────────────────────────
def test_upload_basic(client):
    r = _upload(client, hold_rows=standard_hold_rows())
    assert r.status_code == 200
    body = r.json()
    assert body["filename"] == "AP_Test.xlsx"
    assert body["invoice_count"] == 3
    assert body["hold_count"] == 1
    assert body["upload_id"] > 0


def test_upload_rejects_non_xlsx(client):
    files = {"file": ("notes.txt", b"hello", "text/plain")}
    r = client.post("/api/upload", files=files)
    assert r.status_code == 400
    assert ".xlsx" in r.json()["detail"]


def test_upload_rejects_corrupt_xlsx(client):
    files = {"file": ("bad.xlsx", b"not really an xlsx", "application/octet-stream")}
    r = client.post("/api/upload", files=files)
    assert r.status_code == 400


def test_invoices_after_upload(client):
    _upload(client, hold_rows=standard_hold_rows())
    body = client.get("/api/invoices").json()
    assert body["upload"]["filename"] == "AP_Test.xlsx"
    assert len(body["invoices"]) == 3
    inv = next(i for i in body["invoices"] if i["vendor"] == "Vendor One")
    assert inv["on_hold"] is True
    assert inv["note"] == ""
    assert inv["attachments"] == []


def test_holds_after_upload(client):
    _upload(client, hold_rows=standard_hold_rows())
    holds = client.get("/api/holds").json()["holds"]
    assert len(holds) == 1
    assert holds[0]["vendor"] == "Vendor One"
    assert holds[0]["amount"] == pytest.approx(1000.00)


# ──────────────────────────────────────────────────────────────────────
# Notes
# ──────────────────────────────────────────────────────────────────────
def test_save_note_create(client):
    _upload(client)
    r = client.put("/api/notes", json={
        "org": "Americans for Prosperity", "bill": "B-001", "note": "looks fine",
    })
    assert r.status_code == 200
    assert r.json()["author"] == "tester@example.com"
    body = client.get("/api/invoices").json()
    inv = next(i for i in body["invoices"] if i["bill"] == "B-001")
    assert inv["note"] == "looks fine"
    assert inv["note_author"] == "tester@example.com"
    assert inv["note_updated_at"]  # ISO timestamp present


def test_save_note_update_existing(client):
    _upload(client)
    payload = {"org": "Americans for Prosperity", "bill": "B-001", "note": "first"}
    client.put("/api/notes", json=payload)
    payload["note"] = "second"
    client.put("/api/notes", json=payload)
    body = client.get("/api/invoices").json()
    inv = next(i for i in body["invoices"] if i["bill"] == "B-001")
    assert inv["note"] == "second"


def test_notes_persist_across_uploads(client):
    """Note added after upload #1 should still be attached after upload #2."""
    _upload(client, name="day1.xlsx")
    client.put("/api/notes", json={
        "org": "Americans for Prosperity", "bill": "B-001", "note": "carry-over",
    })
    # Re-upload (same data — same key (org, bill) reappears)
    _upload(client, name="day2.xlsx")
    body = client.get("/api/invoices").json()
    assert body["upload"]["filename"] == "day2.xlsx"
    inv = next(i for i in body["invoices"] if i["bill"] == "B-001")
    assert inv["note"] == "carry-over"


# ──────────────────────────────────────────────────────────────────────
# Attachments
# ──────────────────────────────────────────────────────────────────────
def test_attachment_lifecycle(client):
    _upload(client)
    org, bill = "Americans for Prosperity", "B-001"
    qs = {"org": org, "bill": bill}

    # Create
    files = {"file": ("receipt.pdf", b"%PDF-1.4 fake", "application/pdf")}
    r = client.post("/api/attachments", params=qs, files=files)
    assert r.status_code == 200
    att = r.json()
    assert att["name"] == "receipt.pdf"
    assert att["author"] == "tester@example.com"
    assert att["uploaded_at"]
    att_id = att["id"]

    # List
    r = client.get("/api/attachments", params=qs)
    assert r.status_code == 200
    lst = r.json()
    assert len(lst) == 1
    assert lst[0]["id"] == att_id

    # Joined into invoices payload
    body = client.get("/api/invoices").json()
    inv = next(i for i in body["invoices"] if i["bill"] == bill)
    assert len(inv["attachments"]) == 1
    a = inv["attachments"][0]
    assert a["id"] == att_id
    assert a["name"] == "receipt.pdf"
    assert a["author"] == "tester@example.com"
    assert a["uploaded_at"]

    # Download
    r = client.get(f"/api/attachments/{att_id}/download")
    assert r.status_code == 200
    assert r.content == b"%PDF-1.4 fake"

    # Delete
    r = client.delete(f"/api/attachments/{att_id}")
    assert r.status_code == 200
    assert client.get("/api/attachments", params=qs).json() == []
    # Download now 404s
    assert client.get(f"/api/attachments/{att_id}/download").status_code == 404


def test_attachment_delete_unknown_id_404(client):
    r = client.delete("/api/attachments/9999")
    assert r.status_code == 404


def test_attachments_persist_across_uploads(client):
    _upload(client, name="day1.xlsx")
    qs = {"org": "Americans for Prosperity", "bill": "B-001"}
    files = {"file": ("ev.txt", b"evidence", "text/plain")}
    att_id = client.post("/api/attachments", params=qs, files=files).json()["id"]

    _upload(client, name="day2.xlsx")
    body = client.get("/api/invoices").json()
    inv = next(i for i in body["invoices"] if i["bill"] == "B-001")
    assert any(a["id"] == att_id for a in inv["attachments"])


def test_multiple_attachments_for_same_invoice(client):
    _upload(client)
    qs = {"org": "Americans for Prosperity", "bill": "B-001"}
    for n in ("a.txt", "b.txt", "c.txt"):
        client.post("/api/attachments", params=qs,
                    files={"file": (n, b"x", "text/plain")})
    lst = client.get("/api/attachments", params=qs).json()
    assert [a["name"] for a in lst] == ["a.txt", "b.txt", "c.txt"]


# ──────────────────────────────────────────────────────────────────────
# Latest-upload semantics
# ──────────────────────────────────────────────────────────────────────
def test_latest_upload_supersedes_previous(client):
    """After two uploads, /api/invoices returns rows from the latest only."""
    _upload(client, name="old.xlsx", ap_rows=standard_ap_rows())

    # Upload 2 has a different invoice set
    from .conftest import _entity_header, _invoice
    new_rows = [
        _entity_header("New Org"),
        _invoice("New Vendor", "B-NEW", 42),
    ]
    _upload(client, name="new.xlsx", ap_rows=new_rows)

    body = client.get("/api/invoices").json()
    assert body["upload"]["filename"] == "new.xlsx"
    vendors = [i["vendor"] for i in body["invoices"]]
    assert vendors == ["New Vendor"]


# ──────────────────────────────────────────────────────────────────────
# Upload history
# ──────────────────────────────────────────────────────────────────────
def test_uploads_list_empty(client):
    r = client.get("/api/uploads")
    assert r.status_code == 200
    assert r.json() == {"uploads": []}


def test_uploads_list_returns_history_newest_first(client):
    from .conftest import _entity_header, _invoice
    _upload(client, name="day1.xlsx")
    _upload(client, name="day2.xlsx",
            ap_rows=[_entity_header("Org A"), _invoice("V", "B", 50)])
    _upload(client, name="day3.xlsx",
            ap_rows=[_entity_header("Org B"), _invoice("V2", "B2", 99)])

    body = client.get("/api/uploads").json()
    files = [u["filename"] for u in body["uploads"]]
    assert files == ["day3.xlsx", "day2.xlsx", "day1.xlsx"]
    # Each row carries its summary counts
    assert all("invoice_count" in u and "hold_count" in u and "uploaded_at" in u
               for u in body["uploads"])


def test_invoices_filter_by_upload_id_returns_historical_snapshot(client):
    from .conftest import _entity_header, _invoice
    r1 = _upload(client, name="day1.xlsx",
                 ap_rows=[_entity_header("Old"), _invoice("OldV", "OB", 100)])
    upload_id_1 = r1.json()["upload_id"]
    _upload(client, name="day2.xlsx",
            ap_rows=[_entity_header("New"), _invoice("NewV", "NB", 200)])

    # Latest (no param) → day2
    latest = client.get("/api/invoices").json()
    assert latest["upload"]["filename"] == "day2.xlsx"
    assert [i["vendor"] for i in latest["invoices"]] == ["NewV"]

    # Historical (?upload_id=…) → day1
    hist = client.get(f"/api/invoices?upload_id={upload_id_1}").json()
    assert hist["upload"]["filename"] == "day1.xlsx"
    assert [i["vendor"] for i in hist["invoices"]] == ["OldV"]


def test_holds_filter_by_upload_id(client):
    """Each upload's hold list is independently retrievable by id."""
    r1 = _upload(client, name="day1.xlsx",
                 hold_rows=[["A", "Vendor One", "ACH", "T1", "n1"]])
    upload_id_1 = r1.json()["upload_id"]
    _upload(client, name="day2.xlsx",
            hold_rows=[["A", "Vendor One", "ACH", "T1", "n1"],
                       ["B", "Vendor Two", "Wire", "T2", "n2"]])

    hist = client.get(f"/api/holds?upload_id={upload_id_1}").json()
    assert len(hist["holds"]) == 1
    latest = client.get("/api/holds").json()
    assert len(latest["holds"]) == 2


def test_invoices_with_unknown_upload_id_returns_empty(client):
    _upload(client)
    body = client.get("/api/invoices?upload_id=99999").json()
    assert body == {"upload": None, "invoices": []}


def test_notes_visible_when_viewing_historical_upload(client):
    """Notes are global by (org, bill) — they show up on historical snapshots too."""
    r1 = _upload(client, name="day1.xlsx")
    upload_id_1 = r1.json()["upload_id"]
    client.put("/api/notes", json={
        "org": "Americans for Prosperity", "bill": "B-001", "note": "annotated",
    })
    _upload(client, name="day2.xlsx")

    hist = client.get(f"/api/invoices?upload_id={upload_id_1}").json()
    inv = next(i for i in hist["invoices"] if i["bill"] == "B-001")
    assert inv["note"] == "annotated"
