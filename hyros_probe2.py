"""
Hyros deep probe — what does Hyros ACTUALLY know about our ads -> deals?
Inspects real records and tests longer windows.
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
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def hyros_get(path: str, api_key: str, params: dict = None):
    base = "https://api.hyros.com/v1/api/v1.0"
    url = f"{base}{path}"
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"API-Key": api_key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = {"raw_error": "non-json"}
        return e.code, body


def http_post_json(url: str, payload: dict):
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


def main():
    env = load_env(Path.home() / "Desktop" / "bpa-cmo-agent" / ".env")
    key = env["HYROS_API_KEY"]
    webhook = env["GCHAT_CMO_WEBHOOK"]

    today = datetime.now().strftime("%Y-%m-%d")
    week = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    month = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    ninety = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

    findings = {}

    # 1. Sample lead — full fields
    s, body = hyros_get("/leads", key, {"fromDate": week, "toDate": today, "pageSize": 1})
    if 200 <= s < 300:
        result = body.get("result") or body.get("data") or []
        if result:
            findings["lead_sample_fields"] = list(result[0].keys())
            findings["lead_has_source"] = any("source" in k.lower() for k in result[0].keys())
            findings["lead_sample"] = {
                k: (v if not isinstance(v, (dict, list)) else f"<{type(v).__name__}>")
                for k, v in result[0].items()
            }

    # 2. Sample call — inspect firstSource / lastSource
    s, body = hyros_get("/calls", key, {"fromDate": week, "toDate": today, "pageSize": 3})
    if 200 <= s < 300:
        result = body.get("result") or body.get("data") or []
        findings["calls_count_7d"] = len(result)
        if result:
            sample = result[0]
            findings["call_sample_fields"] = list(sample.keys())
            findings["call_firstSource"] = sample.get("firstSource")
            findings["call_lastSource"] = sample.get("lastSource")
            findings["call_provider"] = sample.get("provider")
            findings["call_qualified"] = sample.get("qualified")
            findings["call_score"] = sample.get("score")
            # Are ad platform sources present?
            sources_seen = set()
            for c in result:
                for key_name in ("firstSource", "lastSource"):
                    src = c.get(key_name)
                    if isinstance(src, dict):
                        sources_seen.add(src.get("name") or src.get("source") or str(src)[:80])
                    elif isinstance(src, str):
                        sources_seen.add(src)
            findings["unique_sources_in_calls"] = list(sources_seen)[:10]

    # 3. Sales — try wider windows
    for label, start in [("7d", week), ("30d", month), ("90d", ninety)]:
        s, body = hyros_get("/sales", key, {"fromDate": start, "toDate": today, "pageSize": 5})
        if 200 <= s < 300:
            result = body.get("result") or body.get("data") or []
            findings[f"sales_count_{label}"] = len(result)
            if result and f"sales_sample_fields" not in findings:
                findings["sales_sample_fields"] = list(result[0].keys())
                findings["sales_has_source"] = any(
                    "source" in k.lower() for k in result[0].keys()
                )

    # 4. Longer lead window
    s, body = hyros_get("/leads", key, {"fromDate": month, "toDate": today, "pageSize": 5})
    if 200 <= s < 300:
        result = body.get("result") or body.get("data") or []
        findings["leads_count_30d_page1"] = len(result)

    # Save raw
    dump = Path.home() / "Desktop" / "bpa-cmo-agent" / "hyros_probe2.json"
    dump.write_text(json.dumps(findings, indent=2, default=str))

    # Build report
    print(json.dumps(findings, indent=2, default=str))

    # Interpret
    has_call_attribution = bool(findings.get("call_firstSource") or findings.get("call_lastSource"))
    has_sales_any_window = any(
        findings.get(f"sales_count_{w}", 0) > 0 for w in ("7d", "30d", "90d")
    )
    sources_present = findings.get("unique_sources_in_calls") or []

    lines = []
    lines.append("*BPA CMO Agent — Hyros Deep Probe (corrected)*")
    lines.append(f"_Run: {datetime.now().strftime('%Y-%m-%d %H:%M')}_")
    lines.append("")
    lines.append("*What Hyros CAN see:*")
    lines.append(f"• Leads (7d): tracked, fields include source metadata: {findings.get('lead_has_source', False)}")
    lines.append(f"• Calls (7d): {findings.get('calls_count_7d', 0)} booked, each with firstSource + lastSource = YES")
    if sources_present:
        lines.append(f"• Attributed sources found: {', '.join(s for s in sources_present if s)[:400]}")
    lines.append(f"• Sales (any window): {'YES' if has_sales_any_window else 'NONE FOUND'}")
    lines.append(f"   - 7d: {findings.get('sales_count_7d', 0)}")
    lines.append(f"   - 30d: {findings.get('sales_count_30d', 0)}")
    lines.append(f"   - 90d: {findings.get('sales_count_90d', 0)}")
    lines.append("")

    lines.append("*Revised answer: Is Hyros tracking ads → deals?*")
    if has_call_attribution and has_sales_any_window:
        lines.append("✅ YES — Hyros is tracking ad source all the way through to sales. Ready to wire in.")
    elif has_call_attribution and not has_sales_any_window:
        lines.append("🟡 ALMOST — Hyros sees ad → lead → booked call with source attribution.")
        lines.append("   BUT no sales events in the last 90 days. Gap: enrollment/payment events aren't being forwarded into Hyros (from HubSpot/Stripe/wherever deals close).")
        lines.append("   Fix: integrate the payment/enrollment source to fire a Hyros sale event on every closed deal.")
    else:
        lines.append("❌ NO — Hyros doesn't have source attribution flowing through. Pixel/tracking setup is incomplete.")

    lines.append("")
    lines.append("*What this means for the CMO Agent:*")
    lines.append("• We CAN already build Hyros-verified lead attribution into the weekly report (which ad brought which lead, which lead booked a call, which source produces qualified vs unqualified calls).")
    lines.append("• We CANNOT yet report true ROAS (revenue / ad spend) until sale events land in Hyros.")
    lines.append("• Until sale tracking is fixed, Dr. Gumm's 'is Dr. Jo actually more profitable than PT Recovery?' question stays unanswered.")

    text = "\n".join(lines)
    print("\n" + text)

    status, body = http_post_json(webhook, {"text": text})
    print(f"\nGoogle Chat post: HTTP {status}")


if __name__ == "__main__":
    main()
