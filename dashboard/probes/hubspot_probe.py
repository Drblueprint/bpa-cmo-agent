"""One-time probe to confirm HubSpot internal field names and deal stage IDs.

Run manually: python -m dashboard.probes.hubspot_probe
Output goes to stdout; copy the IDs into dashboard/config.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests
from dotenv import dotenv_values


def main() -> None:
    env = dotenv_values(Path(__file__).resolve().parents[2] / ".env")
    token = env.get("HUBSPOT_TOKEN")
    if not token:
        sys.exit("HUBSPOT_TOKEN not found in .env")

    headers = {"Authorization": f"Bearer {token}"}

    # 1. Contact properties — look for typeform_asset_download, sdr_owner, bds, sme
    print("=" * 60)
    print("CONTACT PROPERTIES")
    print("=" * 60)
    r = requests.get(
        "https://api.hubapi.com/crm/v3/properties/contacts",
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    wanted = {"typeform", "sdr", "bds", "sme", "utm_source"}
    for p in r.json().get("results", []):
        name = p.get("name", "").lower()
        label = p.get("label", "").lower()
        if any(w in name or w in label for w in wanted):
            print(f"  {p['name']:40s}  ({p.get('label')})  type={p.get('type')}")

    # 2. Deal pipelines and stages — look for 15-min, Strategy, Closed-Won
    print()
    print("=" * 60)
    print("DEAL PIPELINES + STAGES")
    print("=" * 60)
    r = requests.get(
        "https://api.hubapi.com/crm/v3/pipelines/deals",
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    for p in r.json().get("results", []):
        print(f"\nPipeline: {p['label']}  (id={p['id']})")
        for s in p.get("stages", []):
            print(f"  stage id={s['id']:30s} label={s['label']}")


if __name__ == "__main__":
    main()
