"""Standalone probe: print all distinct typeform_asset_download values seen
in HubSpot contacts over the last 90 days, with counts.

Run manually:
    python -m dashboard.probes.asset_probe

Use the output to populate ASSET_TO_GROUP in dashboard/config.py.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import dotenv_values


HS_API = "https://api.hubapi.com"


def main() -> None:
    env = dotenv_values(Path(__file__).resolve().parents[2] / ".env")
    token = env.get("HUBSPOT_TOKEN")
    if not token:
        sys.exit("HUBSPOT_TOKEN not found in .env")

    end = date.today()
    start = end - timedelta(days=90)
    start_ms = int(datetime.combine(start, datetime.min.time(),
                                     tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(datetime.combine(end, datetime.max.time(),
                                   tzinfo=timezone.utc).timestamp() * 1000)

    body = {
        "filterGroups": [{
            "filters": [
                {"propertyName": "typeform_asset_download",
                 "operator": "HAS_PROPERTY"},
                {"propertyName": "createdate", "operator": "BETWEEN",
                 "value": start_ms, "highValue": end_ms},
            ]
        }],
        "properties": ["typeform_asset_download"],
        "limit": 100,
    }

    counts: dict[str, int] = {}
    after = None
    while True:
        b = dict(body)
        if after:
            b["after"] = after
        r = requests.post(
            f"{HS_API}/crm/v3/objects/contacts/search",
            headers={"Authorization": f"Bearer {token}"},
            json=b, timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        for x in data.get("results", []):
            asset = (x.get("properties") or {}).get("typeform_asset_download")
            if asset:
                counts[asset] = counts.get(asset, 0) + 1
        after = (data.get("paging") or {}).get("next", {}).get("after")
        if not after:
            break

    print(f"Distinct typeform_asset_download values seen "
          f"between {start} and {end}:\n")
    for asset, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:5d}  {asset}")
    print(f"\nTotal distinct values: {len(counts)}")


if __name__ == "__main__":
    main()
