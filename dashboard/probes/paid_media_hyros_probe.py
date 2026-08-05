"""Hyros probe for the paid media reconciliation report.

Unlike dashboard/data/hyros_loader.py, this keeps the FULL firstSource /
lastSource objects rather than collapsing them to one label, so attribution
can be resolved at ad level and not just campaign level.

Read-only. GET requests only.
Run from repo root: python dashboard/probes/paid_media_hyros_probe.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, r"C:\Users\kxbox\OneDrive\Desktop\bpa-cmo-agent")

import requests
import streamlit as st

HYROS_API = "https://api.hyros.com/v1/api/v1.0"

OUT = Path(r"C:\Users\kxbox\AppData\Local\Temp\claude\C--Users-kxbox--claude\b68f6f0d-e602-4cb3-ad0b-df9a70eb0f7c\scratchpad")

WINDOWS = {
    "w14": (date(2026, 7, 22), date(2026, 8, 4)),
    "w7": (date(2026, 7, 29), date(2026, 8, 4)),
    "w3": (date(2026, 8, 2), date(2026, 8, 4)),
    "checksum": (date(2026, 7, 21), date(2026, 8, 3)),
}

CANDIDATES = ["/calls", "/call", "/orders", "/order", "/sales",
              "/attribution", "/ads", "/campaigns"]

KEY = st.secrets["HYROS_API_KEY"]

# Skip any output file that already exists, so a retry under a rate limit
# doesn't re-burn quota re-fetching data already on disk. Pass --force to
# ignore existing files and re-pull everything. Matches the Task 1 FB probe.
FORCE = "--force" in sys.argv[1:]

# Printed once, on the very first /leads response of the run, so we confirm
# the actual pagination shape instead of assuming it. See _next_page_params.
_LOGGED_LEADS_KEYS = False


def _get(path: str, params: dict) -> tuple[int, dict]:
    r = requests.get(f"{HYROS_API}{path}", headers={"API-Key": KEY},
                      params=params, timeout=90)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"_text": r.text[:600]}


def _next_page_params(payload: dict, params: dict) -> dict | None:
    """Build params for the next page, or None if there is no next page.

    Verified against the live API (not assumed): pulled page 1 with
    pageSize=5, took the nextPageId it returned, sent it back as pageId,
    and confirmed the lead ids on page 2 were disjoint from page 1 (a real
    next page, not a repeat). nextPageToken/pageToken is kept as a fallback
    in case a different window or account state ever returns that shape
    instead, so an unrecognized scheme surfaces rather than being dropped.
    """
    if payload.get("nextPageId"):
        return dict(params, pageId=payload["nextPageId"])
    if payload.get("nextPageToken"):
        return dict(params, pageToken=payload["nextPageToken"])
    return None


def pull_leads(start: date, end: date) -> list[dict]:
    """Fetch every lead in the window, following Hyros page tokens.

    Guards against silent truncation: a page that comes back exactly
    pageSize rows long with no pagination token is suspicious (that is the
    signature of an unrecognized token, not necessarily a genuine last
    page), and prints a loud warning instead of quietly stopping.
    """
    global _LOGGED_LEADS_KEYS
    rows: list[dict] = []
    params = {
        "fromDate": start.isoformat(),
        "toDate": end.isoformat(),
        "pageSize": 250,
    }
    page = 0
    while True:
        status, payload = _get("/leads", params)
        if status >= 400:
            raise RuntimeError(f"Hyros /leads {status}: {payload}")
        if not _LOGGED_LEADS_KEYS:
            print(f"  [diagnostic] /leads top-level keys: {sorted(payload.keys())}")
            _LOGGED_LEADS_KEYS = True
        batch = payload.get("result") or payload.get("data") or []
        if not isinstance(batch, list):
            batch = []
        rows.extend(batch)
        next_params = _next_page_params(payload, params)
        if next_params is None and len(batch) == params.get("pageSize"):
            print(f"  WARNING: page returned exactly pageSize="
                  f"{params['pageSize']} rows with no pagination token. "
                  f"This may be silent truncation rather than a genuine "
                  f"last page. top_level_keys={sorted(payload.keys())}")
        page += 1
        if next_params is None or not batch or page > 80:
            break
        params = next_params
        time.sleep(0.3)
    return rows


def flatten(lead: dict) -> dict:
    """Keep ad-level name AND campaign-level category for both sources."""
    def parts(src):
        if not isinstance(src, dict):
            return (src or None), None
        cat = src.get("category")
        cat_name = cat.get("name") if isinstance(cat, dict) else cat
        return src.get("name"), cat_name

    f_name, f_cat = parts(lead.get("firstSource"))
    l_name, l_cat = parts(lead.get("lastSource"))
    return {
        "lead_id": lead.get("id"),
        "email": (lead.get("email") or "").strip().lower() or None,
        "created": lead.get("createdDate") or lead.get("created") or lead.get("creationDate"),
        "first_source_name": f_name,
        "first_source_category": f_cat,
        "last_source_name": l_name,
        "last_source_category": l_cat,
        "raw_first": lead.get("firstSource"),
        "raw_last": lead.get("lastSource"),
    }


def discover() -> dict:
    """Probe candidate endpoints so we know what Hyros actually exposes.

    GET only, one request per candidate, no retries on failure. A 404 is a
    useful result (that endpoint does not exist on this plan/account), not
    an error to work around.
    """
    start, end = WINDOWS["w14"]
    found = {}
    for path in CANDIDATES:
        status, payload = _get(path, {
            "fromDate": start.isoformat(),
            "toDate": end.isoformat(),
            "pageSize": 5,
        })
        keys = sorted(payload.keys()) if isinstance(payload, dict) else []
        sample = payload.get("result") or payload.get("data") or []
        found[path] = {
            "status": status,
            "top_level_keys": keys,
            "sample": sample[:2] if isinstance(sample, list) else str(sample)[:400],
        }
        print(f"{path:14s} -> {status}")
        time.sleep(0.3)
    return found


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    for wname, (start, end) in WINDOWS.items():
        path = OUT / f"hyros_{wname}.json"
        if path.exists() and not FORCE:
            print(f"{path.name} exists, skipping")
            continue
        raw = pull_leads(start, end)
        rows = [flatten(x) for x in raw]
        path.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        no_email = sum(1 for r in rows if not r["email"])
        unattr = sum(1 for r in rows if not r["first_source_name"])
        print(f"{wname:9s} leads={len(rows):4d} no_email={no_email} "
              f"unattributed={unattr}")

    endpoints_path = OUT / "hyros_endpoints.json"
    if endpoints_path.exists() and not FORCE:
        print(f"{endpoints_path.name} exists, skipping")
    else:
        endpoints_path.write_text(
            json.dumps(discover(), indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
