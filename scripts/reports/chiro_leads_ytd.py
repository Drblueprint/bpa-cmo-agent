"""One-shot report: every Chiro lead YTD with full activity profile.

Run: python scripts/reports/chiro_leads_ytd.py

Output: docs/reports/2026-XX-XX-chiro-leads-ytd.csv

Columns: HubSpot URL · Contact · Email · Mobile · Phone · Asset ·
Submitted (CT) · Created (CT) · Retro-stamped · Lifecycle · Contract Tier ·
Send Contract Option · SDR · BDS · SME · Latest 15-min Outcome ·
Latest 15-min (CT) · Latest Strategy Outcome · Latest Strategy (CT) ·
Closed-Won? · Closed-Won Amount · Closed-Won Date (CT) ·
Other Open Deal Stage.

Retro-stamped = YES when typeform_submission_date is >=7 days after
createdate (i.e., a pre-existing contact whose submission_date got
re-stamped by a bulk update — informational, not exclusionary).
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from dotenv import dotenv_values

# Repo root on sys.path so we can import dashboard.config
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dashboard import config as cfg

TOKEN = dotenv_values(str(ROOT / ".env")).get("HUBSPOT_TOKEN")
if not TOKEN:
    sys.exit("HUBSPOT_TOKEN missing in .env")
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def main() -> None:
    year_start = datetime(datetime.now(timezone.utc).year, 1, 1, tzinfo=timezone.utc)
    today = datetime.now(timezone.utc)
    start_ms = int(year_start.timestamp() * 1000)
    end_ms = int(today.timestamp() * 1000)

    # 1) All typeform contacts YTD whose asset maps to Chiro
    contacts: dict[str, dict] = {}
    body = {
        "filterGroups": [{
            "filters": [
                {"propertyName": "typeform_asset_download", "operator": "HAS_PROPERTY"},
                {"propertyName": "typeform_submission_date", "operator": "BETWEEN",
                 "value": start_ms, "highValue": end_ms},
            ]
        }],
        "properties": [
            "firstname", "lastname", "email", "phone", "mobilephone", "createdate",
            "typeform_asset_download", "typeform_submission_date", "lifecyclestage",
            "sdr_owner", "bds", "sme", "contract_tier", "send_contract_options",
            "utm_source",
        ],
        "limit": 100,
    }
    after = None
    while True:
        b = dict(body)
        if after:
            b["after"] = after
        r = requests.post(
            "https://api.hubapi.com/crm/v3/objects/contacts/search",
            headers=H, json=b, timeout=60,
        )
        r.raise_for_status()
        d = r.json()
        for c in d.get("results", []):
            p = c.get("properties") or {}
            fn = (p.get("firstname") or "").lower()
            ln = (p.get("lastname") or "").lower()
            if fn == "test" or ln == "test":
                continue
            em = (p.get("email") or "").strip().lower()
            if em in cfg.MARKETING_EXCLUDED_EMAILS:
                continue
            asset = p.get("typeform_asset_download") or ""
            if cfg.ASSET_TO_GROUP.get(asset) != "Chiro":
                continue
            contacts[c["id"]] = p
        after = (d.get("paging") or {}).get("next", {}).get("after")
        if not after:
            break
    print(f"Chiro contacts with submission in YTD: {len(contacts)}", file=sys.stderr)

    # --- Filter to FRESH 2026 leads only: createdate must be in YTD ---
    # The submission_date field is unreliable in HubSpot (bulk-stamps can
    # back-fill it for historical contacts). The contact's createdate is the
    # immutable signal of "when did this person first enter our system".
    fresh: dict[str, dict] = {}
    excluded = 0
    for cid, p in contacts.items():
        cre = p.get("createdate")
        if not cre:
            excluded += 1
            continue
        try:
            cd = datetime.fromisoformat(cre.replace("Z", "+00:00"))
            if cd >= year_start:
                fresh[cid] = p
            else:
                excluded += 1
        except Exception:
            excluded += 1
    print(f"FRESH 2026 leads (createdate in YTD): {len(fresh)}", file=sys.stderr)
    print(f"Excluded (createdate pre-2026 or missing): {excluded}", file=sys.stderr)
    contacts = fresh

    # 2) Contact -> deals via associations
    cids = list(contacts.keys())
    c2deals: dict[str, list[str]] = defaultdict(list)
    for i in range(0, len(cids), 100):
        batch = cids[i:i + 100]
        r = requests.post(
            "https://api.hubapi.com/crm/v4/associations/contacts/deals/batch/read",
            headers=H, json={"inputs": [{"id": cid} for cid in batch]}, timeout=60,
        )
        r.raise_for_status()
        for item in r.json().get("results", []):
            cid = str(item.get("from", {}).get("id"))
            for t in item.get("to", []):
                c2deals[cid].append(str(t.get("toObjectId")))

    all_deal_ids = sorted({d for ds in c2deals.values() for d in ds})
    deals: dict[str, dict] = {}
    for i in range(0, len(all_deal_ids), 100):
        batch = all_deal_ids[i:i + 100]
        r = requests.post(
            "https://api.hubapi.com/crm/v3/objects/deals/batch/read", headers=H,
            json={
                "properties": ["dealname", "dealstage", "amount", "closedate", "createdate"],
                "inputs": [{"id": d} for d in batch],
            }, timeout=60,
        )
        if r.status_code >= 400:
            continue
        for d in r.json().get("results", []):
            deals[d["id"]] = d.get("properties") or {}
    print(f"Deals fetched: {len(deals)}", file=sys.stderr)

    # 3) YTD meetings: search by start_time, then associate to contacts
    meetings_body = {
        "filterGroups": [{"filters": [{"propertyName": "hs_meeting_start_time",
                                          "operator": "BETWEEN",
                                          "value": start_ms, "highValue": end_ms}]}],
        "properties": ["hs_activity_type", "hs_meeting_outcome",
                       "hs_meeting_start_time", "hs_meeting_title"],
        "limit": 100,
    }
    m_records = []
    after = None
    while True:
        b = dict(meetings_body)
        if after:
            b["after"] = after
        r = requests.post(
            "https://api.hubapi.com/crm/v3/objects/meetings/search",
            headers=H, json=b, timeout=60,
        )
        r.raise_for_status()
        d = r.json()
        for o in d.get("results", []):
            p = o.get("properties") or {}
            m_records.append({
                "id": o["id"],
                "type": (p.get("hs_activity_type") or "").lower(),
                "title": (p.get("hs_meeting_title") or "").lower(),
                "outcome": (p.get("hs_meeting_outcome") or "").upper(),
                "start": p.get("hs_meeting_start_time"),
            })
        after = (d.get("paging") or {}).get("next", {}).get("after")
        if not after:
            break
    print(f"YTD meetings: {len(m_records)}", file=sys.stderr)

    mids = [m["id"] for m in m_records]
    m2c: dict[str, str] = {}
    for i in range(0, len(mids), 100):
        batch = mids[i:i + 100]
        r = requests.post(
            "https://api.hubapi.com/crm/v4/associations/meetings/contacts/batch/read",
            headers=H, json={"inputs": [{"id": mid} for mid in batch]}, timeout=60,
        )
        if r.status_code >= 400:
            continue
        for item in r.json().get("results", []):
            mid = str(item.get("from", {}).get("id"))
            cids_ = [str(t.get("toObjectId")) for t in item.get("to", [])]
            if cids_:
                m2c[mid] = cids_[0]

    c15: dict[str, dict] = {}
    cstr: dict[str, dict] = {}
    for m in m_records:
        cid = m2c.get(m["id"])
        if not cid or cid not in contacts:
            continue
        is15 = "15 min" in m["type"] or "15 min" in m["title"] or "15-min" in m["title"]
        isStrat = "strategy" in m["type"] or "strategy" in m["title"]
        target = c15 if is15 else (cstr if isStrat else None)
        if target is None:
            continue
        prev = target.get(cid)
        if prev is None or (m["start"] or "") > (prev["start"] or ""):
            target[cid] = m

    # 4) Closed-won per contact + representative open-deal stage
    cwon: dict[str, dict] = {}
    deal_stage: dict[str, str] = {}
    for cid, dids in c2deals.items():
        for did in dids:
            d = deals.get(did) or {}
            if d.get("dealstage") in cfg.STAGES_CLOSED_WON:
                cwon[cid] = d
                break
        if cid not in cwon and dids:
            d = deals.get(dids[0]) or {}
            deal_stage[cid] = d.get("dealstage", "")

    def fmt_ct(iso):
        if not iso:
            return ""
        try:
            return (datetime.fromisoformat(iso.replace("Z", "+00:00"))
                    .astimezone(timezone(timedelta(hours=-5)))
                    .strftime("%m/%d/%Y %I:%M %p"))
        except Exception:
            return iso

    out_path = ROOT / "docs" / "reports" / f"{today.date().isoformat()}-chiro-leads-2026-created.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            "HubSpot URL", "Contact", "Email", "Mobile", "Phone",
            "Asset", "Submitted (CT)", "Created (CT)", "Retro-stamped",
            "Lifecycle", "Contract Tier", "Send Contract Option",
            "SDR Owner", "BDS", "SME",
            "Latest 15-min Outcome", "Latest 15-min (CT)",
            "Latest Strategy Outcome", "Latest Strategy (CT)",
            "Closed-Won?", "Closed-Won Amount", "Closed-Won Date (CT)",
            "Other Open Deal Stage",
        ])
        rows = []
        for cid, p in contacts.items():
            sub = p.get("typeform_submission_date")
            cre = p.get("createdate")
            retro = ""
            try:
                if sub and cre:
                    sd = datetime.fromisoformat(sub.replace("Z", "+00:00")).date()
                    cd = datetime.fromisoformat(cre.replace("Z", "+00:00")).date()
                    retro = "YES" if (sd - cd).days >= 7 else "no"
            except Exception:
                pass
            m15 = c15.get(cid) or {}
            mstr = cstr.get(cid) or {}
            won = cwon.get(cid)
            rows.append([
                cfg.hubspot_contact_url(cid),
                f"{(p.get('firstname') or '')} {(p.get('lastname') or '')}".strip(),
                p.get("email") or "",
                p.get("mobilephone") or "",
                p.get("phone") or "",
                p.get("typeform_asset_download") or "",
                fmt_ct(sub), fmt_ct(cre), retro,
                p.get("lifecyclestage") or "",
                p.get("contract_tier") or "",
                p.get("send_contract_options") or "",
                cfg.resolve_owner(p.get("sdr_owner")),
                cfg.resolve_owner(p.get("bds")),
                cfg.resolve_owner(p.get("sme")),
                m15.get("outcome", ""), fmt_ct(m15.get("start", "")),
                mstr.get("outcome", ""), fmt_ct(mstr.get("start", "")),
                "YES" if won else "no",
                won.get("amount", "") if won else "",
                fmt_ct(won.get("closedate", "")) if won else "",
                deal_stage.get(cid, "") if not won else "",
                sub or "",  # sort key, dropped before write
            ])
        rows.sort(key=lambda r: r[-1], reverse=True)
        for r in rows:
            w.writerow(r[:-1])
    print(f"WROTE {out_path}", file=sys.stderr)
    print(f"ROWS {len(rows)}", file=sys.stderr)


if __name__ == "__main__":
    main()
