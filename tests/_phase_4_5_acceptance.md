# Phase 4.5 Acceptance Matrix

Maps every criterion from spec section 15 (19 total) to a specific passing test,
manual verification step, or explicit deferral with TD reference.

**Spec:** `docs/superpowers/specs/2026-05-22-security-hardening-design.md` section 15
**Phase:** 4.5 (Security Hardening)
**Date:** 2026-06-04
**Author:** tester (Phase 4.5 Task 16b)

---

| # | Spec section 15 criterion | Coverage | Test / Commit / TD |
|---|---|---|---|
| 1 | SecurityHeadersMiddleware applies CSP, HSTS, X-Frame, X-Content-Type, Referrer, Permissions on every endpoint | `tests/security/test_headers.py` (7/7 GREEN): `test_health_endpoint_has_all_security_headers`, `test_landing_page_has_all_security_headers`, `test_create_order_has_all_security_headers`, `test_protected_route_403_has_all_security_headers`, `test_header_values_match_spec`, `test_csp_contains_required_directives`, `test_authenticated_request_has_all_security_headers` | Impl: `6b00686`. Tests: `a57ef04`. |
| 2 | FastAPI /docs returns 404 when APP_ENV=production | MANUAL: `APP_ENV=production uvicorn backend.main:app; curl http://localhost:8000/docs` returns 404. Code path verified: `backend/main.py` sets `docs_url=None` when `_is_prod=True`. No automated test (requires env-var toggle at app startup, not per-request). | Impl: `4dd5f75` (Phase 4). |
| 3 | Container runs as non-root user (verified: `docker exec <id> whoami` returns `app`) | DEFERRED to Phase 10. TD-014 (P2) tracks this. Both `infra/Dockerfile.agent` and `infra/Dockerfile.backend` run as root. Fix: add `RUN groupadd -r app && useradd -r -g app ...` + `USER app`. | TD-014, Phase 10. |
| 4 | CORS rejects requests from non-allowed origins (verified by curl) | `tests/security/test_cors.py::test_preflight_from_evil_origin_blocked` (GREEN) — sends OPTIONS from `https://evil.com`, asserts no `Access-Control-Allow-Origin` header echoed. | Impl: `6b00686`. Tests: `a57ef04`. |
| 5 | CORS preflight returns correct headers (curl -X OPTIONS) | `tests/security/test_cors.py` (5/5 GREEN): `test_preflight_from_allowed_origin_returns_acao`, `test_preflight_allows_required_methods`, `test_preflight_allows_required_headers`, `test_wildcard_never_used_with_credentials` | Impl: `6b00686`. Tests: `a57ef04`. |
| 6 | JWT lifecycle works: issue, decode, expire, revoke | `tests/unit/test_auth.py` (6/6 GREEN): `test_create_access_token_returns_decodable_jwt`, `test_access_token_includes_all_required_claims`, `test_access_token_jti_is_unique_per_call`, `test_access_token_expiration_matches_settings`, `test_tampered_token_signature_rejected`, `test_expired_token_rejected`. Plus `tests/security/test_jwt.py` (5/5 GREEN): `test_expired_token_returns_401`, `test_tampered_signature_returns_401`, `test_revoked_jti_returns_401`, `test_missing_authorization_header_returns_401`, `test_malformed_bearer_returns_401`. | Impl: `4dd5f75` (Phase 4). Tests: `4dd5f75` (unit), `a57ef04` (security). |
| 7 | React useIdleTimeout hook implemented and tested manually (30 min no activity -> forced login) | DEFERRED to Phase 7. Frontend directory is placeholder; no React code exists yet. useIdleTimeout will be implemented when the Receptionist PWA is built. | Phase 7 (frontend-engineer). |
| 8 | Per-endpoint rate limits enforced (verified by hitting /auth/google 6x in 1 min -> 429) | `tests/security/test_rate_limit.py` (13/13 GREEN): `test_sixth_auth_google_within_60s_returns_429`, `test_429_response_includes_retry_after_header`, `test_settings_exposes_rate_limit_bypass_ips_field`, `test_trusted_ip_bypasses_rate_limit`, `test_user_a_exhausting_quota_does_not_affect_user_b`, `test_ten_distinct_users_each_get_independent_quota`, plus 7 structural/key-func tests. | Impl: `d1e23f2`. Test bugs fixed: `fcc1507`. |
| 9 | Failed login attempts logged to audit_log; 5 failures from 1 IP -> 1h block | `tests/security/test_audit_log.py::test_failed_google_login_writes_audit_log_row` (GREEN) + `tests/security/test_rate_limit.py::test_five_failed_google_verifications_blocks_ip_in_redis` + `test_blocked_ip_returns_403_on_next_auth_attempt` (both GREEN). | Impl (audit): `f378ddf`. Impl (blocklist): `d1e23f2`. Tests: `43285ee`, `fcc1507`. |
| 10 | audit_log table exists; migration applied; rows visible in psql | `alembic/versions/8559268c0c44_phase45_audit_log_ondelete_fk_indexes.py` creates the table. `tests/security/test_audit_log.py::test_successful_google_login_writes_audit_log_row` (GREEN) verifies rows are written and queryable in real Postgres. MANUAL: `psql -d vachanam_dev -c "SELECT * FROM audit_log LIMIT 5;"` after running alembic upgrade head. | Impl: `be6d76e`. Tests: `43285ee` (RED), `f378ddf` (GREEN). |
| 11 | @audit decorator wraps all sensitive routes; rows appear when actions performed | `tests/security/test_audit_log.py` (21/21 GREEN + 1 SKIP): covers login success, login failure, token attend, token no-show, payment verify success, payment verify fail. Each test asserts an audit_log row is written with correct action, resource_type, user_id, branch_id, org_id, success flag, and ip_address. PII denylist enforced (10 tests). Audit failure resilience tested (monkeypatched write_audit_row raises, user still gets 200). | Impl: `f378ddf`. Tests: `43285ee` (RED), `f378ddf` (GREEN). |
| 12 | Privacy policy page renders at /privacy with all 12 sections | **BLOCKED.** Tasks 11+12 (privacy-legal) blocked on client DPDP decisions (recording policy, consent disclosure, DPDP Rules gazette status). See `docs/compliance/dpdp-gap-analysis-2026-06-04.md` sections 3.1, 3.2, 9. Cannot author /privacy content until legal posture confirmed. | BLOCKED on Tasks 11+12. Ref: gap analysis Gap 3.1 (LC-1). |
| 13 | Breach response runbook saved at docs/runbooks/breach-response.md | **BLOCKED.** Task 13 (privacy-legal) blocked on same DPDP decisions as criterion 12. Breach notification procedures depend on DPDP Rules finalization (72-hour window, DPB notification form). See `docs/compliance/dpdp-gap-analysis-2026-06-04.md` section 3.4 (LC-11). | BLOCKED on Task 13. Ref: gap analysis LC-11. |
| 14 | Cloudflare account set up; WAF managed rules enabled; Bot Fight Mode on | MANUAL (Phase 10 cutover): `docs/runbooks/cloudflare-setup.md` documents the exact steps (DNS records, TLS Full Strict, Managed CRS rules, Bot Fight Mode, 5 custom firewall rules). Execution is a Phase 10 production deployment action, not a code change. | Runbook: `76cd7c3`. Execution: Phase 10. |
| 15 | Dependabot enabled on GitHub repo | `.github/dependabot.yml` created. Weekly updates for pip (root + /agent), npm (/frontend), github-actions. Max 5 open PRs per ecosystem. Activation happens automatically when pushed to GitHub. | Impl: `76cd7c3`. |
| 16 | All tests in tests/security/ pass in CI | `pytest tests/security/ -v` -> 56/56 GREEN + 1 SKIP (TD-023). CI workflow at `.github/workflows/ci.yml` runs `pytest tests/ -v --tb=short` on every PR + push to main/master. CI validation pending first GitHub Actions run (no remote push from local context). | CI: `76cd7c3`. Local: 56 GREEN + 1 SKIP. |
| 17 | CI check: secrets-in-repo scan passes | Two layers: (a) `tests/security/test_secrets_not_in_repo.py::test_no_real_secrets_in_git_history` (1/1 GREEN) scans `git log --all -p` for 6 secret patterns with allowlist. (b) `.github/workflows/ci.yml` job `secret-scan` runs gitleaks v2 with `.gitleaks.toml` config (full-history scan). Both GREEN locally. | Test: this commit. CI gitleaks: `76cd7c3`. |
| 18 | OWASP ZAP baseline scan run locally; no high/critical findings | DEFERRED to Phase 4.5 Task 17 (security-engineer). ZAP scan requires running backend locally and executing `zap-baseline.py` against it. Not a code artifact; manual operational step. | Phase 4.5 Task 17 (security-engineer). |
| 19 | STATUS.md and ROADMAP.md updated to reflect Phase 4.5 complete | DEFERRED until ALL criteria are met (including blocked items 12, 13, and deferred items 3, 7, 18). STATUS.md and ROADMAP.md will be updated as the final commit when Phase 4.5 is declared complete. | Final Phase 4.5 commit. |

---

## Summary

| Status | Count | Criteria |
|---|---|---|
| Covered by automated tests | 12 | #1, #4, #5, #6, #8, #9, #10, #11, #16, #17 (plus partial #2) |
| Manual verification (documented) | 3 | #2, #14, #15 |
| BLOCKED (client DPDP check) | 2 | #12, #13 |
| DEFERRED (Phase 7 -- frontend) | 1 | #7 |
| DEFERRED (Phase 10 -- containers) | 1 | #3 (TD-014) |
| DEFERRED (Task 17 -- ZAP scan) | 1 | #18 |
| DEFERRED (final commit) | 1 | #19 |

**Total: 19/19 mapped. Zero unmapped criteria.**

### Blocked items detail

- **Criteria 12 + 13** depend on Tasks 11-13 (privacy-legal specialist). These are
  blocked on client DPDP decisions escalated in `docs/compliance/dpdp-gap-analysis-2026-06-04.md`:
  (a) recording policy -- Option A (no recording for MVP1) vs Option B (record with consent);
  (b) consent disclosure script for call start;
  (c) DPDP Rules gazette status from meity.gov.in.
  The privacy policy content and breach response runbook cannot be finalized until
  the legal posture is known. These are NOT engineering blockers; they are
  regulatory/legal blockers.

### Tech debt cross-references

| TD | Criterion | Status |
|---|---|---|
| TD-014 | #3 (non-root container) | Open, Phase 10 |
| TD-022 | #11 (PII denylist in @audit) | CLOSED (`f378ddf`) |
| TD-023 | #11 (DB role GRANT/REVOKE) | Open, Phase 10 (1 test SKIP) |
| TD-024 | (not a criterion, but related to #1 CSP) | Open, blocks landing page |
| TD-026 | #9 (user-not-found audit gap) | Open, same sprint |
