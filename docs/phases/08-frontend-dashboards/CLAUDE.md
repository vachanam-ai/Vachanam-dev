# Phase 8 — Owner + Admin Dashboards ⬜ TODO

**Goal:** Two more pages inside the same React PWA built in Phase 7. Owner sees their clinic's analytics. Vinay's admin view shows every org, plan, billing cycle, and platform-wide revenue.

**Effort:** 3 days. **Prerequisites:** Phase 7 ✅ (auth, app shell, API client all set up).

---

## Backend additions

### `backend/routers/dashboard.py`
- `GET /dashboard/{branch_id}/stats?days=30` — daily aggregates from `tokens` table
- Returns: `[{date, total, attended, no_show, cancelled, voice, whatsapp, walk_in}, ...]`
- Branch-scoped via `assert_branch_access`

### `backend/routers/admin.py`
- All endpoints gated by `Depends(require_admin)` — only users with `is_admin=True` (Vinay)
- `GET /admin/orgs` — every Organization with plan, status, owner_email, created_at
- `GET /admin/revenue` — `BillingCycle` aggregates grouped by plan (count, total revenue)
- `GET /admin/orgs/{org_id}/branches` — drill-in
- `GET /admin/usage?org_id=...&days=30` — calls + minutes consumed per branch (from `calls` table)

---

## Frontend additions

```
frontend/src/pages/
├── Dashboard.jsx           # owner dashboard, /dashboard route
└── AdminDashboard.jsx      # /admin route, gate by is_admin in JWT

frontend/src/components/
├── WeeklyChart.jsx         # Recharts line/bar
├── KpiCard.jsx             # big number + delta vs prev period
├── DoctorPerformanceTable.jsx
└── RevenueTable.jsx        # admin only
```

Use `recharts` (lightweight) for visualizations.

---

## Owner dashboard — what it shows

1. **Hero KPIs (4 cards):** total bookings this month, attended %, no-show %, calls answered
2. **Last 30 days** — stacked bar chart: voice / whatsapp / walk_in per day
3. **By doctor** — table sorted by # bookings, with attended/no-show breakdown
4. **Peak times** — heatmap or simple table of hour-of-day → call count
5. **No revenue estimates** (per [feedback-dashboard-display.md](../../../memory/feedback-dashboard-display.md))
6. **Free minutes** — shows REMAINING this cycle (not used)

Layout switches based on plan: Solo sees simpler view, Multi sees per-branch comparison.

---

## Admin dashboard (Vinay) — what it shows

1. **All clinics** table: name, plan, status (trial/active/paused), trial expiry date, monthly revenue
2. **This month P&L:** total revenue – total Vobiz costs – total infra cost = net margin
3. **Per-clinic drill-down:** minutes used, overage charged, last 5 calls, last 5 bookings
4. **Failed payments / churn** — billing cycles with `status='failed'`

---

## Acceptance criteria

```
[ ] GET /dashboard/<branch>/stats?days=7 returns aggregates, gated by branch_id
[ ] GET /admin/orgs returns all orgs, 403 for non-admin
[ ] Owner login → /dashboard renders with their branch's data, no other branch leaks
[ ] Admin login (is_admin=true) → /admin renders, shows all clinics
[ ] Charts render without console errors on Chrome + Safari mobile
[ ] No raw patient phones, no medical info visible anywhere
[ ] Empty-state copy when a branch has no data yet
```

---

## What this phase does NOT do

- ❌ No CSV export (post-MVP)
- ❌ No date range picker (post-MVP — 7d/30d/90d toggle only)
- ❌ No email digests (post-MVP)
- ❌ No subscription management UI on owner dashboard — that's Phase 9 (owner sees plan + can upgrade)

Move on to [Phase 9](../09-subscriptions-onboarding/CLAUDE.md).
