"""
Pull all ACTIVE campaigns, ad sets, and ads from FB Ads Manager.
For each active ad, extract destination URL / landing page URL.
No external deps — stdlib only.
"""

import json
import urllib.parse
import urllib.request
from pathlib import Path


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


def fetch_all_pages(url: str, params: dict) -> list:
    """Fetch all paginated results from FB Graph API."""
    results = []
    data = http_get(url, params)
    results.extend(data.get("data", []))
    # Follow pagination
    while True:
        paging = data.get("paging", {})
        next_url = paging.get("next")
        if not next_url:
            break
        with urllib.request.urlopen(next_url, timeout=30) as r:
            data = json.loads(r.read().decode())
        results.extend(data.get("data", []))
    return results


def fetch_active_campaigns(token: str, account_id: str) -> list:
    url = f"https://graph.facebook.com/v19.0/act_{account_id}/campaigns"
    params = {
        "fields": "id,name,status,objective,daily_budget,lifetime_budget",
        "effective_status": '["ACTIVE"]',
        "access_token": token,
        "limit": 200,
    }
    return fetch_all_pages(url, params)


def fetch_active_adsets(token: str, campaign_id: str) -> list:
    url = f"https://graph.facebook.com/v19.0/{campaign_id}/adsets"
    params = {
        "fields": "id,name,status,effective_status,daily_budget,lifetime_budget,targeting",
        "effective_status": '["ACTIVE"]',
        "access_token": token,
        "limit": 200,
    }
    return fetch_all_pages(url, params)


def fetch_active_ads(token: str, adset_id: str) -> list:
    url = f"https://graph.facebook.com/v19.0/{adset_id}/ads"
    params = {
        "fields": "id,name,status,effective_status,creative{id,name,object_story_spec,link_url,call_to_action_type}",
        "effective_status": '["ACTIVE"]',
        "access_token": token,
        "limit": 200,
    }
    return fetch_all_pages(url, params)


def fetch_creative_detail(token: str, creative_id: str) -> dict:
    url = f"https://graph.facebook.com/v19.0/{creative_id}"
    params = {
        "fields": "id,name,object_story_spec,link_url,call_to_action_type,asset_feed_spec,object_url",
        "access_token": token,
    }
    try:
        return http_get(url, params)
    except Exception as e:
        return {"error": str(e)}


def extract_url_from_creative(creative: dict) -> str:
    """
    Try every known location where FB stores destination URLs in a creative.
    Returns the URL string or 'NOT FOUND'.
    """
    if not creative:
        return "NOT FOUND"

    # Direct link_url field
    if creative.get("link_url"):
        return creative["link_url"]

    # object_url
    if creative.get("object_url"):
        return creative["object_url"]

    # object_story_spec -> link_data -> link
    oss = creative.get("object_story_spec", {})

    link_data = oss.get("link_data", {})
    if link_data.get("link"):
        return link_data["link"]
    # child_attachments (carousel)
    for child in link_data.get("child_attachments", []):
        if child.get("link"):
            return child["link"]

    # video_data -> call_to_action -> value -> link
    video_data = oss.get("video_data", {})
    cta = video_data.get("call_to_action", {})
    cta_value = cta.get("value", {})
    if cta_value.get("link"):
        return cta_value["link"]

    # photo_data
    photo_data = oss.get("photo_data", {})
    if photo_data.get("url"):
        return photo_data["url"]

    # asset_feed_spec -> link_urls
    afs = creative.get("asset_feed_spec", {})
    link_urls = afs.get("link_urls", [])
    if link_urls and link_urls[0].get("website_url"):
        return link_urls[0]["website_url"]

    return "NOT FOUND"


def main():
    env_path = Path.home() / "Desktop" / "bpa-cmo-agent" / ".env"
    env = load_env(env_path)
    token = env["FB_ADS_TOKEN"]
    account_id = env["FB_AD_ACCOUNT_ID"]

    flagged_slugs = [
        "/tof-cold-typeform/",
        "/tof-top10-typeform/",
        "/million-dollar-team-tof/",
        "/3-secrets-tof/",
        "/one-secret-tof/",
        "/tof-four-ps-of-practice-performance/",
    ]

    print("Fetching ACTIVE campaigns...")
    campaigns = fetch_active_campaigns(token, account_id)
    print(f"  Found {len(campaigns)} active campaigns.")

    all_ads = []

    for camp in campaigns:
        camp_id = camp["id"]
        camp_name = camp["name"]
        camp_budget = camp.get("daily_budget") or camp.get("lifetime_budget") or "N/A"

        print(f"  Campaign: {camp_name} (id={camp_id})")

        adsets = fetch_active_adsets(token, camp_id)
        print(f"    Found {len(adsets)} active ad sets.")

        for adset in adsets:
            adset_id = adset["id"]
            adset_name = adset["name"]
            adset_budget = adset.get("daily_budget") or adset.get("lifetime_budget") or "inherits from campaign"

            ads = fetch_active_ads(token, adset_id)
            print(f"      Ad set: {adset_name} — {len(ads)} active ads")

            for ad in ads:
                ad_id = ad["id"]
                ad_name = ad["name"]
                ad_status = ad.get("effective_status", ad.get("status", "?"))

                # Extract URL from embedded creative
                creative = ad.get("creative", {})
                creative_id = creative.get("id")
                url = extract_url_from_creative(creative)

                # If not found in embedded, fetch full creative detail
                if url == "NOT FOUND" and creative_id:
                    full_creative = fetch_creative_detail(token, creative_id)
                    url = extract_url_from_creative(full_creative)

                all_ads.append({
                    "campaign_id": camp_id,
                    "campaign_name": camp_name,
                    "campaign_budget_daily": camp_budget,
                    "adset_id": adset_id,
                    "adset_name": adset_name,
                    "adset_budget_daily": adset_budget,
                    "ad_id": ad_id,
                    "ad_name": ad_name,
                    "ad_status": ad_status,
                    "destination_url": url,
                    "creative_id": creative_id or "none",
                })

    print(f"\nTotal active ads found: {len(all_ads)}\n")

    # ---- OUTPUT ----
    # Group by campaign
    by_campaign = {}
    for ad in all_ads:
        key = (ad["campaign_id"], ad["campaign_name"], ad["campaign_budget_daily"])
        by_campaign.setdefault(key, {})
        adset_key = (ad["adset_id"], ad["adset_name"], ad["adset_budget_daily"])
        by_campaign[key].setdefault(adset_key, []).append(ad)

    print("=" * 90)
    print("BPA FACEBOOK ADS — ACTIVE AD INVENTORY")
    print(f"Pulled: 2026-04-24")
    print("=" * 90)

    flagged_hits = []

    for (cid, cname, cbudget), adsets in by_campaign.items():
        budget_display = f"${int(cbudget)/100:,.2f}/day" if str(cbudget).isdigit() else cbudget
        print(f"\nCAMPAIGN: {cname}")
        print(f"  Budget: {budget_display} | ID: {cid}")
        print(f"  Status: ACTIVE")

        for (asid, asname, asbudget), ads_list in adsets.items():
            abudget_display = f"${int(asbudget)/100:,.2f}/day" if str(asbudget).isdigit() else asbudget
            print(f"\n  AD SET: {asname}")
            print(f"    Budget: {abudget_display} | ID: {asid}")

            for ad in ads_list:
                url = ad["destination_url"]
                flagged = any(slug in url for slug in flagged_slugs)
                flag_marker = "  <<< FLAGGED BROKEN PAGE" if flagged else ""
                print(f"\n    AD: {ad['ad_name']}")
                print(f"      Status: {ad['ad_status']}")
                print(f"      URL: {url}{flag_marker}")
                print(f"      Ad ID: {ad['ad_id']} | Creative ID: {ad['creative_id']}")

                if flagged:
                    flagged_hits.append({
                        "campaign": cname,
                        "adset": asname,
                        "ad": ad["ad_name"],
                        "url": url,
                        "ad_id": ad["ad_id"],
                    })

    print("\n" + "=" * 90)
    print("FLAGGED ADS — pointing to pages flagged as potentially broken")
    print("=" * 90)
    if flagged_hits:
        for h in flagged_hits:
            print(f"  Campaign: {h['campaign']}")
            print(f"  Ad Set:   {h['adset']}")
            print(f"  Ad:       {h['ad']}")
            print(f"  URL:      {h['url']}")
            print(f"  Ad ID:    {h['ad_id']}")
            print()
    else:
        print("  None of the active ads are pointing to the flagged page slugs.")

    print("\n" + "=" * 90)
    print("URL SUMMARY — all unique destination URLs in active ads")
    print("=" * 90)
    urls = {}
    for ad in all_ads:
        u = ad["destination_url"]
        urls[u] = urls.get(u, 0) + 1
    for u, count in sorted(urls.items(), key=lambda x: -x[1]):
        flagged = any(slug in u for slug in flagged_slugs)
        flag_marker = "  <<< FLAGGED" if flagged else ""
        print(f"  [{count} ad(s)] {u}{flag_marker}")

    # Save JSON for later use
    out_json = Path.home() / "Desktop" / "bpa-cmo-agent" / "active_ads_2026-04-24.json"
    out_json.write_text(json.dumps(all_ads, indent=2))
    print(f"\nFull JSON saved to: {out_json}")


if __name__ == "__main__":
    main()
