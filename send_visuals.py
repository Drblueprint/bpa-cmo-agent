"""
BPA CMO Agent — visual report.
Refetches FB Ads data, generates 3 QuickChart.io charts, posts as
Google Chat cardV2 with embedded images. Pure stdlib.
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


def http_get(url: str, params: dict) -> dict:
    q = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{url}?{q}", timeout=30) as r:
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


def fetch_fb(token: str, account_id: str) -> list[dict]:
    return http_get(
        f"https://graph.facebook.com/v19.0/act_{account_id}/insights",
        {
            "date_preset": "last_7d",
            "level": "campaign",
            "fields": "campaign_name,spend,impressions,clicks,ctr,actions",
            "access_token": token,
            "limit": 100,
        },
    ).get("data", [])


def leads_of(actions):
    if not actions:
        return 0.0
    for a in actions:
        if a.get("action_type") == "lead":
            return float(a.get("value", 0))
    for a in actions:
        if a.get("action_type") == "offsite_conversion.fb_pixel_lead":
            return float(a.get("value", 0))
    return 0.0


def short_name(n: str, max_len: int = 38) -> str:
    # Strip "DS | " prefix, underscores around category names
    n = n.replace("DS | ", "").replace("__", "")
    n = n.replace(" Funnel Setup", "").replace(" Funnel", "")
    n = n.replace(" | CBO | USA", "").replace("Apr 2026 ", "")
    if len(n) > max_len:
        n = n[: max_len - 1] + "…"
    return n


def segment_of(name: str) -> str:
    lower = name.lower()
    if "rob" in lower:
        return "chiro_rob"
    if "jo" in lower and "chiro" in lower:
        return "chiro_jo"
    if "pt" in lower or "recovery" in lower:
        return "pt_recovery"
    if "theraray" in lower:
        return "theraray"
    if "emx" in lower or "fort worth" in lower:
        return "emx_event"
    if "retargeting" in lower or "testimonials" in lower:
        return "retargeting"
    return "other"


def chart_url(config: dict, w: int = 700, h: int = 420) -> str:
    compact = json.dumps(config, separators=(",", ":"))
    return (
        "https://quickchart.io/chart"
        f"?bkg=white&w={w}&h={h}&c={urllib.parse.quote(compact)}"
    )


def build_spend_chart(rows: list[dict]) -> str:
    rows = sorted(rows, key=lambda r: r["spend"], reverse=True)
    labels = [short_name(r["name"]) for r in rows]
    spend = [round(r["spend"], 0) for r in rows]
    # Color: red for zero-lead, green for CPL < $100, yellow else
    colors = []
    for r in rows:
        if r["leads"] == 0:
            colors.append("#E53935")  # red
        elif r["cpl"] is not None and r["cpl"] < 100:
            colors.append("#43A047")  # green
        elif r["cpl"] is not None and r["cpl"] < 250:
            colors.append("#FB8C00")  # orange
        else:
            colors.append("#8E24AA")  # purple (high CPL)

    cfg = {
        "type": "horizontalBar",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": "Spend ($)",
                    "data": spend,
                    "backgroundColor": colors,
                }
            ],
        },
        "options": {
            "title": {
                "display": True,
                "text": "Spend by Campaign — Last 7 Days (color = efficiency)",
                "fontSize": 16,
            },
            "legend": {"display": False},
            "plugins": {
                "datalabels": {
                    "anchor": "end",
                    "align": "right",
                    "color": "#222",
                    "font": {"weight": "bold"},
                    "formatter": "(val) => '$' + val.toLocaleString()",
                }
            },
            "scales": {
                "xAxes": [{"ticks": {"beginAtZero": True}}]
            },
        },
    }
    return chart_url(cfg, w=900, h=520)


def build_cpl_chart(rows: list[dict]) -> str:
    # Only campaigns with leads
    rows_with_leads = [r for r in rows if r["leads"] > 0 and r["cpl"] is not None]
    rows_with_leads = sorted(rows_with_leads, key=lambda r: r["cpl"])
    labels = [short_name(r["name"]) for r in rows_with_leads]
    cpls = [round(r["cpl"], 2) for r in rows_with_leads]
    colors = [
        "#43A047" if c < 100 else ("#FB8C00" if c < 250 else "#E53935")
        for c in cpls
    ]

    cfg = {
        "type": "horizontalBar",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": "Cost per Lead ($)",
                    "data": cpls,
                    "backgroundColor": colors,
                }
            ],
        },
        "options": {
            "title": {
                "display": True,
                "text": "Cost per Lead by Campaign (green < $100, red > $250)",
                "fontSize": 16,
            },
            "legend": {"display": False},
            "plugins": {
                "datalabels": {
                    "anchor": "end",
                    "align": "right",
                    "color": "#222",
                    "font": {"weight": "bold"},
                    "formatter": "(val) => '$' + val.toLocaleString()",
                }
            },
            "scales": {"xAxes": [{"ticks": {"beginAtZero": True}}]},
        },
    }
    return chart_url(cfg, w=900, h=480)


def build_segment_chart(rows: list[dict]) -> str:
    # Group chiro vs non-chiro
    chiro_spend = sum(r["spend"] for r in rows if "chiro" in segment_of(r["name"]))
    chiro_leads = sum(r["leads"] for r in rows if "chiro" in segment_of(r["name"]))
    nonchiro_spend = sum(r["spend"] for r in rows if "chiro" not in segment_of(r["name"]))
    nonchiro_leads = sum(r["leads"] for r in rows if "chiro" not in segment_of(r["name"]))

    total_spend = chiro_spend + nonchiro_spend
    total_leads = chiro_leads + nonchiro_leads

    cfg = {
        "type": "bar",
        "data": {
            "labels": ["% of Spend", "% of Leads"],
            "datasets": [
                {
                    "label": "Chiro",
                    "backgroundColor": "#E53935",
                    "data": [
                        round(chiro_spend / total_spend * 100, 1) if total_spend else 0,
                        round(chiro_leads / total_leads * 100, 1) if total_leads else 0,
                    ],
                },
                {
                    "label": "Non-Chiro (PT/TheraRay/EMX)",
                    "backgroundColor": "#43A047",
                    "data": [
                        round(nonchiro_spend / total_spend * 100, 1) if total_spend else 0,
                        round(nonchiro_leads / total_leads * 100, 1) if total_leads else 0,
                    ],
                },
            ],
        },
        "options": {
            "title": {
                "display": True,
                "text": "The Imbalance: Chiro takes 58% of spend, delivers 21% of leads",
                "fontSize": 16,
            },
            "plugins": {
                "datalabels": {
                    "anchor": "end",
                    "align": "top",
                    "color": "#222",
                    "font": {"weight": "bold"},
                    "formatter": "(val) => val + '%'",
                }
            },
            "scales": {
                "yAxes": [
                    {"ticks": {"beginAtZero": True, "max": 100, "callback": "(v) => v + '%'"}}
                ]
            },
        },
    }
    return chart_url(cfg, w=800, h=450)


def main():
    env_path = Path.home() / "Desktop" / "bpa-cmo-agent" / ".env"
    env = load_env(env_path)

    campaigns = fetch_fb(env["FB_ADS_TOKEN"], env["FB_AD_ACCOUNT_ID"])
    rows = []
    for c in campaigns:
        spend = float(c.get("spend", 0))
        leads = leads_of(c.get("actions"))
        rows.append(
            {
                "name": c.get("campaign_name", ""),
                "spend": spend,
                "leads": leads,
                "cpl": (spend / leads) if leads else None,
                "ctr": float(c.get("ctr", 0)),
            }
        )

    spend_url = build_spend_chart(rows)
    cpl_url = build_cpl_chart(rows)
    segment_url = build_segment_chart(rows)

    total_spend = sum(r["spend"] for r in rows)
    total_leads = sum(r["leads"] for r in rows)
    blended_cpl = total_spend / total_leads if total_leads else 0

    today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    # Google Chat cardV2 payload
    payload = {
        "cardsV2": [
            {
                "cardId": "bpa-cmo-visual",
                "card": {
                    "header": {
                        "title": "BPA CMO Agent — Visual Report",
                        "subtitle": f"Last 7 days ({start} → {today})",
                        "imageUrl": "https://img.icons8.com/fluency/96/combo-chart.png",
                        "imageType": "CIRCLE",
                    },
                    "sections": [
                        {
                            "header": "Top-line",
                            "widgets": [
                                {
                                    "decoratedText": {
                                        "topLabel": "Spend",
                                        "text": f"${total_spend:,.0f}",
                                        "bottomLabel": "last 7 days",
                                    }
                                },
                                {
                                    "decoratedText": {
                                        "topLabel": "Leads",
                                        "text": f"{total_leads:,.0f}",
                                        "bottomLabel": f"blended CPL ${blended_cpl:,.2f}",
                                    }
                                },
                            ],
                        },
                        {
                            "header": "Spend Distribution",
                            "widgets": [
                                {"image": {"imageUrl": spend_url}},
                                {
                                    "textParagraph": {
                                        "text": "<b>Red</b> = zero leads · <b>Green</b> = CPL &lt; $100 · <b>Orange</b> = $100–$250 · <b>Purple</b> = high CPL",
                                    }
                                },
                            ],
                        },
                        {
                            "header": "Cost per Lead — Ranked",
                            "widgets": [
                                {"image": {"imageUrl": cpl_url}},
                                {
                                    "textParagraph": {
                                        "text": "<b>PT Recovery Copy 3</b> leads at $54.57. <b>Dr. Rob LAL</b> is dragging at $675.",
                                    }
                                },
                            ],
                        },
                        {
                            "header": "The Core Imbalance",
                            "widgets": [
                                {"image": {"imageUrl": segment_url}},
                                {
                                    "textParagraph": {
                                        "text": "Chiro gets <b>58%</b> of spend but delivers <b>21%</b> of leads. 5.4× more expensive per lead. The problem isn't the chiro audience — it's <b>Dr. Rob's creative</b>, which produced 2 leads on $3,459 across 3 audiences.",
                                    }
                                },
                            ],
                        },
                        {
                            "header": "Recommended Actions",
                            "widgets": [
                                {
                                    "textParagraph": {
                                        "text": (
                                            "<b>Cut ($3,459 freed):</b><br>"
                                            "• Dr. Rob / CA — $1,302, 0 leads<br>"
                                            "• Dr. Rob / Interests — $807, 0 leads<br>"
                                            "• Dr. Rob / LAL — $1,350, 2 leads @ $675 CPL<br><br>"
                                            "<b>Scale:</b><br>"
                                            "• PT Recovery Copy 3 → +$1,845/wk (proven $54 CPL)<br>"
                                            "• PT Recovery Copy 2 + TheraRay → +$900/wk<br><br>"
                                            "<b>Test:</b><br>"
                                            "• New chiro creative WITHOUT Dr. Rob → $700/wk<br>"
                                            "  (Dr. Jo solo scale · Aaron Gumm as talent · member testimonial)"
                                        )
                                    }
                                }
                            ],
                        },
                        {
                            "header": "Blindspots",
                            "widgets": [
                                {
                                    "textParagraph": {
                                        "text": (
                                            "• FB-reported leads only — <b>Hyros attribution not yet wired in</b><br>"
                                            "• No creative review yet — Dr. Rob vs Dr. Jo hook/copy diff unknown<br>"
                                            "• No HubSpot lead→enrolled data"
                                        )
                                    }
                                }
                            ],
                        },
                    ],
                },
            }
        ]
    }

    status, body = http_post_json(env["GCHAT_CMO_WEBHOOK"], payload)
    print(f"Posted visual report: HTTP {status}")
    if status >= 400:
        print(body)
    else:
        print("Check Google Chat — 3 charts + summary card delivered.")


if __name__ == "__main__":
    main()
