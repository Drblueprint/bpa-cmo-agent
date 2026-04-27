"""
BPA CMO Agent — manual first run.
Pulls last 7 days from FB Ads, synthesizes a constraint-first report,
posts to Google Chat.
Uses only Python stdlib (no external deps).
"""

import json
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta


def load_env(path: Path) -> dict:
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def http_get(url: str, params: dict) -> dict:
    q = urllib.parse.urlencode(params)
    full = f"{url}?{q}"
    with urllib.request.urlopen(full, timeout=30) as r:
        return json.loads(r.read().decode())


def http_post_json(url: str, payload: dict) -> tuple[int, str]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def fetch_fb_campaigns(token: str, account_id: str) -> list[dict]:
    url = f"https://graph.facebook.com/v19.0/act_{account_id}/insights"
    params = {
        "date_preset": "last_7d",
        "level": "campaign",
        "fields": "campaign_name,spend,impressions,clicks,ctr,cpc,reach,actions,cost_per_action_type",
        "access_token": token,
        "limit": 100,
    }
    data = http_get(url, params)
    return data.get("data", [])


def get_action_value(actions: list, action_type: str) -> float:
    if not actions:
        return 0.0
    for a in actions:
        if a.get("action_type") == action_type:
            return float(a.get("value", 0))
    return 0.0


def summarize_campaigns(campaigns: list[dict]) -> dict:
    total_spend = sum(float(c.get("spend", 0)) for c in campaigns)
    total_impressions = sum(int(c.get("impressions", 0)) for c in campaigns)
    total_clicks = sum(int(c.get("clicks", 0)) for c in campaigns)
    total_leads = sum(get_action_value(c.get("actions"), "lead") for c in campaigns)
    # fallback: some accounts track leads differently
    if total_leads == 0:
        total_leads = sum(
            get_action_value(c.get("actions"), "offsite_conversion.fb_pixel_lead")
            for c in campaigns
        )

    blended_ctr = (total_clicks / total_impressions * 100) if total_impressions else 0
    blended_cpc = (total_spend / total_clicks) if total_clicks else 0
    blended_cpl = (total_spend / total_leads) if total_leads else 0

    # rank campaigns
    enriched = []
    for c in campaigns:
        spend = float(c.get("spend", 0))
        leads = get_action_value(c.get("actions"), "lead")
        if leads == 0:
            leads = get_action_value(
                c.get("actions"), "offsite_conversion.fb_pixel_lead"
            )
        cpl = (spend / leads) if leads else None
        enriched.append(
            {
                "name": c.get("campaign_name", "Unknown"),
                "spend": spend,
                "impressions": int(c.get("impressions", 0)),
                "clicks": int(c.get("clicks", 0)),
                "ctr": float(c.get("ctr", 0)),
                "leads": leads,
                "cpl": cpl,
            }
        )

    by_spend = sorted(enriched, key=lambda x: x["spend"], reverse=True)
    by_cpl = sorted(
        [e for e in enriched if e["cpl"] is not None and e["leads"] > 0],
        key=lambda x: x["cpl"],
    )

    return {
        "total_spend": total_spend,
        "total_impressions": total_impressions,
        "total_clicks": total_clicks,
        "total_leads": total_leads,
        "blended_ctr": blended_ctr,
        "blended_cpc": blended_cpc,
        "blended_cpl": blended_cpl,
        "top_by_spend": by_spend[:5],
        "best_cpl": by_cpl[:3],
        "worst_cpl": by_cpl[-3:] if len(by_cpl) >= 3 else [],
        "zero_lead_campaigns": [e for e in enriched if e["leads"] == 0 and e["spend"] > 50],
    }


def build_report(summary: dict) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    lines = []
    lines.append(f"*BPA CMO Agent — Weekly Paid Media Report*")
    lines.append(f"_Period: {start} → {today} (last 7 days)_")
    lines.append(f"_Source: Facebook Ads | v1 manual run_")
    lines.append("")
    lines.append("*Headline*")
    lines.append(_headline(summary))
    lines.append("")
    lines.append("*Top-line numbers*")
    lines.append(f"• Spend: ${summary['total_spend']:,.2f}")
    lines.append(f"• Impressions: {summary['total_impressions']:,}")
    lines.append(f"• Clicks: {summary['total_clicks']:,}")
    lines.append(f"• Leads (FB-reported): {summary['total_leads']:,.0f}")
    lines.append(f"• Blended CTR: {summary['blended_ctr']:.2f}%")
    lines.append(f"• Blended CPC: ${summary['blended_cpc']:,.2f}")
    if summary["total_leads"]:
        lines.append(f"• Blended CPL: ${summary['blended_cpl']:,.2f}")
    else:
        lines.append("• Blended CPL: n/a (no FB-reported leads — attribution may be in Hyros only)")
    lines.append("")

    lines.append("*Top 5 campaigns by spend*")
    for c in summary["top_by_spend"]:
        cpl_str = f"CPL ${c['cpl']:,.2f}" if c["cpl"] else "no leads tracked"
        lines.append(
            f"• {c['name']} — ${c['spend']:,.0f} spent, {c['leads']:.0f} leads, {cpl_str}, CTR {c['ctr']:.2f}%"
        )
    lines.append("")

    if summary["best_cpl"]:
        lines.append("*Best CPL (what's working)*")
        for c in summary["best_cpl"]:
            lines.append(
                f"• {c['name']} — CPL ${c['cpl']:,.2f} ({c['leads']:.0f} leads, ${c['spend']:,.0f} spent)"
            )
        lines.append("")

    if summary["worst_cpl"]:
        lines.append("*Worst CPL (what's not working)*")
        for c in summary["worst_cpl"]:
            lines.append(
                f"• {c['name']} — CPL ${c['cpl']:,.2f} ({c['leads']:.0f} leads, ${c['spend']:,.0f} spent)"
            )
        lines.append("")

    if summary["zero_lead_campaigns"]:
        lines.append("*Zero-lead campaigns burning spend >$50*")
        for c in summary["zero_lead_campaigns"]:
            lines.append(f"• {c['name']} — ${c['spend']:,.0f} spent, 0 leads")
        lines.append("")

    lines.append("*Constraint (this week)*")
    lines.append(_constraint(summary))
    lines.append("")
    lines.append("*Recommended actions*")
    for a in _actions(summary):
        lines.append(f"• {a}")
    lines.append("")
    lines.append("*Blindspots*")
    lines.append("• This report does not yet include Hyros-verified ROAS. FB-reported leads only.")
    lines.append("• No creative/copy analysis in this run — Paid Media only.")
    lines.append("• No HubSpot lead→enrolled attribution.")

    return "\n".join(lines)


def _headline(s: dict) -> str:
    if s["total_leads"] == 0:
        return f"Spent ${s['total_spend']:,.0f} this week with zero FB-reported leads. Either lead tracking is broken or the account isn't running a lead-gen objective."
    return f"Spent ${s['total_spend']:,.0f} this week generating {s['total_leads']:.0f} leads at ${s['blended_cpl']:,.2f} blended CPL."


def _constraint(s: dict) -> str:
    if s["total_leads"] == 0:
        return "ATTRIBUTION. Cannot diagnose campaigns without lead tracking. Fix FB pixel lead events or verify Hyros is the source of truth, then re-run."
    if s["zero_lead_campaigns"]:
        total_wasted = sum(c["spend"] for c in s["zero_lead_campaigns"])
        return f"WASTED SPEND. ${total_wasted:,.0f} burned on campaigns with zero leads this week. Cut or diagnose before Friday."
    if s["blended_ctr"] < 1.0:
        return f"CREATIVE. Blended CTR of {s['blended_ctr']:.2f}% is below 1% — audiences aren't engaging. Test new hooks."
    return "No single constraint flagged by this top-line view. Need creative/copy/funnel depth — future sub-agents."


def _actions(s: dict) -> list[str]:
    actions = []
    if s["total_leads"] == 0:
        actions.append("Verify FB pixel lead events are firing (check Events Manager)")
        actions.append("Confirm campaign objectives are set to Leads or Conversions")
        actions.append("Cross-check with Hyros — is it showing leads Facebook isn't?")
        return actions
    if s["zero_lead_campaigns"]:
        for c in s["zero_lead_campaigns"][:3]:
            actions.append(f"Review '{c['name']}' — cut or iterate this week (${c['spend']:,.0f} at stake)")
    if s["worst_cpl"]:
        top_offender = s["worst_cpl"][-1]
        actions.append(f"Diagnose '{top_offender['name']}' (CPL ${top_offender['cpl']:,.2f}) — creative, audience, or offer?")
    if s["best_cpl"]:
        winner = s["best_cpl"][0]
        actions.append(f"Consider scaling '{winner['name']}' — best CPL at ${winner['cpl']:,.2f}")
    if not actions:
        actions.append("Stable week. Next priority: wire up Hyros attribution for real ROAS.")
    return actions


def post_to_google_chat(webhook: str, text: str) -> tuple[int, str]:
    # Google Chat accepts a simple text payload; supports *bold* and _italic_
    return http_post_json(webhook, {"text": text})


def main():
    env_path = Path.home() / "Desktop" / "bpa-cmo-agent" / ".env"
    env = load_env(env_path)

    required = ["FB_ADS_TOKEN", "FB_AD_ACCOUNT_ID", "GCHAT_CMO_WEBHOOK"]
    missing = [k for k in required if not env.get(k)]
    if missing:
        print(f"MISSING env vars: {missing}")
        return

    print("Pulling Facebook Ads insights (last 7 days)...")
    try:
        campaigns = fetch_fb_campaigns(env["FB_ADS_TOKEN"], env["FB_AD_ACCOUNT_ID"])
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"FB API error {e.code}: {body}")
        return

    print(f"Got {len(campaigns)} campaigns.")
    if not campaigns:
        print("No data returned. Either no spend in last 7 days or token lacks permissions.")
        return

    summary = summarize_campaigns(campaigns)
    print(f"Total spend: ${summary['total_spend']:,.2f}")
    print(f"Total leads: {summary['total_leads']:.0f}")

    report = build_report(summary)

    # Save a local copy
    out = Path.home() / "Desktop" / "bpa-cmo-agent" / "last_report.txt"
    out.write_text(report)
    print(f"\nReport saved to: {out}\n")
    print(report)
    print()

    print("Posting to Google Chat...")
    status, body = post_to_google_chat(env["GCHAT_CMO_WEBHOOK"], report)
    if 200 <= status < 300:
        print(f"Posted successfully (HTTP {status}).")
    else:
        print(f"Post failed (HTTP {status}): {body}")


if __name__ == "__main__":
    main()
