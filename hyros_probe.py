"""
Hyros connectivity + data probe.
Answers: Is Hyros configured to track ads -> leads -> sales/deals?
Posts a status summary to the BPA CMO Agent Google Chat space per delivery rule.
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


def hyros_get(path: str, api_key: str, params: dict = None) -> tuple[int, dict]:
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
            body = {"raw_error": "non-json response"}
        return e.code, body
    except Exception as e:
        return -1, {"error": str(e)}


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


def main():
    env = load_env(Path.home() / "Desktop" / "bpa-cmo-agent" / ".env")
    key = env["HYROS_API_KEY"]
    webhook = env["GCHAT_CMO_WEBHOOK"]

    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    # Try the most common Hyros endpoints
    probes = [
        ("/leads", {"fromDate": week_ago, "toDate": today, "pageSize": 5}),
        ("/sales", {"fromDate": week_ago, "toDate": today, "pageSize": 5}),
        ("/orders", {"fromDate": week_ago, "toDate": today, "pageSize": 5}),
        ("/calls", {"fromDate": week_ago, "toDate": today, "pageSize": 5}),
        ("/attribution/sources", {}),
        ("/attribution", {"fromDate": week_ago, "toDate": today}),
    ]

    results = []
    for path, params in probes:
        status, body = hyros_get(path, key, params)
        preview = {}
        if isinstance(body, dict):
            if "result" in body and isinstance(body["result"], list):
                preview = {"count": len(body["result"]), "sample_keys": list(body["result"][0].keys()) if body["result"] else []}
            elif "data" in body and isinstance(body["data"], list):
                preview = {"count": len(body["data"]), "sample_keys": list(body["data"][0].keys()) if body["data"] else []}
            else:
                preview = {"keys": list(body.keys())[:10]}
        results.append({"path": path, "status": status, "preview": preview, "raw": body})
        print(f"{path}: HTTP {status}")
        print(f"  preview: {json.dumps(preview)[:300]}")

    # Write full raw output to a local file
    dump_path = Path.home() / "Desktop" / "bpa-cmo-agent" / "hyros_probe_raw.json"
    dump_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nRaw probe output: {dump_path}")

    # Build status summary for Google Chat
    lines = []
    lines.append("*BPA CMO Agent — Hyros Integration Status Check*")
    lines.append(f"_Probe run: {datetime.now().strftime('%Y-%m-%d %H:%M')}_")
    lines.append("")
    lines.append("*Endpoints probed*")
    for r in results:
        if 200 <= r["status"] < 300:
            count = r["preview"].get("count")
            if count is not None:
                lines.append(f"✅ `{r['path']}` — HTTP {r['status']} — {count} records returned")
            else:
                keys = r["preview"].get("keys", [])
                lines.append(f"✅ `{r['path']}` — HTTP {r['status']} — keys: {', '.join(keys[:5])}")
        else:
            lines.append(f"❌ `{r['path']}` — HTTP {r['status']}")

    lines.append("")
    any_sales = any(
        200 <= r["status"] < 300 and r["preview"].get("count", 0) > 0
        for r in results
        if r["path"] in ("/sales", "/orders")
    )
    any_leads = any(
        200 <= r["status"] < 300 and r["preview"].get("count", 0) > 0
        for r in results
        if r["path"] == "/leads"
    )
    any_attribution = any(
        200 <= r["status"] < 300 for r in results if "attribution" in r["path"]
    )

    lines.append("*Answer: Is Hyros tracking ads → leads → deals?*")
    if any_sales and any_attribution:
        lines.append("✅ YES — sales data AND attribution endpoints are responding. Ready to wire into reports.")
    elif any_sales:
        lines.append("🟡 PARTIAL — sales data is flowing but attribution endpoint unclear. Need to verify ad-level attribution.")
    elif any_leads:
        lines.append("🟡 PARTIAL — leads tracked, but no sales/deals found yet. Either no deals closed last 7 days OR enrollment events aren't being sent to Hyros.")
    else:
        lines.append("❌ NOT YET — Hyros API responding but no sales/leads data returned. Likely pixel setup or enrollment event forwarding is incomplete.")

    lines.append("")
    lines.append("*Next step*")
    if any_sales and any_attribution:
        lines.append("Extend the CMO Agent to pull Hyros attribution data and replace FB-reported leads with Hyros-verified numbers.")
    else:
        lines.append("Marketing Manager needs to verify: (1) Hyros tracking pixel is installed on all landing pages, (2) enrollment/sale events are forwarded to Hyros from HubSpot/Stripe, (3) ad tracking tags (UTM or Hyros-specific) are attached to every FB campaign.")

    text = "\n".join(lines)
    print("\n" + text)

    status, body = http_post_json(webhook, {"text": text})
    print(f"\nGoogle Chat post: HTTP {status}")


if __name__ == "__main__":
    main()
