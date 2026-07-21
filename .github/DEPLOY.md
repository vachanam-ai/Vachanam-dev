# Deploy & Rollback

## Pipeline (auto)
Push to `master` → `ci.yml` runs lint · pytest(PG+Redis) · frontend · gitleaks.
All green → **release** job:
1. Auto-bumps semver from Conventional Commits since the last `v*` tag
   (`BREAKING CHANGE`/`type!:` → major · `feat:` → minor · else → patch).
2. Pushes the tag + cuts a GitHub Release (auto notes).
3. Deploys the **Fly agent** (`vachanam-agent`).

**Render** (backend) and **Cloudflare Pages** (frontend) auto-deploy from the
same push via their native GitHub hookup — the pipeline doesn't touch them.

## Rollback (one click)
Actions → **Rollback** → Run workflow → enter a prior tag (e.g. `v1.2.3`).
Redeploys the Fly agent from that tag. Render + Cloudflare: use their dashboard
one-click rollback (the workflow prints exact steps).

## Required secret
`FLY_API_TOKEN` — Settings → Secrets and variables → Actions.
Get it: `fly tokens create deploy -x 999999h`.

## Versioning
Baseline seeded at `v1.0.0` (prod-live). No prior `v*` tag → first release seeds
`v1.0.0`; every subsequent master push bumps from the latest.
