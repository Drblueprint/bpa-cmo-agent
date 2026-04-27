"""
BPA CMO Agent — Weekly Report v3.
FB Ads + Hyros + HubSpot. Full funnel, revenue, and attribution reconciliation.
Default: terminal + save. Pass --post to publish to CMO Agent Google Chat.
"""

import argparse
import json
import sys
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# Reuse v2 code for FB + Hyros by import
sys.path.insert(0, str(Path(__file__).parent))
from weekly_report_v2 import (
    load_env, http_get, http_post_json,
    fb_insights, fb_leads_of,
    hyros_attributed_calls, hyros_leads,
    build_campaign_rows, segment_rollup, talent_rollup,
    segment_of, talent_of,
    hyros_lead_source_rollup,
)
from hubspot_puller import pull_all as pull_hubspot, lookup_contacts_by_email
from hubspot_puller import typeform_asset_of, TYPEFORM_ASSET_PROPERTY
from speed_to_lead import (
    pull_typeform_contacts, pull_owner_names, get_lead_owner,
    first_outbound_touch, iso_to_dt, fmt_delta, fmt_ct, SDR_IDS,
)


def reconcile_three_sources(fb_leads: float, hyros_leads: int, hs_contacts: int,
                             hs_facebook_leads: int) -> dict:
    """Compare FB-reported leads vs Hyros vs HubSpot new contacts."""
    return {
        "fb_leads": fb_leads,
        "hyros_leads": hyros_leads,
        "hs_new_contacts": hs_contacts,
        "hs_facebook_tagged": hs_facebook_leads,
        "facebook_attribution_rate": (hs_facebook_leads / fb_leads * 100) if fb_leads else 0,
    }


def identify_constraint(fb_rows: list, hs_summary: dict, rev: dict, reconciliation: dict,
                        customer_summary: dict = None) -> dict:
    """Highest-leverage constraint across the full funnel."""
    constraints = []

    # 1. Wasted spend (FB)
    zero_lead_spend = sum(r["spend"] for r in fb_rows if r["leads_fb"] == 0 and r["spend"] > 100)
    zero_lead_names = [r["name"] for r in fb_rows if r["leads_fb"] == 0 and r["spend"] > 100]
    if zero_lead_spend > 500:
        constraints.append({
            "layer": "Creative/Targeting",
            "severity": "HIGH",
            "headline": f"${zero_lead_spend:,.0f} on campaigns producing ZERO FB leads",
            "detail": f"Top offenders: {', '.join(n[:40] for n in zero_lead_names[:3])}",
            "action": "Pause or creative-refresh these campaigns today.",
        })

    # UTM passthrough rate intentionally not checked - attribution model uses
    # Hyros (FB ad -> lead) + HubSpot typeform_asset_download (lead -> form),
    # so utm_source=facebook in HubSpot is not a required signal.

    # 3. MQL → SQL drop-off
    lc = hs_summary.get("by_lifecycle", {})
    leads_count = lc.get("lead", 0)
    mql = lc.get("marketingqualifiedlead", 0)
    sql = lc.get("salesqualifiedlead", 0)
    opp = lc.get("opportunity", 0)
    cust = lc.get("customer", 0)
    if leads_count > 0 and mql / max(leads_count, 1) < 0.15:
        constraints.append({
            "layer": "Lead Quality / SDR",
            "severity": "MEDIUM",
            "headline": f"Only {mql/leads_count*100:.0f}% of new Leads became MQLs ({mql}/{leads_count})",
            "detail": "SDR filter or lead quality breaking down between form fill and qualified.",
            "action": "Pull SDR activity log, spot-check 10 disqualified leads this week.",
        })

    # 4. Revenue vs spend (use typeform-attributed revenue as primary - these are the marketing deals)
    total_spend = sum(r["spend"] for r in fb_rows)
    tf_rev = rev.get("typeform_revenue", 0)
    tf_count = rev.get("typeform_count", 0)
    revenue_for_roas = tf_rev if tf_rev > 0 else rev.get("revenue", 0)
    roas_label = f"marketing ROAS ({tf_count} typeform deals)" if tf_rev > 0 else "blended ROAS (no typeform attribution)"
    if total_spend > 1000 and revenue_for_roas > 0:
        roas = revenue_for_roas / total_spend
        if roas < 1.5:
            constraints.append({
                "layer": "Unit Economics",
                "severity": "HIGH",
                "headline": f"{roas_label} = {roas:.2f}x (${revenue_for_roas:,.0f} on ${total_spend:,.0f} spend)",
                "detail": "Revenue pacing behind spend. Check AOV + close rate vs targets.",
                "action": "Review the closed won deals against SME call tape. Are we selling Plan A or discounting?",
            })

    # 5. Customer source attribution dark spot
    if customer_summary and customer_summary.get("total_active", 0) > 5:
        cs = customer_summary
        unattributed = cs["by_source"].get("UNKNOWN", 0) + cs["by_source"].get("DIRECT", 0)
        unattributed_pct = (unattributed / cs["total_active"] * 100) if cs["total_active"] else 0
        if unattributed_pct > 50:
            constraints.append({
                "layer": "Customer Attribution",
                "severity": "MEDIUM",
                "headline": (f"{unattributed_pct:.0f}% of {cs['total_active']} active BPA doctors "
                             f"show UNKNOWN/DIRECT source in HubSpot"),
                "detail": "Can't credit marketing for customers it closed. UTM passthrough broken at customer stage.",
                "action": "Audit hidden-field UTM on intake forms + HubSpot contact source override settings.",
            })

    constraints.sort(key=lambda c: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}[c["severity"]])
    return {
        "top_constraint": constraints[0] if constraints else None,
        "all_constraints": constraints,
    }


def render_text(fb_report: dict, hs_data: dict, reconciliation: dict,
                constraints: dict, window_days: int,
                hyros_lead_sources: dict = None,
                hyros_hs_xref: dict = None,
                stl_records: list = None) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=window_days)).strftime("%Y-%m-%d")
    L = []
    L.append(f"*BPA CMO Agent - Weekly Report v3*")
    L.append(f"_Window: {start} to {today} ({window_days}d)_")
    L.append(f"_Sources: Facebook Ads + Hyros + HubSpot (FULL FUNNEL)_")
    L.append("")

    # TOP CONSTRAINT
    L.append("*🎯 Top Constraint*")
    tc = constraints["top_constraint"]
    if tc:
        L.append(f"*[{tc['severity']}] {tc['layer']}*")
        L.append(f"→ {tc['headline']}")
        L.append(f"   {tc['detail']}")
        L.append(f"   *Action:* {tc['action']}")
    else:
        L.append("✓ No single dominant constraint. Funnel is balanced. Optimize at margin.")
    L.append("")

    # TOP-LINE NUMBERS (FB + Hyros combined)
    rev = hs_data['revenue_summary']
    tf_rev = rev.get('typeform_revenue', 0)
    tf_count = rev.get('typeform_count', 0)
    total_spend = fb_report['total_spend']
    tf_attr = hs_data['contact_summary']['typeform_attributed']

    L.append("*📊 Campaign Performance (FB + Hyros)*")
    L.append(f"• Spend: ${total_spend:,.0f} | Impressions: {fb_report['total_impressions']:,} | Clicks: {fb_report['total_clicks']:,} (CTR {fb_report['blended_ctr']:.2f}%)")
    L.append(f"• FB Leads: {fb_report['fb_total_leads']:.0f} (CPL ${fb_report['blended_cpl_fb']:,.2f}) → Hyros confirmed: {fb_report['hyros_leads_count']} leads | {fb_report['hyros_calls']} calls ({fb_report['hyros_qualified']} qualified)")
    L.append(f"• HubSpot: {hs_data['contact_summary']['count']} new contacts | {tf_attr} typeform-attributed | Closed Won: {rev['count']} deal(s)")
    if tf_count > 0:
        L.append(f"• *Marketing ROAS: {(tf_rev / total_spend):.2f}x* | Revenue: ${tf_rev:,.0f} (AOV ${rev.get('typeform_aov', 0):,.0f}) across {tf_count} typeform-attributed deal(s)")
    elif total_spend > 0 and rev['revenue'] > 0:
        L.append(f"• ROAS: {(rev['revenue'] / total_spend):.2f}x (${rev['revenue']:,.0f} revenue / no typeform deal attribution yet)")
    L.append("")

    # HUBSPOT FUNNEL
    L.append("*🔻 HubSpot Lifecycle Funnel (new contacts this window)*")
    lc = hs_data['contact_summary']['by_lifecycle']
    order = [
        ("subscriber", "Subscriber"),
        ("lead", "Lead"),
        ("marketingqualifiedlead", "MQL"),
        ("salesqualifiedlead", "SQL"),
        ("opportunity", "Opportunity"),
        ("customer", "Customer"),
    ]
    for key, label in order:
        if key in lc and lc[key] > 0:
            L.append(f"• {label}: {lc[key]}")
    L.append("")

    # SDR / SALES FUNNEL
    f = hs_data['funnel_summary']['funnel']
    L.append("*📞 Deal Funnel (marketing pipelines, this window)*")
    L.append(f"• New marketing leads → deals: {hs_data['funnel_summary']['deal_count']}")
    for key, label in [
        ("new_lead", "New Marketing Lead"),
        ("call15_booked", "15-min Booked"),
        ("call15_qualified", "15-min Completed Qualified"),
        ("strategy_scheduled", "Strategy Call Scheduled"),
        ("strategy_qualified", "Strategy Call Completed Qualified"),
        ("closing_scheduled", "Closing Call Scheduled"),
        ("closing_complete", "Closing Call Complete"),
        ("closed_won", "Closed Won"),
    ]:
        if key in f and f[key] > 0:
            L.append(f"  - {label}: {f[key]}")
    L.append("")

    # HYROS LEAD SOURCE ATTRIBUTION
    hls = hyros_lead_sources or {}
    if hls.get("total", 0) > 0:
        L.append("*🎯 Hyros Lead Attribution (originating FB ad)*")
        L.append(f"• Total Hyros leads this window: {hls['total']}")
        L.append(f"• Ad-attributed: {hls['attributed']} ({hls['attribution_rate']:.0f}%)"
                 f" / Unattributed: {hls['unattributed']}")
        L.append(f"• Confirmed reached HubSpot (!hubspot tag): {hls.get('hubspot_confirmed', 0)}"
                 f" / Booked a call: {hls.get('calls_booked', 0)}")
        if hls.get("by_segment"):
            seg_parts = ", ".join(
                f"{s}: {n}" for s, n in sorted(hls["by_segment"].items(), key=lambda x: -x[1])
            )
            L.append(f"• By vertical: {seg_parts}")
        if hls.get("by_ad"):
            L.append("• Top originating ads (Hyros first-touch):")
            for ad_name, n in list(hls["by_ad"].items())[:8]:
                L.append(f"  - {ad_name}: {n} lead(s)")
        if hls.get("by_campaign"):
            L.append("• Top originating campaigns (Hyros):")
            for camp, n in list(hls["by_campaign"].items())[:5]:
                L.append(f"  - {camp}: {n} lead(s)")
        if hls.get("by_creative"):
            L.append("• Top creatives (Hyros):")
            for creative, n in list(hls["by_creative"].items())[:5]:
                L.append(f"  - {creative}: {n} lead(s)")
        L.append("")

    # 15-MIN CALL BOOKINGS - individual lead profiles
    xref = hyros_hs_xref or {}
    call_booked_leads = sorted(
        [v for v in xref.values() if v["call_booked"] and (v.get("ad_name") or v.get("campaign"))],
        key=lambda v: v.get("campaign", "")
    )
    if call_booked_leads:
        L.append(f"*📞 15-Min Call Bookings This Window ({len(call_booked_leads)} leads)*")
        for lead in call_booked_leads:
            name = lead["name"]
            lc = lead["lifecycle"]
            tf = lead["typeform_asset"] or "typeform not set"
            seg = lead["typeform_segment"] or "-"
            ad = lead["ad_name"] or "?"
            creative = lead["creative"] or "?"
            camp = lead["campaign"] or "?"
            hs_flag = "" if lead["in_hubspot"] else " (not in HubSpot)"
            L.append(f"  *{name}* ({lead['email']}){hs_flag}")
            L.append(f"    Lifecycle: {lc} | Asset: {tf} [{seg}]")
            L.append(f"    Ad: {ad} | Creative: {creative}")
            L.append(f"    Campaign: {camp}")
        L.append("")

    # HYROS -> HUBSPOT CHAIN SUMMARY
    if xref:
        in_hs = [v for v in xref.values() if v["in_hubspot"]]
        tf_matched = [v for v in in_hs if v["typeform_asset"]]
        L.append("*🔗 Hyros - HubSpot Attribution Chain*")
        L.append(f"• Confirmed reached HubSpot: {len(in_hs)} | Booked 15-min call: {len(call_booked_leads)}")
        L.append(f"• Typeform asset known on confirmed leads: {len(tf_matched)}")
        if tf_matched:
            by_seg: dict = {}
            by_asset: dict = {}
            for v in tf_matched:
                seg = v["typeform_segment"] or "Other"
                by_seg[seg] = by_seg.get(seg, 0) + 1
                asset = v["typeform_asset"]
                by_asset[asset] = by_asset.get(asset, 0) + 1
            seg_str = ", ".join(f"{s}: {n}" for s, n in sorted(by_seg.items(), key=lambda x: -x[1]))
            L.append(f"• By vertical: {seg_str}")
            L.append("• By typeform asset:")
            for asset, n in sorted(by_asset.items(), key=lambda x: -x[1])[:6]:
                L.append(f"  - {asset}: {n}")
        L.append("")

    # LEAD PIPELINE - combined typeform + speed-to-lead + FB ad spend context
    stl = stl_records or []
    if stl:
        stl_touched  = [r for r in stl if r["delta_hours"] is not None]
        stl_untouched = [r for r in stl if r["delta_hours"] is None]
        total_spend  = fb_report["total_spend"]
        fb_leads_n   = fb_report["fb_total_leads"]
        cpl          = fb_report["blended_cpl_fb"]

        L.append("*📋 Lead Pipeline - This Window's Typeform Submissions*")
        L.append(f"• {len(stl)} submissions | {len(stl_touched)} touched | {len(stl_untouched)} not yet touched")
        L.append(f"• FB Spend: ${total_spend:,.0f} | FB Leads: {fb_leads_n:.0f} | Blended CPL: ${cpl:,.2f}")

        # Speed to lead summary
        if stl_touched:
            avg_h    = sum(r["delta_hours"] for r in stl_touched) / len(stl_touched)
            sorted_h = sorted(r["delta_hours"] for r in stl_touched)
            mid      = len(sorted_h) // 2
            median_h = (sorted_h[mid] + sorted_h[~mid]) / 2
            u1h  = sum(1 for r in stl_touched if r["delta_hours"] <= 1)
            u4h  = sum(1 for r in stl_touched if r["delta_hours"] <= 4)
            u24h = sum(1 for r in stl_touched if r["delta_hours"] <= 24)
            L.append(f"• Speed to lead - median: {fmt_delta(median_h)} | avg: {fmt_delta(avg_h)} | "
                     f"<1h: {u1h} ({u1h*100//len(stl_touched)}%) | <4h: {u4h} | <24h: {u24h} | "
                     f"untouched: {len(stl_untouched)}")

        # By asset downloaded
        by_asset_t: dict = defaultdict(list)
        by_asset_u: dict = defaultdict(int)
        for r in stl:
            asset = r["tf_name"]
            if r["delta_hours"] is not None:
                by_asset_t[asset].append(r["delta_hours"])
            else:
                by_asset_u[asset] += 1
        all_assets = set(list(by_asset_t.keys()) + list(by_asset_u.keys()))
        if all_assets:
            L.append("• By asset downloaded:")
            for asset in sorted(all_assets):
                at = by_asset_t.get(asset, [])
                au = by_asset_u.get(asset, 0)
                avg_str = f"avg {fmt_delta(sum(at)/len(at))}" if at else "no touch"
                L.append(f"  - {asset}: {len(at)} touched ({avg_str}) | {au} untouched")

        # By rep
        by_rep_t: dict = defaultdict(list)
        by_rep_u: dict = defaultdict(int)
        for r in stl:
            if r["delta_hours"] is not None:
                by_rep_t[r["owner"]].append(r["delta_hours"])
            else:
                by_rep_u[r["owner"]] += 1
        all_reps = set(list(by_rep_t.keys()) + list(by_rep_u.keys()))
        if all_reps:
            L.append("• By SDR:")
            for rep in sorted(all_reps):
                deltas = by_rep_t.get(rep, [])
                un = by_rep_u.get(rep, 0)
                avg_str = f"avg {fmt_delta(sum(deltas)/len(deltas))}" if deltas else "no touches"
                L.append(f"  - {rep}: {len(deltas)} touched ({avg_str}) | {un} untouched")

        # Per-lead table sorted: touched fastest first, then untouched oldest first
        sorted_stl = sorted(stl,
            key=lambda r: (r["delta_hours"] is None, r["delta_hours"] or 0))
        L.append("• Per lead (sub time CT → first touch):")
        for r in sorted_stl:
            sub_str   = fmt_ct(r["sub_dt"])
            owner_str = r["owner"]
            asset_str = r["tf_name"]
            if r["delta_hours"] is not None:
                touch_str = fmt_ct(r["touch_dt"])
                speed_str = fmt_delta(r["delta_hours"])
                L.append(f"  - {r['name']} | {owner_str} | {asset_str} | "
                         f"sub:{sub_str} → touch:{touch_str} ({speed_str})")
            else:
                L.append(f"  - {r['name']} | {owner_str} | {asset_str} | "
                         f"sub:{sub_str} → NO TOUCH YET")
        L.append("")

    # SEGMENTS (FB + Hyros combined, TheraRay gets HubSpot segment overlay)
    theraray_seg = fb_report.get("theraray_segment", {})
    L.append("*📈 By Segment (FB Spend + Hyros)*")
    seg_sorted = sorted(fb_report["segments"].items(), key=lambda x: x[1]["spend"], reverse=True)
    for s, v in seg_sorted[:6]:
        cpl_str = f"${v['cpl_fb']:,.0f}" if v["cpl_fb"] else "n/a"
        cpc_str = f" | ${v['cost_per_call']:,.0f}/call" if v["cost_per_call"] else ""
        line = (f"• {s}: ${v['spend']:,.0f} spend | {v['leads_fb']:.0f} FB leads (CPL {cpl_str}) | "
                f"{v['hyros_calls']} Hyros calls{cpc_str}")
        if s == "TheraRay" and theraray_seg:
            tr_total = theraray_seg.get("total_in_window", 0)
            tr_fb    = theraray_seg.get("facebook_in_window", 0)
            line += f" | HubSpot segment: {tr_total} added this window ({tr_fb} from Facebook)"
        L.append(line)
    L.append("")

    # TYPEFORM-ATTRIBUTED REVENUE (marketing deals only)
    if rev.get('by_typeform_asset'):
        L.append("*💰 Marketing Revenue - Typeform-Attributed Deals*")
        L.append(f"• {tf_count} of {rev['count']} closed won deals have a typeform submission on the contact")
        if rev.get('by_typeform_segment'):
            L.append("• By vertical:")
            for seg, v in sorted(rev['by_typeform_segment'].items(), key=lambda x: -x[1]['revenue']):
                L.append(f"  - {seg}: {v['count']} deal(s), ${v['revenue']:,.0f}")
        L.append("• By asset:")
        for asset, v in list(rev['by_typeform_asset'].items())[:8]:
            L.append(f"  - {asset}: {v['count']} deal(s), ${v['revenue']:,.0f}")
        L.append("")
    elif rev['count'] > 0:
        L.append("*💰 Closed Won Deals*")
        L.append(f"• {rev['count']} deals, ${rev['revenue']:,.0f} total - no typeform attribution found on associated contacts")
        L.append("")

    # REVENUE BY HUBSPOT SOURCE (all closed won)
    if rev['count'] > 0 and rev.get('by_source'):
        L.append("*Revenue by HubSpot Source (all closed won)*")
        for src, v in sorted(rev['by_source'].items(), key=lambda x: -x[1]['revenue']):
            L.append(f"• {src}: {v['count']} deal(s), ${v['revenue']:,.0f}")
        L.append("")

    # CURRENT BPA DOCTORS
    cs = hs_data.get("customer_summary", {})
    if cs.get("total_active", 0) > 0:
        L.append("*👨‍⚕️ Current BPA Doctors (HubSpot)*")
        L.append(f"• Total active: {cs['total_active']} (SALES-V2 closed won - all time)")
        if cs.get("new_in_window", 0) > 0:
            L.append(f"• New contacts in this window: {cs['new_in_window']}")
        L.append(f"• Facebook-attributed (utm_source=facebook): {cs.get('facebook_attributed', 0)} ({cs.get('facebook_pct', 0):.0f}%)")
        if cs.get("by_source"):
            L.append("• By original source:")
            for src, n in sorted(cs["by_source"].items(), key=lambda x: -x[1])[:6]:
                L.append(f"  - {src}: {n}")
        if hls and hls.get("by_campaign"):
            L.append("• Top acquiring campaigns this window (Hyros):")
            for camp, n in list(hls["by_campaign"].items())[:5]:
                L.append(f"  - {camp}: {n} lead(s)")
        cust_tf = cs.get("by_typeform_asset", {})
        if cust_tf:
            cust_tf_total = cs.get("typeform_attributed", 0)
            cust_tf_rate = cs.get("typeform_attribution_rate", 0)
            L.append(f"• Typeform-attributed: {cust_tf_total} ({cust_tf_rate:.0f}%) - entry asset known")
            L.append("• Top entry assets (customers):")
            for asset_name, n in list(cust_tf.items())[:6]:
                L.append(f"  - {asset_name}: {n}")
        elif cs.get("total_active", 0) > 0:
            L.append("• Typeform asset: not set on these contacts (run a HubSpot re-import or check property name)")
        L.append("")

    # TYPEFORM LEAD SOURCES (new contacts this window)
    cs_contact = hs_data.get("contact_summary", {})
    tf_assets = cs_contact.get("by_typeform_asset", {})
    tf_total = cs_contact.get("typeform_attributed", 0)
    tf_rate = cs_contact.get("typeform_attribution_rate", 0)
    if tf_total > 0:
        L.append("*📋 Typeform Asset Sources (new leads this window)*")
        L.append(f"• Typeform-attributed leads: {tf_total} of {cs_contact.get('count', 0)} ({tf_rate:.0f}%)")
        tf_segs = cs_contact.get("by_typeform_segment", {})
        if tf_segs:
            seg_parts = ", ".join(f"{s}: {n}" for s, n in sorted(tf_segs.items(), key=lambda x: -x[1]))
            L.append(f"• By vertical: {seg_parts}")
        L.append("• By asset (top 8):")
        for asset_name, n in list(tf_assets.items())[:8]:
            L.append(f"  - {asset_name}: {n}")
        L.append("")

    # ATTRIBUTION CONFIDENCE - 3-source reconciliation
    L.append("*🔍 Attribution Reconciliation (3 sources)*")
    L.append(f"• FB reports: {reconciliation['fb_leads']:.0f} leads")
    L.append(f"• Hyros sees: {reconciliation['hyros_leads']} leads ({hls.get('hubspot_confirmed', 0)} confirmed reached HubSpot via !hubspot tag)")
    L.append(f"• HubSpot shows: {reconciliation['hs_new_contacts']} new contacts ({reconciliation['hs_facebook_tagged']} with utm_source=facebook)")
    xref_in_hs = sum(1 for v in xref.values() if v["in_hubspot"]) if xref else 0
    xref_tf = sum(1 for v in xref.values() if v["typeform_asset"]) if xref else 0
    if xref:
        L.append(f"• Hyros-to-HubSpot email match: {xref_in_hs} of {len(xref)} confirmed leads found, {xref_tf} with typeform asset")
    L.append("✓ Attribution model: Hyros (FB ad -> lead) + HubSpot typeform_asset_download (lead -> form). UTM passthrough rate not required.")
    L.append("")

    # ADDITIONAL CONSTRAINTS
    if len(constraints["all_constraints"]) > 1:
        L.append("*Other constraints surfaced*")
        for c in constraints["all_constraints"][1:]:
            L.append(f"• [{c['severity']}] {c['layer']}: {c['headline']}")
        L.append("")

    # BLINDSPOTS
    L.append("*Known Blindspots*")
    L.append("• Marketing ROAS uses typeform-attributed deals only. Deals without a typeform contact are excluded (non-marketing closes).")
    L.append("• Hyros sale events not wired - Hyros cannot confirm revenue yet, only lead and call attribution.")
    L.append("• Ad-creative level: run ad_level_report.py for creative-level diagnosis.")
    return "\n".join(L)


THERARAY_LIST_ID = "6280"

def pull_theraray_segment(token: str, days: int) -> dict:
    """Pull TheraRay User Request Form contacts added to HubSpot list in last N days.
    Uses v3 lists memberships API (list 6280 is a v3 object list, not v1).
    Returns total added in window + Facebook-attributed count."""
    from hubspot_puller import hs_request as _hs
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)

    # Step 1: page through all memberships, collect IDs added within window
    contact_ids_in_window = []
    after = None
    while True:
        url = f"/crm/v3/lists/{THERARAY_LIST_ID}/memberships?limit=100"
        if after:
            url += f"&after={after}"
        s, r = _hs("GET", url, token)
        if s >= 400:
            break
        for m in r.get("results", []):
            ts_str = m.get("membershipTimestamp", "")
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except Exception:
                continue
            if ts >= cutoff_dt:
                contact_ids_in_window.append(str(m["recordId"]))
        paging = r.get("paging", {})
        after = (paging.get("next") or {}).get("after")
        if not after:
            break

    if not contact_ids_in_window:
        return {"total_in_window": 0, "facebook_in_window": 0}

    # Step 2: batch-read contact properties to check utm_source
    fb_count = 0
    for i in range(0, len(contact_ids_in_window), 100):
        batch_ids = contact_ids_in_window[i:i+100]
        payload = {
            "inputs": [{"id": cid} for cid in batch_ids],
            "properties": ["utm_source", "hs_analytics_source"],
        }
        s2, r2 = _hs("POST", "/crm/v3/objects/contacts/batch/read", token, payload)
        if s2 >= 400:
            continue
        for contact in r2.get("results", []):
            props = contact.get("properties", {})
            utm_val = (props.get("utm_source") or "").lower()
            src_val = (props.get("hs_analytics_source") or "").lower()
            if "meta" in utm_val or "facebook" in utm_val or "paid_social" in src_val:
                fb_count += 1

    return {"total_in_window": len(contact_ids_in_window), "facebook_in_window": fb_count}


def post_to_gchat(webhook: str, text: str):
    return http_post_json(webhook, {"text": text})


def main():
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--post", action="store_true", help="Post to CMO Agent Google Chat")
    p.add_argument("--save", action="store_true", default=True)
    args = p.parse_args()

    env = load_env(Path(__file__).parent / ".env")
    today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

    preset_map = {7: "last_7d", 14: "last_14d", 28: "last_28d", 30: "last_30d", 90: "last_90d"}
    preset = preset_map.get(args.days, "last_7d")

    # FB + Hyros (v2 logic)
    print(f"Pulling FB Ads ({args.days}d)...")
    fb = fb_insights(env["FB_ADS_TOKEN"], env["FB_AD_ACCOUNT_ID"], preset)
    print(f"  {len(fb)} campaigns")

    print(f"Pulling Hyros ({args.days}d)...")
    calls = hyros_attributed_calls(env["HYROS_API_KEY"], start, today)
    leads = hyros_leads(env["HYROS_API_KEY"], start, today)
    print(f"  {len(calls)} calls, {len(leads)} leads")
    lead_sources = hyros_lead_source_rollup(leads)
    print(f"  {lead_sources['attributed']} of {lead_sources['total']} leads have ad attribution")


    rows = build_campaign_rows(fb, calls)
    fb_total_leads = sum(r["leads_fb"] for r in rows)

    # FB report (v2 shape)
    total_spend = sum(r["spend"] for r in rows)
    total_impressions = sum(r["impressions"] for r in rows)
    total_clicks = sum(r["clicks"] for r in rows)
    total_calls = sum(r["hyros_calls"] for r in rows)
    total_qualified = sum(r["hyros_qualified"] for r in rows)
    fb_report = {
        "total_spend": total_spend,
        "total_impressions": total_impressions,
        "total_clicks": total_clicks,
        "fb_total_leads": fb_total_leads,
        "hyros_leads_count": len(leads),
        "hyros_calls": total_calls,
        "hyros_qualified": total_qualified,
        "blended_ctr": (total_clicks/total_impressions*100) if total_impressions else 0,
        "blended_cpl_fb": (total_spend/fb_total_leads) if fb_total_leads else 0,
        "segments": segment_rollup(rows),
        "talents": talent_rollup(rows),
        "rows": rows,
    }

    # HubSpot
    print(f"Pulling HubSpot ({args.days}d)...")
    hs = pull_hubspot(env["HUBSPOT_TOKEN"], args.days)
    print(f"  {hs['contact_summary']['count']} contacts, "
          f"{hs['funnel_summary']['deal_count']} marketing deals, "
          f"{hs['revenue_summary']['count']} closed won "
          f"(${hs['revenue_summary']['revenue']:,.0f})")

    # TheraRay HubSpot segment
    print("Pulling TheraRay segment...")
    theraray_seg = pull_theraray_segment(env["HUBSPOT_TOKEN"], args.days)
    fb_report["theraray_segment"] = theraray_seg
    print(f"  {theraray_seg['total_in_window']} added this window, {theraray_seg['facebook_in_window']} from Facebook")

    # Speed-to-lead: typeform submissions this window with first touch timing
    print(f"Pulling speed-to-lead data ({args.days}d)...")
    stl_contacts = pull_typeform_contacts(env["HUBSPOT_TOKEN"], args.days)
    owner_names = pull_owner_names(env["HUBSPOT_TOKEN"])
    stl_records = []
    for c in stl_contacts:
        props = c.get("properties", {})
        contact_id = c.get("id", "")
        first = (props.get("firstname") or "").strip()
        last = (props.get("lastname") or "").strip()
        name = f"{first} {last}".strip() or (props.get("email") or contact_id)
        sub_dt = iso_to_dt(props.get("typeform_submission_date")) or iso_to_dt(props.get("createdate"))
        tf_val = props.get(TYPEFORM_ASSET_PROPERTY) or ""
        tf = typeform_asset_of(tf_val)
        tf_name = tf["name"] if tf else (tf_val or "unknown")
        tf_seg  = tf["segment"] if tf else "Other"
        candidate_ids = [
            get_lead_owner(env["HUBSPOT_TOKEN"], contact_id),
            props.get("sdr_owner"),
            props.get("hubspot_owner_id"),
        ]
        owner_id = "unassigned"
        for cid in candidate_ids:
            if cid and str(cid) in SDR_IDS:
                owner_id = str(cid)
                break
        if owner_id == "unassigned":
            owner_id = props.get("hubspot_owner_id") or "unassigned"
        owner_name = SDR_IDS.get(owner_id) or owner_names.get(owner_id, owner_id)
        touch = first_outbound_touch(env["HUBSPOT_TOKEN"], contact_id, sub_dt)
        delta_hours = (touch["ts"] - sub_dt).total_seconds() / 3600 if (touch and sub_dt) else None
        stl_records.append({
            "name": name,
            "tf_name": tf_name,
            "tf_seg": tf_seg,
            "owner": owner_name,
            "sub_dt": sub_dt,
            "touch_dt": touch["ts"] if touch else None,
            "delta_hours": delta_hours,
        })
    touched = [r for r in stl_records if r["delta_hours"] is not None]
    untouched = [r for r in stl_records if r["delta_hours"] is None]
    print(f"  {len(stl_records)} typeform submissions, {len(touched)} touched, {len(untouched)} not yet touched")

    # Cross-reference all Hyros leads that reached HubSpot or booked a call.
    # Union of !hubspot-tagged and call-booked leads, looked up by email.
    hs_tagged = lead_sources.get("hubspot_leads_by_email", {})
    call_booked_by_email = {
        src["email"]: src
        for src in lead_sources.get("call_booked_leads", [])
        if src.get("email")
    }
    all_xref_emails = list(set(list(hs_tagged.keys()) + list(call_booked_by_email.keys())))
    hyros_hs_xref = {}
    if all_xref_emails:
        print(f"Cross-referencing {len(all_xref_emails)} Hyros leads (HubSpot confirmed + call booked)...")
        hs_contact_props = lookup_contacts_by_email(env["HUBSPOT_TOKEN"], all_xref_emails)
        for email in all_xref_emails:
            hyros_src = hs_tagged.get(email) or call_booked_by_email.get(email, {})
            hs_props = hs_contact_props.get(email, {})
            tf_val = hs_props.get("typeform_asset_download") or ""
            tf_asset = typeform_asset_of(tf_val)
            first = (hs_props.get("firstname") or "").strip()
            last = (hs_props.get("lastname") or "").strip()
            name = f"{first} {last}".strip() or email
            hyros_hs_xref[email] = {
                "name": name,
                "email": email,
                "ad_name": hyros_src.get("ad_name", ""),
                "campaign": hyros_src.get("campaign", ""),
                "creative": hyros_src.get("creative", ""),
                "call_booked": hyros_src.get("call_booked", False),
                "has_hubspot": hyros_src.get("has_hubspot", False),
                "lifecycle": hs_props.get("lifecyclestage") or "-",
                "typeform_asset": tf_asset["name"] if tf_asset else (tf_val or None),
                "typeform_segment": tf_asset["segment"] if tf_asset else None,
                "in_hubspot": bool(hs_props),
            }
        confirmed = sum(1 for v in hyros_hs_xref.values() if v["in_hubspot"])
        call_count = sum(1 for v in hyros_hs_xref.values() if v["call_booked"])
        typeform_matched = sum(1 for v in hyros_hs_xref.values() if v["typeform_asset"])
        print(f"  {confirmed} found in HubSpot, {call_count} booked a 15-min call, {typeform_matched} with typeform asset")

    # Reconcile
    hs_facebook_count = hs["contact_summary"].get("facebook_leads", 0)
    reconciliation = reconcile_three_sources(
        fb_total_leads,
        len(leads),
        hs["contact_summary"]["count"],
        hs_facebook_count,
    )

    # Constraints
    constraints = identify_constraint(rows, hs["contact_summary"], hs["revenue_summary"],
                                      reconciliation, hs.get("customer_summary"))

    text = render_text(fb_report, hs, reconciliation, constraints, args.days,
                       lead_sources, hyros_hs_xref, stl_records)

    if args.save:
        out = Path(__file__).parent / f"report_v3_{today}.txt"
        out.write_text(text, encoding="utf-8")
        print(f"\nSaved: {out}")

    print("\n" + text + "\n")

    if args.post:
        webhook = env.get("GCHAT_CMO_WEBHOOK")
        if not webhook:
            print("GCHAT_CMO_WEBHOOK missing. Cannot post.")
            return
        status, resp = post_to_gchat(webhook, text)
        print(f"Google Chat post: HTTP {status}")
    else:
        print("(Not posted. Use --post to publish.)")


if __name__ == "__main__":
    main()
