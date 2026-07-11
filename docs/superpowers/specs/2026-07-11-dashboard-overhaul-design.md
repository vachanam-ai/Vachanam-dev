# Dashboard Overhaul — detail, lifetime counts, GSAP animation

**Date:** 2026-07-11 · **Approved by:** Vinay (chat) · **Scope:** clinic-owner Dashboard page + /analytics/overview extension

## Goal

The owner dashboard must (1) show lifetime + this-month totals alongside today/period numbers, (2) add a peak-hours heatmap, and (3) feel alive: GSAP-animated chart (curvy lines, growing bars, visible numbers), count-up KPIs, staggered reveals, hover micro-interactions. Approach A: extend in place, no new dependencies (gsap ^3.12.5 already installed).

## Standing constraints

- RULE 1: every new query filters branch_id; branch access asserted from JWT.
- NO revenue estimates anywhere on the clinic dashboard (Vinay standing rule).
- Free-minutes display = remaining-style framing kept as is (existing donut).
- `prefers-reduced-motion: reduce` → all durations 0 via `gsap.matchMedia()`.
- No new npm dependencies. FIXLOG row + tests; frontend gate = `npm run build`.

## 1. Backend — extend `Overview` (backend/routers/analytics.py)

New fields on the existing `Overview` response (same endpoint, same auth):

```python
class LifetimeTotals(BaseModel):
    bookings: int      # count(*) tokens/appointments ever for branch
    calls: int         # count(*) answered calls ever (CallLog)
    patients: int      # count(*) patients on file (is_primary rows)
    minutes: int       # sum(call minutes) ever

class MonthTotals(BaseModel):
    bookings: int      # calendar-month bookings
    calls: int         # calendar-month answered calls
    new_patients: int  # patients created this calendar month

class HourLoad(BaseModel):
    hour: int          # 8..21 IST
    calls: int         # answered calls started in that hour, selected period

class Overview(...):  # existing fields unchanged, plus:
    lifetime: LifetimeTotals
    month: MonthTotals
    hourly_load: list[HourLoad]     # for the peak-hours heatmap
    hourly_by_weekday: list[dict]   # {weekday: 0-6, hour: 8-21, calls: n} — heatmap grid
```

Implementation notes:
- 4 lifetime counts = simple branch-scoped aggregates, no date filter.
- Month = [first of current month 00:00 IST, now].
- Hour bucketing in IST (Asia/Kolkata) — clinics think in local time.
- Weekday×hour grid over the SELECTED period (7/14/30d param already exists).
- All computed in the same request — dashboard already wakes Neon; no new wake.

## 2. Frontend layout (Dashboard.jsx, top → bottom)

1. Today strip (existing 6 KPI cards) — numbers count up on load.
2. **NEW Lifetime band** — slim dark-teal full-width band directly under the
   KPI strip: "Since day one · X bookings · Y calls answered · Z patients ·
   N voice minutes" — four count-up numerals, white on teal.
3. Voice-minutes donut (sweeps from 0 to pct on load) + **NEW This-month
   mini-block** (bookings / calls / new patients, count-up) sharing the row
   with Busiest days.
4. **Bookings & show rate chart — complete rebuild** (section 3).
5. **NEW Peak hours heatmap** — grid: rows Mon–Sun, cols 8:00–21:00, cell
   fill = teal intensity scaled to calls; cells stagger-fade in; caption
   "Your phone is busiest {weekday} {hour}–{hour+1}". Empty state: "No calls
   in this period yet."
6. Call quality, Booking sources, Doctors, Doctor load — unchanged content,
   stagger-reveal on scroll + card hover lift (y: -3, shadow).

File split (Dashboard.jsx is 528 lines; new content forces it):
- `frontend/src/components/dash/TrendChart.jsx` — the rebuilt chart
- `frontend/src/components/dash/Heatmap.jsx` — peak-hours grid
- `frontend/src/components/dash/useCountUp.js` — count-up hook (gsap textContent tween, snap: 1)
- `frontend/src/lib/motion.js` — extend with `revealStagger`-style dashboard reveal if not reusable as is
- Dashboard.jsx keeps layout + data fetching only.

## 3. Chart v2 — complete redesign (TrendChart.jsx)

Data: existing `daily` (seen/upcoming/no_show/cancelled per day) + `calls_daily` + show-rate series. SVG, viewBox scaled, no chart library.

**Geometry**
- Stacked bars, rounded top corners (rx=3 on top segment only), bar width
  ~55% of slot; 7d/14d/30d all fit via viewBox math.
- Lines = smooth cubic Bézier through points (Catmull-Rom → Bézier
  conversion, tension 0.5) — NO polyline corners.
- Calls curve gets a gradient area fill beneath (same path closed to
  baseline, 8% opacity).

**Palette (replaces current)**
- Seen `#0f766e` (deep teal) · Upcoming `#5eead4` (aqua) · No-show
  `#f59e0b` (amber) · Cancelled `#e5e9ee` (recessive neutral — must not
  dominate as today)
- Show-rate line: gradient stroke `#d97706 → #f0b429`, width 2.5
- Calls curve: `#0e7490`, width 2, area fill `#0e7490` at 0.08 opacity
- Gridlines `#eef2f6`, axis labels slate.

**Numbers (always visible)**
- Each bar's total pops in above it (font-ui, 11px, slate) as the bar lands.
- Show-rate % labels at first/last points; all points on hover.
- Hover: vertical crosshair line + tooltip card (day, seen, upcoming,
  no-show, cancelled, calls, show-rate). Tooltip slides y: -4 on move
  between days.

**Animation timeline (gsap, on mount / on data change)**
1. Gridlines + axes fade in (0.2s)
2. Bars: scaleY 0→1 from baseline (transformOrigin bottom), stagger 0.04
   left→right, ease power2.out; each bar's value label scale-pops (0→1,
   back.out(1.7)) 0.1s after its bar
3. Calls curve: strokeDasharray/offset draw left→right (0.8s, ease none)
   with a leading dot that travels the path and fades at the end; area fill
   fades in after the stroke completes
4. Show-rate curve: same draw, starts 0.2s after calls curve; point markers
   pop in behind the draw head
5. Range switch (7/14/30): tween existing rects to new x/y/height and MORPH
   line `d` attributes (gsap attr tween between path strings with equal
   point counts — resample both paths to a fixed point count first);
   fallback: quick fade-out/in if point counts differ.
- Reduced motion: timeline durations 0 (gsap.matchMedia).

## 4. Page load orchestration

- One master timeline: KPI count-ups start immediately (0.8s, snap: 1);
  lifetime band numbers follow at +0.15s; donut sweep +0.2s.
- Below-fold sections reveal on IntersectionObserver (reuse Landing's
  revealStagger pattern from src/lib/motion.js): autoAlpha 0→1, y 14→0,
  stagger 0.06.
- Hover micro-interactions: cards lift y:-3 + shadow 0.15s; chart bar
  hover = brightness bump + tooltip.

## 5. Error handling

- New Overview fields are additive — old frontend renders fine against new
  API and vice versa (fields optional in JS access, `?.`).
- Heatmap/lifetime blocks render skeleton placeholders while loading and a
  quiet empty state on zero data; never block the rest of the dashboard.
- Chart with <2 days of data: bars only, no line draw (a 1-point curve is
  meaningless), no crash.

## 6. Testing

- Backend (tests/integration/test_analytics_overview_extras.py):
  lifetime counts correct; month boundary (booking last month excluded);
  hourly bucket in IST; weekday grid shape; RULE 1 — second branch's data
  never leaks into first's totals.
- Frontend: `npm run build` green. Manual: load dashboard, watch sequence;
  toggle OS reduced-motion → everything instant; switch 7/14/30 → morph.

## Out of scope

- No revenue/₹ anywhere (standing rule). No new chart pages. No websocket
  live updates (10s+ polling already exists on Monitoring; Dashboard stays
  fetch-on-load + React Query refetch). No export/print. No per-doctor
  drill-down charts (later if asked).
