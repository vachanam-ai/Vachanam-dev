# Monochrome UI Redesign — "clinic desk"

Date: 2026-07-29 · Approved by Vinay (mockup + Team-names tweak) · Status: implemented

## Goal

Replace the teal/cream "calm clinic ledger" look with the monochrome BizLink
reference the user supplied: one neutral ground, near-black ink accent, a
single sage-cream band as the only warm note, **General Sans** as the sole
typeface, a **left sidebar** shell, and working dark mode. Teal removed
entirely. GSAP used where it earns its place (content reveals, count-ups,
chart draws) — not on the chrome.

Trigger: the Doctor "My schedule" page was ~6700px tall and unreadable; the
ask expanded to reskin the whole frontend to match the reference.

## Constraints (from Vinay)

- "Same font, same colours, same everything. Remove teal entirely if needed."
- Do NOT touch the doctor/schedule **data model** or backend, nor the
  caller-identity code edits (session_state, removed name gates).
- Team-member names: black+bold (light) / white+bold (dark).

## Approach — cascade, not rewrite

Tailwind reads the palette through CSS-variable tokens by **name**
(`teal`, `cream`, `surface`, `ink`, `hairline`, `gold`…). Remapping the token
**values** in `index.css` re-themes all 18 pages with zero per-page edits. The
`teal*` names were **kept** (now the neutral accent scale) to avoid a
111-site rename — "remove teal" = remap `--teal` → near-black. New tokens
(`band`, `pill`, `line2`, `accent`/`accent-ink`, `sel*`, `good/warn/danger`)
were added to `tailwind.config.js`.

Dark mode inverts the accent BizLink-style: a black button in light becomes a
light button in dark (`--accent` / `--accent-ink` swap). This is why raw
`bg-teal text-white` had to be replaced with `bg-accent text-accent-ink`
everywhere — `text-white` on the inverted (light) accent is invisible in dark.

## What changed

**Foundation**
- `public/fonts/general-sans-{400,500,600,700}.woff2` self-hosted (Fontshare,
  ~90KB); `@font-face` in `index.css`; `index.html` drops Google Fonts, adds
  font preload + monochrome `theme-color`; `public/_headers` long-caches fonts.
- `index.css`: full monochrome token set (light `:root` + `.dark`), restyled
  shared classes (`.card`, `.btn-*` primary=black pill, `.chip-*`, `.tag-*`,
  `.field`, `.numeral`=General Sans tabular, `.section-title`, `.eyebrow`),
  reduced-motion guard. Removed the teal paper-grain + radial glows.
- `tailwind.config.js`: fonts → General Sans; new colour names registered.
- `lib/motion.js`: reduced-motion short-circuits; `pulseRow` → sage flash.

**Structure**
- `Shell.jsx` rebuilt: top navbar → **left sidebar** (brand → nav w/ inline
  icons → user block + theme + sign-out), sticky desktop rail + slide-in
  mobile drawer.

**Pages**
- `DoctorSchedule.jsx`: rebuilt as an **accordion** — compact doctor rows that
  expand to reveal the editor + exact-date publisher (was always-open, the
  6700px cause). Add-doctor collapses behind a button. Removed dead
  `MyUpcomingPatients`; fixed broken `text-gold-deep` token.
- `Dashboard.jsx` + `dash/TrendChart.jsx` + `dash/Heatmap.jsx`: de-tealed —
  lifetime band → black `sel` card, donut arc → accent, trend toggle →
  accent, heatmap intensity → `rgb(var(--accent)/α)` (theme-adaptive), chart
  series → semantic green/amber + neutral (no teal), amber → warn tokens.
- `Queue.jsx`: semantic status tags (attended = green).
- `Login.jsx` / `Register.jsx` / `Landing.jsx`: hardcoded teal panels
  (`bg-[#0e4a49]`) → black `sel` panels; `bg-teal text-white` badges → accent;
  undefined `bg-mist` token fixed; hero gradient neutralised.
- Global: every `bg-teal text-white` → `bg-accent text-accent-ink`;
  `ErrorBoundary.jsx` + Razorpay checkout theme de-tealed.

## Verification

- `npm run build` green; fonts bundled into `dist/fonts` + referenced in CSS.
- `npm run test` (vitest) 6/6 green.
- No `bg-teal text-white` combos, no hardcoded teal hex remain in `src`.

## Not done (deliberate)

Internal pages (Admin, Monitoring, Settings, Treatments, Patients, WalkIn,
Availability, Help, MyTickets, SupportAdmin, TvDisplay) inherit the monochrome
system automatically and had their dangerous colour combos fixed, but were not
individually re-laid-out — diminishing returns for internal tooling. Revisit
per-page only if a specific screen reads poorly.
