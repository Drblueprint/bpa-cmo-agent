"""
HubSpot puller — pulls deals, contacts, and funnel metrics
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
    by_source = defaultdict(lambda: {"count": 0, "revenue": 0.0})
    by_pipeline = defaultdict(lambda: {"count": 0, "revenue": 0.0})
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
    return {
        "count": len(deals),
        "revenue": total_revenue,
        "aov": (total_revenue / len(deals)) if deals else 0,
        "by_source": dict(by_source),
        "by_pipeline": dict(by_pipeline),
    }


def summarize_contacts(contacts: list) -> dict:
    by_lifecycle = defaultdict(int)
    by_source = defaultdict(int)
    by_fb_campaign = defaultdict(int)
    paid_social_emails = []
    for c in contacts:
        props = c.get("properties", {})
        by_lifecycle[props.get("lifecyclestage") or "none"] += 1
        src = props.get("hs_latest_source") or props.get("hs_analytics_source") or "UNKNOWN"
        by_source[src] += 1
        if src == "PAID_SOCIAL":
            campaign = props.get("hs_latest_source_data_1") or props.get("hs_analytics_source_data_1") or "unknown"
            by_fb_campaign[campaign] += 1
            email = props.get("email")
            if email:
                paid_social_emails.append(email)
    return {
        "count": len(contacts),
        "by_lifecycle": dict(by_lifecycle),
        "by_source": dict(by_source),
        "by_fb_campaign": dict(by_fb_campaign),
        "paid_social_emails": paid_social_emails,
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
    deals_won = pull_deals_closed_won(token, from_ms, to_ms)
    contacts = pull_contacts_in_window(token, from_ms, to_ms)

    return {
        "window_start": start.isoformat(),
        "window_end": now.isoformat(),
        "days": days,
        "deals_marketing_created": deals_marketing,
        "deals_closed_won": deals_won,
        "contacts_created": contacts,
        "funnel_summary": summarize_funnel(deals_marketing),
        "revenue_summary": summarize_closed_won(deals_won),
        "contact_summary": summarize_contacts(contacts),
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

    env = load_env(Path.home() / "Desktop" / "bpa-cmo-agent" / ".env")
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
