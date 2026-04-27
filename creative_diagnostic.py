"""
BPA CMO Agent — Creative Diagnostic.
Finds underperforming ads and pulls their creative assets (image, headline,
body, CTA) so we can visually + copy-level diagnose why they're failing.

Outputs:
 - creative_diagnostic_<date>/ folder with downloaded images
 - creative_diagnostic_<date>.json with copy + metrics per ad
 - creative_diagnostic_<date>.md with a human-readable brief
"""

import argparse
import json
import os
import urllib.parse
import urllib.request
import urllib.error
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


def http_get(url: str, params: dict = None):
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


def action_value(actions, atype):
    if not actions:
        return 0.0
    for a in actions:
        if a.get("action_type") == atype:
            return float(a.get("value", 0))
    return 0.0


def leads_of(actions):
    v = action_value(actions, "lead")
    if v:
        return v
    return action_value(actions, "offsite_conversion.fb_pixel_lead")


def fb_ad_insights(token: str, account: str, preset: str) -> list:
    all_data = []
    url = f"https://graph.facebook.com/v19.0/act_{account}/insights"
    params = {
        "date_preset": preset,
        "level": "ad",
        "fields": "ad_id,ad_name,campaign_name,adset_name,spend,impressions,clicks,ctr,cpc,reach,actions",
        "access_token": token,
        "limit": 100,
    }
    status, body = http_get(url, params)
    if status >= 400:
        print(f"FB error {status}: {body}")
        return []
    all_data.extend(body.get("data", []))
    next_url = (body.get("paging") or {}).get("next")
    iters = 0
    while next_url and iters < 20:
        status, body = http_get(next_url)
        if status >= 400:
            break
        all_data.extend(body.get("data", []))
        next_url = (body.get("paging") or {}).get("next")
        iters += 1
    return all_data


def fb_get_ad_creative(token: str, ad_id: str) -> dict:
    """Pull the creative object + attached image/video for a given ad."""
    url = f"https://graph.facebook.com/v19.0/{ad_id}"
    fields = "creative{id,name,title,body,image_url,image_hash,thumbnail_url,video_id,object_story_spec,asset_feed_spec,effective_object_story_id,call_to_action_type,link_url}"
    status, body = http_get(url, {"fields": fields, "access_token": token})
    if status >= 400:
        return {"error": body}
    return body.get("creative", {})


def fb_resolve_image_url(token: str, creative: dict) -> str:
    """Best-effort: return a usable image URL from a creative object."""
    # Direct
    if creative.get("image_url"):
        return creative["image_url"]
    if creative.get("thumbnail_url"):
        return creative["thumbnail_url"]
    # From object_story_spec (static image/link ads)
    oss = creative.get("object_story_spec") or {}
    link = oss.get("link_data") or {}
    if link.get("picture"):
        return link["picture"]
    if link.get("image_hash"):
        # Resolve hash → URL via /adimages
        status, body = http_get(
            f"https://graph.facebook.com/v19.0/act_{creative.get('account_id', '')}/adimages",
            {"hashes": json.dumps([link["image_hash"]]), "access_token": token, "fields": "url,url_128"},
        )
        if status == 200:
            images = body.get("data", [])
            if images:
                return images[0].get("url") or images[0].get("url_128", "")
    # Video thumbnail
    if creative.get("video_id"):
        status, body = http_get(
            f"https://graph.facebook.com/v19.0/{creative['video_id']}",
            {"fields": "picture,thumbnails{uri,is_preferred}", "access_token": token},
        )
        if status == 200:
            if body.get("picture"):
                return body["picture"]
            thumbs = (body.get("thumbnails") or {}).get("data", [])
            if thumbs:
                pref = [t for t in thumbs if t.get("is_preferred")]
                if pref:
                    return pref[0].get("uri", "")
                return thumbs[0].get("uri", "")
    return ""


def extract_copy(creative: dict) -> dict:
    """Pull headline, body, description, CTA from a creative object."""
    copy = {
        "headline": creative.get("title", ""),
        "body": creative.get("body", ""),
        "description": "",
        "cta": creative.get("call_to_action_type", ""),
        "link_url": creative.get("link_url", ""),
    }
    oss = creative.get("object_story_spec") or {}
    link = oss.get("link_data") or {}
    if link:
        copy["headline"] = copy["headline"] or link.get("name", "")
        copy["body"] = copy["body"] or link.get("message", "")
        copy["description"] = link.get("description", "")
        cta = link.get("call_to_action") or {}
        copy["cta"] = copy["cta"] or cta.get("type", "")
        copy["link_url"] = copy["link_url"] or link.get("link", "")
    video = oss.get("video_data") or {}
    if video:
        copy["headline"] = copy["headline"] or video.get("title", "")
        copy["body"] = copy["body"] or video.get("message", "")
        cta = video.get("call_to_action") or {}
        copy["cta"] = copy["cta"] or cta.get("type", "")
    # Asset feed (DPA / multi-creative) — grab the first variant
    afs = creative.get("asset_feed_spec") or {}
    bodies = afs.get("bodies") or []
    titles = afs.get("titles") or []
    descs = afs.get("descriptions") or []
    if bodies and not copy["body"]:
        copy["body"] = bodies[0].get("text", "")
    if titles and not copy["headline"]:
        copy["headline"] = titles[0].get("text", "")
    if descs and not copy["description"]:
        copy["description"] = descs[0].get("text", "")
    return copy


def download(url: str, dest: Path) -> bool:
    if not url:
        return False
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            dest.write_bytes(r.read())
        return True
    except Exception as e:
        print(f"    download failed: {e}")
        return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--min-spend", type=float, default=100.0,
                   help="Minimum spend threshold to flag an ad as underperforming")
    p.add_argument("--max-ads", type=int, default=12)
    args = p.parse_args()

    env = load_env(Path.home() / "Desktop" / "bpa-cmo-agent" / ".env")
    token = env["FB_ADS_TOKEN"]
    account = env["FB_AD_ACCOUNT_ID"]

    preset_map = {7: "last_7d", 14: "last_14d", 28: "last_28d", 30: "last_30d"}
    preset = preset_map.get(args.days, "last_7d")

    today = datetime.now().strftime("%Y-%m-%d")
    out_dir = Path.home() / "Desktop" / "bpa-cmo-agent" / f"creative_diagnostic_{today}"
    out_dir.mkdir(exist_ok=True)

    print(f"Pulling FB ad-level insights ({args.days}d)...")
    rows = fb_ad_insights(token, account, preset)
    print(f"  {len(rows)} ads")

    enriched = []
    for r in rows:
        spend = float(r.get("spend", 0))
        if spend < args.min_spend:
            continue
        leads = leads_of(r.get("actions"))
        ctr = float(r.get("ctr", 0))
        enriched.append({
            "ad_id": r.get("ad_id"),
            "ad_name": r.get("ad_name"),
            "campaign": r.get("campaign_name"),
            "adset": r.get("adset_name"),
            "spend": spend,
            "impressions": int(r.get("impressions", 0)),
            "clicks": int(r.get("clicks", 0)),
            "ctr": ctr,
            "leads": leads,
            "cpl": (spend / leads) if leads else None,
        })

    # Identify underperformers: 0 leads, OR CPL > 2x median, OR CTR < 1%
    zero = [a for a in enriched if a["leads"] == 0]
    lead_pool = [a for a in enriched if a["leads"] > 0]
    lead_pool_sorted = sorted(lead_pool, key=lambda x: x["cpl"], reverse=True) if lead_pool else []
    median_cpl = None
    if lead_pool_sorted:
        mid = len(lead_pool_sorted) // 2
        median_cpl = lead_pool_sorted[mid]["cpl"]

    flagged = []
    for a in zero:
        a["flag_reason"] = "0 leads"
        flagged.append(a)
    if median_cpl:
        for a in lead_pool:
            if a["cpl"] > 2 * median_cpl and a["spend"] >= args.min_spend:
                a["flag_reason"] = f"CPL ${a['cpl']:,.0f} = {a['cpl']/median_cpl:.1f}x median"
                flagged.append(a)
    for a in enriched:
        if a not in flagged and a["ctr"] < 1.0 and a["spend"] >= args.min_spend * 2:
            a["flag_reason"] = f"CTR {a['ctr']:.2f}% (click starve)"
            flagged.append(a)

    flagged = sorted(flagged, key=lambda x: x["spend"], reverse=True)[:args.max_ads]
    print(f"\nFlagged {len(flagged)} underperforming ads (spend ≥ ${args.min_spend:.0f}):")
    for a in flagged:
        print(f"  • {a['ad_name'][:55]} — ${a['spend']:,.0f}, {a['flag_reason']}")

    print("\nPulling creative + images for each...")
    results = []
    for i, a in enumerate(flagged):
        print(f"  [{i+1}/{len(flagged)}] {a['ad_name'][:55]}")
        creative = fb_get_ad_creative(token, a["ad_id"])
        if creative.get("error"):
            print(f"    skipped: {creative['error']}")
            continue
        copy = extract_copy(creative)
        img_url = fb_resolve_image_url(token, creative)
        img_path = None
        if img_url:
            safe = "".join(c if c.isalnum() else "_" for c in a["ad_name"][:50])
            img_path = out_dir / f"{i+1:02d}_{safe}.jpg"
            if download(img_url, img_path):
                print(f"    image saved: {img_path.name}")
            else:
                img_path = None

        results.append({
            "rank": i + 1,
            "ad_id": a["ad_id"],
            "ad_name": a["ad_name"],
            "campaign": a["campaign"],
            "adset": a["adset"],
            "metrics": {
                "spend": a["spend"],
                "impressions": a["impressions"],
                "clicks": a["clicks"],
                "ctr": a["ctr"],
                "leads": a["leads"],
                "cpl": a["cpl"],
            },
            "flag_reason": a["flag_reason"],
            "copy": copy,
            "image_url": img_url,
            "image_path": str(img_path) if img_path else None,
            "creative_id": creative.get("id"),
        })

    # Save JSON
    json_out = out_dir / "diagnostic.json"
    json_out.write_text(json.dumps(results, indent=2))

    # Save markdown brief
    md = [f"# Creative Diagnostic — {today}",
          f"_Window: last {args.days}d · Flagged ads: {len(results)}_",
          ""]
    for r in results:
        m = r["metrics"]
        md.append(f"## {r['rank']}. {r['ad_name']}")
        md.append(f"**Campaign:** {r['campaign']} › **Adset:** {r['adset']}")
        md.append(f"**Flag:** {r['flag_reason']}")
        cpl = f"${m['cpl']:,.0f}" if m["cpl"] else "—"
        md.append(f"**Metrics:** ${m['spend']:,.0f} spend · {m['impressions']:,} impr · "
                  f"{m['clicks']:,} clicks · CTR {m['ctr']:.2f}% · "
                  f"{m['leads']:.0f} leads · CPL {cpl}")
        md.append("")
        md.append("**Copy:**")
        md.append(f"- Headline: {r['copy']['headline'] or '—'}")
        md.append(f"- Body: {r['copy']['body'] or '—'}")
        md.append(f"- Description: {r['copy']['description'] or '—'}")
        md.append(f"- CTA: {r['copy']['cta'] or '—'}")
        if r.get("image_path"):
            md.append(f"- Image: `{Path(r['image_path']).name}`")
        md.append("")
    (out_dir / "diagnostic.md").write_text("\n".join(md))

    print(f"\nSaved:")
    print(f"  {json_out}")
    print(f"  {out_dir / 'diagnostic.md'}")
    print(f"  Images in: {out_dir}/")


if __name__ == "__main__":
    main()
