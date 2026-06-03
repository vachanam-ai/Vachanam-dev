# Vachanam — Graphify AST Report
**Generated:** 2026-06-03
**Tool:** graphify 0.8.30 (AST-only extraction, no LLM semantic pass)
**Mode:** Pure structural extraction via tree-sitter. Docs and non-code files not included (require LLM key for semantic pass).
**Corpus:** 46 code files (.py, .toml, .yaml, .json, .yml) | 402 nodes | 1006 edges

---

## God Nodes (most-connected, everything flows through these)

| Degree | Node | Why central |
|---|---|---|
| 41 | `SilenceState` (enum) | Every silence-handling path transitions through this state machine — 4 states, used by agent.py, silence_handler.py, and 19 test cases |
| 40 | `agent.py` | Top-level orchestrator file; imports from backend models, config, database, and all 5 agent service modules — the highest fan-in file in the repo |
| 32 | `Doctor` (schema model) | Core entity: imported by both `agent/agent.py` (runtime DB queries) and `backend/routers/queue.py` (API layer) — bridges the voice-call plane and the HTTP plane |
| 28 | `queue.py` (router) | 28 edge connections; the most-tested backend router — auth guard, branch guard, and token operations all converge here |
| 27 | `Base` (SQLAlchemy declarative base) | All 11 schema tables inherit from it — any schema change ripples through this node |
| 25 | `CurrentUser` (dataclass) | Every authenticated request in the backend flows through this dataclass — auth middleware, branch guard, queue router, auth router |
| 23 | `sanitize_for_tts()` | Rule 6 enforcement node: 23 connections confirm it is called at every TTS output site in the voice agent |

---

## Surprising Connections

1. **`agent/agent.py` imports directly from `backend/config.py`, `backend/database.py`, and `backend/models/schema.py`** — the voice agent (Fly.io Mumbai) shares its Python import path with the backend (Render Singapore). These are two separate deployment units. The 3 cross-service imports work in dev (monorepo) but require the backend package to be on `PYTHONPATH` at agent build time. This is intentional (shared ORM models) but creates a hard coupling: any schema change requires both the agent and backend containers to redeploy together.

2. **`Doctor`, `Patient`, `Token` are imported by both `agent/` and `backend/`** — 8 edges from the agent side, 8 from the backend side on `Doctor` alone. The schema is the de-facto API contract between the two services. There is no protobuf/OpenAPI schema separating them.

3. **`test_rate_limit.py` (25 degree, currently RED)** — ranks in the top 10 god-node list despite containing zero passing tests. It is the largest single test file by connection count. Its 13 RED tests are the executable spec for Phase 4.5 Task 5 (`fastapi-limiter` middleware). The graph shows it already imports `config.py` and `jose` — the implementation interface is fully pre-wired.

4. **`SilenceState` (41 degree) outranks `agent.py` (40 degree)** — the silence state machine is the most-connected node in the entire codebase. More things depend on silence-state transitions than on the agent entrypoint itself. This is architecturally sound (the silence handler is a safety-critical component) but signals it is a high-impact change surface.

5. **`booking_tools.py` (23 degree) has no corresponding test file in `tests/` that directly imports it** — the 4 booking tool functions (`route_to_doctor`, `check_availability`, `assign_token`, `confirm_booking`) are exercised only through `tests/integration/test_booking_flow.py` (full DB path). There are no isolated unit tests for the tool functions themselves.

---

## Confidence Notes

All relationships are `EXTRACTED` (AST-derived, deterministic). No `INFERRED` or `AMBIGUOUS` edges — this is a code-only AST pass. Semantic relationships between docs, phase plans, and code are not captured (would require LLM pass with an API key).

---

## Suggested Questions for Future Graph Queries

1. "What happens to all callers of `assign_token()` if the Redis connection drops?" (blast radius of TD-011/TD-012 area)
2. "Which backend endpoints are reachable without `branch_guard` enforcement?" (Rule 1 audit)
3. "Trace the data flow from `on_user_turn_completed()` to `confirm_booking()`" (voice booking path)
4. "What imports `settings.jwt_secret` and how many hops from the auth router?" (secret surface area)
5. "Which schema tables have no test that queries them directly?" (coverage gap audit)
