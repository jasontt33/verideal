"""Microsoft Graph / SharePoint integration for P-number document lookup.

Credentials are read from environment variables:
  AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET

Falls back to /data/sp_map.json (or app-dir sp_map.json) if Azure creds are absent.
"""
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log = logging.getLogger(__name__)

SP_DRIVE_ID = os.getenv(
    "SP_DRIVE_ID",
    "b!-7E_08zvtUeK20bVTeozH7bOrP-DTWBPjI-Ihlrg_FvsAjWNnMCgS7Xt5bJKR1Ed",
)
SF_APPROVED_PATH = os.getenv(
    "SF_APPROVED_PATH",
    "AP/Salesforce Payment Processing/SF Accounting Approved",
)
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

_sp_token: Optional[str] = None
_sp_token_expiry: float = 0
_sp_token_lock = threading.Lock()


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
            url  = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
            resp = requests.post(url, data={
                "grant_type":    "client_credentials",
                "client_id":     client_id,
                "client_secret": client_secret,
                "scope":         "https://graph.microsoft.com/.default",
            }, timeout=15, verify=False)
            if resp.status_code == 200:
                data             = resp.json()
                _sp_token        = data["access_token"]
                _sp_token_expiry = time.time() + data.get("expires_in", 3600)
                return _sp_token
            log.warning("SP token request returned %s", resp.status_code)
        except Exception as e:
            log.warning("SP auth error: %s", e)
        return None


def _load_sp_map() -> dict:
    """Load static sp_map.json fallback from /data or alongside this module."""
    for path in [Path("/data/sp_map.json"), Path(__file__).parent / "sp_map.json"]:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {}


def search_sf_approved(p_numbers: list[str]) -> dict[str, str]:
    """Return {p_number: sharepoint_url} for each found P-number.

    Tries Azure Graph API first; falls back to sp_map.json if creds absent.
    """
    if not p_numbers:
        return {}

    token = _get_sp_token()
    if not token:
        sp_map = _load_sp_map()
        if sp_map:
            result = {p: sp_map[p] for p in p_numbers if p in sp_map}
            if result:
                log.info("[SP] sp_map.json fallback: found %d/%d P-numbers", len(result), len(p_numbers))
            return result
        log.info("[SP] No Azure creds and no sp_map.json — SharePoint lookup skipped")
        return {}

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    result: dict[str, str] = {}
    query = " OR ".join(p_numbers)
    url   = (
        f"{GRAPH_BASE}/drives/{SP_DRIVE_ID}/root:/{SF_APPROVED_PATH}:"
        f"/search(q='{query}')?$select=name,webUrl&$top=50"
    )
    try:
        resp = requests.get(url, headers=headers, timeout=20, verify=False)
        if resp.status_code == 200:
            p_pat = re.compile(r"\b(P-\d{4,6})\b", re.IGNORECASE)
            for item in resp.json().get("value", []):
                name = item.get("name", "")
                web  = item.get("webUrl", "")
                m    = p_pat.search(name)
                if m and web:
                    pnum = m.group(1).upper()
                    if pnum in p_numbers:
                        result[pnum] = web
                        log.info("[SP] Found %s: %s", pnum, name)
        else:
            log.warning("[SP] Search returned %s", resp.status_code)
    except Exception as e:
        log.warning("[SP] Search error: %s", e)

    missing = [p for p in p_numbers if p not in result]
    if missing:
        log.info("[SP] Not found in SF Approved: %s", missing)
    return result
