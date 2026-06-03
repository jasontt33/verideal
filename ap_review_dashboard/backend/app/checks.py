"""Receipt and invoice PDF validation.

Fetches each unique receipt_url from the invoice list, extracts text via
pdfplumber, and runs six checks per invoice:
  - ACH routing number match
  - ACH account number match
  - Address ZIP match
  - Vendor name fuzzy match
  - Invoice total amount match
  - Bill-to entity match

Modifies invoice dicts in-place, populating:
  receipt_checked, receipt_flags, invoice_checked, invoice_flags
"""
import io
import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    import pdfplumber as _pdfplumber
except ImportError:  # not installed in test env; PDF checks will be no-ops
    _pdfplumber = None  # type: ignore

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

EXCLUDE_ZIPS = {"22203", "22201", "22202", "66101", "66102", "20001", "20002", "20036", "64106"}

ENTITY_ALIASES: dict[str, list[str]] = {
    "stand together, inc.": [
        "stand together chamber of commerce",
        "stand together chamber of commerce, inc.",
        "stand together chamber of commerce, inc. dba stand together",
        "stand together inc",
    ],
    "americans for prosperity": ["afp"],
    "americans for prosperity action": ["afp action"],
    "americans for prosperity state pac": ["afp state pac", "afp pac"],
    "stand together trust": ["stt"],
    "stand together foundation": ["stf"],
    "stand together communications": ["stc"],
    "bill of rights institute": ["bri"],
    "libre": ["libre initiative", "libre action"],
    "cva": ["concerned veterans for america"],
    "yes, every kid, inc.": ["yes every kid", "yek"],
    "bigger picture us, inc": ["bigger picture"],
}

# Known false-positive vendors for specific check types
ZIP_FP_VENDORS = {
    "Cavalier Consulting", "Canvass America, LLC", "Targeted Victory",
    "Angelo State University Foundation, Inc.", "Elek Enterprises LLC", "Traypml, Inc.",
}
VENDOR_NAME_FP = {
    "People Who Think, LLC", "Angelo State University Foundation, Inc.",
    "Traypml, Inc.", "Frost Brown Todd LLC dba FBT Gibbons LLP",
}
ENTITY_FP_VENDORS = {
    "People Who Think, LLC", "Traypml, Inc.", "May Adam Gerdes & Thompson LLP",
}

_pdf_cache: dict[str, str] = {}
_pdf_cache_lock = threading.Lock()


# ── Text helpers ──────────────────────────────────────────────────────────────

def _normalize(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[,\.\-]", " ", s)
    s = re.sub(r"\b(llc|inc|ltd|corp|co|dba|the|and|&)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _entity_match(sage_entity: str, pdf_billto: str) -> bool:
    se = sage_entity.lower().strip()
    bt = pdf_billto.lower()
    if _normalize(se) in _normalize(bt) or _normalize(bt) in _normalize(se):
        return True
    for alias in ENTITY_ALIASES.get(se, []):
        if _normalize(alias) in _normalize(bt):
            return True
    for canonical, aliases in ENTITY_ALIASES.items():
        if se == canonical or se in [a.lower() for a in aliases]:
            for a in aliases + [canonical]:
                if _normalize(a) in _normalize(bt):
                    return True
    return False


def _vendor_match(sage_vendor: str, pdf_text: str) -> bool:
    nv = _normalize(sage_vendor)
    nt = _normalize(pdf_text[:600])
    if not nv or len(pdf_text) < 50:
        return True
    words = [w for w in nv.split() if len(w) > 2]
    if not words:
        return True
    return sum(1 for w in words if w in nt) / len(words) >= 0.55


def _extract_total(text: str) -> Optional[float]:
    patterns = [
        r"(?:total\s+amount\s+due|amount\s+due|total\s+due|invoice\s+total|grand\s+total|balance\s+due)\s*:?\s*(?:usd\s*)?\$?\s*([\d,]+\.?\d*)",
        r"(?:^|\n)\s*total\s*:?\s*\$?\s*([\d,]+\.?\d*)\s*(?:\n|$)",
        r"total\s+\$\s*([\d,]+\.?\d*)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
        if m:
            try:
                v = float(m.group(1).replace(",", ""))
                if v > 0:
                    return v
            except Exception:
                pass
    return None


def _extract_billto(text: str) -> str:
    m = re.search(
        r"(?:bill\s+to|billed\s+to|invoiced\s+to)\s*[:\n](.*?)(?:\n\n|\Z)",
        text, re.IGNORECASE | re.DOTALL,
    )
    if m:
        return m.group(1)[:250]
    m = re.search(r"^To:\s*(.+)$", text, re.MULTILINE)
    if m:
        return m.group(1)[:250]
    return text[:300]


def _fetch_pdf_text(url: str) -> str:
    with _pdf_cache_lock:
        if url in _pdf_cache:
            return _pdf_cache[url]
    text = ""
    try:
        if _pdfplumber is None:
            return ""
        r = requests.get(url, timeout=25, allow_redirects=True, verify=False)
        if r.status_code == 200 and "pdf" in r.headers.get("content-type", "").lower():
            with _pdfplumber.open(io.BytesIO(r.content)) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        else:
            log.warning("PDF fetch %s: HTTP %s", url[:60], r.status_code)
    except Exception as e:
        log.warning("PDF fetch error for %s: %s", url[:60], e)
    with _pdf_cache_lock:
        _pdf_cache[url] = text
    return text


# ── PRF helpers ───────────────────────────────────────────────────────────────

def _is_prf(text: str) -> bool:
    """True iff the PDF text contains 'PAYMENT REQUEST FORM' (whitespace-tolerant)."""
    if not text:
        return False
    return bool(re.search(r"PAYMENT\s+REQUEST\s+FORM", text, re.IGNORECASE))


def _looks_like_brand_example(raw: str) -> bool:
    """Detect placeholder/example text in a PRF Brand field.

    Forms like 'ex. STCC, AFP, STF, ST-' or 'STCC, AFP, STF' are template
    examples in the form's left column, not filled values.
    """
    s = raw.strip()
    return bool(
        re.search(r"\bex\.?\s", s, re.IGNORECASE)
        or (s.count(",") >= 2 and len(s) < 40)
        or s.endswith("-")
        or re.match(r"^[A-Z]{2,5}(,\s*[A-Z]{2,5})+$", s)
    )


# ── Main entry point ──────────────────────────────────────────────────────────

def run_receipt_checks(invoices: list[dict[str, Any]]) -> None:
    """Fetch PDFs and run all checks. Modifies invoices in-place."""
    url_list = list({i["receipt_url"] for i in invoices if i.get("receipt_url")})
    if not url_list:
        log.info("No receipt URLs — skipping PDF checks.")
        return

    log.info("Fetching %d unique PDFs...", len(url_list))
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_fetch_pdf_text, url): url for url in url_list}
        done = 0
        for future in as_completed(futures):
            future.result()
            done += 1
            if done % 10 == 0:
                log.info("  %d/%d PDFs processed...", done, len(url_list))

    ok = sum(1 for v in _pdf_cache.values() if v)
    log.info("Fetched %d/%d PDFs with text.", ok, len(url_list))

    for inv in invoices:
        url  = inv.get("receipt_url", "")
        text = _pdf_cache.get(url, "")
        inv["receipt_checked"] = bool(url)
        inv["invoice_checked"] = bool(url) and bool(text)
        inv.setdefault("receipt_flags", [])
        inv.setdefault("invoice_flags", [])
        if not text:
            continue

        method   = (inv.get("payment_method") or "").lower()
        is_ach   = "ach" in method or "bank" in method
        is_check = "check" in method

        # Routing number
        rm = re.search(
            r"(?:routing\s*(?:number|#|no\.?)|aba\s*(?:number|#|routing)|routing/aba)\s*[:\s]*(\d{9})",
            text, re.IGNORECASE,
        )
        if is_ach and rm and inv.get("ach_routing"):
            sage_r = re.sub(r"\D", "", inv["ach_routing"])
            if sage_r and sage_r != rm.group(1):
                inv["receipt_flags"].append({
                    "type": "routing_mismatch", "severity": "high",
                    "label": "Routing # Mismatch",
                    "detail": f"PDF: {rm.group(1)} | SAGE: {sage_r}",
                })

        # Account number
        am = re.search(
            r"(?:account\s*(?:number|#|no\.?)|acct\s*(?:number|#|no\.?))\s*[:\s]*(\d{6,17})",
            text, re.IGNORECASE,
        )
        if is_ach and am and inv.get("ach_account"):
            sage_a = re.sub(r"\D", "", inv["ach_account"])
            pdf_a  = am.group(1)
            if (sage_a and pdf_a and len(pdf_a) >= 8
                    and pdf_a not in sage_a and sage_a not in pdf_a
                    and sage_a[-6:] != pdf_a[-6:]):
                inv["receipt_flags"].append({
                    "type": "account_mismatch", "severity": "high",
                    "label": "Account # Mismatch",
                    "detail": f"PDF: {pdf_a} | SAGE: {sage_a}",
                })

        # ZIP code
        if (is_ach or is_check) and inv.get("zip"):
            sage_z = re.sub(r"\D", "", inv["zip"])[:5]
            for line in text.split("\n"):
                zm = re.search(r"\b([A-Z]{2})[,\s]+(\d{5})\b", line)
                if zm and zm.group(2) not in EXCLUDE_ZIPS:
                    if zm.group(2) != sage_z:
                        inv["receipt_flags"].append({
                            "type": "zip_mismatch", "severity": "medium",
                            "label": "Address ZIP Mismatch",
                            "detail": f"PDF: {zm.group(2)} | SAGE: {sage_z}",
                        })
                    break

        # Vendor name
        if not _vendor_match(inv.get("vendor", ""), text):
            inv["invoice_flags"].append({
                "type": "vendor_mismatch", "severity": "high",
                "label": "Vendor Name Mismatch",
                "detail": f"SAGE: {inv.get('vendor', '')} | PDF: {text[:70].strip()}",
            })

        # Amount
        pdf_total  = _extract_total(text)
        sage_total = float(inv.get("amount", 0) or 0)
        if pdf_total and sage_total and abs(pdf_total - sage_total) > 0.02:
            inv["invoice_flags"].append({
                "type": "amount_mismatch", "severity": "high",
                "label": "Amount Mismatch",
                "detail": f"PDF total: ${pdf_total:,.2f} | SAGE: ${sage_total:,.2f}",
            })

        # Bill-to entity
        billto = _extract_billto(text)
        if not _entity_match(inv.get("org", inv.get("entity", "")), billto):
            inv["invoice_flags"].append({
                "type": "entity_mismatch", "severity": "medium",
                "label": "Bill-To Entity Mismatch",
                "detail": f"SAGE entity: {inv.get('org', inv.get('entity', ''))} | PDF bill-to: {billto[:80].strip()}",
            })

    # Remove known false positives
    for inv in invoices:
        v = inv.get("vendor", "")
        inv["receipt_flags"] = [
            f for f in inv["receipt_flags"]
            if not (f["type"] == "zip_mismatch" and v in ZIP_FP_VENDORS)
        ]
        inv["invoice_flags"] = [
            f for f in inv["invoice_flags"]
            if not (f["type"] == "vendor_mismatch" and v in VENDOR_NAME_FP)
            and not (f["type"] == "entity_mismatch" and v in ENTITY_FP_VENDORS)
        ]

    flagged = sum(1 for i in invoices if i["receipt_flags"] or i["invoice_flags"])
    log.info("Receipt checks complete. %d invoices flagged.", flagged)
