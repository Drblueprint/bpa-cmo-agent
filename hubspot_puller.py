"""
HubSpot puller -pulls deals, contacts, and funnel metrics
for the CMO weekly report v3.
Pure stdlib.
"""

import json
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from collections import defaultdict


HS_BASE = "https://api.hubapi.com"

# Custom HubSpot contact property that marks a current BPA member.
# Set to "active" in this account. Change here if the property name differs.
CUSTOMER_STATUS_PROPERTY = "status"

# HubSpot internal name for the "Typeform Asset Download" custom property.
# Verify in HubSpot → Contacts → any record → Edit property → internal name.
TYPEFORM_ASSET_PROPERTY = "typeform_asset_download"

# Typeform ID → asset metadata. IDs are the 8-char Typeform form IDs.
# Versioned IDs (e.g., Bk2mBKtv-v2-vjRmK) are matched on the first segment.
TYPEFORM_ASSETS = {
    # PT Recovery
    "Bk2mBKtv": {"name": "Recovery Program - PT",                           "segment": "PT Recovery"},
    "J3c2bopX": {"name": "GHL - Revolutionizing Your PT",                   "segment": "PT Recovery"},
    "dVorB3zL": {"name": "GHL - The Informed Physical Therapist",           "segment": "PT Recovery"},
    "FntbAiwB": {"name": "GHL - Scaling Success - PT",                      "segment": "PT Recovery"},
    "c3eZNWai": {"name": "GHL - Can We Help You Scale? - PT",               "segment": "PT Recovery"},
    "tvt0SXEc": {"name": "GHL - 5 Million Dollar Practice Secret - PT",     "segment": "PT Recovery"},
    "RgiH0AP6": {"name": "GHL - Top 10 PT",                                 "segment": "PT Recovery"},
    # Chiro
    "G2XSMBQ2": {"name": "GHL - Can We Help You Scale? (Cold) - Chiro",    "segment": "Chiro"},
    "kq3O4WCH": {"name": "Top 10 - BPA Typeform",                          "segment": "Chiro"},
    "RuxSc00b": {"name": "Are You A Good Fit For BPA?",                     "segment": "Chiro"},
    "dbBedZQ2": {"name": "5 Million Dollar Practice Secrets - Chiro",       "segment": "Chiro"},
    "oZZrFJrU": {"name": "The Informed Chiropractor",                       "segment": "Chiro"},
    "Az5i6mFe": {"name": "BPA Revenue Pyramid",                             "segment": "Chiro"},
    "pA4t4h28": {"name": "The Big Chiropractic Practice Growth Problem",    "segment": "Chiro"},
    "iFdpzfQP": {"name": "Chiro Never Reach $1M",                          "segment": "Chiro"},
    "NeYfDACk": {"name": "Adding High-Premium Niches to Your Chiro Practice","segment": "Chiro"},
    "EJiqOhZZ": {"name": "GHL - Cory Hennessey Case Study",                "segment": "Chiro"},
    "qhtyKDv9": {"name": "GHL - 4 P's Of Practice Performance",            "segment": "Chiro"},
    "Pg69MDm9": {"name": "GHL - High Impact Checklist",                    "segment": "Chiro"},
    "GlTte50Q": {"name": "GHL - Dr. Melissa Arnold Opt-In",                "segment": "Chiro"},
    "XLBa3d5k": {"name": "GHL - Josiah Fitzsimmons Case Study",            "segment": "Chiro"},
    # EMX / Event
    "sb2SXsps": {"name": "EMX Fort Worth - Chiro",                         "segment": "EMX / Event"},
    "YTRTGc0T": {"name": "VEMX",                                            "segment": "EMX / Event"},
    "lunch-N-learn": {"name": "Virtual Lunch and Learn",                   "segment": "EMX / Event"},
}


# HubSpot stores display names (set by the Typeform integration), not form IDs.
# This maps the exact strings HubSpot stores to the canonical form ID in TYPEFORM_ASSETS.
HUBSPOT_TYPEFORM_NAMES = {
    "can we help you scale typeform":              "G2XSMBQ2",  # Chiro version (most common)
    "top 10 typeform":                             "kq3O4WCH",
    "bpa revenue pyramid typeform":                "Az5i6mFe",
    "emx fort worth 2026":                         "sb2SXsps",
    "emx forth worth typeform":                    "sb2SXsps",  # typo variant in HubSpot
    "5 million dollar practice secrets typeform":  "dbBedZQ2",  # Chiro version
    "recovery program (pt) typeform":              "Bk2mBKtv",
    "chiro never reach $1m":                       "iFdpzfQP",
    "the informed chiro typeform":                 "oZZrFJrU",
}


def typeform_asset_of(value: str) -> dict | None:
    """Map a HubSpot 'Typeform Asset Download' property value to asset metadata.

    Check order: exact form ID, versioned ID prefix, HubSpot display name alias,
    then case-insensitive name match against TYPEFORM_ASSETS names.
    """
    if not value:
        return None
    v = value.strip()
    if v in TYPEFORM_ASSETS:
        return TYPEFORM_ASSETS[v]
    prefix = v.split("-")[0]
    if prefix and prefix in TYPEFORM_ASSETS:
        return TYPEFORM_ASSETS[prefix]
    # HubSpot display name alias (case-insensitive)
    v_lower = v.lower()
    form_id = HUBSPOT_TYPEFORM_NAMES.get(v_lower)
    if form_id and form_id in TYPEFORM_ASSETS:
        return TYPEFORM_ASSETS[form_id]
    # Fallback: exact name match in TYPEFORM_ASSETS
    for meta in TYPEFORM_ASSETS.values():
        if meta["name"].lower() == v_lower:
            return meta
    return None

# Pipelines relevant to marketing attribution (from probe)
MARKETING_PIPELINES = {
    "11415832": "SDR Pipeline",
    "705868912": "PT Marketing Pipeline",
    "default": "Sales Pipeline",
    "8346417": "SALES - V2",
}

# Stages representing progression in SDR / PT / Sales pipelines
STAGE_BUCKETS = {
    # New marketing leads
    "1197483324": "new_lead",       # SDR: New marketing Lead
    "1031544103": "new_lead",       # PT: New Marketing Lead
    # 15-min booked
    "33595198":   "call15_booked",  # SDR
    "1031449106": "call15_booked",  # PT
    "14814277":   "call15_booked",  # Sales
    # 15-min completed qualified
    "33630024":   "call15_qualified",  # SDR
    "1031449108": "call15_qualified",  # PT
    "244868722":  "call15_qualified",  # Sales 15 Min Call Completed
    # Strategy call scheduled
    "1269186469": "strategy_scheduled",  # SDR
    "1031527734": "strategy_scheduled",  # PT
    "appointmentscheduled": "strategy_scheduled",  # Sales
    # Strategy call completed qualified
    "33630026":   "strategy_qualified",  # SDR
    "1270074157": "strategy_qualified",  # PT
    "qualifiedtobuy": "strategy_qualified",  # Sales
    "1057070392": "strategy_qualified",  # PT BAMFAM
    # Closing calls
    "1269193335": "closing_scheduled",  # SDR Closing Call Scheduled
    "1214324055": "closing_complete",   # SDR Closing Call Complete
    "1057070393": "closing_complete",   # PT Closing Call Complete
    # Won/Lost
    "closedwon":   "closed_won",
    "closedlost":  "closed_lost",
    "24094605":    "closed_won",   # SALES-V2
    "24094606":    "closed_lost",  # SALES-V2
    "23989362":    "closed_won",   # Contract Pipeline
    "23989363":    "closed_lost",
}


def hs_request(method: str, path: str, token: str, payload: dict = None, params: dict = None):
    url = HS_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"error": e.read().decode()[:500]}


def search_paginate(object_type: str, token: str, payload: dict, max_results: int = 10000) -> list:
    """Paginate /crm/v3/objects/{type}/search using the 'after' cursor."""
    results = []
    after = None
    while True:
        body = dict(payload)
        body["limit"] = min(100, max_results - len(results))
        if after:
            body["after"] = after
        status, resp = hs_request("POST", f"/crm/v3/objects/{object_type}/search", token, body)
        if status >= 400:
            print(f"  HubSpot API error {status}: {resp.get('message', resp)}")
            break
        batch = resp.get("results", [])
        results.extend(batch)
        if len(results) >= max_results:
            break
        paging = (resp.get("paging") or {}).get("next") or {}
        after = paging.get("after")
        if not after or not batch:
            break
    return results


def lookup_contacts_by_email(token: str, emails: list) -> dict:
    """Batch-fetch HubSpot contacts by email. Returns dict of email -> properties."""
    if not emails:
        return {}
    result = {}
    for i in range(0, len(emails), 100):
        chunk = emails[i:i + 100]
        payload = {
            "inputs": [{"id": e} for e in chunk],
            "properties": [
                "email", "firstname", "lastname", "lifecyclestage",
                TYPEFORM_ASSET_PROPERTY, "typeform_submission_date",
                "hs_analytics_source", "utm_source", "utm_campaign",
            ],
            "idProperty": "email",
        }
        status, resp = hs_request("POST", "/crm/v3/objects/contacts/batch/read", token, payload)
        if status >= 400:
            continue
        for r in resp.get("results", []):
            email = (r.get("properties", {}).get("email") or "").lower().strip()
            if email:
                result[email] = r.get("properties", {})
    return result


def pull_deals_in_window(token: str, from_ms: int, to_ms: int, pipelines: list) -> list:
    """Deals created within window in the given pipelines."""
    payload = {
        "filterGroups": [{
            "filters": [
                {"propertyName": "createdate", "operator": "GTE", "value": str(from_ms)},
                {"propertyName": "createdate", "operator": "LTE", "value": str(to_ms)},
                {"propertyName": "pipeline", "operator": "IN", "values": pipelines},
            ]
        }],
        "properties": [
            "dealname", "amount", "pipeline", "dealstage", "createdate",
            "closedate", "hs_analytics_source", "hs_analytics_source_data_1",
            "hs_analytics_source_data_2", "dealtype", "hubspot_owner_id",
        ],
        "sorts": [{"propertyName": "createdate", "direction": "DESCENDING"}],
    }
    return search_paginate("deals", token, payload, max_results=5000)


def pull_deals_closed_won(token: str, from_ms: int, to_ms: int) -> list:
    """Deals marked closed won within the window (any pipeline)."""
    payload = {
        "filterGroups": [{
            "filters": [
                {"propertyName": "closedate", "operator": "GTE", "value": str(from_ms)},
                {"propertyName": "closedate", "operator": "LTE", "value": str(to_ms)},
                {"propertyName": "dealstage", "operator": "IN",
                 "values": ["closedwon", "24094605", "23989362"]},
            ]
        }],
        "properties": [
            "dealname", "amount", "pipeline", "dealstage", "createdate",
            "closedate", "hs_analytics_source", "hs_analytics_source_data_1",
            "hubspot_owner_id",
        ],
    }
    return search_paginate("deals", token, payload, max_results=2000)


def get_deal_contact_ids(token: str, deal_id: str) -> list:
    """Contact IDs associated with a deal via HubSpot v4 associations API."""
    status, resp = hs_request("GET", f"/crm/v4/objects/deals/{deal_id}/associations/contacts", token)
    if status >= 400:
        return []
    return [r.get("toObjectId") for r in resp.get("results", []) if r.get("toObjectId")]


def batch_get_contacts(token: str, contact_ids: list, properties: list) -> dict:
    """Batch-fetch contacts by ID. Returns dict of id -> properties."""
    if not contact_ids:
        return {}
    payload = {
        "inputs": [{"id": str(cid)} for cid in contact_ids],
        "properties": properties,
    }
    status, resp = hs_request("POST", "/crm/v3/objects/contacts/batch/read", token, payload)
    if status >= 400:
        return {}
    return {r["id"]: r.get("properties", {}) for r in resp.get("results", [])}


def enrich_deals_with_typeform(token: str, deals: list) -> list:
    """For each closed won deal, find the associated contact's typeform_asset_download."""
    enriched = []
    for deal in deals:
        contact_ids = get_deal_contact_ids(token, deal.get("id"))
        typeform_asset = None
        typeform_segment = None
        if contact_ids:
            contacts = batch_get_contacts(token, contact_ids, [TYPEFORM_ASSET_PROPERTY])
            for props in contacts.values():
                tf_val = props.get(TYPEFORM_ASSET_PROPERTY)
                if tf_val:
                    asset = typeform_asset_of(tf_val)
                    typeform_asset = asset["name"] if asset else tf_val
                    typeform_segment = asset["segment"] if asset else "Other"
                    break
        enriched.append({**deal, "_typeform_asset": typeform_asset, "_typeform_segment": typeform_segment})
    return enriched


def pull_contacts_in_window(token: str, from_ms: int, to_ms: int) -> list:
    """Contacts created in window with attribution fields."""
    payload = {
        "filterGroups": [{
            "filters": [
                {"propertyName": "createdate", "operator": "GTE", "value": str(from_ms)},
                {"propertyName": "createdate", "operator": "LTE", "value": str(to_ms)},
            ]
        }],
        "properties": [
            "email", "lifecyclestage", "createdate",
            "hs_analytics_source", "hs_analytics_source_data_1",
            "hs_analytics_source_data_2", "hs_latest_source",
            "hs_latest_source_data_1", "hs_latest_source_data_2",
            "first_conversion_event_name", "first_conversion_date",
            "utm_source", "utm_medium", "utm_campaign", "utm_content",
            TYPEFORM_ASSET_PROPERTY,
        ],
    }
    return search_paginate("contacts", token, payload, max_results=5000)


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def summarize_funnel(deals: list) -> dict:
    """Count deals that hit each funnel bucket by current stage."""
    funnel = defaultdict(int)
    total_value = 0.0
    by_pipeline = defaultdict(lambda: defaultdict(int))
    for d in deals:
        props = d.get("properties", {})
        stage = props.get("dealstage")
        pipeline = props.get("pipeline")
        bucket = STAGE_BUCKETS.get(stage, "other")
        funnel[bucket] += 1
        by_pipeline[pipeline][bucket] += 1
        amt = props.get("amount")
        if amt:
            try:
                total_value += float(amt)
            except Exception:
                pass
    return {
        "funnel": dict(funnel),
        "by_pipeline": {k: dict(v) for k, v in by_pipeline.items()},
        "total_value": total_value,
        "deal_count": len(deals),
    }


def summarize_closed_won(deals: list) -> dict:
    total_revenue = 0.0
    typeform_revenue = 0.0
    typeform_count = 0
    by_source = defaultdict(lambda: {"count": 0, "revenue": 0.0})
    by_pipeline = defaultdict(lambda: {"count": 0, "revenue": 0.0})
    by_typeform_asset: dict = defaultdict(lambda: {"count": 0, "revenue": 0.0})
    by_typeform_segment: dict = defaultdict(lambda: {"count": 0, "revenue": 0.0})
    for d in deals:
        props = d.get("properties", {})
        amt = 0.0
        try:
            amt = float(props.get("amount") or 0)
        except Exception:
            pass
        total_revenue += amt
        src = props.get("hs_analytics_source") or "UNKNOWN"
        by_source[src]["count"] += 1
        by_source[src]["revenue"] += amt
        pipe = props.get("pipeline") or "UNKNOWN"
        by_pipeline[pipe]["count"] += 1
        by_pipeline[pipe]["revenue"] += amt
        tf_asset = d.get("_typeform_asset")
        tf_seg = d.get("_typeform_segment")
        if tf_asset:
            typeform_revenue += amt
            typeform_count += 1
            by_typeform_asset[tf_asset]["count"] += 1
            by_typeform_asset[tf_asset]["revenue"] += amt
        if tf_seg:
            by_typeform_segment[tf_seg]["count"] += 1
            by_typeform_segment[tf_seg]["revenue"] += amt
    return {
        "count": len(deals),
        "revenue": total_revenue,
        "aov": (total_revenue / len(deals)) if deals else 0,
        "typeform_count": typeform_count,
        "typeform_revenue": typeform_revenue,
        "typeform_aov": (typeform_revenue / typeform_count) if typeform_count else 0,
        "by_source": dict(by_source),
        "by_pipeline": dict(by_pipeline),
        "by_typeform_asset": dict(sorted(by_typeform_asset.items(), key=lambda x: -x[1]["revenue"])),
        "by_typeform_segment": dict(by_typeform_segment),
    }


def summarize_contacts(contacts: list) -> dict:
    by_lifecycle = defaultdict(int)
    by_source = defaultdict(int)
    by_fb_campaign = defaultdict(int)
    by_typeform_asset: dict = defaultdict(int)
    by_typeform_segment: dict = defaultdict(int)
    facebook_leads = 0
    for c in contacts:
        props = c.get("properties", {})
        by_lifecycle[props.get("lifecyclestage") or "none"] += 1
        src = props.get("hs_latest_source") or props.get("hs_analytics_source") or "UNKNOWN"
        by_source[src] += 1
        # Use utm_source=facebook as the reliable paid social signal
        utm_src = (props.get("utm_source") or "").lower()
        utm_campaign = props.get("utm_campaign") or props.get("hs_latest_source_data_1") or "unknown"
        if utm_src == "facebook":
            facebook_leads += 1
            by_fb_campaign[utm_campaign] += 1
        elif src == "PAID_SOCIAL":
            # Fallback for contacts without UTM properties
            facebook_leads += 1
            campaign = props.get("hs_latest_source_data_1") or props.get("hs_analytics_source_data_1") or "unknown"
            by_fb_campaign[campaign] += 1
        asset = typeform_asset_of(props.get(TYPEFORM_ASSET_PROPERTY))
        if asset:
            by_typeform_asset[asset["name"]] += 1
            by_typeform_segment[asset["segment"]] += 1
    typeform_total = sum(by_typeform_asset.values())
    return {
        "count": len(contacts),
        "by_lifecycle": dict(by_lifecycle),
        "by_source": dict(by_source),
        "by_fb_campaign": dict(by_fb_campaign),
        "facebook_leads": facebook_leads,
        "by_typeform_asset": dict(sorted(by_typeform_asset.items(), key=lambda x: -x[1])),
        "by_typeform_segment": dict(by_typeform_segment),
        "typeform_attributed": typeform_total,
        "typeform_attribution_rate": (typeform_total / len(contacts) * 100) if contacts else 0,
    }


SALES_V2_PIPELINE = "8346417"
SALES_V2_CLOSED_WON = "24094605"


def pull_customers_active(token: str) -> list:
    """Current BPA doctors - contacts associated with Closed Won deals in the SALES-V2 pipeline.

    This is the authoritative source: a closed won deal in SALES-V2 = money collected.
    """
    contact_properties = [
        "email", "firstname", "lastname", "lifecyclestage", "createdate",
        "hs_analytics_source", "hs_analytics_source_data_1",
        "hs_analytics_source_data_2", "hs_latest_source",
        "hs_latest_source_data_1", "hs_latest_source_data_2",
        "utm_source", "utm_medium", "utm_campaign", "utm_content",
        TYPEFORM_ASSET_PROPERTY,
    ]

    # Pull all closed won deals from SALES-V2 (no date filter - all time)
    payload = {
        "filterGroups": [{"filters": [
            {"propertyName": "pipeline", "operator": "EQ", "value": SALES_V2_PIPELINE},
            {"propertyName": "dealstage", "operator": "EQ", "value": SALES_V2_CLOSED_WON},
        ]}],
        "properties": ["dealname", "amount", "closedate", "createdate"],
    }
    deals = search_paginate("deals", token, payload, max_results=5000)

    # Collect all associated contact IDs across all deals
    all_contact_ids: list = []
    seen_deal_contacts: set = set()
    for deal in deals:
        for cid in get_deal_contact_ids(token, deal.get("id")):
            if cid not in seen_deal_contacts:
                seen_deal_contacts.add(cid)
                all_contact_ids.append(cid)

    if not all_contact_ids:
        return []

    # Batch-fetch contacts in chunks of 100 (HubSpot batch read limit)
    contacts = []
    for i in range(0, len(all_contact_ids), 100):
        chunk = all_contact_ids[i:i + 100]
        result = batch_get_contacts(token, chunk, contact_properties)
        for cid, props in result.items():
            contacts.append({"id": cid, "properties": props})

    return contacts


def summarize_customers(customers: list, window_from_ms: int = None, window_to_ms: int = None) -> dict:
    """Source attribution + Typeform asset breakdown for current BPA doctor contacts."""
    by_source: dict = defaultdict(int)
    by_fb_campaign: dict = defaultdict(int)
    by_typeform_asset: dict = defaultdict(int)
    by_typeform_segment: dict = defaultdict(int)
    lifecycle_counts: dict = defaultdict(int)
    status_values: dict = defaultdict(int)
    new_in_window = 0

    facebook_customers = 0
    for c in customers:
        props = c.get("properties", {})
        src = props.get("hs_latest_source") or props.get("hs_analytics_source") or "UNKNOWN"
        by_source[src] += 1
        utm_src = (props.get("utm_source") or "").lower()
        utm_campaign = props.get("utm_campaign") or props.get("hs_latest_source_data_1") or "unknown"
        if utm_src == "facebook":
            facebook_customers += 1
            by_fb_campaign[utm_campaign] += 1
        elif src == "PAID_SOCIAL":
            facebook_customers += 1
            campaign = props.get("hs_latest_source_data_1") or props.get("hs_analytics_source_data_1") or "unknown"
            by_fb_campaign[campaign] += 1
        lifecycle_counts[props.get("lifecyclestage") or "none"] += 1
        asset = typeform_asset_of(props.get(TYPEFORM_ASSET_PROPERTY))
        if asset:
            by_typeform_asset[asset["name"]] += 1
            by_typeform_segment[asset["segment"]] += 1
        if window_from_ms and window_to_ms:
            cd = props.get("createdate")
            if cd:
                try:
                    if window_from_ms <= int(cd) <= window_to_ms:
                        new_in_window += 1
                except (ValueError, TypeError):
                    pass

    typeform_total = sum(by_typeform_asset.values())
    return {
        "total_active": len(customers),
        "new_in_window": new_in_window,
        "facebook_attributed": facebook_customers,
        "facebook_pct": (facebook_customers / len(customers) * 100) if customers else 0,
        "typeform_attributed": typeform_total,
        "typeform_attribution_rate": (typeform_total / len(customers) * 100) if customers else 0,
        "by_source": dict(by_source),
        "by_fb_campaign": dict(sorted(by_fb_campaign.items(), key=lambda x: -x[1])),
        "by_typeform_asset": dict(sorted(by_typeform_asset.items(), key=lambda x: -x[1])),
        "by_typeform_segment": dict(by_typeform_segment),
        "lifecycle_counts": dict(lifecycle_counts),
    }


def pull_all(token: str, days: int) -> dict:
    now = datetime.now()
    start = now - timedelta(days=days)
    from_ms = ms(start)
    to_ms = ms(now)

    deals_marketing = pull_deals_in_window(
        token, from_ms, to_ms,
        list(MARKETING_PIPELINES.keys())
    )
    deals_won_raw = pull_deals_closed_won(token, from_ms, to_ms)
    deals_won = enrich_deals_with_typeform(token, deals_won_raw)
    contacts = pull_contacts_in_window(token, from_ms, to_ms)
    customers = pull_customers_active(token)

    return {
        "window_start": start.isoformat(),
        "window_end": now.isoformat(),
        "days": days,
        "deals_marketing_created": deals_marketing,
        "deals_closed_won": deals_won,
        "contacts_created": contacts,
        "customers_active": customers,
        "funnel_summary": summarize_funnel(deals_marketing),
        "revenue_summary": summarize_closed_won(deals_won),
        "contact_summary": summarize_contacts(contacts),
        "customer_summary": summarize_customers(customers, from_ms, to_ms),
    }


if __name__ == "__main__":
    import sys
    from pathlib import Path

    def load_env(path: Path) -> dict:
        env = {}
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
        return env

    env = load_env(Path(__file__).parent /".env")
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    print(f"Pulling HubSpot last {days}d...")
    data = pull_all(env["HUBSPOT_TOKEN"], days)
    print(f"\n=== {days}d Window ===")
    print(f"Contacts created: {data['contact_summary']['count']}")
    print(f"  By lifecycle: {data['contact_summary']['by_lifecycle']}")
    print(f"  By source: {data['contact_summary']['by_source']}")
    print(f"\nMarketing deals created: {data['funnel_summary']['deal_count']}")
    print(f"  Funnel: {data['funnel_summary']['funnel']}")
    print(f"\nClosed won: {data['revenue_summary']['count']} deals, ${data['revenue_summary']['revenue']:,.0f}")
    print(f"  AOV: ${data['revenue_summary']['aov']:,.0f}")
    print(f"  By source: {data['revenue_summary']['by_source']}")
