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
    if not s:
        return ""
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
        for items in query_results.values():
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
