"""Hyros probe for the paid media reconciliation report.

Unlike dashboard/data/hyros_loader.py, this keeps the FULL firstSource /
lastSource objects rather than collapsing them to one label, so attribution
can be resolved at ad level and not just campaign level.

Read-only. GET requests only.
Run from repo root: python dashboard/probes/paid_media_hyros_probe.py

Source-tier mapping (verified against live data, not assumed; see
task-2-report.md for the id-join confirmation):

    Hyros field                          Facebook equivalent
    ------------------------------------  ------------------------
    firstSource.category.name            campaign name
    firstSource.name                     ad set name
    firstSource.adSource.adSourceId       ad set id
    firstSource.sourceLinkAd.name         ad name
    firstSource.sourceLinkAd.adSourceId   ad id
    firstSource.adSource.adAccountId      ad account id

Confirmed by id join: 14 of 17 distinct sourceLinkAd.adSourceId values match
a FB ad_id exactly, and 10 of 12 adSource.adSourceId values match a FB
adset_id, with zero ad-level collisions. Later tasks should join Hyros to
Facebook on these numeric ids, not on the name fields, which are one tier
coarser than they look (firstSource.name is ad-SET level, not ad level;
true ad-level name/id live under sourceLinkAd).
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

# Printed once per endpoint path, on its first response of the run, so we
# confirm the actual pagination shape instead of assuming it transfers from
# one endpoint to another. See _next_page_params and _pull_all.
_LOGGED_KEYS: set[str] = set()


def _get(path: str, params: dict) -> tuple[int, dict]:
    r = requests.get(f"{HYROS_API}{path}", headers={"API-Key": KEY},
                      params=params, timeout=90)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"_text": r.text[:600]}


def _next_page_params(payload: dict, params: dict) -> dict | None:
    """Build params for the next page, or None if there is no next page.

    Verified against the live API for /leads, /calls, AND /sales (not
    assumed): pulled page 1 with a small pageSize, took the nextPageId
    each endpoint returned, sent it back as pageId, and confirmed the
    record ids on page 2 were disjoint from page 1 on every one of the
    three. /sales looked like it lacked this scheme during endpoint
    discovery, but that was because the discovery sample's pageSize (5 or
    250) exceeded the actual result count, so no next page ever existed to
    produce a token: forcing pageSize=2 against a window with 16 sales
    produced a real nextPageId that paginates correctly, identical to
    /leads and /calls. nextPageToken/pageToken is kept as a fallback in
    case some other endpoint ever returns that shape instead, so an
    unrecognized scheme surfaces rather than being dropped.
    """
    if payload.get("nextPageId"):
        return dict(params, pageId=payload["nextPageId"])
    if payload.get("nextPageToken"):
        return dict(params, pageToken=payload["nextPageToken"])
    return None


def _pull_all(path: str, start: date, end: date, page_size: int = 250) -> list[dict]:
    """Fetch every record in the window for the given endpoint, following
    Hyros page tokens. Shared by /leads, /calls, and /sales: all three use
    the identical nextPageId -> pageId scheme (verified separately for
    each, see _next_page_params).

    Guards against silent truncation: a page that comes back exactly
    page_size rows long with no pagination token is suspicious (that is
    the signature of an unrecognized token, not necessarily a genuine last
    page), and prints a loud warning instead of quietly stopping.
    """
    rows: list[dict] = []
    params = {
        "fromDate": start.isoformat(),
        "toDate": end.isoformat(),
        "pageSize": page_size,
    }
    page = 0
    while True:
        status, payload = _get(path, params)
        if status >= 400:
            raise RuntimeError(f"Hyros {path} {status}: {payload}")
        if path not in _LOGGED_KEYS:
            print(f"  [diagnostic] {path} top-level keys: {sorted(payload.keys())}")
            _LOGGED_KEYS.add(path)
        batch = payload.get("result") or payload.get("data") or []
        if not isinstance(batch, list):
            batch = []
        rows.extend(batch)
        next_params = _next_page_params(payload, params)
        if next_params is None and len(batch) == params.get("pageSize"):
            print(f"  WARNING: {path} page returned exactly pageSize="
                  f"{params['pageSize']} rows with no pagination token. "
                  f"This may be silent truncation rather than a genuine "
                  f"last page. top_level_keys={sorted(payload.keys())}")
        page += 1
        if next_params is None or not batch or page > 80:
            break
        params = next_params
        time.sleep(0.3)
    return rows


def pull_leads(start: date, end: date) -> list[dict]:
    """Fetch every lead in the window, following Hyros page tokens."""
    return _pull_all("/leads", start, end)


def pull_calls(start: date, end: date) -> list[dict]:
    """Fetch every call in the window. Same pagination scheme as /leads."""
    return _pull_all("/calls", start, end)


def pull_sales(start: date, end: date) -> list[dict]:
    """Fetch every sale in the window. Same pagination scheme as /leads,
    confirmed directly (see _next_page_params) despite discovery's sample
    not showing a nextPageId key.
    """
    return _pull_all("/sales", start, end)


def _source_parts(src) -> tuple[str | None, str | None]:
    """Split a firstSource/lastSource object into (name, category name).

    `name` here is the Facebook ad-SET level name, not the ad name (see the
    source-tier table in the module docstring). The true ad-level name and
    id live under src["sourceLinkAd"], which is only reachable through the
    raw_first/raw_last fields this module preserves, not through this
    flattened pair.
    """
    if not isinstance(src, dict):
        return (src or None), None
    cat = src.get("category")
    cat_name = cat.get("name") if isinstance(cat, dict) else cat
    return src.get("name"), cat_name


def flatten(lead: dict) -> dict:
    """Keep ad-level name AND campaign-level category for both sources."""
    f_name, f_cat = _source_parts(lead.get("firstSource"))
    l_name, l_cat = _source_parts(lead.get("lastSource"))
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


def flatten_call(call: dict) -> dict:
    """Flatten a /calls record: same source shape as flatten(), plus the
    call-specific fields Step 7 needs. externalId is the HubSpot engagement
    id for this call.
    """
    f_name, f_cat = _source_parts(call.get("firstSource"))
    l_name, l_cat = _source_parts(call.get("lastSource"))
    lead = call.get("lead") or {}
    return {
        "id": call.get("id"),
        "name": call.get("name"),
        "state": call.get("state"),
        "qualified": call.get("qualified"),
        "creationDate": call.get("creationDate"),
        "externalId": call.get("externalId"),
        "email": (lead.get("email") or "").strip().lower() or None,
        "first_source_name": f_name,
        "first_source_category": f_cat,
        "last_source_name": l_name,
        "last_source_category": l_cat,
        "raw_first": call.get("firstSource"),
        "raw_last": call.get("lastSource"),
    }


def flatten_sale(sale: dict) -> dict:
    """Flatten a /sales record.

    Only records WHETHER a source block is present (has_first_source), not
    the object itself: Step 8's job is to characterize revenue data (does
    Hyros have real sale amounts, what do they look like), not to resolve
    sale-level ad attribution.
    """
    lead = sale.get("lead") or {}
    usd_price = sale.get("usdPrice") or {}
    product = sale.get("product") or {}
    integration = (sale.get("provider") or {}).get("integration") or {}
    return {
        "id": sale.get("id"),
        "order_id": sale.get("orderId"),
        "created": sale.get("creationDate"),
        "usd_price": usd_price.get("price"),
        "product_name": product.get("name"),
        "product_tag": product.get("tag"),
        "provider_integration_type": integration.get("type"),
        "email": (lead.get("email") or "").strip().lower() or None,
        "has_first_source": isinstance(sale.get("firstSource"), dict),
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


def _has_ad_source_id(row: dict) -> bool:
    """True if either raw source block carries a real ad-level id."""
    for key in ("raw_first", "raw_last"):
        src = row.get(key) or {}
        if isinstance(src, dict) and (src.get("sourceLinkAd") or {}).get("adSourceId"):
            return True
    return False


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

    for wname, (start, end) in WINDOWS.items():
        path = OUT / f"hyros_calls_{wname}.json"
        if path.exists() and not FORCE:
            print(f"{path.name} exists, skipping")
            continue
        raw = pull_calls(start, end)
        rows = [flatten_call(x) for x in raw]
        path.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        with_ad_id = sum(1 for r in rows if _has_ad_source_id(r))
        print(f"{wname:9s} calls={len(rows):4d} with_ad_source_id={with_ad_id}")

    for wname, (start, end) in WINDOWS.items():
        path = OUT / f"hyros_sales_{wname}.json"
        if path.exists() and not FORCE:
            print(f"{path.name} exists, skipping")
            continue
        raw = pull_sales(start, end)
        rows = [flatten_sale(x) for x in raw]
        path.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        has_source = sum(1 for r in rows if r["has_first_source"])
        prices = [r["usd_price"] for r in rows]
        print(f"{wname:9s} sales={len(rows):4d} has_source={has_source} "
              f"prices={prices}")

    endpoints_path = OUT / "hyros_endpoints.json"
    if endpoints_path.exists() and not FORCE:
        print(f"{endpoints_path.name} exists, skipping")
    else:
        endpoints_path.write_text(
            json.dumps(discover(), indent=1), encoding="utf-8")

    # Aggregate diagnostics across all windows, read back from disk (so
    # this is correct even when some windows were skipped this run) and
    # deduped by id (the windows overlap, so naive concatenation would
    # double-count records that fall inside more than one window).
    calls_by_id: dict[str, dict] = {}
    for wname in WINDOWS:
        p = OUT / f"hyros_calls_{wname}.json"
        if p.exists():
            for r in json.loads(p.read_text(encoding="utf-8")):
                calls_by_id[r["id"]] = r
    all_calls = list(calls_by_id.values())
    if all_calls:
        with_ad_id_total = sum(1 for r in all_calls if _has_ad_source_id(r))
        print(f"\ncalls, distinct across all windows: {len(all_calls)}, "
              f"with sourceLinkAd.adSourceId (first or last): "
              f"{with_ad_id_total} ({with_ad_id_total / len(all_calls):.0%})")

    sales_by_id: dict[str, dict] = {}
    for wname in WINDOWS:
        p = OUT / f"hyros_sales_{wname}.json"
        if p.exists():
            for r in json.loads(p.read_text(encoding="utf-8")):
                sales_by_id[r["id"]] = r
    all_sales = list(sales_by_id.values())
    if all_sales:
        with_source = sum(1 for r in all_sales if r.get("has_first_source"))
        prices = sorted(r.get("usd_price") for r in all_sales)
        print(f"sales, distinct across all windows: {len(all_sales)}, "
              f"with a source block: {with_source}, "
              f"without: {len(all_sales) - with_source}")
        print(f"usd_price distribution: {prices}")


if __name__ == "__main__":
    main()
