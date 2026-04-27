"""
Tool implementations for the BPA CMO Agent listener.

Each @beta_tool function is exposed to Claude via the Anthropic tool_runner.
All tools are READ-ONLY: they pull and summarize data. None of them write,
post, delete, or modify anything in external systems.

Subprocess execution is used for tools that wrap existing scripts, so the
existing scripts don't need refactoring and any print-side effects stay
contained.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

from anthropic import beta_tool


BASE = Path(__file__).parent


# --- env helpers ---------------------------------------------------------

def _load_env() -> dict:
    env = {}
    for line in (BASE / ".env").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def _run_script(args: list[str], timeout: int = 120) -> str:
    """Run a Python script in this directory, return stdout (truncated on over-length)."""
    cmd = [sys.executable, *args]
    try:
        r = subprocess.run(
            cmd, cwd=str(BASE), capture_output=True, text=True,
            timeout=timeout, env={**__import__("os").environ, "PYTHONWARNINGS": "ignore"},
        )
    except subprocess.TimeoutExpired:
        return f"TIMEOUT after {timeout}s running {' '.join(args)}"

    out = r.stdout.strip()
    err = r.stderr.strip()
    if r.returncode != 0:
        return f"SCRIPT FAILED (exit {r.returncode})\nstderr:\n{err[:3000]}\n\nstdout:\n{out[:2000]}"
    if len(out) > 12000:
        out = out[:12000] + f"\n\n[output truncated, {len(out)-12000} more chars]"
    return out or "(no output)"


def _http_get(url: str, params: dict | None = None) -> tuple[int, dict]:
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"error": e.read().decode()[:500]}
    except Exception as e:
        return 0, {"error": str(e)}


def _action_value(actions: list | None, atype: str) -> float:
    if not actions:
        return 0.0
    for a in actions:
        if a.get("action_type") == atype:
            return float(a.get("value", 0))
    return 0.0


# --- tools ---------------------------------------------------------------

@beta_tool
def run_weekly_ad_report(days: int = 7) -> str:
    """Run the full weekly marketing report: FB Ads + Hyros + HubSpot.

    Produces the complete funnel picture: spend, leads, CPL, booked calls,
    closed deals, ROAS, attribution-match rate, and the highest-leverage
    constraint for the week. This is the definitive weekly snapshot.

    Use when Dr. Gumm asks for "the weekly report", "what did we do last week",
    "how's the marketing doing overall", "full funnel picture", or ROAS questions.

    Slow tool (~30-60 seconds). Do not call more than once per conversation.

    Args:
        days: Report window in days. Default 7.
    """
    return _run_script(["weekly_report_v3.py", "--days", str(days)], timeout=180)


@beta_tool
def pull_ad_level_data(days: int = 7, filter_text: str = "") -> str:
    """Pull ad-level Facebook Ads performance (not just campaign-level).

    Returns each individual ad's name, campaign, spend, impressions, clicks,
    CTR, CPC, leads, and CPL. Optionally filter to only ads whose name or
    campaign contains a substring (e.g., "rob" for Dr. Rob ads, "pt" for
    PT Recovery, "audit" for $1M Audit funnel).

    Use when Dr. Gumm asks about specific ads, wants to compare individual
    creative performance, or needs per-ad CPL/CTR.

    Fast tool (~5-15 seconds). Safe to call once per conversation.

    Args:
        days: Lookback window in days. Default 7.
        filter_text: Case-insensitive substring to filter ad/campaign names.
            Empty string returns all ads.
    """
    args = ["ad_level_report.py", "--days", str(days)]
    if filter_text.strip():
        args.extend(["--filter", filter_text.strip()])
    return _run_script(args, timeout=60)


@beta_tool
def run_creative_diagnostic(days: int = 7, min_spend: float = 100.0) -> str:
    """Find underperforming ads and pull their creative (copy + image direction).

    Flags ads with zero leads, ads with CPL above 2x median, or ads with CTR
    below 1%. For each flagged ad, returns the headline, body, CTA, image URL,
    and metrics so Dr. Gumm can diagnose whether it's a creative problem, a
    targeting problem, or a landing-page problem.

    Use when Dr. Gumm asks "which ads aren't working", "show me the losers",
    "what's broken in creative", or wants a kill list.

    Medium-speed tool (~15-30 seconds). Only call when diagnostic is needed.

    Args:
        days: Lookback window in days. Default 7.
        min_spend: Minimum ad-level spend to consider. Default $100.
    """
    return _run_script(
        ["creative_diagnostic.py", "--days", str(days),
         "--min-spend", str(min_spend), "--max-ads", "10"],
        timeout=180,
    )


@beta_tool
def pull_hubspot_funnel(days: int = 7) -> str:
    """Pull HubSpot funnel metrics: contacts, deals by stage, closed-won, MQL rates.

    Returns new contacts by source (OFFLINE / DIRECT / PAID_SOCIAL / REFERRALS),
    deals by pipeline stage (new lead → 15-min booked → qualified → strategy
    scheduled → closed-won), closed-won revenue, and paid-social attribution rate.

    Use when Dr. Gumm asks about HubSpot, MQLs, closed deals, revenue last week,
    AOV, pipeline health, or attribution.

    Medium-speed tool (~10-20 seconds).

    Args:
        days: Lookback window in days. Default 7.
    """
    # Run a small inline script that imports hubspot_puller.pull_all and prints results
    inline = f"""
import sys, json
sys.path.insert(0, '{BASE}')
from pathlib import Path
from hubspot_puller import pull_all
from weekly_report_v2 import load_env
env = load_env(Path('{BASE}/.env'))
result = pull_all(env['HUBSPOT_TOKEN'], days={days})
contacts = result.get('contact_summary', {{}})
closed = result.get('revenue_summary', {{}})
deals_by_stage = (result.get('funnel_summary') or {{}}).get('funnel', {{}})
print(f'HubSpot funnel -last {days} days')
print(f'New contacts: {{contacts.get("count", 0)}}')
tf_total = contacts.get('typeform_attributed', 0)
tf_rate = contacts.get('typeform_attribution_rate', 0)
print(f'Typeform-attributed: {{tf_total}} ({{tf_rate:.0f}}%)')
print('By source:')
for src, n in (contacts.get('by_source') or {{}}).items():
    print(f'  {{src}}: {{n}}')
if contacts.get('by_typeform_segment'):
    print('By Typeform vertical:')
    for seg, n in sorted((contacts.get('by_typeform_segment') or {{}}).items(), key=lambda x: -x[1]):
        print(f'  {{seg}}: {{n}}')
if contacts.get('by_typeform_asset'):
    print('Top Typeform assets:')
    for asset_name, n in list((contacts.get('by_typeform_asset') or {{}}).items())[:8]:
        print(f'  {{asset_name}}: {{n}}')
print()
print(f'Closed won: {{closed.get("count", 0)}} deals = ${{closed.get("revenue", 0):,.0f}}')
print(f'AOV: ${{closed.get("aov", 0):,.0f}}')
print()
print('Funnel by bucket:')
for bucket, n in sorted((deals_by_stage or {{}}).items()):
    print(f'  {{bucket}}: {{n}}')
"""
    try:
        r = subprocess.run(
            [sys.executable, "-c", inline], cwd=str(BASE),
            capture_output=True, text=True, timeout=60,
            env={**__import__("os").environ, "PYTHONWARNINGS": "ignore"},
        )
        if r.returncode != 0:
            return f"HubSpot pull failed:\n{r.stderr[:1500]}"
        return r.stdout.strip() or "(empty)"
    except subprocess.TimeoutExpired:
        return "HubSpot pull timed out after 60s."


@beta_tool
def pull_hyros_attribution(days: int = 7) -> str:
    """Pull Hyros attribution: leads and booked calls with their ad sources.

    Returns the ad sources Hyros has attributed to leads and booked calls in
    the window. Useful for answering "which ads are Hyros crediting" vs
    "which ads Facebook reports as converting".

    Note: Hyros sale-event integration is currently NOT wired on Dr. Gumm's
    account, so revenue/ROAS from Hyros is unreliable. Use this for lead and
    call attribution only.

    Fast tool (~5-15 seconds).

    Args:
        days: Lookback window in days. Default 7.
    """
    env = _load_env()
    if "HYROS_API_KEY" not in env:
        return "Hyros API key not configured."
    base = "https://api.hyros.com/v1/api/v1.0"
    headers_hint = env["HYROS_API_KEY"]
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    until = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _call(path):
        url = f"{base}{path}?fromDate={since}&toDate={until}&pageSize=250"
        req = urllib.request.Request(url, headers={"API-Key": headers_hint})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            return {"error": str(e)}

    leads = _call("/leads")
    calls = _call("/calls")

    out = [f"Hyros attribution -{since} → {until}"]
    lead_rows = (leads.get("result") or {}).get("leads") or leads.get("data") or []
    call_rows = (calls.get("result") or {}).get("calls") or calls.get("data") or []
    out.append(f"Leads tracked: {len(lead_rows)}")
    out.append(f"Booked calls tracked: {len(call_rows)}")

    source_counts = {}
    for c in call_rows:
        src = (c.get("firstSource") or c.get("lastSource") or "unattributed")
        if isinstance(src, dict):
            src = src.get("name", "unattributed")
        source_counts[src] = source_counts.get(src, 0) + 1

    if source_counts:
        out.append("\nBooked calls by attributed source:")
        for src, n in sorted(source_counts.items(), key=lambda x: -x[1])[:15]:
            out.append(f"  {src}: {n}")
    else:
        out.append("\nNo call-source attribution data returned.")

    out.append("\nReminder: Hyros sale events aren't wired on this account; revenue/ROAS from Hyros is unreliable.")
    return "\n".join(out)


@beta_tool
def get_campaign_performance(campaign_name_contains: str, days: int = 7) -> str:
    """Get detailed performance for a specific Facebook campaign by name match.

    Returns the campaign's spend, impressions, clicks, CTR, CPC, leads, CPL,
    and also the individual ads within it and their per-ad performance.
    Useful when Dr. Gumm asks about a specific campaign or talent by name
    (e.g., "how's Dr. Rob doing", "what's happening with the PT Recovery
    campaign", "EMX results").

    Fast tool (~5-15 seconds).

    Args:
        campaign_name_contains: Case-insensitive substring of the campaign name.
        days: Lookback window. Default 7.
    """
    env = _load_env()
    token = env["FB_ADS_TOKEN"]
    acct = env["FB_AD_ACCOUNT_ID"]
    preset_map = {7: "last_7d", 14: "last_14d", 28: "last_28d", 30: "last_30d"}
    preset = preset_map.get(days, "last_7d")

    # Pull ad-level with campaign name field
    status, body = _http_get(
        f"https://graph.facebook.com/v19.0/act_{acct}/insights",
        {
            "date_preset": preset,
            "level": "ad",
            "fields": "ad_id,ad_name,campaign_name,spend,impressions,clicks,ctr,cpc,actions",
            "access_token": token,
            "limit": 500,
        },
    )
    if status >= 400:
        return f"FB API error {status}: {body}"

    rows = body.get("data", [])
    match = [r for r in rows if campaign_name_contains.lower() in (r.get("campaign_name") or "").lower()]
    if not match:
        return f"No campaigns matching '{campaign_name_contains}' in last {days}d."

    # Aggregate at campaign level
    by_campaign: dict[str, dict] = {}
    for r in match:
        c = r["campaign_name"]
        d = by_campaign.setdefault(c, {"spend": 0, "impr": 0, "clicks": 0, "leads": 0, "ads": []})
        d["spend"] += float(r.get("spend", 0))
        d["impr"] += int(r.get("impressions", 0))
        d["clicks"] += int(r.get("clicks", 0))
        d["leads"] += _action_value(r.get("actions"), "lead") or _action_value(r.get("actions"), "offsite_conversion.fb_pixel_lead")
        d["ads"].append({
            "ad": r.get("ad_name", "")[:70],
            "spend": float(r.get("spend", 0)),
            "ctr": float(r.get("ctr", 0)),
            "leads": _action_value(r.get("actions"), "lead") or _action_value(r.get("actions"), "offsite_conversion.fb_pixel_lead"),
        })

    out = [f"Campaigns matching '{campaign_name_contains}' -last {days}d\n"]
    for name, d in sorted(by_campaign.items(), key=lambda x: -x[1]["spend"]):
        ctr = (d["clicks"] / d["impr"] * 100) if d["impr"] else 0
        cpl = (d["spend"] / d["leads"]) if d["leads"] else None
        out.append(f"*{name}*")
        out.append(f"  ${d['spend']:,.0f} spend · {d['impr']:,} impr · {d['clicks']:,} clicks · "
                   f"CTR {ctr:.2f}% · {d['leads']:.0f} leads · "
                   f"CPL {'$'+format(cpl, ',.0f') if cpl else '—'}")
        out.append("  Ads in this campaign:")
        for a in sorted(d["ads"], key=lambda x: -x["spend"])[:8]:
            a_cpl = (a["spend"] / a["leads"]) if a["leads"] else None
            out.append(f"    - {a['ad']}: ${a['spend']:,.0f}, CTR {a['ctr']:.2f}%, "
                       f"{a['leads']:.0f} leads, CPL {'$'+format(a_cpl, ',.0f') if a_cpl else '—'}")
        out.append("")
    return "\n".join(out)


@beta_tool
def pull_hyros_lead_sources(days: int = 7) -> str:
    """Pull new Hyros leads and show which FB ad and campaign originated each one.

    For every lead Hyros tracked in the window, extracts the firstSource ad name
    and campaign so you can see which specific FB ads are generating leads
    according to Hyros (independent of FB self-reported numbers). Also shows
    vertical breakdown and unattributed count.

    Use when Dr. Gumm asks "which ads are generating leads in Hyros", "what does
    Hyros say about lead sources", or when cross-checking FB lead counts vs Hyros.

    Fast tool (~5-15 seconds).

    Args:
        days: Lookback window in days. Default 7.
    """
    inline = f"""
import sys
sys.path.insert(0, r'{BASE}')
from pathlib import Path
from weekly_report_v2 import load_env, hyros_leads, hyros_lead_source_rollup
from datetime import datetime, timedelta

env = load_env(Path(r'{BASE}') / '.env')
now = datetime.now()
start = (now - timedelta(days={days})).strftime('%Y-%m-%d')
today = now.strftime('%Y-%m-%d')

print(f'Pulling Hyros leads {start} to {today}...')
leads = hyros_leads(env['HYROS_API_KEY'], start, today)
r = hyros_lead_source_rollup(leads)

print(f'\\nHyros Lead Attribution - last {days} days')
print(f'Total leads: {{r[\"total\"]}}')
print(f'Ad-attributed: {{r[\"attributed\"]}} ({{r[\"attribution_rate\"]:.0f}}%)')
print(f'Unattributed: {{r[\"unattributed\"]}}')
if r.get('by_segment'):
    print('\\nBy vertical:')
    for seg, n in sorted(r['by_segment'].items(), key=lambda x: -x[1]):
        print(f'  {{seg}}: {{n}}')
if r.get('by_ad'):
    print('\\nTop originating ads (first-touch):')
    for ad, n in list(r['by_ad'].items())[:15]:
        print(f'  {{ad}}: {{n}} lead(s)')
if r.get('by_campaign'):
    print('\\nTop originating campaigns:')
    for camp, n in list(r['by_campaign'].items())[:10]:
        print(f'  {{camp}}: {{n}} lead(s)')
"""
    try:
        r = subprocess.run(
            [sys.executable, "-c", inline], cwd=str(BASE),
            capture_output=True, text=True, timeout=60,
            env={**__import__("os").environ, "PYTHONWARNINGS": "ignore"},
        )
        if r.returncode != 0:
            return f"Hyros lead source pull failed:\\n{r.stderr[:1500]}"
        return r.stdout.strip() or "(empty)"
    except subprocess.TimeoutExpired:
        return "Hyros lead source pull timed out after 60s."


@beta_tool
def pull_hubspot_customers(days: int = 7) -> str:
    """Pull current BPA doctors from HubSpot: contacts with lifecycle=customer OR status=active.

    Returns total active member count, how many are new in the reporting window,
    and their original source attribution (which ad channels / FB campaigns they
    came from). This is the closest proxy for closed-customer attribution until
    the Hyros sale-event webhook is wired.

    Use when Dr. Gumm asks "how many BPA doctors do we have", "current members",
    "customer count", "where are our customers coming from", or any question about
    the closed → active member stage of the funnel.

    Medium-speed tool (~10-20 seconds). Queries all-time active customers;
    the `days` window only affects the 'new contacts in period' count.

    Args:
        days: Window for counting new customers in this period. Default 7.
    """
    inline = f"""
import sys
sys.path.insert(0, r'{BASE}')
from pathlib import Path
from hubspot_puller import pull_customers_active, summarize_customers
from weekly_report_v2 import load_env
from datetime import datetime, timedelta

env = load_env(Path(r'{BASE}') / '.env')
customers = pull_customers_active(env['HUBSPOT_TOKEN'])
now = datetime.now()
start = now - timedelta(days={days})
from_ms = int(start.timestamp() * 1000)
to_ms   = int(now.timestamp() * 1000)
cs = summarize_customers(customers, from_ms, to_ms)

print(f"BPA Doctors (HubSpot) -lifecycle=customer OR status=active")
print(f"Total active: {{cs['total_active']}}")
print(f"New in last {days}d: {{cs['new_in_window']}}")
print(f"Paid social attributed: {{cs['paid_social_attributed']}} ({{cs['paid_social_pct']:.0f}}%)")
print(f"Typeform asset known: {{cs['typeform_attributed']}} ({{cs['typeform_attribution_rate']:.0f}}%)")
print("\\nBy original source:")
for src, n in sorted(cs['by_source'].items(), key=lambda x: -x[1]):
    print(f"  {{src}}: {{n}}")
if cs.get('by_typeform_asset'):
    print("\\nTop entry assets (Typeform Asset Download property):")
    for asset_name, n in list(cs['by_typeform_asset'].items())[:15]:
        print(f"  {{asset_name}}: {{n}}")
if cs.get('by_typeform_segment'):
    print("\\nBy vertical (from Typeform asset):")
    for seg, n in sorted(cs['by_typeform_segment'].items(), key=lambda x: -x[1]):
        print(f"  {{seg}}: {{n}}")
if cs.get('by_fb_campaign'):
    print("\\nTop FB campaigns (paid social customers):")
    for camp, n in list(cs['by_fb_campaign'].items())[:10]:
        print(f"  {{camp}}: {{n}}")
print("\\nLifecycle stage breakdown:")
for lc, n in sorted(cs['lifecycle_counts'].items(), key=lambda x: -x[1]):
    print(f"  {{lc}}: {{n}}")
print("\\nStatus property breakdown:")
for sv, n in sorted(cs['status_values'].items(), key=lambda x: -x[1]):
    print(f"  {{sv}}: {{n}}")
"""
    try:
        r = subprocess.run(
            [sys.executable, "-c", inline], cwd=str(BASE),
            capture_output=True, text=True, timeout=60,
            env={**__import__("os").environ, "PYTHONWARNINGS": "ignore"},
        )
        if r.returncode != 0:
            return f"Customer pull failed:\n{r.stderr[:1500]}"
        return r.stdout.strip() or "(empty)"
    except subprocess.TimeoutExpired:
        return "Customer pull timed out after 60s."


@beta_tool
def search_chat_history(keyword: str, days_back: int = 14) -> str:
    """Search the BPA CMO Agent Google Chat space for past messages by keyword.

    Returns messages from the chat history whose text contains the keyword
    (case-insensitive). Use when Dr. Gumm references "what Kurt said last
    week", "the conversation we had about X", "earlier today", etc., and
    you need older context than the most recent 20 messages already in
    your prompt.

    Fast tool (~3-10 seconds).

    Args:
        keyword: Case-insensitive substring to search for.
        days_back: How many days of chat history to search. Default 14.
    """
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GReq
    from googleapiclient.discovery import build

    token_path = BASE / "gchat_token.json"
    scopes = [
        "https://www.googleapis.com/auth/chat.messages.readonly",
        "https://www.googleapis.com/auth/chat.spaces.readonly",
    ]
    creds = Credentials.from_authorized_user_file(str(token_path), scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(GReq())
        token_path.write_text(creds.to_json())
    svc = build("chat", "v1", credentials=creds)

    # Find the CMO space
    page = None
    space_name = None
    while True:
        resp = svc.spaces().list(pageSize=100, pageToken=page).execute()
        for s in resp.get("spaces", []):
            if (s.get("displayName") or "").lower() == "bpa cmo agent":
                space_name = s["name"]
                break
        if space_name:
            break
        page = resp.get("nextPageToken")
        if not page:
            break
    if not space_name:
        return "Could not find the BPA CMO Agent space."

    since = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat(timespec="seconds").replace("+00:00", "Z")
    flt = f'createTime > "{since}"'
    messages, page = [], None
    while True:
        resp = svc.spaces().messages().list(
            parent=space_name, pageSize=100, pageToken=page,
            filter=flt, orderBy="createTime ASC",
        ).execute()
        messages.extend(resp.get("messages", []))
        page = resp.get("nextPageToken")
        if not page:
            break

    # Filter by keyword
    kw = keyword.lower()
    SENDER_NAMES = {
        "103942791329982000538": "Dr. Gumm",
        "117991766839002131558": "Kurt",
        "114022495153014004089": "CMO Agent",
    }
    hits = []
    for m in messages:
        text = (m.get("text") or "").strip()
        if not text or kw not in text.lower():
            continue
        sid = (m.get("sender") or {}).get("name", "").split("/")[-1]
        who = SENDER_NAMES.get(sid, f"unknown({sid[-5:]})")
        hits.append((m.get("createTime", ""), who, text))

    if not hits:
        return f"No chat history matches for '{keyword}' in the last {days_back} days."

    out = [f"Found {len(hits)} matches for '{keyword}' in last {days_back} days:\n"]
    for ts, who, text in hits[-25:]:  # last 25 hits
        preview = text if len(text) <= 500 else text[:500] + "…"
        out.append(f"[{ts}] {who}")
        out.append(preview)
        out.append("")
    return "\n".join(out)


# --- tool collection ---------------------------------------------------------

ALL_TOOLS = [
    run_weekly_ad_report,
    pull_ad_level_data,
    run_creative_diagnostic,
    pull_hubspot_funnel,
    pull_hyros_attribution,
    pull_hyros_lead_sources,
    pull_hubspot_customers,
    get_campaign_performance,
    search_chat_history,
]
