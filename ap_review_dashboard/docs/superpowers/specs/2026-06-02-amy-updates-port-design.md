# Port Amy's AP Dashboard Updates into the FastAPI Backend

**Date:** 2026-06-02
**Status:** Approved
**Author:** JT (with Claude)

## Background

Amy maintains a single-file Python HTTP server prototype of the AP Review Dashboard in
`amy/ap_server.py` + `amy/dashboard_template.html`. The actual deployed application
is a FastAPI + Postgres + Docker port living under `backend/` + `frontend/`.

Amy delivered a new revision of her prototype in `updates-from-amy/` containing a
substantial set of new features and behavior changes. The `amy/` directory is no
longer used; her files should be treated as a **specification** of the changes to
port into the FastAPI backend, not files to copy in.

This spec captures exactly what to port, what to leave behind, and how to organize
the changes.

## Goals

- Land all of Amy's intended user-facing improvements in the deployed FastAPI app.
- Keep file boundaries that already exist in the backend (`parser.py`,
  `checks.py`, `sharepoint.py`, `main.py`); add one new file for entity reference
  data.
- Make the new SharePoint search strategy and bill-number tier configurable via
  env vars so we can dial it down without code revert if results are noisy.
- Include unit tests for the new logic so future iteration on entity tables and
  PRF detection doesn't silently regress behavior.

## Non-Goals

- Keeping the `amy/` prototype updated. It is deprecated.
- Porting Amy's `RESULT_CACHE` / 303-redirect upload flow — FastAPI's existing
  `/api/upload` + background-task flow is already in place.
- Porting client-side xlsx fallback parsing — the deployed server is always
  reachable for end users.
- Porting the `/ping` endpoint — FastAPI exposes its own health.
- Updating Amy's `IT_Setup_Instructions.md` / `config.json.template` — those
  assume a standalone Windows on-prem deployment of her prototype, which we don't
  use.

## Behavior changes (all adopted from Amy's prototype)

1. **SharePoint folder switch.** Search `AP/Daily Payment Approvals` (with
   subfolders) instead of `AP/Salesforce Payment Processing/SF Accounting
   Approved`.
2. **Two-tier filename matching.** Tier 1: P-number in filename (existing).
   Tier 2 (new): bill number in filename, after normalizing both filename and
   bill to lowercase-alphanumeric-only, with a configurable minimum normalized
   bill length (default 4).
3. **Multiple SP docs per invoice.** Return all matches, each tagged with
   `reason: "P-number" | "Bill number"`. Show every match in the dashboard.
4. **Drop ZIP-mismatch check.** Stop emitting the receipt-side ZIP flag.
   Removed at AP team's request.
5. **Skip amount check for PRFs.** If the PDF text contains
   `PAYMENT REQUEST FORM`, do not run the SAGE-vs-PDF amount comparison.
6. **Permissive entity match.** Two-pass entity detection: (a) extract bill-to
   from an address block (street + ZIP), then full text; (b) only flag
   `entity_mismatch` if a *known* ST entity is found AND it differs from the
   SAGE entity AND the SAGE entity itself doesn't also appear anywhere in the
   text. For PRFs, use the `Brand:` field with template/example-text rejection.
7. **Merge KPI counts.** Frontend "Receipt Discrepancies" tile counts both
   `receipt_flags` (remittance issues: routing/account mismatches) and
   `invoice_flags` (vendor/entity/amount mismatches). Same combined logic for
   per-org rollup counts.
8. **Frontend additions.** Rename "SF Doc" column → "SP Docs"; multi-doc
   rendering with shortened filenames and `reason` tooltips; per-org table gets
   a "Receipt" column with the existing PDF-proxy link.
9. **Hold matching normalization.** Strip `1.) ` / `2.) ` numeric-list prefixes
   from hold-list vendor names before matching; compare on both raw-lowercase
   and a normalized form.

## Design

### Approach: drop-in upgrades to existing modules

Stick with current file boundaries. One new file (`entities.py`) for the
entity reference dataset; modifications to `checks.py`, `sharepoint.py`,
`models.py`, `main.py`, and `frontend/index.html`. `parser.py` is unchanged
(it already strips HTML-wrapped receipt URLs).

### Data model

Single new column on `invoices`:

```python
sp_docs = Column(Text, default="[]")  # JSON array
```

`sp_docs` holds the full list of SharePoint matches for the invoice:

```json
[
  {"name": "BP-12345_invoice.pdf",
   "url":  "https://thecss.sharepoint.com/...",
   "reason": "P-number"},
  {"name": "STT-0042-receipt.pdf",
   "url":  "https://thecss.sharepoint.com/...",
   "reason": "Bill number"}
]
```

`sp_url` is kept as the denormalized first-match URL so any consumer that
wants a single link doesn't need to parse JSON.

**Migration:** the existing pattern in `main.py` startup — idempotent
`ALTER TABLE invoices ADD COLUMN IF NOT EXISTS sp_docs TEXT DEFAULT '[]'`.
No external migration tool. No backfill needed.

### `backend/app/entities.py` — new file

Pure data + match helpers. No I/O. Easy to unit-test.

```python
ALL_ENTITY_NAMES: list[str]              # ~80 canonical + alias strings
BRAND_TO_PARENT: dict[str, str]          # brand → canonical paying entity
ENTITY_ALIASES_FULL: dict[str, list[str]]  # canonical → aliases

def normalize(s: str) -> str
def resolve_entity(name_lower: str) -> str
def entities_match(sage: str, found: str) -> bool
def find_entity_in_invoice(text: str) -> tuple[str | None, str | None]
    # iterates ALL_ENTITY_NAMES sorted by length desc;
    # uses \b word boundaries for short (≤5 char) entities
```

The dataset content is copied verbatim from `updates-from-amy/ap_server 2.py`
(`ALL_ENTITY_NAMES`, `BRAND_TO_PARENT`, `ENTITY_ALIASES_FULL`).

### `backend/app/sharepoint.py` — rewritten public surface

```python
def search_supporting_docs(invoices: list[dict]) -> dict[str, list[dict]]:
    """Return {f"{vendor}||{bill}": [{name, url, reason}, ...]}.
    Tries Azure Graph first, falls back to sp_map.json, else returns {}."""
```

Old `search_sf_approved(p_numbers)` is removed. Only one caller
(`_run_checks_background` in `main.py`), which we update in this change.

**Config (env):**

| Var | Default | Purpose |
|---|---|---|
| `AZURE_TENANT_ID` / `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` | unset | Graph auth (existing) |
| `SP_DRIVE_ID` | existing P2P drive id | Drive id (existing) |
| `SP_SEARCH_FOLDER` | `AP/Daily Payment Approvals` | Search root (replaces `SF_APPROVED_PATH`) |
| `SP_MIN_BILL_LENGTH` | `4` | Min normalized bill length for tier 2 |
| `SP_BILL_TIER_ENABLED` | `true` | Toggle tier 2 entirely |
| `SP_SEARCH_CONCURRENCY` | `8` | Thread-pool size for Graph search calls |

**Internal structure:**

```
_normalize_for_match(s)
_matches_invoice(filename, vendor, bill, p_number) -> (bool, reason)
_graph_search(token, query) -> raw items
_search_via_azure(invoices)    # tier 1 + tier 2, concurrent, deduped queries
_search_via_sp_map(invoices)   # supports legacy {P-number: url}
                               # and new {filename: url} (auto-detected
                               # by checking if any key ends in .pdf)
search_supporting_docs(invoices)
```

**Concurrency & dedup:** build a deduped query set (P-numbers + tier-2 bills),
submit through `ThreadPoolExecutor(max_workers=SP_SEARCH_CONCURRENCY)`,
cache `{normalized_query: [raw_graph_items]}` per upload. For each Graph
result, run `_matches_invoice` against every invoice — one PDF can attach to
multiple invoices if the filename matches both.

**Token cache:** unchanged (module-level `_sp_token`, lock, 60s expiry buffer).

**Failure modes:**

| Condition | Behavior |
|---|---|
| No Azure creds AND no sp_map.json | Log, return `{}`. |
| Auth fails | Log, return `{}`. |
| Per-query timeout / 429 | Log, skip that query, continue. Partial results. |
| Non-PDF Graph results | Filtered out (only `.pdf`). |

### `backend/app/checks.py` — modified

Public surface (`run_receipt_checks(invoices)`) is unchanged.

**Removed:**
- ZIP-mismatch flag emission and the `ZIP_FP_VENDORS` allowlist.
- Inline `ENTITY_ALIASES` (small table) — superseded by `entities.ENTITY_ALIASES_FULL`.
- Old `entity_match()` and `vendor_match()` — replaced by the helpers below.

**Added — three helpers, file-local:**

```python
def _is_prf(text: str) -> bool
def _extract_vendor_from_invoice(text, sage_vendor) -> tuple[str | None, str]
    # result_type ∈ {"match", "dba_match", "prf_blank", "no_text", "mismatch"}
def _extract_billto(text: str) -> str
def _looks_like_brand_example(raw: str) -> bool
```

`_extract_vendor_from_invoice` order of operations:
1. PRF: parse `Vendor Name:` field; detect blank/checkbox-only values
   (`""`, `NEW`, `Existing`, `NewExisting`, <2 alpha chars) → `prf_blank`.
2. DBA: if SAGE vendor has `dba X`, match `X` anywhere in text → `dba_match`.
3. Full legal name (or pre-DBA portion) anywhere in text → `match`.
4. Remit-to / pay-to / make-checks-payable section → `match` or `dba_match`.
5. Fuzzy: ≥60% of SAGE words ≥4 chars present in first 800 chars → `match`.
6. Else → `mismatch`.

`_extract_billto` order of operations:
1. Scan lines for ZIP pattern (`[A-Z]{2}\s+\d{5}`).
2. Walk back up to 6 lines to find a street-address or PO-box line.
3. Walk back further to find a non-title-prefix, non-attn, non-numeric candidate.
4. Fallback to old `Bill To:` / `To:` regex if no address block found.

`_looks_like_brand_example` rejects PRF brand-field values like
`ex. STCC, AFP, STF, ST-` and `STCC, AFP, STF` (template example text).

**Per-invoice check loop (rewritten):**

```
For each invoice with fetched PDF text:

  # Remittance checks (receipt_flags) — unchanged except ZIP removed
  if ACH or check:
      routing comparison → routing_mismatch
      account comparison → account_mismatch

  # Vendor check (invoice_flags)
  extracted, result = _extract_vendor_from_invoice(text, inv.vendor)
  if result == "mismatch":
      flag vendor_mismatch

  # Amount check (invoice_flags)
  if not _is_prf(text):
      compare PDF total vs SAGE; flag amount_mismatch on diff > 0.02

  # Entity check (invoice_flags)
  if _is_prf(text):
      brand = parse "Brand:" field
      if brand and not _looks_like_brand_example(brand):
          if not entities_match(sage_entity, brand):
              flag entity_mismatch
  else:
      found, canonical = find_entity_in_invoice(_extract_billto(text))
      if not found:
          found, canonical = find_entity_in_invoice(text)
      if found and not entities_match(sage_entity, canonical):
          _, sage_in_text = find_entity_in_invoice(text)
          if not (sage_in_text and entities_match(sage_entity, sage_in_text)):
              flag entity_mismatch
```

**Allowlists kept:** `VENDOR_NAME_FP`, `ENTITY_FP_VENDORS`.
**Allowlist removed:** `ZIP_FP_VENDORS`.
**Allowlist content change:** `ENTITY_FP_VENDORS` drops `"People Who Think, LLC"` (Amy removed it — entity match for that vendor is now expected to succeed under the new permissive logic). The post-check filter loop that strips `receipt_flags` entries for ZIP-allowlisted vendors is removed entirely.

**Concurrency:** unchanged — existing `ThreadPoolExecutor` for PDF fetches.

### `backend/app/main.py` — wiring

**`_run_checks_background(upload_id, invoices)`:**

```python
sp_results = sharepoint.search_supporting_docs(invoices)
for inv in invoices:
    key = f"{inv['vendor']}||{inv['bill']}"
    docs = sp_results.get(key, [])
    inv['sp_docs'] = docs
    inv['sp_url']  = docs[0]['url'] if docs else inv.get('sp_url', '')

run_receipt_checks(invoices)

# In the DB persist loop:
row.sp_docs       = json.dumps(inv_dict.get('sp_docs', []))
row.sp_url        = inv_dict.get('sp_url', row.sp_url)
row.receipt_flags = json.dumps(inv_dict.get('receipt_flags', []))
row.invoice_flags = json.dumps(inv_dict.get('invoice_flags', []))
```

**`InvoiceOut` Pydantic model:** add `sp_docs: list[dict] = []`.

**Row → dict serializer:** add `"sp_docs": json.loads(inv.sp_docs) if inv.sp_docs else []`.

**`/api/check/{upload_id}` re-run endpoint:** no separate code path; inherits
the new behavior through the shared background-task function.

**Removed:** `_scan_p_numbers` Excel pre-scan helper (if present) — SP search
now derives queries from parsed invoice records.

### `frontend/index.html` — modifications

JS snippets below are illustrative pseudo-JS — match the existing single-file
template's string-concatenation style when implementing, not ES6 template
literals.

1. Column header `<th>SF Doc</th>` → `<th>SP Docs</th>`.
2. Multi-doc rendering — replace single-anchor logic with a map over
   `inv.sp_docs` (legacy fallback to `inv.sp_url` if `sp_docs` is empty).
   Shorten display names by stripping known entity prefixes (`BP-`, `STT-`,
   `STF-`, etc.), converting `_` to space, dropping `.pdf`, capping at 30 chars.
   Tooltip surfaces `reason` ("P-number" vs "Bill number").
3. KPI tile "Receipt Discrepancies":
   ```js
   const flagged = invoiceData.filter(i =>
     (i.receipt_flags && i.receipt_flags.length) ||
     (i.invoice_flags && i.invoice_flags.length));
   const allFlags = invoiceData.flatMap(i =>
     [...(i.receipt_flags||[]), ...(i.invoice_flags||[])]);
   const high = allFlags.filter(f => f.severity === 'high').length;
   const med  = allFlags.filter(f => f.severity === 'medium').length;
   ```
   Same combined logic in per-org rollup card counts.
4. Per-org table gets a `<th>Receipt</th>` between `W-9 Type` and `Status`,
   and a corresponding row cell rendering the receipt badge plus (if
   `receipt_url` is set) a "📄 View Receipt" link via the existing
   `/api/pdf?url=…` proxy.
5. Hold-vendor matching: strip leading `\d+\.\)\s*` prefix before comparing;
   compare both raw-lowercase and a normalized form (`,.-` → space, drop
   `llc/inc/ltd/corp/co/dba`, collapse whitespace).

### Tests

Add `backend/tests/` with `pytest` as the harness. Add `pytest` and
`pytest-mock` to `backend/requirements-dev.txt`. Minimal `conftest.py`.

| File | Covers |
|---|---|
| `tests/test_entities.py` | `normalize`, `resolve_entity`, `entities_match` (brand→parent, alias→canonical, case-insensitive, "Stand Together Inc" ≡ "Stand Together, Inc."), `find_entity_in_invoice` (longest-match precedence, `\b` boundary for short entities) |
| `tests/test_checks_vendor.py` | `_extract_vendor_from_invoice` — PRF blank/checkbox, DBA, remit-to, fuzzy, mismatch |
| `tests/test_checks_billto.py` | `_extract_billto` — address-block detection, attn/title rejection, numeric-line rejection, fallback regex |
| `tests/test_checks_prf.py` | `_is_prf`, `_looks_like_brand_example` |
| `tests/test_sharepoint.py` | `_normalize_for_match`, `_matches_invoice`, dispatch in `search_supporting_docs` (Azure / sp_map / empty) with mocked `requests` |

### Rollout

1. Merge to `main`. Deploy to dev (`ap-dashboard.dev.standtogether.org`).
2. Add four new env vars to dev `.env`. Restart `web` container.
3. Verify on a recent SAGE export:
   - `sp_docs` column exists post-startup.
   - Multi-doc badges render in the SP Docs column.
   - "Receipt Discrepancies" KPI = `receipt_flags + invoice_flags`.
   - PRFs don't raise spurious entity-mismatch flags from template text.
   - PRFs don't raise amount-mismatch flags.
   - No ZIP-mismatch flags appear.
4. If tier-2 produces noise, flip `SP_BILL_TIER_ENABLED=false` and restart —
   no code revert needed.
5. After Amy signs off in dev, promote to production.

### Rollback

- Code revert restores the old SP-search flow.
- `sp_docs` DB column stays — harmless if unused. Drop later if desired.
- Remove the four new env vars from `.env`; no behavior change since the code
  path is gone.

## Configuration summary

### `.env.example` additions

```bash
# SharePoint search
SP_SEARCH_FOLDER=AP/Daily Payment Approvals
SP_MIN_BILL_LENGTH=4
SP_BILL_TIER_ENABLED=true
SP_SEARCH_CONCURRENCY=8
```

### `docker-compose.yml` additions to the `web` service `environment:` block

```yaml
SP_SEARCH_FOLDER:      ${SP_SEARCH_FOLDER:-AP/Daily Payment Approvals}
SP_MIN_BILL_LENGTH:    ${SP_MIN_BILL_LENGTH:-4}
SP_BILL_TIER_ENABLED:  ${SP_BILL_TIER_ENABLED:-true}
SP_SEARCH_CONCURRENCY: ${SP_SEARCH_CONCURRENCY:-8}
```

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Tier-2 bill-number matching produces false positives | `SP_MIN_BILL_LENGTH` and `SP_BILL_TIER_ENABLED` are env-tunable without code change |
| Graph API call volume scales with invoice count | `SP_SEARCH_CONCURRENCY` cap; per-upload query dedup cache; if needed, bump min-length to 6 |
| New permissive entity-match misses real mismatches | Allowlists `VENDOR_NAME_FP` and `ENTITY_FP_VENDORS` kept; reviewers still see the full PDF; tests guard the most surprising cases |
| Entity dataset rebrand requires a code deploy | Acceptable for v1; revisit (Approach C — JSON config) only if rebrands become frequent |
| Schema migration race on multi-replica deploy | Single replica today; `ADD COLUMN IF NOT EXISTS` is idempotent regardless |

## Estimated effort

~1 day of focused work for code + tests, plus a dev-environment verification pass.
