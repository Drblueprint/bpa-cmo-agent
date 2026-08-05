"""HubSpot probe for the paid media reconciliation report.

Supplies the third independent lead count (marketing contacts) and the
authoritative booked-call count (meetings), plus an email-to-contact-id map
so Hyros leads can be joined to HubSpot records.

Read-only. GET and CRM search POST only (search is read-only despite POST).
Run from repo root: python dashboard/probes/paid_media_hubspot_probe.py
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

from dashboard.data import hubspot_loader as hl

OUT = Path(r"C:\Users\kxbox\AppData\Local\Temp\claude\C--Users-kxbox--claude\b68f6f0d-e602-4cb3-ad0b-df9a70eb0f7c\scratchpad")

WINDOWS = {
    "w14": (date(2026, 7, 22), date(2026, 8, 4)),
    "w7": (date(2026, 7, 29), date(2026, 8, 4)),
    "w3": (date(2026, 8, 2), date(2026, 8, 4)),
    "checksum": (date(2026, 7, 21), date(2026, 8, 3)),
}

TOKEN = st.secrets["HUBSPOT_TOKEN"]

# Skip any output file that already exists, so a retry under a rate limit
# doesn't re-burn quota re-fetching data already on disk. Pass --force to
# ignore existing files and re-pull everything. Matches Tasks 1 and 2.
FORCE = "--force" in sys.argv[1:]


def W(fn):
    """Unwrap a @st.cache_data-decorated loader so it runs outside Streamlit."""
    return getattr(fn, "__wrapped__", fn)


def lookup_contact_ids(emails: list[str]) -> dict[str, str]:
    """Map lowercased email -> HubSpot contact id. Batches of 100."""
    out: dict[str, str] = {}
    uniq = sorted({e for e in emails if e})
    url = "https://api.hubapi.com/crm/v3/objects/contacts/search"
    headers = {"Authorization": f"Bearer {TOKEN}",
               "Content-Type": "application/json"}

    for i in range(0, len(uniq), 100):
        chunk = uniq[i:i + 100]
        body = {
            "filterGroups": [{"filters": [
                {"propertyName": "email", "operator": "IN", "values": chunk}
            ]}],
            "properties": ["email"],
            "limit": 100,
        }
        r = requests.post(url, headers=headers, json=body, timeout=60)
        if r.status_code >= 400:
            print(f"  lookup batch {i} failed {r.status_code}: {r.text[:300]}")
            continue
        for res in r.json().get("results", []):
            em = (res.get("properties", {}).get("email") or "").strip().lower()
            if em:
                out[em] = str(res.get("id"))
        time.sleep(0.2)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    keep_c = ["hs_id", "email", "created", "recent_conversion_event",
              "utm_source", "analytics_source"]
    keep_m = ["meeting_id", "contact_id", "activity_type", "outcome",
              "start_time", "booked_at"]

    for wname, (start, end) in WINDOWS.items():
        out_path = OUT / f"hubspot_{wname}.json"
        if out_path.exists() and not FORCE:
            print(f"{out_path.name} exists, skipping")
            continue

        contacts = W(hl.load_marketing_contacts)(start, end)
        meetings = W(hl.load_meetings_in_window)(start, end)

        missing_c = [c for c in keep_c if c not in contacts.columns]
        missing_m = [c for c in keep_m if c not in meetings.columns]
        if missing_c or missing_m:
            print(f"  COLUMN DRIFT: contacts missing {missing_c}, "
                  f"meetings missing {missing_m}")
            print(f"  contacts.columns = {list(contacts.columns)}")
            print(f"  meetings.columns = {list(meetings.columns)}")

        hyros_path = OUT / f"hyros_{wname}.json"
        hyros_emails = []
        if hyros_path.exists():
            hyros_emails = [r["email"] for r in
                            json.loads(hyros_path.read_text(encoding="utf-8"))]
        else:
            print(f"  WARNING: {hyros_path.name} missing, run Task 2 first")

        email_to_id = lookup_contact_ids(hyros_emails)

        payload = {
            "contacts": contacts[keep_c].to_dict(orient="records"),
            "meetings": meetings[keep_m].to_dict(orient="records"),
            "email_to_id": email_to_id,
        }
        out_path.write_text(
            json.dumps(payload, indent=1, default=str), encoding="utf-8")
        print(f"{wname:9s} contacts={len(contacts):4d} "
              f"meetings={len(meetings):4d} "
              f"hyros_emails_matched={len(email_to_id)}/{len(set(hyros_emails))}")


if __name__ == "__main__":
    main()
