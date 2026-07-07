from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Numeric, Boolean, DateTime,
    ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship
from .db import Base


class Upload(Base):
    __tablename__ = "uploads"
    id = Column(Integer, primary_key=True)
    filename = Column(String(512), nullable=False)
    stored_path = Column(String(1024), nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    invoice_count = Column(Integer, default=0)
    hold_count = Column(Integer, default=0)
    # "pending" | "running" | "complete" | "skipped"
    check_status = Column(String(16), default="pending", nullable=False)


class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True)
    upload_id = Column(Integer, ForeignKey("uploads.id", ondelete="CASCADE"), nullable=False)
    # Core fields
    org = Column(String(512), nullable=False)
    vendor = Column(String(512), nullable=False)
    bill = Column(String(256), nullable=False, default="")
    invoice_date = Column(String(32), default="")
    due_date = Column(String(32), default="")
    ref = Column(Text, default="")
    amount = Column(Numeric(14, 2), nullable=False, default=0)
    w9 = Column(String(128), default="")
    on_hold = Column(Boolean, default=False, nullable=False)
    # Timing
    gl_date = Column(String(32), default="")
    due_in = Column(Integer, nullable=True)
    # Address
    addr1 = Column(String(512), default="")
    addr2 = Column(String(512), default="")
    addr3 = Column(String(512), default="")
    city = Column(String(256), default="")
    country = Column(String(128), default="")
    country_code = Column(String(32), default="")
    state = Column(String(64), default="")
    zip = Column(String(32), default="")
    # Payment / ACH
    payment_method = Column(String(128), default="")
    ach_account_type = Column(String(64), default="")
    ach_routing = Column(String(64), default="")
    ach_account = Column(String(64), default="")
    ach_enabled = Column(Boolean, default=False)
    # SAGE audit fields
    last_payment = Column(String(32), default="")
    modified_by = Column(String(256), default="")
    created_at = Column(String(32), default="")
    modified_at = Column(String(32), default="")
    doc_id = Column(String(128), default="")
    receipt_url = Column(Text, default="")
    non_ded_bank = Column(Boolean, default=False)
    p_number = Column(String(32), default="")
    sp_url = Column(Text, default="")
    sp_docs = Column(Text, default="[]")  # JSON array of {name, url, reason}
    hold_info = Column(Text, default="")
    # Vendor-level flags (from Payment History + Vendor Modified sheets)
    vendor_id = Column(String(128), default="")
    mod_flagged = Column(Boolean, default=False)
    true_last_payment = Column(String(32), default="")
    true_modified_at = Column(String(32), default="")
    true_modified_by = Column(String(256), default="")
    vendor_created_at = Column(String(32), default="")
    # Receipt / invoice check results (populated externally; stored as JSON arrays)
    receipt_checked = Column(Boolean, default=False)
    receipt_flags = Column(Text, default="[]")
    invoice_checked = Column(Boolean, default=False)
    invoice_flags = Column(Text, default="[]")

    __table_args__ = (
        Index("ix_invoices_org_bill", "org", "bill"),
    )


class Hold(Base):
    __tablename__ = "holds"
    id = Column(Integer, primary_key=True)
    upload_id = Column(Integer, ForeignKey("uploads.id", ondelete="CASCADE"), nullable=False)
    org = Column(String(512), default="")
    vendor = Column(String(512), nullable=False)
    reason = Column(Text, default="")
    ticket = Column(String(64), default="N/A")
    notes = Column(Text, default="")
    amount = Column(Numeric(14, 2), default=0)


class InvoiceNote(Base):
    """Reviewer notes — persisted across uploads, keyed by (org, bill)."""
    __tablename__ = "invoice_notes"
    id = Column(Integer, primary_key=True)
    org = Column(String(512), nullable=False)
    bill = Column(String(256), nullable=False)
    note = Column(Text, default="")
    author_email = Column(String(255), default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("org", "bill", name="uq_invoice_notes_org_bill"),
    )


class Attachment(Base):
    """Manual file attachments — persisted across uploads, keyed by (org, bill)."""
    __tablename__ = "attachments"
    id = Column(Integer, primary_key=True)
    org = Column(String(512), nullable=False)
    bill = Column(String(256), nullable=False)
    original_name = Column(String(512), nullable=False)
    stored_path = Column(String(1024), nullable=False)
    content_type = Column(String(128), default="")
    size_bytes = Column(Integer, default=0)
    author_email = Column(String(255), default="")
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_attachments_org_bill", "org", "bill"),
    )
