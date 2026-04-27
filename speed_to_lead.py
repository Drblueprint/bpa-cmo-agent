"""
Speed-to-lead: time from Typeform submission to first outbound sales touch (logged SMS or email)
in HubSpot, for typeform-attributed contacts created in the last N days.

Clock start : typeform_submission_date property (Central Time display)
First touch : earliest logged SMS (Communications API) or outbound email (Engagements API)

Usage:
    python speed_to_lead.py            # last 30 days
    python speed_to_lead.py --days 14
    python speed_to_lead.py --days 60
"""

import sys
import argparse
sys.path.insert(0, r"C:\Users\kxbox\OneDrive\Desktop\bpa-cmo-agent")
sys.stdout.reconfigure(encoding="utf-8")

from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from hubspot_puller import hs_request, search_paginate, TYPEFORM_ASSET_PROPERTY, typeform_asset_of
from weekly_report_v2 import load_env

# Central Time: CDT = UTC-5, CST = UTC-6. Use UTC-5 (CDT, Apr-Oct).
CENTRAL = timezone(timedelta(hours=-5))

# Known SDR owner IDs - checked against lead owner, SDR owner, and contact owner fields
SDR_IDS = {
    "79870794": "Garrett Hustedt",
    "89638769": "Peyton Fulghum",
    "568393136": "Haley Stewart",   # owner ID from HubSpot owners list
    "61097347":  "Haley Stewart",   # user-provided ID (kept as fallback)
    "78947719":  "Gage",
}

def ts_to_dt(ms: int | str | None) -> datetime | None:
    """Convert HubSpot Unix-ms timestamp to UTC datetime."""
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)
    except (ValueError, OSError):
        return None

def iso_to_dt(s: str | None) -> datetime | None:
    """Convert HubSpot ISO date string to UTC datetime."""
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except ValueError:
        return None

def to_ct(dt: datetime | None) -> datetime | None:
    if not dt:
        return None
    return dt.astimezone(CENTRAL)

def fmt_ct(dt: datetime | None) -> str:
    if not dt:
        return "no date"
    return to_ct(dt).strftime("%m/%d %I:%M %p CT")

def fmt_delta(hours: float) -> str:
    if hours < 1:
        return f"{hours*60:.0f}m"
    if hours < 24:
        return f"{hours:.1f}h"
    return f"{hours/24:.1f}d"

def get_engagements(token: str, contact_id: str) -> list[dict]:
    """Pull all v1 engagements (EMAIL, CALL, NOTE, TASK, MEETING) for a contact."""
    results = []
    offset = None
    while True:
        url = f"/crm/v1/engagements/associated/CONTACT/{contact_id}/paged?limit=100"
        if offset:
            url += f"&offset={offset}"
        s, r = hs_request("GET", url, token)
        if s >= 400:
            break
        for item in r.get("results", []):
            results.append(item)
        if not r.get("hasMore"):
            break
        offset = r.get("offset")
    return results

def get_communications(token: str, contact_id: str) -> list[dict]:
    """Pull logged SMS/WhatsApp via the v3 Communications object (separate from v1 engagements)."""
    # Step 1: get communication IDs associated with this contact
    s, r = hs_request("GET", f"/crm/v4/objects/contacts/{contact_id}/associations/communications", token)
    if s >= 400:
        return []
    comm_ids = [str(x.get("toObjectId")) for x in r.get("results", []) if x.get("toObjectId")]
    if not comm_ids:
        return []
    # Step 2: batch-read communication objects for timestamp + owner
    payload = {
        "inputs": [{"id": cid} for cid in comm_ids],
        "properties": ["hs_createdate", "hs_body_preview", "hubspot_owner_id",
                       "hs_communication_channel_type", "hs_lastmodifieddate"],
    }
    s2, r2 = hs_request("POST", "/crm/v3/objects/communications/batch/read", token, payload)
    if s2 >= 400:
        return []
    return r2.get("results", [])

def first_outbound_touch(token: str, contact_id: str, after_dt: datetime | None) -> dict | None:
    """Return the earliest outbound EMAIL or SMS touch after after_dt across both APIs."""
    candidates = []

    # v1 engagements: EMAIL (outbound only)
    for eng in get_engagements(token, contact_id):
        e = eng.get("engagement", {})
        etype = e.get("type", "")
        if etype != "EMAIL":
            continue
        meta = eng.get("metadata", {})
        direction = (meta.get("direction") or "").upper()
        if direction == "INCOMING_EMAIL":
            continue
        ts = ts_to_dt(e.get("timestamp"))
        if not ts or (after_dt and ts < after_dt):
            continue
        owner_id = str(e.get("ownerId") or "")
        candidates.append({"type": "Email", "ts": ts, "owner_id": owner_id})

    # v3 Communications: logged SMS
    for comm in get_communications(token, contact_id):
        props = comm.get("properties", {})
        ts = iso_to_dt(props.get("hs_createdate"))
        if not ts or (after_dt and ts < after_dt):
            continue
        owner_id = str(props.get("hubspot_owner_id") or "")
        channel = props.get("hs_communication_channel_type") or "SMS"
        candidates.append({"type": channel, "ts": ts, "owner_id": owner_id})

    if not candidates:
        return None
    return min(candidates, key=lambda x: x["ts"])

def pull_typeform_contacts(token: str, days: int) -> list[dict]:
    """Search HubSpot for contacts with typeform_asset_download set, created in last N days."""
    since_ms = int((datetime.now(tz=timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    payload = {
        "filterGroups": [{
            "filters": [
                {"propertyName": TYPEFORM_ASSET_PROPERTY, "operator": "HAS_PROPERTY"},
                {"propertyName": "typeform_submission_date", "operator": "GTE", "value": str(since_ms)},
            ]
        }],
        "properties": [
            "email", "firstname", "lastname", "createdate",
            TYPEFORM_ASSET_PROPERTY, "typeform_submission_date",
            "lifecyclestage", "hubspot_owner_id", "sdr_owner",
        ],

        "limit": 100,
    }
    contacts = list(search_paginate("contacts", token, payload))
    return contacts

def get_lead_owner(token: str, contact_id: str) -> str | None:
    """Get the owner ID from the HubSpot Lead record associated with this contact."""
    s, r = hs_request("GET", f"/crm/v4/objects/contacts/{contact_id}/associations/leads", token)
    if s >= 400:
        return None
    lead_ids = [str(x.get("toObjectId")) for x in r.get("results", []) if x.get("toObjectId")]
    if not lead_ids:
        return None
    # Take the most recent lead - batch read to get owner
    payload = {
        "inputs": [{"id": lid} for lid in lead_ids[:10]],
        "properties": ["hubspot_owner_id", "hs_lead_name", "hs_createdate"],
    }
    s2, r2 = hs_request("POST", "/crm/v3/objects/leads/batch/read", token, payload)
    if s2 >= 400:
        return None
    leads = r2.get("results", [])
    if not leads:
        return None
    # Use the most recently created lead's owner
    leads.sort(key=lambda x: x.get("properties", {}).get("hs_createdate") or "", reverse=True)
    return str(leads[0].get("properties", {}).get("hubspot_owner_id") or "")


def pull_owner_names(token: str) -> dict[str, str]:
    """Fetch all HubSpot owner IDs -> first name mapping."""
    names = {}
    s, r = hs_request("GET", "/crm/v3/owners?limit=100", token)
    if s < 400:
        for owner in r.get("results", []):
            oid = str(owner.get("id", ""))
            first = owner.get("firstName") or ""
            last = owner.get("lastName") or ""
            names[oid] = f"{first} {last}".strip() or oid
    return names

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    args = p.parse_args()

    env = load_env(Path(r"C:\Users\kxbox\OneDrive\Desktop\bpa-cmo-agent\.env"))
    token = env["HUBSPOT_TOKEN"]

    print(f"Pulling typeform-attributed contacts (last {args.days}d)...")
    contacts = pull_typeform_contacts(token, args.days)
    print(f"  {len(contacts)} contacts found\n")

    records = []
    owner_ids_seen = set()

    for c in contacts:
        props = c.get("properties", {})
        contact_id = c.get("id", "")
        email = props.get("email") or ""
        first = (props.get("firstname") or "").strip()
        last = (props.get("lastname") or "").strip()
        name = f"{first} {last}".strip() or email

        # Prefer typeform_submission_date over createdate as the start clock
        sub_dt = iso_to_dt(props.get("typeform_submission_date")) or \
                 iso_to_dt(props.get("createdate"))

        tf_val = props.get(TYPEFORM_ASSET_PROPERTY) or ""
        tf = typeform_asset_of(tf_val)
        tf_name = tf["name"] if tf else (tf_val or "unknown")
        tf_seg = tf["segment"] if tf else "Other"
        # Resolve owner by checking lead owner, sdr_owner, and contact owner in priority order.
        # Use the first field that matches a known SDR; fall back to contact owner.
        candidate_ids = [
            get_lead_owner(token, contact_id),
            props.get("sdr_owner"),
            props.get("hubspot_owner_id"),
        ]
        sdr_owner = "unassigned"
        for cid in candidate_ids:
            if cid and str(cid) in SDR_IDS:
                sdr_owner = str(cid)
                break
        if sdr_owner == "unassigned":
            # No SDR match - fall back to contact owner raw ID (resolved to name later)
            sdr_owner = props.get("hubspot_owner_id") or "unassigned"

        # Pull engagements + communications and find first outbound touch after form submission
        touch = first_outbound_touch(token, contact_id, sub_dt)

        if touch:
            delta_hours = (touch["ts"] - sub_dt).total_seconds() / 3600 if sub_dt else None
            owner_ids_seen.add(touch["owner_id"])
        else:
            delta_hours = None

        records.append({
            "name": name,
            "email": email,
            "tf_name": tf_name,
            "tf_seg": tf_seg,
            "sdr_owner": sdr_owner,
            "sub_dt": sub_dt,
            "touch_dt": touch["ts"] if touch else None,
            "touch_type": touch["type"] if touch else None,
            "touch_owner": touch["owner_id"] if touch else None,
            "delta_hours": delta_hours,
        })

    owner_names = pull_owner_names(token)

    # Resolve sdr_owner ID -> name: SDR_IDS first, then full owner list
    for rec in records:
        oid = rec["sdr_owner"]
        rec["sdr_owner"] = SDR_IDS.get(oid) or owner_names.get(oid, oid)

    # ── REPORT ────────────────────────────────────────────────────────────────
    touched = [r for r in records if r["delta_hours"] is not None]
    untouched = [r for r in records if r["delta_hours"] is None]

    print(f"\n{'='*80}")
    print(f"{'SPEED TO LEAD REPORT':^80}")
    print(f"Window: last {args.days} days  |  {len(records)} typeform leads  |  "
          f"{len(touched)} touched  |  {len(untouched)} NOT yet touched")
    print(f"{'='*80}\n")

    # Aggregate stats
    if touched:
        avg_h = sum(r["delta_hours"] for r in touched) / len(touched)
        sorted_h = sorted(r["delta_hours"] for r in touched)
        mid = len(sorted_h) // 2
        median_h = (sorted_h[mid] + sorted_h[~mid]) / 2
        under_1h = sum(1 for r in touched if r["delta_hours"] <= 1)
        under_4h = sum(1 for r in touched if r["delta_hours"] <= 4)
        under_24h = sum(1 for r in touched if r["delta_hours"] <= 24)
        print(f"SUMMARY")
        print(f"  Average time to first touch : {fmt_delta(avg_h)}")
        print(f"  Median time to first touch  : {fmt_delta(median_h)}")
        print(f"  Touched within 1h           : {under_1h} ({under_1h/len(touched)*100:.0f}%)")
        print(f"  Touched within 4h           : {under_4h} ({under_4h/len(touched)*100:.0f}%)")
        print(f"  Touched within 24h          : {under_24h} ({under_24h/len(touched)*100:.0f}%)")
        print(f"  Not yet touched             : {len(untouched)} ({len(untouched)/len(records)*100:.0f}%)")
        print()

    # By SDR owner (from contact property)
    by_rep: dict[str, list] = defaultdict(list)
    by_rep_untouched: dict[str, int] = defaultdict(int)
    for r in records:
        rep = r["sdr_owner"]
        if r["delta_hours"] is not None:
            by_rep[rep].append(r["delta_hours"])
        else:
            by_rep_untouched[rep] += 1
    all_reps = set(list(by_rep.keys()) + list(by_rep_untouched.keys()))
    if all_reps:
        print(f"BY SDR OWNER")
        for rep in sorted(all_reps):
            deltas = by_rep.get(rep, [])
            un = by_rep_untouched.get(rep, 0)
            if deltas:
                avg = sum(deltas) / len(deltas)
                print(f"  {rep:<20} {len(deltas):>3} touched (avg {fmt_delta(avg)}) | {un} untouched")
            else:
                print(f"  {rep:<20}   0 touched | {un} untouched")
        print()

    # By vertical/segment
    by_seg: dict[str, list] = defaultdict(list)
    by_seg_untouched: dict[str, int] = defaultdict(int)
    for r in records:
        if r["delta_hours"] is not None:
            by_seg[r["tf_seg"]].append(r["delta_hours"])
        else:
            by_seg_untouched[r["tf_seg"]] += 1
    if by_seg or by_seg_untouched:
        all_segs = set(list(by_seg.keys()) + list(by_seg_untouched.keys()))
        print(f"BY VERTICAL")
        for seg in sorted(all_segs):
            deltas = by_seg.get(seg, [])
            un = by_seg_untouched.get(seg, 0)
            if deltas:
                avg = sum(deltas) / len(deltas)
                print(f"  {seg:<20} {len(deltas):>3} touched (avg {fmt_delta(avg)}) | {un} untouched")
            else:
                print(f"  {seg:<20}   0 touched | {un} untouched")
        print()

    # Individual records sorted by delta (fastest first, untouched at end)
    print(f"{'─'*80}")
    print(f"LEAD-BY-LEAD (fastest first, untouched at end)")
    print(f"{'─'*80}")
    sorted_records = sorted(records, key=lambda r: (r["delta_hours"] is None, r["delta_hours"] or 0))
    for r in sorted_records:
        sub_str = fmt_ct(r["sub_dt"])
        sdr = r["sdr_owner"]
        if r["delta_hours"] is not None:
            touch_str = fmt_ct(r["touch_dt"])
            print(f"  {r['name']:<28} {sdr:<12} {r['tf_seg']:<14} sub:{sub_str}  "
                  f"touch:{touch_str} ({fmt_delta(r['delta_hours'])})  {r['touch_type']}")
        else:
            print(f"  {r['name']:<28} {sdr:<12} {r['tf_seg']:<14} sub:{sub_str}  *** NO TOUCH YET ***")

    print(f"\n{'='*80}")
    print("Done.")

if __name__ == "__main__":
    main()
