import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Depends, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import desc, text
from sqlalchemy.orm import Session

from .auth import current_user
from .db import Base, engine, get_db
from .models import Upload, Invoice, Hold, InvoiceNote, Attachment
from .parser import parse_xlsx

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/data/uploads"))
ATTACHMENT_DIR = Path(os.getenv("ATTACHMENT_DIR", "/data/attachments"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)

Base.metadata.create_all(bind=engine)


def _migrate_columns() -> None:
    """Idempotent column-add for environments whose tables predate new fields.
    Postgres-only; on SQLite (tests) create_all already includes the columns."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        # Original audit columns
        conn.execute(text("ALTER TABLE invoice_notes ADD COLUMN IF NOT EXISTS author_email VARCHAR(255) DEFAULT ''"))
        conn.execute(text("ALTER TABLE attachments ADD COLUMN IF NOT EXISTS author_email VARCHAR(255) DEFAULT ''"))
        # Extended invoice columns added in v2
        for col_sql in [
            "gl_date VARCHAR(32) DEFAULT ''",
            "due_in INTEGER",
            "addr1 VARCHAR(512) DEFAULT ''",
            "addr2 VARCHAR(512) DEFAULT ''",
            "city VARCHAR(256) DEFAULT ''",
            "state VARCHAR(64) DEFAULT ''",
            "zip VARCHAR(32) DEFAULT ''",
            "payment_method VARCHAR(128) DEFAULT ''",
            "ach_account_type VARCHAR(64) DEFAULT ''",
            "ach_routing VARCHAR(64) DEFAULT ''",
            "ach_account VARCHAR(64) DEFAULT ''",
            "ach_enabled BOOLEAN DEFAULT FALSE",
            "last_payment VARCHAR(32) DEFAULT ''",
            "modified_by VARCHAR(256) DEFAULT ''",
            "modified_at VARCHAR(32) DEFAULT ''",
            "receipt_url TEXT DEFAULT ''",
            "vendor_id VARCHAR(128) DEFAULT ''",
            "mod_flagged BOOLEAN DEFAULT FALSE",
            "true_last_payment VARCHAR(32) DEFAULT ''",
            "true_modified_at VARCHAR(32) DEFAULT ''",
            "true_modified_by VARCHAR(256) DEFAULT ''",
            "vendor_created_at VARCHAR(32) DEFAULT ''",
            "receipt_checked BOOLEAN DEFAULT FALSE",
            "receipt_flags TEXT DEFAULT '[]'",
            "invoice_checked BOOLEAN DEFAULT FALSE",
            "invoice_flags TEXT DEFAULT '[]'",
        ]:
            col_name = col_sql.split()[0]
            conn.execute(text(
                f"ALTER TABLE invoices ADD COLUMN IF NOT EXISTS {col_name} {' '.join(col_sql.split()[1:])}"
            ))


_migrate_columns()

app = FastAPI(title="AP Review Dashboard")


# ──────────────────────────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────────────────────────
class InvoiceOut(BaseModel):
    id: int
    org: str
    vendor: str
    bill: str
    date: str
    due_date: str
    ref: str
    amount: float
    w9: str
    on_hold: bool
    note: str = ""
    attachments: list[dict] = []


class HoldOut(BaseModel):
    id: int
    org: str
    vendor: str
    reason: str
    ticket: str
    notes: str
    amount: float


class NoteIn(BaseModel):
    org: str
    bill: str
    note: str


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────
def _latest_upload(db: Session) -> Optional[Upload]:
    return db.query(Upload).order_by(desc(Upload.uploaded_at)).first()


def _resolve_upload(db: Session, upload_id: Optional[int]) -> Optional[Upload]:
    if upload_id is not None:
        return db.get(Upload, upload_id)
    return _latest_upload(db)


def _serialize_invoice(
    inv: Invoice, note_obj: Optional[InvoiceNote], atts: list,
) -> dict:
    def _s(v):
        return v or ""

    return {
        # Core fields (original names kept for API/notes/attachment key compat)
        "id": inv.id,
        "org": inv.org,
        "vendor": inv.vendor,
        "bill": inv.bill,
        "date": _s(inv.invoice_date),
        "due_date": _s(inv.due_date),
        "ref": _s(inv.ref),
        "amount": float(inv.amount),
        "w9": _s(inv.w9),
        "on_hold": inv.on_hold,
        # Timing
        "gl_date": _s(inv.gl_date),
        "due_in": inv.due_in,
        # Address
        "addr1": _s(inv.addr1),
        "addr2": _s(inv.addr2),
        "city": _s(inv.city),
        "state": _s(inv.state),
        "zip": _s(inv.zip),
        # Payment / ACH
        "payment_method": _s(inv.payment_method),
        "ach_account_type": _s(inv.ach_account_type),
        "ach_routing": _s(inv.ach_routing),
        "ach_account": _s(inv.ach_account),
        "ach_enabled": bool(inv.ach_enabled),
        # SAGE audit
        "last_payment": _s(inv.last_payment),
        "modified_by": _s(inv.modified_by),
        "modified_at": _s(inv.modified_at),
        "receipt_url": _s(inv.receipt_url),
        # Vendor-level flags
        "vendor_id": _s(inv.vendor_id),
        "mod_flagged": bool(inv.mod_flagged),
        "true_last_payment": inv.true_last_payment or None,
        "true_modified_at": inv.true_modified_at or None,
        "true_modified_by": inv.true_modified_by or None,
        "vendor_created_at": inv.vendor_created_at or None,
        # Receipt / invoice check results
        "receipt_checked": bool(inv.receipt_checked),
        "receipt_flags": json.loads(inv.receipt_flags or "[]"),
        "invoice_checked": bool(inv.invoice_checked),
        "invoice_flags": json.loads(inv.invoice_flags or "[]"),
        # Reviewer data
        "note": note_obj.note if note_obj else "",
        "note_author": (note_obj.author_email or "") if note_obj else "",
        "note_updated_at": note_obj.updated_at.isoformat() if note_obj else "",
        "attachments": [
            {
                "id": a.id,
                "name": a.original_name,
                "author": a.author_email or "",
                "uploaded_at": a.uploaded_at.isoformat(),
            }
            for a in atts
        ],
    }


# ──────────────────────────────────────────────────────────────────────
# API routes
# ──────────────────────────────────────────────────────────────────────
@app.get("/api/uploads")
def list_uploads(db: Session = Depends(get_db)):
    """Return every prior upload, newest first — for the history selector."""
    rows = db.query(Upload).order_by(desc(Upload.uploaded_at)).all()
    return {
        "uploads": [
            {
                "id": u.id,
                "filename": u.filename,
                "uploaded_at": u.uploaded_at.isoformat(),
                "invoice_count": u.invoice_count,
                "hold_count": u.hold_count,
            }
            for u in rows
        ]
    }


@app.get("/api/invoices")
def list_invoices(
    upload_id: Optional[int] = Query(None, description="Specific upload to view; defaults to latest"),
    db: Session = Depends(get_db),
):
    upload = _resolve_upload(db, upload_id)
    if not upload:
        return {"upload": None, "invoices": []}

    invoices = (
        db.query(Invoice)
        .filter(Invoice.upload_id == upload.id)
        .order_by(Invoice.org, Invoice.id)
        .all()
    )

    notes = {(n.org, n.bill): n for n in db.query(InvoiceNote).all()}

    atts_by_key: dict = {}
    for a in db.query(Attachment).order_by(Attachment.uploaded_at).all():
        atts_by_key.setdefault((a.org, a.bill), []).append(a)

    return {
        "upload": {
            "id": upload.id,
            "filename": upload.filename,
            "uploaded_at": upload.uploaded_at.isoformat(),
        },
        "invoices": [
            _serialize_invoice(
                inv,
                notes.get((inv.org, inv.bill)),
                atts_by_key.get((inv.org, inv.bill), []),
            )
            for inv in invoices
        ],
    }


@app.get("/api/holds")
def list_holds(
    upload_id: Optional[int] = Query(None, description="Specific upload to view; defaults to latest"),
    db: Session = Depends(get_db),
):
    upload = _resolve_upload(db, upload_id)
    if not upload:
        return {"holds": []}
    holds = db.query(Hold).filter(Hold.upload_id == upload.id).all()
    return {
        "holds": [
            {
                "id": h.id,
                "org": h.org,
                "vendor": h.vendor,
                "reason": h.reason,
                "ticket": h.ticket,
                "notes": h.notes,
                "amount": float(h.amount or 0),
            }
            for h in holds
        ]
    }


@app.post("/api/upload")
async def upload_spreadsheet(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Please upload a .xlsx file")

    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    stored_name = f"{stamp}_{uuid.uuid4().hex[:8]}_{file.filename}"
    stored_path = UPLOAD_DIR / stored_name
    with stored_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    try:
        parsed = parse_xlsx(str(stored_path))
    except Exception as e:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Parse error: {e}")

    upload = Upload(
        filename=file.filename,
        stored_path=str(stored_path),
        invoice_count=len(parsed["invoices"]),
        hold_count=len(parsed["holds"]),
    )
    db.add(upload)
    db.flush()

    for inv in parsed["invoices"]:
        db.add(Invoice(
            upload_id=upload.id,
            org=inv["org"],
            vendor=inv["vendor"],
            bill=inv["bill"],
            invoice_date=inv.get("date", ""),
            due_date=inv.get("due_date", ""),
            gl_date=inv.get("gl_date", ""),
            due_in=inv.get("due_in"),
            ref=inv.get("ref", ""),
            amount=inv["amount"],
            w9=inv.get("w9", ""),
            on_hold=inv["on_hold"],
            addr1=inv.get("addr1", ""),
            addr2=inv.get("addr2", ""),
            city=inv.get("city", ""),
            state=inv.get("state", ""),
            zip=inv.get("zip", ""),
            payment_method=inv.get("payment_method", ""),
            ach_account_type=inv.get("ach_account_type", ""),
            ach_routing=inv.get("ach_routing", ""),
            ach_account=inv.get("ach_account", ""),
            ach_enabled=inv.get("ach_enabled", False),
            last_payment=inv.get("last_payment", ""),
            modified_by=inv.get("modified_by", ""),
            modified_at=inv.get("modified_at", ""),
            receipt_url=inv.get("receipt_url", ""),
            vendor_id=inv.get("vendor_id", ""),
            mod_flagged=inv.get("mod_flagged", False),
            true_last_payment=inv.get("true_last_payment") or "",
            true_modified_at=inv.get("true_modified_at") or "",
            true_modified_by=inv.get("true_modified_by") or "",
            vendor_created_at=inv.get("vendor_created_at") or "",
            receipt_checked=inv.get("receipt_checked", False),
            receipt_flags=json.dumps(inv.get("receipt_flags", [])),
            invoice_checked=inv.get("invoice_checked", False),
            invoice_flags=json.dumps(inv.get("invoice_flags", [])),
        ))

    for h in parsed["holds"]:
        db.add(Hold(
            upload_id=upload.id,
            org=h["org"],
            vendor=h["vendor"],
            reason=h["reason"],
            ticket=h["ticket"],
            notes=h["notes"],
            amount=h["amount"],
        ))

    db.commit()

    return {
        "upload_id": upload.id,
        "filename": upload.filename,
        "invoice_count": upload.invoice_count,
        "hold_count": upload.hold_count,
    }


@app.put("/api/notes")
def upsert_note(
    payload: NoteIn,
    db: Session = Depends(get_db),
    user: dict = Depends(current_user),
):
    existing = (
        db.query(InvoiceNote)
        .filter(InvoiceNote.org == payload.org, InvoiceNote.bill == payload.bill)
        .one_or_none()
    )
    if existing:
        existing.note = payload.note
        existing.author_email = user["email"]
    else:
        db.add(InvoiceNote(
            org=payload.org, bill=payload.bill, note=payload.note,
            author_email=user["email"],
        ))
    db.commit()
    return {"status": "ok", "author": user["email"]}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    return user


@app.get("/api/attachments")
def list_attachments(
    org: str = Query(...),
    bill: str = Query(...),
    db: Session = Depends(get_db),
):
    atts = (
        db.query(Attachment)
        .filter(Attachment.org == org, Attachment.bill == bill)
        .order_by(Attachment.uploaded_at)
        .all()
    )
    return [
        {
            "id": a.id,
            "name": a.original_name,
            "author": a.author_email or "",
            "uploaded_at": a.uploaded_at.isoformat(),
        }
        for a in atts
    ]


@app.post("/api/attachments")
async def add_attachment(
    org: str = Query(...),
    bill: str = Query(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: dict = Depends(current_user),
):
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_name = file.filename or "upload.bin"
    stored = f"{stamp}_{uuid.uuid4().hex[:12]}_{safe_name}"
    stored_path = ATTACHMENT_DIR / stored

    size = 0
    with stored_path.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            out.write(chunk)
            size += len(chunk)

    att = Attachment(
        org=org,
        bill=bill,
        original_name=safe_name,
        stored_path=str(stored_path),
        content_type=file.content_type or "",
        size_bytes=size,
        author_email=user["email"],
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return {
        "id": att.id,
        "name": att.original_name,
        "author": att.author_email,
        "uploaded_at": att.uploaded_at.isoformat(),
    }


@app.get("/api/attachments/{att_id}/download")
def download_attachment(att_id: int, db: Session = Depends(get_db)):
    att = db.get(Attachment, att_id)
    if not att or not Path(att.stored_path).exists():
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(att.stored_path, filename=att.original_name)


@app.delete("/api/attachments/{att_id}")
def delete_attachment(att_id: int, db: Session = Depends(get_db)):
    att = db.get(Attachment, att_id)
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")
    Path(att.stored_path).unlink(missing_ok=True)
    db.delete(att)
    db.commit()
    return {"status": "ok"}


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ──────────────────────────────────────────────────────────────────────
# Static frontend
# ──────────────────────────────────────────────────────────────────────
FRONTEND_DIR = Path("/app/frontend")
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
