# Phase 1 — Foundation ✅ DONE

**Goal:** Local dev environment, database schema, container infra. Nothing user-facing.

---

## What was built

### Environment
- [`.env`](../../../.env) — all 26 vars defined. Real keys filled for Sarvam, OpenAI, Gemini, LiveKit, JWT, Razorpay (test), Vobiz partner.
- [`.env.example`](../../../.env.example) — committed template with empty values
- [`.gitignore`](../../../.gitignore) — `.env`, `google-service-account.json`, etc. blocked

### Database
- [`backend/config.py`](../../../backend/config.py) — Pydantic settings loading from `.env`
- [`backend/database.py`](../../../backend/database.py) — async SQLAlchemy engine + `AsyncSessionLocal` + `Base`
- [`backend/models/schema.py`](../../../backend/models/schema.py) — 10 tables:
  - `Organization`, `Branch`, `Doctor`, `Patient`, `Token`, `Call`, `FollowupTask`, `BillingCycle`, `WhatsAppSession`, `User`
- [`alembic.ini`](../../../alembic.ini) + [`alembic/env.py`](../../../alembic/env.py) — async-aware, loads URL from settings

### Container infra
- [`docker-compose.yml`](../../../docker-compose.yml) — Postgres 16 + Redis 7-alpine on 5432/6379

### Test plumbing
- [`pytest.ini`](../../../pytest.ini) — `asyncio_mode = auto`
- [`tests/conftest.py`](../../../tests/conftest.py) — `db` fixture (create_all/drop_all per test), `redis` fixture

---

## Known follow-ups

| Item | Severity | When to fix |
|---|---|---|
| `alembic/versions/2fe8f201bc31_initial_schema.py` was generated 2026-05-15. Schema gained 7+ fields and a new `User` table on 2026-05-22 — migration is stale. | HIGH | Phase 4 first task |
| Docker has not been started in this session — no migrations applied to the local DB | HIGH | Phase 4 acceptance check |
| `User.branch_ids` stored as JSONB list of strings — fine for now, swap to a join table if N grows | LOW | post-MVP |
| `Token.marked_by_user_id` is a plain `UUID(as_uuid=True)` without FK to `users.id` (to avoid the circular dependency at create-time). Add the FK after `User` table stabilizes. | LOW | Phase 8 |

---

## How to bring this phase up from scratch

```bash
docker-compose up -d                      # Postgres + Redis
alembic upgrade head                      # Apply migrations (Phase 4 must regenerate first)
python -c "from backend.config import settings; print(settings.app_env)"   # smoke test
pytest tests/unit/ -v                     # 23/23 should pass (Phase 2 tests)
```

---

## Files this phase touches

```
.env, .env.example, .gitignore
docker-compose.yml
alembic.ini, alembic/env.py, alembic/versions/2fe8f201bc31_initial_schema.py
backend/config.py
backend/database.py
backend/models/schema.py
pytest.ini
tests/conftest.py
```

Nothing else. Anything outside this list is from Phase 2+.

---

## What this phase does NOT do

- No FastAPI app — that's Phase 4
- No routes, no auth, no business logic
- No production secrets (only test/dev keys)
- No deployment config — that's Phase 10

Move on to [Phase 2](../02-voice-agent/CLAUDE.md) or [Phase 4](../04-backend-core/CLAUDE.md) (the next active phase).
