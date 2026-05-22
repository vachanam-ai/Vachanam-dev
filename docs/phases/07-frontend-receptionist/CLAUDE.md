# Phase 7 — Receptionist PWA ⬜ TODO

**Goal:** A React + Vite Progressive Web App that runs on any receptionist's phone. Opens to today's queue grouped by doctor. Tap to mark patient attended or no-show. Works offline (cached queue, queued mutations replay on reconnect).

**Effort:** 3-4 days. **Prerequisites:** Phase 4 ✅ (queue endpoints exist + JWT auth). Phase 5 + 6 don't need to be done first.

---

## Tech stack

- React 18 + Vite 5
- TailwindCSS 3 (utility classes, no Material/component lib)
- React Query (TanStack Query) for data + optimistic mutations
- Workbox for service worker / PWA cache
- `vite-plugin-pwa` for manifest + SW generation
- axios with JWT interceptor

---

## Folder layout

```
frontend/
├── package.json
├── vite.config.js                # PWA config, /api proxy → localhost:8000
├── tailwind.config.js
├── postcss.config.js
├── index.html
├── public/
│   ├── manifest.json
│   └── icons/                    # 192x192, 512x512 PNG, plus apple-touch
└── src/
    ├── main.jsx
    ├── App.jsx                   # router with auth gate
    ├── api/
    │   └── client.js             # axios + JWT in localStorage
    ├── hooks/
    │   ├── useAuth.js
    │   ├── useQueue.js           # React Query: GET /queue/:branch/today, polls every 30s
    │   └── useMarkAttendance.js  # mutation with optimistic update + queue-on-fail
    ├── pages/
    │   ├── Login.jsx             # Google Sign-In button → POST /auth/google → JWT
    │   ├── Queue.jsx             # main page, doctor sections, patient cards
    │   └── WalkIn.jsx            # later — manual walk-in registration
    └── components/
        ├── PatientCard.jsx       # name, token, attend/no-show buttons
        ├── HeroNumber.jsx        # large "12 remaining" header
        ├── OfflineBanner.jsx
        └── BranchSwitcher.jsx    # if user has access to multiple branches
```

---

## Key UX rules

| Rule | Why |
|---|---|
| Buttons must be ≥ 56px tall (thumbs, dirty hands in clinic context) | Touch ergonomics |
| Single primary color, high contrast | Glanceable in bad lighting |
| Attended/no-show buttons are optimistic — UI updates instantly, mutation queued | Receptionist taps fast, network is unreliable |
| Failed mutations show a small inline retry, never a modal | Don't block them |
| Service worker caches last queue payload — opens to last-known state offline | Clinic might lose wifi briefly |
| Mutation queue stored in IndexedDB, replays on reconnect via SW background sync | No lost taps |
| Never show patient phone numbers (PII) | DPDP Act |

---

## API surface used

```
POST /auth/google           # Google ID token → JWT
GET  /auth/me               # decode JWT, return claims
GET  /queue/{branch_id}/today
PATCH /queue/{branch_id}/token/{token_id}/attend
PATCH /queue/{branch_id}/token/{token_id}/no-show
```

All require `Authorization: Bearer <jwt>`.

---

## Acceptance criteria

```
[ ] npm run dev → opens http://localhost:5173, shows Login
[ ] Google sign-in completes → /queue page loads with today's data
[ ] Tap Attended on a patient card → green check appears instantly, server confirms in <500ms
[ ] Disconnect wifi, tap Attended → still shows green (optimistic), small "queued" indicator
[ ] Reconnect wifi → queued mutation fires, indicator clears, server reflects change
[ ] Add to Home Screen on Android → installs as PWA, opens without browser chrome
[ ] No patient phone numbers visible in any view (privacy audit)
[ ] User scoped to Branch A cannot see Branch B's queue (route guard + server 403)
```

---

## Manual setup

1. Google Cloud Console → OAuth consent screen → add `localhost:5173` and prod URL to authorized origins
2. Copy `GOOGLE_OAUTH_CLIENT_ID` to `frontend/.env` as `VITE_GOOGLE_OAUTH_CLIENT_ID`
3. Generate PWA icons (any tool, just need 192 and 512 PNG)

---

## What this phase does NOT do

- ❌ No analytics dashboard (Phase 8)
- ❌ No admin features for Vinay (Phase 8)
- ❌ No subscription management UI (Phase 9 — owner sees it in their dashboard)
- ❌ Not deployed to Cloudflare yet — that's Phase 10. `npm run dev` only.

Move on to [Phase 8](../08-frontend-dashboards/CLAUDE.md).
