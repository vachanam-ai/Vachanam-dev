# Phase 4 — Backend Core 🔨 ACTIVE (start here next)

**Goal:** Replace the standalone test app with the real `backend/main.py`. Add JWT auth, branch-scoped queue endpoints, and a fresh Alembic migration that covers the schema changes from 2026-05-22. End state: `uvicorn backend.main:app` boots, `/health` returns 200, `/api/create-order` still works, `/queue/{branch_id}/today` returns 401 without a JWT.

**Effort:** 1-2 days. ~7 tasks. Each task self-contained.

**Prerequisites:** Phases 1, 2, 3 ✅. Docker Desktop running. `.env` populated.

---

## Files this phase creates / modifies

```
Create:
  backend/main.py
  backend/middleware/auth_middleware.py
  backend/middleware/branch_guard.py
  backend/routers/auth.py
  backend/routers/queue.py
  backend/routers/health.py            (optional — can live in main.py)
  alembic/versions/<new-hash>_phase4_user_table_and_token_timestamps.py
  tests/unit/test_auth.py
  tests/edge_cases/test_data_isolation.py

Modify:
  backend/database.py                  (add init_db helper)
  backend/payments_test_app.py         → DELETE

Touch (verify only):
  backend/routers/payments.py
  backend/models/schema.py
```

---

## Task list

### Task 1: Bring DB to current schema

Old migration `2fe8f201bc31_initial_schema.py` predates the schema additions. Generate a follow-up.

- [ ] `docker-compose up -d`
- [ ] `alembic upgrade head` — apply existing migration first
- [ ] `alembic revision --autogenerate -m "phase4_user_table_and_token_timestamps"` — picks up `User` table, `Branch.meta_phone_number_id`, `Token.{is_urgent, confirmed_at, attended_at, marked_by_user_id}`, `FollowupTask.{what_to_ask, channel, scheduled_date}`
- [ ] Inspect the generated migration — confirm it ADDS columns/tables (does NOT drop anything)
- [ ] `alembic upgrade head` — apply new migration
- [ ] `psql -U vachanam -d vachanam_dev -c "\d users"` → see the User table
- [ ] Commit:
  ```
  git add alembic/versions/
  git commit -m "feat(db): phase 4 migration — User table + token timestamps + meta_phone_number_id"
  ```

### Task 2: `init_db` helper

- [ ] Append to [`backend/database.py`](../../../backend/database.py):
  ```python
  async def init_db() -> None:
      """No-op in prod (alembic handles it). Useful for tests that bypass alembic."""
      async with engine.begin() as conn:
          await conn.run_sync(Base.metadata.create_all)
  ```
- [ ] Commit: `feat(db): add init_db helper for tests`

### Task 3: Auth middleware (JWT)

- [ ] Create [`backend/middleware/auth_middleware.py`](../../../backend/middleware/auth_middleware.py) with:
  - `create_access_token(user: User) -> str` — HS256, includes `sub`, `email`, `role`, `org_id`, `branch_ids`, `is_admin`, `exp`
  - `class CurrentUser` — wraps decoded claims
  - `get_current_user(credentials = Depends(HTTPBearer()))` — decodes, raises 401 on JWTError
  - `require_admin(current_user = Depends(get_current_user))` — raises 403 if not `is_admin`
- [ ] Create [`backend/middleware/branch_guard.py`](../../../backend/middleware/branch_guard.py) with:
  - `def assert_branch_access(current_user, branch_id: str) -> None` — super_admin bypass; else `branch_id in current_user.branch_ids` else 403
- [ ] Write [`tests/unit/test_auth.py`](../../../tests/unit/test_auth.py) — 2 tests: token contains expected claims; admin flag preserved
- [ ] `pytest tests/unit/test_auth.py -v` → 2 passing
- [ ] Commit: `feat(auth): JWT middleware, CurrentUser, admin/branch guards`

### Task 4: Google OAuth login

- [ ] Create [`backend/routers/auth.py`](../../../backend/routers/auth.py):
  - `POST /auth/google?id_token=<google_id_token>` — verifies via `google.oauth2.id_token.verify_oauth2_token`, looks up `User` by `google_sub` (fallback by email), returns Vachanam JWT
  - 403 if email not in users table — "Not registered. Contact your clinic admin."
- [ ] Seed yourself as admin (manual psql for now):
  ```sql
  INSERT INTO users (id, email, name, role, is_admin) VALUES
    (gen_random_uuid(), 'vinayrongala2002@gmail.com', 'Vinay', 'super_admin', true);
  ```
- [ ] Commit: `feat(auth): Google OAuth → Vachanam JWT issue`

### Task 5: Queue router (receptionist endpoints)

- [ ] Create [`backend/routers/queue.py`](../../../backend/routers/queue.py):
  - `GET /queue/{branch_id}/today` — groups today's tokens by doctor; status in `("confirmed", "attended", "no_show")`; gated by `assert_branch_access`
  - `PATCH /queue/{branch_id}/token/{token_id}/attend` — sets `status="attended"`, `attended_at=now`, `marked_by_user_id=current_user.user_id`; 409 if already terminal
  - `PATCH /queue/{branch_id}/token/{token_id}/no-show` — same shape, status `no_show`
  - Every query filters by `Token.branch_id == branch_id` (also a runtime tripwire: `assert_branch_access` will already have rejected, but the WHERE clause is the actual safety)
- [ ] Write [`tests/edge_cases/test_data_isolation.py`](../../../tests/edge_cases/test_data_isolation.py):
  - Create 2 orgs, 2 branches, 2 tokens
  - Verify `WHERE branch_id = A` returns only A's token; same for B
  - Verify a JWT scoped to Branch A returns 403 when hitting `/queue/<B-id>/today`
- [ ] `pytest tests/edge_cases/test_data_isolation.py -v` → green
- [ ] Commit: `feat(queue): receptionist endpoints with branch isolation + tests`

### Task 6: `backend/main.py` — wire everything

- [ ] Create [`backend/main.py`](../../../backend/main.py):
  ```python
  from contextlib import asynccontextmanager
  from fastapi import FastAPI
  from fastapi.middleware.cors import CORSMiddleware
  from fastapi.responses import FileResponse
  from fastapi.staticfiles import StaticFiles
  from pathlib import Path
  import structlog

  from backend.config import settings

  logger = structlog.get_logger()

  @asynccontextmanager
  async def lifespan(app: FastAPI):
      logger.info("starting", env=settings.app_env)
      yield
      logger.info("shutdown")

  app = FastAPI(title="Vachanam API", version="1.0.0", lifespan=lifespan)
  app.add_middleware(CORSMiddleware,
      allow_origins=[settings.frontend_url, "http://localhost:3000", "http://localhost:5173"],
      allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

  from backend.routers import auth, queue, payments
  app.include_router(auth.router, prefix="/auth", tags=["auth"])
  app.include_router(queue.router, prefix="/queue", tags=["queue"])
  app.include_router(payments.router, prefix="/api", tags=["payments"])

  # Serve the marketing/test landing page from /
  _STATIC = Path(__file__).parent / "static"
  app.mount("/static", StaticFiles(directory=_STATIC), name="static")

  @app.get("/")
  async def index():
      return FileResponse(_STATIC / "index.html")

  @app.get("/health")
  async def health():
      return {"status": "ok", "env": settings.app_env}
  ```
- [ ] `uvicorn backend.main:app --reload --port 8000`
- [ ] Browser checks:
  - `http://localhost:8000/health` → `{"status":"ok"}`
  - `http://localhost:8000/` → landing page renders
  - `curl -X POST http://localhost:8000/api/create-order -H "Content-Type: application/json" -d '{"amount":9900}'` → returns a real Razorpay order
  - `curl http://localhost:8000/queue/abc/today` → 403 (no JWT)
- [ ] Commit: `feat(api): backend/main.py — lifespan, CORS, routers wired, landing page mount`

### Task 7: Retire the standalone test app

- [ ] Delete `backend/payments_test_app.py`
- [ ] Update [`docs/STATUS.md`](../../STATUS.md) — flip Phase 4 from "NEXT" to "DONE"
- [ ] Update [`docs/ROADMAP.md`](../../ROADMAP.md) — same flip
- [ ] Commit: `chore: retire standalone payments_test_app; backend/main.py is now canonical`

---

## Acceptance criteria (all must pass before moving to Phase 5)

```
[ ] alembic upgrade head — no pending migrations
[ ] pytest tests/unit/ -v — 25/25 pass (23 from Phase 2 + 2 new auth tests)
[ ] pytest tests/edge_cases/test_data_isolation.py -v — green
[ ] uvicorn backend.main:app — boots without errors
[ ] GET /health → 200
[ ] GET / → landing page HTML
[ ] POST /api/create-order → real Razorpay order returned
[ ] GET /queue/<any>/today without auth → 401
[ ] GET /queue/<wrong-branch>/today with valid JWT but no access → 403
[ ] backend/payments_test_app.py deleted
[ ] STATUS.md and ROADMAP.md updated
```

---

## What this phase does NOT do

- ❌ No WhatsApp endpoints (that's Phase 5)
- ❌ No APScheduler / background jobs (Phase 6)
- ❌ No frontend changes beyond mounting the existing static page
- ❌ No Razorpay webhook handler (Phase 9)
- ❌ No production secrets — keep dev `.env` values

---

## When stuck

| Symptom | Likely cause | Fix |
|---|---|---|
| `alembic revision --autogenerate` produces an empty migration | Old migration already covered the change OR env.py isn't seeing the model | Confirm `from backend.models import schema  # noqa: F401` line is still in alembic/env.py |
| `ImportError: cannot import name X from backend.routers.queue` | Circular import (queue → auth_middleware → queue) | Move CurrentUser to middleware module; import middleware in queue only |
| Tests fail with `DetachedInstanceError` | Reading SQLAlchemy attribute after `async with AsyncSessionLocal()` closed | Capture the value into a local var **inside** the `async with` block |
| Multiple coroutines crash with weird DB errors in `asyncio.gather` | Sharing a single AsyncSession across tasks | Each coroutine opens its own `async with AsyncSessionLocal() as session:` |

After this phase is fully green, move to [Phase 5 — WhatsApp](../05-whatsapp/CLAUDE.md).
