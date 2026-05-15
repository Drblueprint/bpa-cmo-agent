"""One-off diagnostic: identifies the gap between Hyros-attributed leads
and HubSpot typeform completers for a given campaign group.

Run:
    python -m dashboard.probes.lead_gap_probe --days 7 --group Chiro
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import requests
from dotenv import dotenv_values


HYROS_API = "https://api.hyros.com/v1/api/v1.0"
HS_API = "https://api.hubapi.com"


# Same group regex as dashboard/config.py
GROUP_PATTERNS: dict[str, re.Pattern[str]] = {
    "EMX":         re.compile(r"__EMX__", re.IGNORECASE),
    "Chiro":       re.compile(r"__Chiro__", re.IGNORECASE),
    "PT Recovery": re.compile(r"__PT__|__Recovery__", re.IGNORECASE),
    "TheraRay":    re.compile(r"__Theraray__", re.IGNORECASE),
}


def _source_label(src) -> str:
    if not isinstance(src, dict):
        return src or ""
    cat = src.get("category")
    if isinstance(cat, dict) and cat.get("name"):
        return cat["name"]
    return src.get("name") or ""


def _match_group(source_text: str) -> str | None:
    if not source_text:
        return None
    # EMX checked first so EMX wins over Chiro when both tokens present
    for label in ("EMX", "Chiro", "PT Recovery", "TheraRay"):
        if GROUP_PATTERNS[label].search(source_text):
            return label
    return None


def pull_hyros_leads(key: str, start: date, end: date) -> list[dict]:
    """Pull all Hyros leads in window. Returns list of {email, first_source_label, created}."""
    out = []
    params = {
        "fromDate": start.isoformat(),
        "toDate": end.isoformat(),
        "pageSize": 250,
    }
    r = requests.get(f"{HYROS_API}/leads", headers={"API-Key": key},
                     params=params, timeout=60)
    r.raise_for_status()
    data = r.json()
    leads = data.get("result") or data.get("data") or []
    if not isinstance(leads, list):
        leads = []
    for x in leads:
        out.append({
            "email": (x.get("email") or "").strip().lower(),
            "first_source_text": _source_label(x.get("firstSource")),
            "last_source_text": _source_label(x.get("lastSource")),
            "created": x.get("createdDate") or x.get("created"),
        })
    return out


def search_hubspot_contact_by_email(token: str, email: str) -> dict | None:
    """Return the HubSpot contact for an email (or None)."""
    body = {
        "filterGroups": [{"filters": [
            {"propertyName": "email", "operator": "EQ", "value": email}
        ]}],
        "properties": [
            "firstname", "lastname", "email", "createdate",
            "typeform_asset_download", "lifecyclestage", "n15_min_call_date",
        ],
        "limit": 1,
    }
    r = requests.post(
        f"{HS_API}/crm/v3/objects/contacts/search",
        headers={"Authorization": f"Bearer {token}"},
        json=body, timeout=30,
    )
    r.raise_for_status()
    results = r.json().get("results", [])
    return results[0] if results else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--group", type=str, default="Chiro",
                        choices=["Chiro", "PT Recovery", "TheraRay", "EMX"])
    args = parser.parse_args()

    env = dotenv_values(Path(__file__).resolve().parents[2] / ".env")
    hyros_key = env.get("HYROS_API_KEY")
    hs_token = env.get("HUBSPOT_TOKEN")
    if not hyros_key or not hs_token:
        sys.exit("Missing HYROS_API_KEY or HUBSPOT_TOKEN in .env")

    end = date.today()
    start = end - timedelta(days=args.days)

    print(f"=" * 70)
    print(f"LEAD GAP DIAGNOSTIC — group={args.group}, window={start}..{end}")
    print(f"=" * 70)

    # 1. Pull all Hyros leads in window, filter to group
    all_hyros = pull_hyros_leads(hyros_key, start, end)
    group_hyros = [
        h for h in all_hyros
        if _match_group(h["first_source_text"]) == args.group
        or _match_group(h["last_source_text"]) == args.group
    ]
    print(f"\nHyros leads attributed to {args.group} in window: {len(group_hyros)}")

    # 2. For each, check HubSpot
    in_hubspot_with_typeform = []
    in_hubspot_without_typeform = []
    not_in_hubspot = []
    no_email = []

    for h in group_hyros:
        email = h["email"]
        if not email:
            no_email.append(h)
            continue
        contact = search_hubspot_contact_by_email(hs_token, email)
        if not contact:
            not_in_hubspot.append({**h, "hs_contact": None})
            continue
        props = contact.get("properties", {})
        if props.get("typeform_asset_download"):
            in_hubspot_with_typeform.append({**h, "hs_props": props})
        else:
            in_hubspot_without_typeform.append({**h, "hs_props": props})

    # 3. Report
    print(f"\nBreakdown of {len(group_hyros)} Hyros leads:\n")
    print(f"  {len(in_hubspot_with_typeform):3d}  -> in HubSpot WITH typeform_asset_download (counted in dashboard)")
    print(f"  {len(in_hubspot_without_typeform):3d}  -> in HubSpot WITHOUT typeform_asset_download (NOT counted -- the gap)")
    print(f"  {len(not_in_hubspot):3d}  -> NOT in HubSpot at all (NOT counted -- the gap)")
    print(f"  {len(no_email):3d}  -> no email on Hyros record (NOT countable)")

    if in_hubspot_without_typeform:
        print(f"\n--- The {len(in_hubspot_without_typeform)} contacts in HubSpot WITHOUT typeform ---")
        print(f"{'Email':40s}  {'HS Created':25s}  {'Lifecycle':30s}  Hyros source")
        for r in in_hubspot_without_typeform:
            p = r["hs_props"]
            print(f"  {p.get('email','')[:38]:40s}  "
                  f"{(p.get('createdate') or '')[:25]:25s}  "
                  f"{(p.get('lifecyclestage') or '')[:28]:30s}  "
                  f"{r['first_source_text'][:50]}")

    if not_in_hubspot:
        print(f"\n--- The {len(not_in_hubspot)} Hyros leads NOT in HubSpot at all ---")
        print(f"{'Email':40s}  {'Hyros Created':25s}  Hyros source")
        for r in not_in_hubspot:
            print(f"  {r['email'][:38]:40s}  "
                  f"{(r['created'] or '')[:25]:25s}  "
                  f"{r['first_source_text'][:50]}")

    if no_email:
        print(f"\n--- {len(no_email)} Hyros leads with no email ---")
        for r in no_email:
            print(f"  source: {r['first_source_text'][:60]}, created: {r['created']}")

    # 4. Mapping check -- any contacts in HubSpot WITH typeform but unmapped asset?
    if in_hubspot_with_typeform:
        print(f"\n--- Typeform assets seen on Hyros-attributed contacts ---")
        asset_counts: dict[str, int] = {}
        for r in in_hubspot_with_typeform:
            asset = r["hs_props"].get("typeform_asset_download", "")
            asset_counts[asset] = asset_counts.get(asset, 0) + 1
        for asset, n in sorted(asset_counts.items(), key=lambda kv: -kv[1]):
            print(f"  {n:3d}  {asset!r}")


if __name__ == "__main__":
    main()
