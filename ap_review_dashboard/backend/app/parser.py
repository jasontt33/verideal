"""Parses the AP Payment .xlsx file. Mirrors ap_server.py logic."""
import re
from datetime import datetime, date
from typing import Any, Optional
from openpyxl import load_workbook


def _norm(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _fmt_date(v: Any) -> str:
    """Return ISO date string (YYYY-MM-DD) or empty string."""
    if v is None or v == "":
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, (int, float)) and v > 40000:
        from datetime import timedelta
        d = datetime(1899, 12, 30) + timedelta(days=float(v))
        return d.strftime("%Y-%m-%d")
    return _norm(v)


def _parse_amount(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("$", "").replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _extract_url(raw: Any) -> str:
    """Strip HTML anchor wrappers; return plain URLs unchanged."""
    if not raw:
        return ""
    s = str(raw).strip()
    if "<" not in s:
        return s
    m = re.search(r'href=["\']([^"\']+)["\']', s, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return re.sub(r"<[^>]+>", "", s).strip()


def _find_col(header: list[str], *names: str) -> int:
    lower = [h.lower() for h in header]
    for n in names:
        nl = n.lower()
        for i, h in enumerate(lower):
            if h == nl:
                return i
    for n in names:
        nl = n.lower()
        for i, h in enumerate(lower):
            if nl in h:
                return i
    return -1


def _sheet_rows(ws) -> list[list[Any]]:
    return [list(row) for row in ws.iter_rows(values_only=True)]


def _cell(row: list, col_idx: int, fallback_pos: Optional[int] = None) -> Any:
    """Return value by detected header column, with optional positional fallback."""
    if col_idx >= 0 and col_idx < len(row):
        return row[col_idx]
    if fallback_pos is not None and fallback_pos < len(row):
        return row[fallback_pos]
    return None


def parse_xlsx(path: str) -> dict:
    wb = load_workbook(path, data_only=True)
    sheet_names = wb.sheetnames

    # ── AP sheet ─────────────────────────────────────────────────────────────
    ap_name = next(
        (n for n in sheet_names if "ap" in n.lower() or "dashboard" in n.lower()),
        sheet_names[0],
    )
    rows = _sheet_rows(wb[ap_name])
    if not rows or len(rows) < 2:
        raise ValueError("AP sheet appears empty.")

    # Find header row (row 0 in test format; may be deeper in SAGE exports)
    header_idx = 0
    for i, row in enumerate(rows[:8]):
        if row and any(c and "vendor" in str(c).lower() for c in row if c):
            header_idx = i
            break

    header = [_norm(c).lower() for c in rows[header_idx]]

    # Detect columns by header name; fall back to known SAGE positional indices
    i_org      = _find_col(header, "org")
    i_vendor   = _find_col(header, "vendor name", "vendor")
    i_bill     = _find_col(header, "bill number", "bill #", "bill")
    i_date     = _find_col(header, "date", "invoice date")
    i_due      = _find_col(header, "due date", "due")
    i_gl       = _find_col(header, "gl posting date", "gl date", "gl")
    i_due_in   = _find_col(header, "due in", "days until due", "days")
    i_ref      = _find_col(header, "reference number", "reference", "memo", "description")
    i_amt      = _find_col(header, "total amount", "amount")
    i_w9       = _find_col(header, "w-9 type", "w9 type", "w9")
    # Extended SAGE columns (positional fallbacks match SAGE export layout)
    i_addr1    = _find_col(header, "address 1", "addr1", "address line 1", "address")
    i_city     = _find_col(header, "city")
    i_state    = _find_col(header, "state")
    i_zip      = _find_col(header, "zip", "postal code", "zip code")
    i_pay      = _find_col(header, "payment method", "pay method", "payment type")
    i_ach_type = _find_col(header, "ach account type", "account type")
    i_routing  = _find_col(header, "ach routing", "routing number", "routing")
    i_acct     = _find_col(header, "ach account", "account number", "account")
    i_ach_en   = _find_col(header, "ach enabled", "ach")
    i_last_pmt = _find_col(header, "last payment date", "last payment")
    i_mod_by      = _find_col(header, "modified by", "modified_by")
    i_mod_at      = _find_col(header, "modified at", "modified date", "modified_at")
    i_rcpt_url    = _find_col(header, "receipt url", "document url", "url", "receipt")
    # Additional SAGE columns present in full exports
    i_addr3       = _find_col(header, "address 3", "addr3", "address line 3")
    i_country     = _find_col(header, "country")
    i_country_code = _find_col(header, "country code", "country_code")
    i_doc_id      = _find_col(header, "document id", "doc id", "doc_id", "document number", "doc number")
    i_created_at  = _find_col(header, "created date", "created at", "created_at", "invoice created")
    i_non_ded_bank = _find_col(header, "non ded bank", "non_ded_bank", "non-ded", "non deductible bank")

    if i_vendor < 0 or i_amt < 0:
        raise ValueError(
            "Cannot find Vendor or Amount columns. Header: " + ", ".join(map(str, rows[header_idx]))
        )

    invoices: list[dict] = []
    current_org = ""

    for r in rows[header_idx + 1:]:
        org_val    = _norm(_cell(r, i_org, 0))
        vendor_val = _norm(_cell(r, i_vendor, 2))

        org_lower = org_val.lower()
        if org_lower.startswith("sum for") or org_lower in ("sum total", "grand total"):
            continue
        if vendor_val.lower() in ("vendor name", "vendor"):
            continue

        if org_val and not vendor_val:
            current_org = org_val
            continue

        if not vendor_val:
            continue

        amount = _parse_amount(_cell(r, i_amt, 9))
        if not amount or amount <= 0:
            continue

        def cs(idx, pos=None):
            return _norm(_cell(r, idx, pos))

        bill_val = cs(i_bill, 3)
        p_match = re.search(r"\bP-(\d{4,6})\b", bill_val)

        inv = {
            "org":             current_org or "Unknown Entity",
            "vendor":          vendor_val,
            "bill":            bill_val,
            "date":            _fmt_date(_cell(r, i_date, 4)),
            "due_date":        _fmt_date(_cell(r, i_due, 5)),
            "gl_date":         _fmt_date(_cell(r, i_gl, 6)),
            "due_in":          _parse_int(_cell(r, i_due_in, 7)),
            "ref":             cs(i_ref, 8),
            "amount":          amount,
            "w9":              cs(i_w9, 10),
            "on_hold":         False,
            # Address (SAGE cols 11–18)
            "addr1":           cs(i_addr1, 11),
            "addr2":           cs(-1, 12),
            "addr3":           cs(i_addr3, 13),
            "city":            cs(i_city, 14),
            "country":         cs(i_country, 15),
            "country_code":    cs(i_country_code, 16),
            "state":           cs(i_state, 17),
            "zip":             cs(i_zip, 18),
            # Payment / ACH (SAGE cols 19–23)
            "payment_method":  cs(i_pay, 19),
            "ach_account_type": cs(i_ach_type, 20),
            "ach_routing":     cs(i_routing, 21),
            "ach_account":     cs(i_acct, 22),
            "ach_enabled":     bool(_cell(r, i_ach_en, 23)),
            # SAGE audit cols 25–30
            "last_payment":    _fmt_date(_cell(r, i_last_pmt, 25)),
            "modified_by":     cs(i_mod_by, 26),
            "created_at":      _fmt_date(_cell(r, i_created_at, 27)),
            "modified_at":     _fmt_date(_cell(r, i_mod_at, 28)),
            "doc_id":          cs(i_doc_id, 29),
            "receipt_url":     _extract_url(_cell(r, i_rcpt_url, 30)),
            # Non-deductible bank flag (col 1)
            "non_ded_bank":    bool(_cell(r, i_non_ded_bank, 1)),
            # P-number + SharePoint URL (sp_url populated by background task)
            "p_number":        f"P-{p_match.group(1)}" if p_match else "",
            "sp_url":          "",
            # Hold detail — populated after hold cross-reference below
            "hold_info":       None,
            # Vendor-level flags — populated after parsing History/Modified sheets
            "vendor_id":           "",
            "true_last_payment":   None,
            "true_modified_at":    None,
            "true_modified_by":    None,
            "vendor_created_at":   None,
            "mod_flagged":         False,
            # Receipt checks — always empty from the backend parser
            "receipt_checked":     False,
            "receipt_flags":       [],
            "invoice_checked":     False,
            "invoice_flags":       [],
        }
        invoices.append(inv)

    if not invoices:
        raise ValueError("No invoice rows found. Check file format.")

    # ── Payment History sheet ─────────────────────────────────────────────────
    name_to_id: dict[str, str] = {}
    last_pmt_by_id: dict[str, str] = {}
    ph_name = next(
        (n for n in sheet_names if "payment history" in n.lower()), None
    )
    if ph_name:
        ph_rows = _sheet_rows(wb[ph_name])
        ph_hdr_idx = 0
        for i, row in enumerate(ph_rows[:8]):
            if row and any(c and "vendor id" in str(c).lower() for c in row if c):
                ph_hdr_idx = i
                break
        if ph_rows:
            ph_hdr = [_norm(c).lower() for c in (ph_rows[ph_hdr_idx] or [])]
            v_col  = next((i for i, h in enumerate(ph_hdr) if h in ("vendor", "vendor name")), -1)
            id_col = next((i for i, h in enumerate(ph_hdr) if "vendor id" in h), -1)
            dt_col = next((i for i, h in enumerate(ph_hdr) if "payment date" in h or h == "date"), -1)
            for row in ph_rows[ph_hdr_idx + 1:]:
                if not row:
                    continue
                vname = _norm(row[v_col]) if v_col >= 0 and v_col < len(row) else ""
                vid   = _norm(row[id_col]) if id_col >= 0 and id_col < len(row) else ""
                if vname and vid:
                    name_to_id[vname] = vid
                if vid and dt_col >= 0 and dt_col < len(row) and row[dt_col]:
                    ds = _fmt_date(row[dt_col])
                    if ds and (vid not in last_pmt_by_id or ds > last_pmt_by_id[vid]):
                        last_pmt_by_id[vid] = ds

    # ── Vendor Modified sheet ─────────────────────────────────────────────────
    last_mod_by_id: dict[str, dict] = {}
    created_by_id: dict[str, str]   = {}
    vm_name = next(
        (n for n in sheet_names
         if "vendor modified" in n.lower()
         or ("vendor" in n.lower() and "modified" in n.lower())),
        None,
    )
    if vm_name:
        vm_rows = _sheet_rows(wb[vm_name])
        vm_hdr_idx = 0
        for i, row in enumerate(vm_rows[:8]):
            if row and any(c and str(c).lower().strip() == "action" for c in row if c):
                vm_hdr_idx = i
                break
        if vm_rows:
            vm_hdr = [_norm(c).lower() for c in (vm_rows[vm_hdr_idx] or [])]
            dt_col  = next((i for i, h in enumerate(vm_hdr) if "access date" in h or h == "date"), -1)
            act_col = next((i for i, h in enumerate(vm_hdr) if h == "action"), -1)
            rec_col = next((i for i, h in enumerate(vm_hdr) if h == "record"), -1)
            usr_col = next((i for i, h in enumerate(vm_hdr) if h == "user"), -1)
            for row in vm_rows[vm_hdr_idx + 1:]:
                if not row:
                    continue
                action = _norm(row[act_col]) if act_col >= 0 and act_col < len(row) else ""
                rec    = _norm(row[rec_col]) if rec_col >= 0 and rec_col < len(row) else ""
                user   = _norm(row[usr_col]) if usr_col >= 0 and usr_col < len(row) else ""
                if not rec or dt_col < 0 or dt_col >= len(row) or not row[dt_col]:
                    continue
                ds = _fmt_date(row[dt_col])
                if not ds:
                    continue
                if action == "Modify":
                    if rec not in last_mod_by_id or ds > last_mod_by_id[rec]["date"]:
                        last_mod_by_id[rec] = {"date": ds, "user": user}
                elif action == "Create":
                    if rec not in created_by_id or ds < created_by_id[rec]:
                        created_by_id[rec] = ds

    # Apply vendor-level flags to invoices
    for inv in invoices:
        vid = name_to_id.get(inv["vendor"], "")
        inv["vendor_id"]        = vid
        inv["true_last_payment"] = last_pmt_by_id.get(vid) or None
        mod = last_mod_by_id.get(vid)
        inv["true_modified_at"] = mod["date"] if mod else None
        inv["true_modified_by"] = mod["user"] if mod else None
        inv["vendor_created_at"] = created_by_id.get(vid) or None
        inv["mod_flagged"] = bool(
            inv["true_modified_at"]
            and inv["true_last_payment"]
            and inv["true_modified_at"] > inv["true_last_payment"]
        )

    # ── Hold sheet ────────────────────────────────────────────────────────────
    holds: list[dict] = []
    hold_name = next((n for n in sheet_names if "hold" in n.lower()), None)
    if hold_name:
        hrows = _sheet_rows(wb[hold_name])
        h_idx = 0
        for i in range(min(5, len(hrows))):
            row = hrows[i] or []
            if any(c and "vendor" in str(c).lower() for c in row):
                h_idx = i
                break
        hheader = [_norm(c).lower() for c in (hrows[h_idx] or [])]
        h_org    = next((i for i, h in enumerate(hheader) if "org" in h), -1)
        h_vend   = next((i for i, h in enumerate(hheader) if "vendor" in h), -1)
        h_reason = next((i for i, h in enumerate(hheader) if "reason" in h or "hold" in h), -1)
        h_ticket = next((i for i, h in enumerate(hheader) if "ticket" in h), -1)
        h_notes  = next(
            (i for i, h in enumerate(hheader) if "note" in h or "comment" in h or "status" in h),
            -1,
        )

        for r in hrows[h_idx + 1:]:
            if not r:
                continue
            vendor = _norm(r[h_vend]) if h_vend >= 0 and h_vend < len(r) else ""
            if not vendor:
                continue
            # Strip leading numbering like "1.)" common in SAGE exports
            vendor = re.sub(r"^\d+\.\)\s*", "", vendor).strip()
            if not vendor:
                continue
            holds.append({
                "org":    _norm(r[h_org])    if h_org    >= 0 and h_org    < len(r) else "",
                "vendor": vendor,
                "reason": _norm(r[h_reason]) if h_reason >= 0 and h_reason < len(r) else "",
                "ticket": _norm(r[h_ticket]) if h_ticket >= 0 and h_ticket < len(r) else "N/A",
                "notes":  _norm(r[h_notes])  if h_notes  >= 0 and h_notes  < len(r) else "",
                "amount": 0.0,
            })

    # Cross-reference holds onto invoices (fuzzy vendor match, 12-char prefix)
    if holds:
        hold_vendor_set = set()
        for h in holds:
            vl = h["vendor"].lower()
            hold_vendor_set.add(vl)
            norm = re.sub(r"\b(llc|inc|ltd|corp|co|dba)\b", "", vl).strip()
            hold_vendor_set.add(norm)

        for inv in invoices:
            vl    = inv["vendor"].lower()
            vnorm = re.sub(r"\b(llc|inc|ltd|corp|co|dba)\b", "", vl).strip()
            inv["on_hold"] = (
                any(vl.find(hv[:12]) >= 0 or hv.find(vl[:12]) >= 0 for hv in hold_vendor_set)
                or vl in hold_vendor_set
                or vnorm in hold_vendor_set
            )
            if inv["on_hold"]:
                # Attach the matching hold record details inline
                inv["hold_info"] = next(
                    (
                        h for h in holds
                        if (
                            h["vendor"].lower() == vl
                            or re.sub(r"\b(llc|inc|ltd|corp|co|dba)\b", "", h["vendor"].lower()).strip() == vnorm
                        )
                    ),
                    None,
                )

        for h in holds:
            hv = h["vendor"].lower()[:12]
            hn = re.sub(r"\b(llc|inc|ltd|corp|co|dba)\b", "", h["vendor"].lower()).strip()
            matched = [
                inv for inv in invoices
                if inv["on_hold"] and (
                    hv in inv["vendor"].lower()
                    or hn in re.sub(r"\b(llc|inc|ltd|corp|co|dba)\b", "", inv["vendor"].lower()).strip()
                )
            ]
            if matched:
                h["amount"] = sum(i["amount"] for i in matched)

    return {"invoices": invoices, "holds": holds}
