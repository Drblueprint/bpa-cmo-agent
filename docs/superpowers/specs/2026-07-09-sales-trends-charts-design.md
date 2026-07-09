# Sales Trends Charts — Design

Date: 2026-07-09
Origin: Callum (Head of Sales) wants trend graphs on the SALES tab — close %, dials, and every stage of the sales process — so he can see how the team is trending over any period he chooses. Scoping answers captured with Kurt.

## Goal

Add a "Sales Trends" section to the SALES tab: line charts of the sales funnel and activity metrics over time, bucketed weekly or monthly across the active window, for the whole team or a single rep — each chart backed by a data table.

## Decisions (locked with Kurt)

- **Granularity:** a Weekly / Monthly toggle the manager controls (radio in the section).
- **Charts (all four):** Funnel volume by stage; Conversion rates; SDR call activity; Sales & revenue.
- **Breakdown:** team total by default, with a rep dropdown that filters every chart to one person ("Team (all)" default).
- **Period:** a **dedicated date-range picker inside the Sales Trends section**, independent of the global window / Sales-tab view. Default = last 90 days (≈ 13 weekly points). The manager sets any start/end here; the trends bucket THAT range.
- **Chart library:** Plotly (already a dependency, `plotly>=5.24.1`, currently unused). `plotly.express` for the multi-line charts; `plotly.graph_objects` with a secondary y-axis for the two dual-axis charts.

## Placement & controls

New `st.subheader("Sales Trends")` in `sections/sales.py` after SME Performance, before Asset Performance. At the top of the section:
- **Date range** picker (dedicated to this section): a start + end `st.date_input` pair, defaulting to the last 90 days. Independent of the global date selector. This range is what the trends bucket + load over.
- **Granularity** radio: Weekly (Mon-Sun) / Monthly (calendar month).
- **Rep** selectbox: "Team (all)" + each owner present in the trends range (resolved via `cfg.resolve_owner`); selecting one filters all charts to that owner.

## The four charts

Each chart is followed by a `st.expander("Show data")` with the underlying tidy table (periods as rows, metrics as columns).

1. **Funnel volume by stage** — `px.line`, one line per stage over the buckets: Leads, 15-min Booked, 15-min Held, Strategy Booked, Strategy Held, Closed-Won (counts per bucket). Y = count.
2. **Conversion rates** — `px.line`, three lines: Show % (15-min held / booked), Booking % (strategy booked / 15-min held), Close % (closed-won / strategy held). Y = %.
3. **SDR call activity** — `go` dual-axis: Dials + Connects (counts, left y) as lines; Connect % (connects / dials, right y). Also Booking % (appointments / contacts) available in the data table.
4. **Sales & revenue** — `go` dual-axis: Closed-deal count (left y) + Revenue (right y, $).

## Architecture

- **Period-range builder** (pure): given the active `(start, end)` and granularity, return an ordered list of `(label, bucket_start, bucket_end)` — Weekly = Mon-Sun spanning the window; Monthly = calendar months. Generalizes the existing `_week_ranges` (which only counts back from today) to bucket an arbitrary window.
- **`sales_trends(...)` (new pure function, reconcile.py):** inputs = the window's already-loaded frames (contacts, meetings, deals, contact_deals, aircall calls, fb), the period ranges, and an optional `rep_owner_id`. For each bucket it filters the frames to the bucket dates (and, when `rep_owner_id` is set, to that owner via `sdr_owner` for leads/dials, `bds` for discovery, `sme` for strategy/close) and computes the metric set by reusing the existing funnel/rollup logic (`executive_kpis`-style stage counts + rates, `sdr_call_activity` for dials/connects, deals for sales/revenue). Returns a tidy DataFrame: one row per (period), columns for each metric. Team = no rep filter.
- **Own data load for the trends range:** because the section's date range is independent of (and usually wider than) the active window, it CANNOT reuse `render_sales`'s active-window frames — those wouldn't cover the trends range. The section loads its own frames for its date range via the SAME cached loaders (`load_marketing_contacts`, `load_meetings_in_window`, `load_closed_deals_in_window`, `load_contact_deals`, `load_aircall_calls`, `load_fb_insights`). Loaders are `@st.cache_data(ttl=900)`, so repeated views are cheap; a long first-load range is slower (esp. AirCall pagination) — acceptable, and monthly granularity is the sensible choice for long ranges.
- **Load once per range, bucket in memory:** `sales_trends` slices the loaded trends-range frames per bucket — no per-bucket API calls.
- **Render** (`sales.py`): the 3 controls + load trends-range frames + build period ranges + call `sales_trends` + draw the 4 charts (Plotly) + data-table expanders.

## Data flow

trends date range -> load frames for that range (cached loaders) -> period ranges (weekly/monthly) -> `sales_trends(frames, ranges, rep)` -> tidy time-series DataFrame -> 4 Plotly charts + tables. Metric definitions reuse the shipped rules (held = `COMPLETE*`, `discovery_mask`, attribution owners), so the trend numbers reconcile with the point-in-time tables above (for an overlapping window).

## Error handling / edge cases

- Window too short for the chosen granularity (e.g., Monthly over a 2-week window → 1 bucket) → render a note suggesting a wider range; still draw the single point.
- A rep with no activity in a metric → flat line at 0 (not an error).
- Empty frames → empty charts with an info note.
- A rate with a zero denominator in a bucket → None (gap in the rate line), not 0, so a no-activity week doesn't read as 0 %.
- Buckets ordered oldest → newest on the x-axis.

## Testing

`sales_trends` and the period-range builder are pure → TDD in `dashboard/tests/`:
- Period builder: weekly buckets across a 3-week window (3 buckets, correct Mon-Sun bounds); monthly across a 10-week window (3 calendar months); a window shorter than one bucket (1 bucket).
- `sales_trends`: synthetic frames with activity in two buckets → assert per-bucket funnel counts, conversion rates, dials/connects, sales/revenue; a rep filter isolates one owner's numbers; a bucket with meetings but zero of a denominator yields a None rate (gap), not 0.
- Render verified by `ast.parse` + a live screenshot of the charts.

## Out of scope

- Trending the Speed-to-Lead / Time-to-Close timing metrics — those are built in the separate timing-metrics spec first; once they exist they can be added as additional trend series in a follow-up.
- Exporting charts / scheduled snapshots.
- Per-rep small-multiples (chosen model is team default + single-rep filter, not all-reps-at-once).
