# BPA CMO Agent

Constraint-first marketing analyst for Blueprint to Practice Automation. Pulls Facebook Ads + Hyros, reconciles the data, segments by vertical and talent, and returns CMO-format recommendations. Terminal-first. Never posts to Google Chat unless told to.

## Quick start

```bash
cd ~/Desktop/bpa-cmo-agent

# Weekly report (FB + Hyros reconciliation, segments, talents)
python3 weekly_report_v2.py --days 7

# Ad-level creative analysis (hook rate, CTR, CPL per ad)
python3 ad_level_report.py --days 7
python3 ad_level_report.py --days 14 --filter rob   # only Dr. Rob ads

# Ad-hoc natural-language query
python3 cmo_query.py "how did Dr. Jo do last 14 days?"
python3 cmo_query.py "chiro vs PT Recovery"
python3 cmo_query.py "zero-lead ads"

# Add --post on any report to publish to Google Chat
python3 weekly_report_v2.py --days 7 --post
```

## Scripts

| Script | Purpose |
|---|---|
| `weekly_report_v2.py` | FB + Hyros reconciliation. Segment + talent rollup. Constraint of the week. |
| `ad_level_report.py` | Ad-level creative breakdown. Best/worst CPL, hook rate, zero-lead offenders. |
| `cmo_query.py` | Ad-hoc natural-language queries against last-N-day data. |
| `pull_report.py` | Legacy v1 weekly FB-only pull (kept for reference). |
| `send_visuals.py` | cardV2 Google Chat report with QuickChart images. |
| `hyros_probe.py`, `hyros_probe2.py` | Hyros connectivity + attribution diagnostics. |
| `install_scheduler.sh` | Installs a macOS launchd job that runs `weekly_report_v2.py --post` every Monday 7am. |

## Scheduler

```bash
bash install_scheduler.sh          # install Monday 7am auto-run
bash install_scheduler.sh remove   # uninstall
launchctl start com.bpa.cmo.weekly # trigger immediately for testing
```

Logs: `scheduler.out.log` / `scheduler.err.log` in this folder.

## Subagents (Claude Code)

Defined in `~/.claude/agents/`:

- `bpa-cmo-analyst.md` — top-of-funnel synthesizer, constraint-first
- `bpa-paid-media-analyst.md` — FB + Hyros data specialist
- `bpa-attribution-auditor.md` — tracks the ad → lead → call → deal chain

## Setup

1. Rotate Hyros API key → put in `.env` as `HYROS_API_KEY`
2. Create a Google Chat webhook for the CMO space → `GCHAT_CMO_WEBHOOK`
3. FB Ads token + account ID → `FB_ADS_TOKEN` / `FB_AD_ACCOUNT_ID`
4. Verify: `python3 weekly_report_v2.py --days 7`

## Rules of delivery

- **Never post to Google Chat by default.** The `--post` flag is required, or the scheduler must fire it.
- **Hyros is ground truth for attribution** (when wired). FB under-reports leads.
- **Recommend, don't execute.** Agent never pauses ads or moves budgets.
- **One constraint at a time.** Report the single biggest bottleneck; defer the rest.

## Security

- `.env` is gitignored — never commit it.
- Never paste secrets into chat, email, or Slack.
- Rotate immediately on any leak.

## Known gaps

- Hyros sees no sales — HubSpot → Hyros sale-event webhook not wired. True ROAS impossible until fixed.
- HubSpot form attribution (hidden UTM + `hyros_click_id`) unconfirmed. Typeform reportedly works; HubSpot parity pending audit.
- FB deprecated `video_3_sec_watched_actions`; hook rate now uses `video_play_actions / impressions` as proxy. Some ad types return no video data.

## Status

- [x] Folder scaffolded
- [x] Secrets filled in
- [x] Subagents defined
- [x] v2 weekly report (FB + Hyros + segments + talents)
- [x] Ad-level creative report
- [x] Ad-hoc query tool
- [x] Scheduler installer
- [x] Customer stage tracking — contacts with lifecycle=customer OR status=active now pulled as "Current BPA Doctors" with source attribution in weekly report v3 and as standalone `pull_hubspot_customers` tool
- [x] Typeform asset attribution — all 24 Typeform form IDs mapped to asset names + vertical segments. Weekly report now shows which assets drove new leads and which drove closed customers via `typeform_asset_download` HubSpot property
- [ ] Verify `typeform_asset_download` is the correct HubSpot internal property name (check HubSpot → Contacts → property internal name)
- [ ] HubSpot form hidden-field audit (UTM passthrough to contact source)
- [ ] HubSpot → Hyros sale-event webhook
- [ ] Coaching Call Analyst v1
- [ ] Weekly CEO Brief
