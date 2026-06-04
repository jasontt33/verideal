"""Pytest fixtures. Configures a fresh per-test SQLite DB and tmpdir for files.

Env vars are set BEFORE importing the app so that `app.db.engine` is built
against the test database rather than the production Postgres URL.
"""
import os
import shutil
import tempfile
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import Workbook

# Configure environment before importing the app
TEST_TMP = Path(tempfile.mkdtemp(prefix="ap_test_"))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_TMP / 'test.db'}"
os.environ["UPLOAD_DIR"] = str(TEST_TMP / "uploads")
os.environ["ATTACHMENT_DIR"] = str(TEST_TMP / "attachments")
os.environ["DEV_USER_EMAIL"] = "tester@example.com"
os.environ["DEV_USER_NAME"] = "Test User"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(TEST_TMP, ignore_errors=True)


@pytest.fixture(autouse=True)
def fresh_db():
    """Drop and re-create all tables before each test for isolation."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    # Also clear file dirs
    for d in (Path(os.environ["UPLOAD_DIR"]), Path(os.environ["ATTACHMENT_DIR"])):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)
    yield


@pytest.fixture
def client():
    return TestClient(app)


# ──────────────────────────────────────────────────────────────────────
# Spreadsheet builders
# ──────────────────────────────────────────────────────────────────────
AP_HEADER = [
    "Org", "Non-Ded Bank?", "Vendor name", "Bill number", "Date",
    "Due date", "GL posting date", "Due in", "Reference number",
    "Total amount", "W-9 Type",
]

HOLD_HEADER = ["Org", "Vendor", "Reason", "Ticket", "Notes"]


def build_xlsx_bytes(ap_rows, hold_rows=None,
                     ap_sheet="AP Dashboard", hold_sheet="Hold List",
                     ap_header=None) -> bytes:
    """Build an in-memory .xlsx with the given rows. Returns raw bytes."""
    wb = Workbook()
    ws = wb.active
    ws.title = ap_sheet
    ws.append(ap_header if ap_header is not None else AP_HEADER)
    for r in ap_rows:
        ws.append(r)
    if hold_rows is not None:
        hs = wb.create_sheet(hold_sheet)
        hs.append(HOLD_HEADER)
        for r in hold_rows:
            hs.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def write_xlsx(tmp_path, *args, **kwargs) -> Path:
    """Write an .xlsx into tmp_path/test.xlsx and return the path."""
    data = build_xlsx_bytes(*args, **kwargs)
    p = tmp_path / "test.xlsx"
    p.write_bytes(data)
    return p


# Standard rows used across multiple tests:
def _entity_header(name):
    return [name, None, None, None, None, None, None, None, None, None, None]


def _invoice(vendor, bill, amount, *, org=None, date="2026-04-15",
             due="2026-05-15", ref="some ref", w9="LLC - C"):
    """Build an invoice row matching AP_HEADER positionally."""
    return [
        org, None, vendor, bill, date, due, None, None, ref, amount, w9,
    ]


def standard_ap_rows():
    """A small, realistic invoice set with two entities and a sum row."""
    return [
        _entity_header("Americans for Prosperity"),
        _invoice("Vendor One", "B-001", 1000.00),
        _invoice("Vendor Two", "B-002", 2500.50),
        ["Sum for Americans for Prosperity", None, None, None, None, None,
         None, None, None, 3500.50, None],
        _entity_header("Stand Together, Inc."),
        _invoice("Vendor Three", "B-003", 750.25),
        ["Sum Total", None, None, None, None, None, None, None, None,
         4250.75, None],
    ]


def standard_hold_rows():
    return [
        ["Americans for Prosperity", "Vendor One", "ACH Return", "P2P-1", "Following up"],
    ]
