# Amy's AP Dashboard Updates — Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port Amy's new AP Dashboard features (SharePoint Daily-Payment-Approvals search with bill-number tier matching, PRF-aware vendor/entity/amount checks, expanded entity tables, multi-doc rendering, KPI merge) into the deployed FastAPI backend.

**Architecture:** Drop-in upgrades to existing `backend/app/` modules — add one new file (`entities.py`) for the entity reference dataset, rewrite the SharePoint module's public surface, add helpers + a rewritten check pipeline to `checks.py`, add one DB column, wire it all in `main.py`, and update the single-file frontend. TDD for all pure-logic units (entities + check helpers + SP matching helpers); manual dev verification for integration.

**Tech Stack:** FastAPI · SQLAlchemy 2.x · Postgres 16 · pytest (already configured) · openpyxl · pdfplumber · requests · Microsoft Graph API.

**Source of truth for the new behavior:** `updates-from-amy/ap_server 2.py` and `updates-from-amy/dashboard_template.html`. The design spec is at `docs/superpowers/specs/2026-06-02-amy-updates-port-design.md`.

**Working directory for all commands below:** `/Users/jay-t/stand-together/git/ap_review_dashboard/` (run `git`, `pytest`, `docker compose` from here).

---

## Task 1: Create entity reference module (`entities.py`)

**Files:**
- Create: `backend/app/entities.py`
- Create: `backend/tests/test_entities.py`

The entity dataset is copied verbatim from Amy's prototype at
`updates-from-amy/ap_server 2.py:73-157` (the three constants `ALL_ENTITY_NAMES`,
`BRAND_TO_PARENT`, `ENTITY_ALIASES_FULL`). Match helpers are added on top.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_entities.py`:

```python
"""Tests for backend/app/entities.py — entity name resolution and matching."""
from app.entities import (
    normalize,
    resolve_entity,
    entities_match,
    find_entity_in_invoice,
)


def test_normalize_lowercases_and_strips_punct():
    assert normalize("Stand Together, Inc.") == "stand together"
    assert normalize("Charles Koch  Foundation") == "charles koch foundation"
    assert normalize("STC4") == "stc4"


def test_resolve_entity_brand_to_parent():
    assert resolve_entity("ckf events") == "charles koch foundation"
    assert resolve_entity("cva action") == "americans for prosperity action"


def test_resolve_entity_alias_to_canonical():
    # "afp" is an alias of "americans for prosperity"
    assert resolve_entity("afp") == "americans for prosperity"
    # "stt" is an alias of "stand together trust"
    assert resolve_entity("stt") == "stand together trust"


def test_resolve_entity_passthrough_for_unknown():
    assert resolve_entity("acme widgets") == "acme widgets"


def test_entities_match_brand_and_parent():
    # A brand and its parent paying entity should match
    assert entities_match("Charles Koch Foundation", "CKF Events")


def test_entities_match_alias():
    assert entities_match("Stand Together, Inc.", "Stand Together Chamber of Commerce")
    assert entities_match("Americans for Prosperity", "AFP")


def test_entities_match_case_and_punct_insensitive():
    assert entities_match("STAND TOGETHER, INC.", "stand together inc")


def test_entities_match_distinct_returns_false():
    assert not entities_match("Stand Together Foundation", "Stand Together Trust")
    assert not entities_match("Americans for Prosperity", "Americans for Prosperity Action")


def test_find_entity_in_invoice_longest_match_wins():
    text = "Bill to:\nStand Together Chamber of Commerce\n1310 N Courthouse"
    name, canonical = find_entity_in_invoice(text)
    # Longest match is "stand together chamber of commerce" which is an alias
    # of "stand together, inc."
    assert canonical == "stand together, inc."


def test_find_entity_in_invoice_short_name_word_boundary():
    # 'cva' is a 3-char entity — must not substring-match inside "cvalue"
    name, _ = find_entity_in_invoice("Cvalue Corp")
    assert name is None
    # but should match when whole-word
    name, _ = find_entity_in_invoice("Bill to: CVA action")
    assert name is not None


def test_find_entity_in_invoice_no_match():
    name, canonical = find_entity_in_invoice("Random Vendor LLC, Hollywood CA")
    assert name is None
    assert canonical is None
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd backend && pytest tests/test_entities.py -v
```

Expected: `ImportError` / `ModuleNotFoundError: No module named 'app.entities'`.

- [ ] **Step 3: Create `backend/app/entities.py`**

Copy the three data constants verbatim from
`updates-from-amy/ap_server 2.py:73-157`. Add the helper functions below.
The dataset is too long to inline in this plan — copy lines 73 through ~157
of Amy's file (the closing `}` of `ENTITY_ALIASES_FULL`). Do **not** copy
`ZIP_FP_VENDORS` (it lives on line 159 and is unused).

File skeleton:

```python
"""Entity / brand / alias reference data plus match helpers.

Data copied verbatim from updates-from-amy/ap_server 2.py (lines 73-157).
This is reference data — edit only when a new entity, alias, or brand is
introduced.
"""
import re


# ── Entity & brand data ──────────────────────────────────────────────────
ALL_ENTITY_NAMES = [
    # ... copy verbatim from updates-from-amy/ap_server 2.py:74-110
]

BRAND_TO_PARENT = {
    # ... copy verbatim from updates-from-amy/ap_server 2.py:112-130
}

ENTITY_ALIASES_FULL = {
    # ... copy verbatim from updates-from-amy/ap_server 2.py:133-157
}


# ── Helpers ──────────────────────────────────────────────────────────────
def normalize(s: str) -> str:
    """Lowercase, strip punctuation, drop common suffixes, collapse whitespace."""
    s = s.lower().strip()
    s = re.sub(r"[,\.\-]", " ", s)
    s = re.sub(r"\b(llc|inc|ltd|corp|co|dba|the|and|&)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def resolve_entity(name_lower: str) -> str:
    """Resolve a brand or alias to its canonical paying-entity name."""
    if name_lower in BRAND_TO_PARENT:
        return BRAND_TO_PARENT[name_lower]
    for canonical, aliases in ENTITY_ALIASES_FULL.items():
        if name_lower == canonical or name_lower in [a.lower() for a in aliases]:
            return canonical
    return name_lower


def entities_match(sage_entity: str, found_entity: str) -> bool:
    """True iff two entity strings refer to the same paying entity."""
    se = sage_entity.lower().strip()
    fe = found_entity.lower().strip()
    if not se or not fe:
        return False
    if se == fe:
        return True
    se_n = normalize(se)
    fe_n = normalize(fe)
    if se_n == fe_n:
        return True
    se_r = resolve_entity(se)
    fe_r = resolve_entity(fe)
    if se_r == fe_r:
        return True
    for canonical, aliases in ENTITY_ALIASES_FULL.items():
        all_names = [canonical] + [a.lower() for a in aliases]
        if se in all_names and fe in all_names:
            return True
        if se_r in all_names and fe_r in all_names:
            return True
        if se in all_names and fe_r == canonical:
            return True
        if fe in all_names and se_r == canonical:
            return True
    se_canonical = resolve_entity(se_n)
    fe_canonical = resolve_entity(fe_n)
    if se_canonical == fe_canonical and se_canonical != se_n:
        return True
    return False


def find_entity_in_invoice(text: str):
    """Search text for any known entity name.

    Returns (matched_alias, canonical_entity) or (None, None).
    Iterates ALL_ENTITY_NAMES sorted by length desc so longer matches win.
    Uses \\b word boundaries for short (≤5 char) names to avoid substring noise.
    """
    text_lower = text.lower()
    for name in sorted(ALL_ENTITY_NAMES, key=len, reverse=True):
        if len(name) < 3:
            continue
        if len(name) <= 5:
            pattern = r"\b" + re.escape(name) + r"\b"
        else:
            pattern = re.escape(name)
        if re.search(pattern, text_lower):
            return name, resolve_entity(name)
    return None, None
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd backend && pytest tests/test_entities.py -v
```

Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```
git add backend/app/entities.py backend/tests/test_entities.py
git commit -m "Add entities.py reference data + match helpers"
```

---

## Task 2: Add `_is_prf` and `_looks_like_brand_example` helpers to `checks.py`

**Files:**
- Modify: `backend/app/checks.py` (add two helpers near the top, after existing imports)
- Create: `backend/tests/test_checks_prf.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_checks_prf.py`:

```python
"""Tests for PRF detection and brand-field example rejection in checks.py."""
from app.checks import _is_prf, _looks_like_brand_example


def test_is_prf_detects_form():
    assert _is_prf("PAYMENT REQUEST FORM\nVendor Name: Foo")


def test_is_prf_case_insensitive_and_whitespace_tolerant():
    assert _is_prf("payment   request   form")


def test_is_prf_negative():
    assert not _is_prf("Invoice #1234\nTotal: $500")
    assert not _is_prf("")


def test_brand_example_ex_prefix():
    assert _looks_like_brand_example("ex. STCC, AFP, STF, ST-")
    assert _looks_like_brand_example("Ex STCC")


def test_brand_example_multi_abbrev_short():
    # 3+ comma-separated abbreviations under 40 chars looks like template text
    assert _looks_like_brand_example("STCC, AFP, STF")


def test_brand_example_trailing_dash():
    assert _looks_like_brand_example("ST-")


def test_brand_example_all_abbrev_pattern():
    assert _looks_like_brand_example("STCC, AFP")
    assert _looks_like_brand_example("ABCDE, FGHIJ")


def test_brand_legit_value_not_flagged():
    assert not _looks_like_brand_example("Charles Koch Foundation")
    assert not _looks_like_brand_example("STCC Music")
    assert not _looks_like_brand_example("Americans for Prosperity")
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd backend && pytest tests/test_checks_prf.py -v
```

Expected: `ImportError: cannot import name '_is_prf'` (or similar).

- [ ] **Step 3: Add helpers to `backend/app/checks.py`**

Open `backend/app/checks.py`. Just above the existing `def run_receipt_checks` (search for that line), add:

```python
import re  # may already be imported at top of file — verify and skip if so


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
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd backend && pytest tests/test_checks_prf.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```
git add backend/app/checks.py backend/tests/test_checks_prf.py
git commit -m "Add _is_prf and _looks_like_brand_example helpers to checks.py"
```

---

## Task 3: Add `_extract_billto` helper to `checks.py`

**Files:**
- Modify: `backend/app/checks.py` (add helper after the helpers from Task 2)
- Create: `backend/tests/test_checks_billto.py`

The current `checks.py` has an `extract_billto` (or similar) that uses a naive
`Bill To:` regex. We keep that fallback but prepend an address-block scan.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_checks_billto.py`:

```python
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
    # When nothing matches, return the first 150 chars
    text = "Random invoice text without bill-to information at all."
    result = _extract_billto(text)
    assert result.startswith("Random invoice text")
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd backend && pytest tests/test_checks_billto.py -v
```

Expected: `ImportError: cannot import name '_extract_billto'`.

- [ ] **Step 3: Add `_extract_billto` to `backend/app/checks.py`**

Add directly after `_looks_like_brand_example`:

```python
def _extract_billto(text: str) -> str:
    """Find recipient line by looking for an address block (street + ZIP).

    Strategy:
      1. Scan lines for a US ZIP pattern.
      2. From that line, walk back up to 6 lines to find a street or PO-box line.
      3. Walk back further to find the first non-title, non-attn, non-numeric
         candidate line — that's the recipient.
      4. Fall back to 'Bill To:' / 'To:' regex if no address block found.
      5. Final fallback: first 150 chars of text.
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    zip_pat    = re.compile(r"\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b")
    street_pat = re.compile(
        r"\b\d+\s+\w+[\w\s]*\s+"
        r"(?:blvd|boulevard|ave|avenue|st|street|rd|road|drive|dr|way|lane|ln|place|pl|suite|ste|floor)\b",
        re.IGNORECASE,
    )
    po_pat   = re.compile(r"\bP\.?O\.?\s+Box\s+\d+\b", re.IGNORECASE)
    skip_words = [
        "director","manager","officer","president","vice","senior","head of",
        "controller","accountant","treasurer","secretary","coordinator",
        "billing contact","attention","attn","contact","c/o",
    ]
    skip_pfx = re.compile(
        r"^(Mr\.?|Ms\.?|Mrs\.?|Dr\.?|Prof\.?|Attn:?|Attention:?|C/O|Re:|Dear|To:)\b",
        re.IGNORECASE,
    )
    for i, line in enumerate(lines):
        if not zip_pat.search(line):
            continue
        block = lines[max(0, i - 6):i + 1]
        sidx = next(
            (j for j, bl in enumerate(block) if street_pat.search(bl) or po_pat.search(bl)),
            None,
        )
        if sidx is None or sidx == 0:
            continue
        for k in range(sidx - 1, -1, -1):
            c = block[k].strip()
            if not c or len(c) < 3:
                continue
            if skip_pfx.match(c):
                continue
            if any(sw in c.lower() for sw in skip_words):
                continue
            if re.match(r"^[\d\s\-/\.,]+$", c):
                continue
            return c
    for pat in (r"(?:bill\s+to|billed\s+to|invoiced\s+to)\s*[:\n]\s*(.+)",
                r"^To:\s*\n?\s*(.+)"):
        m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
        if m:
            v = m.group(1).strip()
            if v and len(v) > 2:
                return v
    return text[:150]
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd backend && pytest tests/test_checks_billto.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```
git add backend/app/checks.py backend/tests/test_checks_billto.py
git commit -m "Add address-block bill-to extraction to checks.py"
```

---

## Task 4: Add `_extract_vendor_from_invoice` helper to `checks.py`

**Files:**
- Modify: `backend/app/checks.py` (add helper after `_extract_billto`)
- Create: `backend/tests/test_checks_vendor.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_checks_vendor.py`:

```python
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
    # Words from "Frost Brown Todd LLC dba FBT Gibbons LLP" — at least 60% of
    # the meaningful words (Frost, Brown, Todd, Gibbons) appearing in text
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd backend && pytest tests/test_checks_vendor.py -v
```

Expected: `ImportError: cannot import name '_extract_vendor_from_invoice'`.

- [ ] **Step 3: Add `_extract_vendor_from_invoice` to `backend/app/checks.py`**

Add directly after `_extract_billto`. The function uses `normalize` from
`entities.py`:

```python
from app.entities import normalize as _normalize_entity  # add to imports at top of file
# (If 'from . import entities' is preferred, use entities.normalize below.)


def _extract_vendor_from_invoice(text: str, sage_vendor: str):
    """Smart vendor-name extraction from PDF text.

    Returns (extracted_name | None, result_type) where result_type ∈
    {"match", "dba_match", "prf_blank", "no_text", "mismatch"}.
    """
    if not text or len(text.strip()) < 30:
        return None, "no_text"
    t = text.strip()

    # Payment Request Form — parse Vendor Name field
    if re.search(r"PAYMENT\s+REQUEST\s+FORM", t, re.IGNORECASE):
        m = re.search(r"Vendor\s+Name\s*:\s*\n(.*?)(?:\n|$)", t, re.IGNORECASE)
        if m:
            cand = m.group(1).strip()
            cand_alpha = re.sub(r"\W", "", cand)
            is_blank = (
                not cand_alpha
                or cand_alpha.upper() in ("NEW", "EXISTING", "NEWEXISTING")
                or len(cand_alpha) < 2
            )
            if is_blank:
                return None, "prf_blank"
            sage_norm = _normalize_entity(sage_vendor)
            cand_norm = _normalize_entity(cand)
            if sage_norm in cand_norm or cand_norm in sage_norm:
                return cand, "match"
            return cand, "mismatch"
        return None, "prf_blank"

    # DBA: SAGE vendor has "dba X" — find X anywhere in invoice
    dba_m = re.search(r"\bdba\s+(.+)", sage_vendor, re.IGNORECASE)
    if dba_m:
        dba_name = dba_m.group(1).strip()
        if _normalize_entity(dba_name) in _normalize_entity(t):
            return dba_name, "dba_match"

    # Full legal name (or pre-DBA portion) anywhere in invoice
    sage_norm = _normalize_entity(sage_vendor)
    sage_no_dba = re.sub(r"\s+dba\s+.+", "", sage_vendor, flags=re.IGNORECASE).strip()
    sage_no_dba_norm = _normalize_entity(sage_no_dba)
    if sage_norm in _normalize_entity(t) or sage_no_dba_norm in _normalize_entity(t):
        return sage_vendor, "match"

    # Remit-to / pay-to / make-checks-payable section
    remit_m = re.search(
        r"(?:remit\s+(?:payment\s+)?to|make\s+(?:checks?\s+)?(?:payable\s+)?to"
        r"|pay\s+to(?:\s+the\s+order\s+of)?|please\s+remit(?:\s+check)?\s+to"
        r"|send\s+(?:payment|check)\s+to)\s*:?\s*\n?\s*([^\n]+)",
        t, re.IGNORECASE,
    )
    if remit_m:
        rname = remit_m.group(1).strip()
        if rname and len(rname) > 2:
            rn = _normalize_entity(rname)
            if sage_norm in rn or sage_no_dba_norm in rn:
                return rname, "match"
            if dba_m and _normalize_entity(dba_m.group(1).strip()) in rn:
                return rname, "dba_match"

    # Fuzzy word match (≥60% of vendor words ≥4 chars present in first 800 chars)
    words = [w for w in sage_no_dba_norm.split() if len(w) > 3]
    if words:
        tn = _normalize_entity(t[:800])
        if sum(1 for w in words if w in tn) / len(words) >= 0.6:
            return sage_vendor, "match"

    return None, "mismatch"
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd backend && pytest tests/test_checks_vendor.py -v
```

Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```
git add backend/app/checks.py backend/tests/test_checks_vendor.py
git commit -m "Add PRF-aware vendor extraction to checks.py"
```

---

## Task 5: Rewrite `run_receipt_checks` to use new helpers and drop ZIP check

**Files:**
- Modify: `backend/app/checks.py` (rewrite the per-invoice check loop in `run_receipt_checks`)
- No new tests in this task — pure-logic helpers are already covered; the loop itself is integration-tested manually.

- [ ] **Step 1: Open `backend/app/checks.py` and locate the per-invoice loop in `run_receipt_checks`.**

Identify the existing checks. Today they include (roughly):
- ACH routing-number compare → `routing_mismatch`
- ACH account-number compare → `account_mismatch`
- ZIP-code compare → `zip_mismatch` ← **remove this entire block**
- vendor-name compare via `vendor_match()` → `vendor_mismatch`
- amount compare via `extract_total()` → `amount_mismatch`
- entity compare via `entity_match()` and `extract_billto()` → `entity_mismatch`

Plus a post-pass that strips flags by vendor allowlists `VENDOR_NAME_FP`,
`ENTITY_FP_VENDORS`, `ZIP_FP_VENDORS`.

- [ ] **Step 2: Replace the loop with the new pipeline.**

The rewritten body of `run_receipt_checks` for each invoice with PDF text:

```python
from app.entities import entities_match, find_entity_in_invoice  # add to imports

# ... inside run_receipt_checks, for each invoice that has fetched PDF text:

    # ── Remittance checks (receipt_flags) ─────────────────────────────────
    if is_ach or is_check:
        # existing routing comparison ...
        # existing account comparison ...
        pass
    # NOTE: ZIP-mismatch check intentionally removed (per AP team request).

    # ── Vendor-name check (invoice_flags) ─────────────────────────────────
    extracted, vendor_result = _extract_vendor_from_invoice(text, inv.get("vendor", ""))
    if vendor_result == "mismatch":
        inv["invoice_flags"].append({
            "type": "vendor_mismatch",
            "severity": "high",
            "label": "Vendor Name Mismatch",
            "detail": "SAGE: " + inv.get("vendor", "")
                      + " | PDF: " + (extracted or text[:60]).strip(),
        })

    # ── Amount check (invoice_flags) — skipped for PRFs ───────────────────
    if not _is_prf(text):
        pt = extract_total(text)
        st = float(inv.get("amount", 0) or 0)
        if pt and st and abs(pt - st) > 0.02:
            inv["invoice_flags"].append({
                "type": "amount_mismatch",
                "severity": "high",
                "label": "Amount Mismatch",
                "detail": "PDF total: $" + f"{pt:,.2f}" + " | SAGE: $" + f"{st:,.2f}",
            })

    # ── Bill-to entity check (invoice_flags) ──────────────────────────────
    if _is_prf(text):
        brand_m = re.search(r"Brand\s*:\s*([^\n\(]+)", text, re.IGNORECASE)
        if brand_m:
            raw_brand = brand_m.group(1).strip()
            if not _looks_like_brand_example(raw_brand) and len(raw_brand) >= 2:
                if not entities_match(inv.get("entity", ""), raw_brand):
                    inv["invoice_flags"].append({
                        "type": "entity_mismatch",
                        "severity": "medium",
                        "label": "Bill-To Entity Mismatch",
                        "detail": "SAGE entity: " + inv.get("entity", "")
                                  + " | PDF Brand field: " + raw_brand,
                    })
        # else: PRF brand field unreadable → skip entity check entirely
    else:
        billto_addr = _extract_billto(text)
        found_name, found_canonical = (None, None)
        if billto_addr and len(billto_addr.strip()) > 2:
            found_name, found_canonical = find_entity_in_invoice(billto_addr)
        if found_name is None:
            found_name, found_canonical = find_entity_in_invoice(text)
        if found_name is not None and not entities_match(
                inv.get("entity", ""), found_canonical):
            # Only flag if SAGE entity itself ISN'T anywhere in text
            _, sage_in_text = find_entity_in_invoice(text)
            if not (sage_in_text and entities_match(
                    inv.get("entity", ""), sage_in_text)):
                inv["invoice_flags"].append({
                    "type": "entity_mismatch",
                    "severity": "medium",
                    "label": "Bill-To Entity Mismatch",
                    "detail": "SAGE entity: " + inv.get("entity", "")
                              + " | PDF: " + found_name,
                })
```

Set `inv["receipt_checked"] = True` and `inv["invoice_checked"] = True` as the
current code does — wiring unchanged.

- [ ] **Step 3: Update the post-pass allowlist filter.**

Find the block (at the end of `run_receipt_checks`) that currently strips
flags by vendor allowlists. Replace with:

```python
for inv in invoices:
    v = inv["vendor"]
    inv["invoice_flags"] = [
        f for f in inv["invoice_flags"]
        if not (f["type"] == "vendor_mismatch" and v in VENDOR_NAME_FP)
        and not (f["type"] == "entity_mismatch" and v in ENTITY_FP_VENDORS)
    ]
    # NOTE: receipt_flags filtering by ZIP_FP_VENDORS removed — no ZIP flag emitted.
```

- [ ] **Step 4: Remove the `ZIP_FP_VENDORS` constant and the old helpers.**

Delete from `checks.py`:
- The line `ZIP_FP_VENDORS = {...}` (if it lives in this file).
- The old `entity_match()` function (replaced by `entities_match`).
- The old `vendor_match()` function (replaced by `_extract_vendor_from_invoice`).
- The old inline `ENTITY_ALIASES` dict (now in `entities.py`).
- If there is an old `extract_billto` (no underscore) in this file, delete it —
  the new `_extract_billto` is the only one we use.

Update `ENTITY_FP_VENDORS` to remove `"People Who Think, LLC"`:

```python
ENTITY_FP_VENDORS = {"Traypml, Inc.", "May Adam Gerdes & Thompson LLP"}
```

- [ ] **Step 5: Run the full test suite to confirm nothing else broke.**

```
cd backend && pytest -v
```

Expected: all tests in `test_entities.py`, `test_checks_prf.py`,
`test_checks_billto.py`, `test_checks_vendor.py`, `test_api.py`,
`test_parser.py` PASS. If any pre-existing test relied on `entity_match` or
`vendor_match` directly, it will fail — adapt the test to use the new helpers
or remove if obsolete.

- [ ] **Step 6: Commit**

```
git add backend/app/checks.py
git commit -m "Rewrite run_receipt_checks: drop ZIP check, PRF-aware vendor/amount/entity"
```

---

## Task 6: Rewrite SharePoint module — new public API + helpers

**Files:**
- Modify: `backend/app/sharepoint.py` (full rewrite of public surface; keep token cache)
- Create: `backend/tests/test_sharepoint.py`

The old `search_sf_approved(p_numbers)` is replaced by
`search_supporting_docs(invoices)`. Old function is **removed** (only one
caller, updated in Task 7).

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_sharepoint.py`:

```python
"""Tests for backend/app/sharepoint.py — matching + dispatch."""
import os
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
    # When both could match, P-number wins
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
    # With tier 2 disabled and no P-number, no match
    assert result == {}
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd backend && pytest tests/test_sharepoint.py -v
```

Expected: `ImportError` on `_normalize_for_match`, `_matches_invoice`, or
`search_supporting_docs`.

- [ ] **Step 3: Rewrite `backend/app/sharepoint.py`**

Replace the entire file contents:

```python
"""Microsoft Graph / SharePoint integration for supporting-document lookup.

Credentials and config read from environment variables:
  AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET   — Graph auth
  SP_DRIVE_ID                                             — P2P document library
  SP_SEARCH_FOLDER                                        — folder root to search
  SP_MIN_BILL_LENGTH                                      — min normalized bill len
  SP_BILL_TIER_ENABLED                                    — toggle bill-number tier
  SP_SEARCH_CONCURRENCY                                   — Graph thread-pool size

Falls back to /data/sp_map.json (or app-dir sp_map.json) if Azure creds absent.
"""
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

_sp_token: Optional[str] = None
_sp_token_expiry: float = 0
_sp_token_lock = threading.Lock()


# ── Config helpers ────────────────────────────────────────────────────────
def _drive_id() -> str:
    return os.getenv(
        "SP_DRIVE_ID",
        "b!-7E_08zvtUeK20bVTeozH7bOrP-DTWBPjI-Ihlrg_FvsAjWNnMCgS7Xt5bJKR1Ed",
    )


def _search_folder() -> str:
    return os.getenv("SP_SEARCH_FOLDER", "AP/Daily Payment Approvals")


def _min_bill_length() -> int:
    try:
        return int(os.getenv("SP_MIN_BILL_LENGTH", "4"))
    except ValueError:
        return 4


def _bill_tier_enabled() -> bool:
    return os.getenv("SP_BILL_TIER_ENABLED", "true").lower() in ("true", "1", "yes")


def _concurrency() -> int:
    try:
        return max(1, int(os.getenv("SP_SEARCH_CONCURRENCY", "8")))
    except ValueError:
        return 8


# ── Auth ──────────────────────────────────────────────────────────────────
def _get_sp_token() -> Optional[str]:
    global _sp_token, _sp_token_expiry
    with _sp_token_lock:
        if _sp_token and time.time() < _sp_token_expiry - 60:
            return _sp_token
        tenant_id     = os.getenv("AZURE_TENANT_ID", "")
        client_id     = os.getenv("AZURE_CLIENT_ID", "")
        client_secret = os.getenv("AZURE_CLIENT_SECRET", "")
        if not all([tenant_id, client_id, client_secret]):
            return None
        try:
            resp = requests.post(
                f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
                data={
                    "grant_type":    "client_credentials",
                    "client_id":     client_id,
                    "client_secret": client_secret,
                    "scope":         "https://graph.microsoft.com/.default",
                },
                timeout=15, verify=False,
            )
            if resp.status_code == 200:
                data = resp.json()
                _sp_token        = data["access_token"]
                _sp_token_expiry = time.time() + data.get("expires_in", 3600)
                return _sp_token
            log.warning("SP token request returned %s", resp.status_code)
        except Exception as e:
            log.warning("SP auth error: %s", e)
        return None


# ── sp_map.json fallback ──────────────────────────────────────────────────
def _load_sp_map() -> dict:
    for path in [Path("/data/sp_map.json"), Path(__file__).parent / "sp_map.json"]:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning("Could not load %s: %s", path, e)
    return {}


# ── Matching primitives ───────────────────────────────────────────────────
def _normalize_for_match(s: str) -> str:
    """Lowercase + strip all non-alphanumeric chars."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _matches_invoice(filename: str, vendor: str, bill: str, p_number: str):
    """Match a SharePoint filename to an invoice.

    Tier 1: P-number in filename
    Tier 2: bill number in filename (≥ SP_MIN_BILL_LENGTH chars after normalization)
    Returns (matched: bool, reason: str | None).
    """
    fn_norm = _normalize_for_match(filename)
    min_len = _min_bill_length()
    if p_number:
        pn = _normalize_for_match(p_number)
        if len(pn) >= min_len and pn in fn_norm:
            return True, "P-number"
    if _bill_tier_enabled() and bill:
        bn = _normalize_for_match(bill)
        if len(bn) >= min_len and bn in fn_norm:
            return True, "Bill number"
    return False, None


# ── sp_map.json search path ───────────────────────────────────────────────
def _search_via_sp_map(invoices: list[dict], sp_map: dict) -> dict[str, list[dict]]:
    """Match invoices against sp_map.json.

    Supports both formats:
      - New: {filename.pdf: url}  → match filename against invoices
      - Legacy: {P-XXXXX: url}    → P-number lookup only
    """
    results: dict[str, list[dict]] = {}
    is_new = any(k.lower().endswith(".pdf") for k in sp_map)
    if is_new:
        for inv in invoices:
            key = inv["vendor"] + "||" + inv["bill"]
            matches = []
            for filename, url in sp_map.items():
                matched, reason = _matches_invoice(
                    filename, inv["vendor"], inv["bill"], inv.get("p_number", "")
                )
                if matched:
                    matches.append({"name": filename, "url": url, "reason": reason})
            if matches:
                results[key] = matches
    else:
        p_map = {k.upper(): ([v] if isinstance(v, str) else v) for k, v in sp_map.items()}
        for inv in invoices:
            pn = inv.get("p_number", "").upper()
            if pn and pn in p_map:
                key = inv["vendor"] + "||" + inv["bill"]
                results[key] = [
                    {"name": pn, "url": u, "reason": "P-number"} for u in p_map[pn]
                ]
    return results


# ── Azure Graph search path ───────────────────────────────────────────────
def _graph_search(token: str, query: str) -> list[dict]:
    """One Graph search call. Returns raw {name, webUrl} items or []."""
    hdrs = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    folder = _search_folder()
    drive_id = _drive_id()
    url = (
        f"{GRAPH_BASE}/drives/{drive_id}/root:/{folder}:"
        f"/search(q='{query}')?$select=name,webUrl&$top=50"
    )
    try:
        r = requests.get(url, headers=hdrs, timeout=20, verify=False)
        if r.status_code == 200:
            return r.json().get("value", [])
        log.warning("[SP] Graph search '%s' returned %s", query, r.status_code)
    except Exception as e:
        log.warning("[SP] Graph search error '%s': %s", query, e)
    return []


def _search_via_azure(invoices: list[dict], token: str) -> dict[str, list[dict]]:
    """Tier 1 + Tier 2 Graph search across all invoices, deduped + concurrent."""
    queries: set[str] = set()
    for inv in invoices:
        if inv.get("p_number"):
            queries.add(inv["p_number"])
        if _bill_tier_enabled() and inv.get("bill"):
            bn = _normalize_for_match(inv["bill"])
            if len(bn) >= _min_bill_length():
                queries.add(inv["bill"])

    query_results: dict[str, list[dict]] = {}
    if queries:
        with ThreadPoolExecutor(max_workers=_concurrency()) as ex:
            futures = {ex.submit(_graph_search, token, q): q for q in queries}
            for fut in as_completed(futures):
                q = futures[fut]
                query_results[q] = fut.result()

    results: dict[str, list[dict]] = {}
    for inv in invoices:
        key = inv["vendor"] + "||" + inv["bill"]
        seen_urls = set()
        for q, items in query_results.items():
            for item in items:
                fname = item.get("name", "")
                web   = item.get("webUrl", "")
                if not fname.lower().endswith(".pdf"):
                    continue
                if web in seen_urls:
                    continue
                matched, reason = _matches_invoice(
                    fname, inv["vendor"], inv["bill"], inv.get("p_number", "")
                )
                if matched:
                    results.setdefault(key, []).append(
                        {"name": fname, "url": web, "reason": reason}
                    )
                    seen_urls.add(web)
    return results


# ── Public entry point ────────────────────────────────────────────────────
def search_supporting_docs(invoices: list[dict]) -> dict[str, list[dict]]:
    """Return {f"{vendor}||{bill}": [{name, url, reason}, ...]}.

    Uses Azure Graph if creds are set, else sp_map.json, else returns {}.
    """
    if not invoices:
        return {}
    token = _get_sp_token()
    if token:
        log.info("[SP] Searching '%s' via Azure Graph", _search_folder())
        results = _search_via_azure(invoices, token)
        log.info(
            "[SP] Found %d files across %d invoices",
            sum(len(v) for v in results.values()), len(results),
        )
        return results
    sp_map = _load_sp_map()
    if sp_map:
        log.info("[SP] Using sp_map.json fallback")
        return _search_via_sp_map(invoices, sp_map)
    log.info("[SP] No Azure creds and no sp_map.json — SP lookup skipped")
    return {}
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd backend && pytest tests/test_sharepoint.py -v
```

Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```
git add backend/app/sharepoint.py backend/tests/test_sharepoint.py
git commit -m "Rewrite sharepoint.py: Daily Payment Approvals + bill-number tier matching"
```

---

## Task 7: Add `sp_docs` column to the DB and wire it through `main.py`

**Files:**
- Modify: `backend/app/models.py` (add `sp_docs` Column)
- Modify: `backend/app/main.py` (startup ALTER, `_run_checks_background`, `InvoiceOut`, row→dict serializer)

- [ ] **Step 1: Add column to `Invoice` model.**

In `backend/app/models.py`, find the `Invoice` class and add the new column
directly after the existing `sp_url` line:

```python
    sp_url = Column(Text, default="")           # existing
    sp_docs = Column(Text, default="[]")        # NEW — JSON array of all matches
```

- [ ] **Step 2: Add startup ALTER statement.**

In `backend/app/main.py`, find the existing block of
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements (around `main.py:41`).
Add one new line in the same block:

```python
conn.execute(text(
    "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS sp_docs TEXT DEFAULT '[]'"
))
```

- [ ] **Step 3: Replace the SharePoint import.**

In `backend/app/main.py:22`, find:

```python
from .sharepoint import search_sf_approved
```

Replace with:

```python
from .sharepoint import search_supporting_docs
```

- [ ] **Step 4: Replace the SharePoint call block in `_run_checks_background`.**

In `backend/app/main.py:360-383`, find and DELETE the existing block:

```python
        # SharePoint P-number lookup (fast — one API call)
        p_numbers = list({inv["p_number"] for inv in invoices if inv.get("p_number")})
        if p_numbers:
            sp_map = search_sf_approved(p_numbers)
            if sp_map:
                for inv_dict in invoices:
                    pnum = inv_dict.get("p_number", "")
                    if pnum and pnum in sp_map:
                        inv_dict["sp_url"] = sp_map[pnum]
                for inv_dict in invoices:
                    if not inv_dict.get("sp_url"):
                        continue
                    rows = (
                        db.query(Invoice)
                        .filter(
                            Invoice.upload_id == upload_id,
                            Invoice.org == inv_dict["org"],
                            Invoice.bill == inv_dict["bill"],
                        )
                        .all()
                    )
                    for row in rows:
                        row.sp_url = inv_dict["sp_url"]
                db.commit()
```

Replace with:

```python
        # SharePoint multi-doc lookup (P-number tier + bill-number tier)
        sp_results = search_supporting_docs(invoices)
        for inv_dict in invoices:
            key  = inv_dict["vendor"] + "||" + inv_dict["bill"]
            docs = sp_results.get(key, [])
            inv_dict["sp_docs"] = docs
            inv_dict["sp_url"]  = docs[0]["url"] if docs else inv_dict.get("sp_url", "")
        # Note: DB write of sp_url / sp_docs happens in the consolidated
        # persist loop below (after run_receipt_checks).
```

- [ ] **Step 5: Update the DB persist loop to write `sp_url` and `sp_docs`.**

In `backend/app/main.py:398-402`, find:

```python
            for row in rows:
                row.receipt_checked = inv_dict.get("receipt_checked", False)
                row.receipt_flags   = json.dumps(inv_dict.get("receipt_flags", []))
                row.invoice_checked = inv_dict.get("invoice_checked", False)
                row.invoice_flags   = json.dumps(inv_dict.get("invoice_flags", []))
```

Replace with:

```python
            for row in rows:
                row.sp_url          = inv_dict.get("sp_url", row.sp_url)
                row.sp_docs         = json.dumps(inv_dict.get("sp_docs", []))
                row.receipt_checked = inv_dict.get("receipt_checked", False)
                row.receipt_flags   = json.dumps(inv_dict.get("receipt_flags", []))
                row.invoice_checked = inv_dict.get("invoice_checked", False)
                row.invoice_flags   = json.dumps(inv_dict.get("invoice_flags", []))
```

- [ ] **Step 6: Add `sp_docs` to the `InvoiceOut` Pydantic model.**

Find `InvoiceOut` (around `main.py:144`). Add a new field:

```python
class InvoiceOut(BaseModel):
    ...
    sp_url: str = ""
    sp_docs: list[dict] = []   # NEW
    ...
```

- [ ] **Step 7: Add `sp_docs` to the row→dict serializer.**

Find the function/expression that converts `Invoice` ORM rows to dicts for
the API (around `main.py:241`). Add the new key:

```python
"sp_url":  inv.sp_url or "",
"sp_docs": json.loads(inv.sp_docs) if inv.sp_docs else [],
```

- [ ] **Step 8: Run the test suite.**

```
cd backend && pytest -v
```

Expected: all tests PASS. The fresh-DB fixture in `conftest.py` recreates
all tables via `Base.metadata.create_all`, so SQLite picks up the new
`sp_docs` column automatically.

If `test_api.py` or `test_parser.py` fails due to a missing `sp_docs` field
in fixture data or assertion, update those assertions to allow an empty list.

- [ ] **Step 9: Commit**

```
git add backend/app/models.py backend/app/main.py
git commit -m "Add sp_docs column + wire multi-doc SharePoint results through main.py"
```

---

## Task 8: Update env config

**Files:**
- Modify: `.env.example`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add new vars to `.env.example`.**

Open `.env.example` and append:

```bash

# SharePoint search (new in this release)
SP_SEARCH_FOLDER=AP/Daily Payment Approvals
SP_MIN_BILL_LENGTH=4
SP_BILL_TIER_ENABLED=true
SP_SEARCH_CONCURRENCY=8
```

- [ ] **Step 2: Add new vars to `docker-compose.yml`.**

Open `docker-compose.yml` and inside the `web` service's `environment:`
block (right after the existing `AZURE_*` lines), add:

```yaml
      SP_SEARCH_FOLDER:      ${SP_SEARCH_FOLDER:-AP/Daily Payment Approvals}
      SP_MIN_BILL_LENGTH:    ${SP_MIN_BILL_LENGTH:-4}
      SP_BILL_TIER_ENABLED:  ${SP_BILL_TIER_ENABLED:-true}
      SP_SEARCH_CONCURRENCY: ${SP_SEARCH_CONCURRENCY:-8}
```

- [ ] **Step 3: Validate compose file syntax.**

```
docker compose config > /dev/null
```

Expected: no output, exit 0.

- [ ] **Step 4: Commit**

```
git add .env.example docker-compose.yml
git commit -m "Add SP_SEARCH_FOLDER / SP_MIN_BILL_LENGTH / SP_BILL_TIER_ENABLED / SP_SEARCH_CONCURRENCY env vars"
```

---

## Task 9: Frontend — rename "SF Doc" column to "SP Docs" and render multi-doc

**Files:**
- Modify: `frontend/index.html`

No JS test harness — manually verified via the dev environment in Task 13.

- [ ] **Step 1: Rename the header.**

Open `frontend/index.html`. Find:

```html
<th>SF Doc</th>
```

Replace with:

```html
<th>SP Docs</th>
```

- [ ] **Step 2: Replace the single-link rendering with multi-doc.**

Find the JS that renders the SF-Doc cell. It currently looks roughly like:

```js
// approximately around the per-row render function
let sp = '';
if (pMatch && sharepointFiles[pMatch[0].toUpperCase()]) {
  sp = '<a class="sp-link" href="' + sharepointFiles[pMatch[0].toUpperCase()]
       + '" target="_blank" style="font-size:11.5px;padding:4px 10px;">📎 SF Doc</a>';
} else if (pMatch) {
  sp = '<span class="sp-auto-badge" style="font-size:11px;">🔍 ' + pMatch[0] + '</span>';
}
```

Replace with (use the existing template's string-concat style):

```js
var spDocs = (inv.sp_docs && inv.sp_docs.length > 0)
  ? inv.sp_docs
  : (inv.sp_url
       ? [{name: 'SF Doc', url: inv.sp_url, reason: ''}]
       : []);
var sp = '';
if (spDocs.length > 0) {
  sp = spDocs.map(function(doc){
    var label = esc(
      doc.name.replace(/^(BP|STT|STF|CKF|AFP|AFPF|STC|BRI|STB|STMSE)-/i, '')
              .replace(/_/g, ' ')
              .replace(/\.pdf$/i, '')
              .substring(0, 30)
    );
    var tooltip = doc.reason ? ' title="Matched by ' + esc(doc.reason) + '"' : '';
    return '<a class="sp-link"' + tooltip + ' href="' + esc(doc.url)
           + '" target="_blank" style="font-size:11.5px;padding:4px 10px;'
           + 'margin:1px 2px;display:inline-block;">📎 ' + label + '</a>';
  }).join(' ');
} else if (pMatch) {
  sp = '<span class="sp-auto-badge" style="font-size:11px;">🔍 ' + pMatch[0] + '</span>';
}
```

- [ ] **Step 3: Commit**

```
git add frontend/index.html
git commit -m "Rename SF Doc column to SP Docs and render multi-doc results"
```

---

## Task 10: Frontend — merge KPI counts (receipt + invoice flags)

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: Update the top-of-page KPI tile.**

Find the JS block that computes the "Receipt Discrepancies" KPI. It
currently looks something like:

```js
const receiptFlagged = invoiceData.filter(i => i.receipt_flags && i.receipt_flags.length > 0);
const receiptHigh = receiptFlagged.filter(i => i.receipt_flags.some(f => f.severity === 'high')).length;
const receiptMed  = receiptFlagged.filter(i => i.receipt_flags.some(f => f.severity === 'medium')
    && !i.receipt_flags.some(g => g.severity === 'high')).length;
```

Replace with:

```js
// Receipt Discrepancies KPI counts BOTH receipt_flags (remittance) AND
// invoice_flags (mismatches).
const receiptFlagged = invoiceData.filter(i =>
  (i.receipt_flags && i.receipt_flags.length > 0) ||
  (i.invoice_flags && i.invoice_flags.length > 0)
);
const allFlags = invoiceData.flatMap(i =>
  [...(i.receipt_flags || []), ...(i.invoice_flags || [])]
);
const receiptHigh = allFlags.filter(f => f.severity === 'high').length;
const receiptMed  = allFlags.filter(f => f.severity === 'medium').length;
```

- [ ] **Step 2: Update the per-org rollup counts.**

In the same file, find the per-org table's rollup that currently computes
`rHigh` and `rMed` from `receipt_flags` only:

```js
const rHigh = orgInvs.filter(i => i.receipt_flags && i.receipt_flags.some(f => f.severity === 'high')).length;
const rMed  = orgInvs.filter(i => i.receipt_flags && i.receipt_flags.some(f => f.severity === 'medium')
    && !i.receipt_flags.some(f => f.severity === 'high')).length;
```

Replace with:

```js
const rHigh = orgInvs.filter(i =>
  [...(i.receipt_flags || []), ...(i.invoice_flags || [])].some(f => f.severity === 'high')
).length;
const rMed = orgInvs.filter(i => {
  const all = [...(i.receipt_flags || []), ...(i.invoice_flags || [])];
  return all.some(f => f.severity === 'medium') && !all.some(f => f.severity === 'high');
}).length;
```

- [ ] **Step 3: Commit**

```
git add frontend/index.html
git commit -m "Merge receipt + invoice flag counts in KPI and per-org rollups"
```

---

## Task 11: Frontend — add "Receipt" column to per-org table

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: Add the header cell.**

In the per-org table header (different from the top-level review table), find:

```html
<th>Vendor</th><th>Bill #</th><th>Description</th><th>Invoice Date</th><th>Due Date</th><th>Amount</th><th>W-9 Type</th><th>Status</th><th>Notes</th><th>Attachments</th>
```

Insert `<th>Receipt</th>` between `W-9 Type` and `Status`:

```html
<th>Vendor</th><th>Bill #</th><th>Description</th><th>Invoice Date</th><th>Due Date</th><th>Amount</th><th>W-9 Type</th><th>Receipt</th><th>Status</th><th>Notes</th><th>Attachments</th>
```

- [ ] **Step 2: Add the row cell.**

Find the per-org row template (it currently builds the row string in the
same order as the header). Locate the section that produces the W-9 cell
and add a Receipt cell directly after it:

```js
var receiptCell = '';
if (inv.receipt_url) {
  var pdfProxyUrl = PROXY_URL + '/pdf?url=' + encodeURIComponent(inv.receipt_url);
  receiptCell = '<a class="sp-link" href="' + pdfProxyUrl + '" target="_blank"'
                + ' style="font-size:11px;padding:3px 9px;">📄 View Receipt</a>';
}
// Append <td>${receiptCell}</td> to the row HTML, between W-9 and Status.
```

In whichever expression assembles the per-row HTML, insert the new cell:

```js
+ '<td>' + receiptCell + '</td>'
```

between the existing W-9 cell and Status cell.

- [ ] **Step 3: Commit**

```
git add frontend/index.html
git commit -m "Add Receipt column to per-org table"
```

---

## Task 12: Frontend — normalize hold-vendor matching

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: Find the hold-list matching block.**

Search for the JS that determines which invoices are on hold by comparing
to `holdListData`. The current logic uses a `Set` built from hold-vendor
names lowercased.

Replace it with normalization that:
- strips leading `1.) ` / `2.) ` numeric-list prefix from hold-vendor names
- matches on both raw-lowercase and a normalized form

```js
function normVendor(s) {
  return s.toLowerCase()
          .replace(/[,\.\-]/g, ' ')
          .replace(/\b(llc|inc|ltd|corp|co|dba)\b/g, '')
          .replace(/\s+/g, ' ')
          .trim();
}

// When ingesting hold rows, clean the vendor name once:
holdListData = holdListData.map(function(h){
  return Object.assign({}, h, {
    vendor: (h.vendor || '').replace(/^\d+\.\)\s*/, '').trim()
  });
});

const holdSet = new Set(
  holdListData.flatMap(function(h){
    return [h.vendor.toLowerCase(), normVendor(h.vendor)];
  })
);

// Per-invoice on_hold check:
invoiceData.forEach(function(inv){
  var vl = (inv.vendor || '').toLowerCase();
  var vn = normVendor(inv.vendor || '');
  inv.on_hold = holdSet.has(vl) || holdSet.has(vn);
});
```

- [ ] **Step 2: Commit**

```
git add frontend/index.html
git commit -m "Normalize hold-vendor matching: strip list prefix + canonical form"
```

---

## Task 13: Run full test suite + manual dev verification

**Files:** none — verification only.

- [ ] **Step 1: Run the full backend test suite.**

```
cd backend && pytest -v
```

Expected: all tests PASS — `test_entities.py` (11), `test_checks_prf.py` (8),
`test_checks_billto.py` (7), `test_checks_vendor.py` (11),
`test_sharepoint.py` (11), plus the pre-existing `test_api.py` and
`test_parser.py`.

- [ ] **Step 2: Bring up the stack locally.**

```
docker compose down -v
docker compose up --build
```

Wait for the `web` service to log `Application startup complete`. The
startup ALTER will add the `sp_docs` column to the SQLite/Postgres `invoices`
table.

- [ ] **Step 3: Verify the schema migration.**

```
docker compose exec db psql -U ap_user -d ap_review -c "\d invoices" | grep sp_docs
```

Expected: a line like `sp_docs | text | default '[]'::text`.

- [ ] **Step 4: Upload a SAGE export and verify.**

Open `http://localhost:8000` in a browser. Upload a recent `AP_Payments_*.xlsx`.
After processing completes, verify in the UI:

| Check | Expected |
|---|---|
| **SP Docs column header** | Renders "SP Docs", not "SF Doc". |
| **Multi-doc rendering** | Invoices with multiple SP matches show multiple badges, each linking to a different PDF. Hovering shows "Matched by P-number" or "Matched by Bill number". |
| **KPI tile** | "Receipt Discrepancies" count equals `# invoices with receipt_flags + invoice_flags`. |
| **No ZIP-mismatch flags** | Filter receipts; verify no flag of type `zip_mismatch` appears. |
| **PRFs don't flag entity-mismatch from template text** | Find a PRF invoice; verify no `entity_mismatch` flag caused by "ex. STCC, AFP..." text. |
| **PRFs don't flag amount-mismatch** | Find a PRF; verify no `amount_mismatch` flag. |
| **Per-org table Receipt column** | New "Receipt" column between W-9 Type and Status; "📄 View Receipt" link works for invoices with receipt_url. |
| **Hold matching** | Hold-list vendors with `1.) Vendor Name` prefix correctly mark matching invoices as on-hold. |

- [ ] **Step 5: Test the env-var safety toggle.**

Stop the stack. Set `SP_BILL_TIER_ENABLED=false` in `.env`. Restart:

```
docker compose down
docker compose up
```

Re-upload the same file. Verify:
- Invoices that previously matched by Bill number now have no SP doc.
- Invoices that matched by P-number still have their SP doc.

Restore `SP_BILL_TIER_ENABLED=true` (or remove from `.env`) when done.

- [ ] **Step 6: Final summary commit (no code changes — just a doc note).**

If you discovered any spec deviations during verification, file them as a
follow-up. Otherwise this task has no commit.

---

## Self-review checklist (run before opening the PR)

- [ ] All 9 behavior changes from the spec are implemented (SP folder switch, bill-number tier, multi-doc, ZIP-check drop, PRF amount skip, permissive entity match, KPI merge, frontend additions, hold normalization).
- [ ] `entities.py` is purely data + helpers; no I/O.
- [ ] `sharepoint.py` no longer exports `search_sf_approved`; only `search_supporting_docs`.
- [ ] `checks.py` no longer references `ZIP_FP_VENDORS`, `entity_match`, `vendor_match`, or the inline `ENTITY_ALIASES` dict.
- [ ] `main.py` no longer references `search_sf_approved` or `_scan_p_numbers`.
- [ ] `models.py` has `sp_docs = Column(Text, default="[]")`.
- [ ] Startup ALTER adds `sp_docs` column to existing DBs.
- [ ] `InvoiceOut` and row→dict serializer include `sp_docs`.
- [ ] `.env.example` and `docker-compose.yml` carry the four new env vars.
- [ ] All new tests are in place and pass; existing tests still pass.
- [ ] Manual dev-environment verification (Task 13) passed.
