# Vachanam Data Governance Charter

**Owner:** Vinay Rongala (Founder, Grievance Officer, Data Protection point of contact)
**Adopted:** 2026-07-11 · **Review cadence:** quarterly (see §8 calendar)

This charter is the single map of how Vachanam governs data: who is accountable, how data is classified, how it lives and dies, who may touch it, and on what schedule we verify all of that. Every control referenced here is either enforced in code (cited) or published in a public document (linked). Where something is aspiration, it is listed in §9 as a gap with a date — never silently blended with what exists.

---

## 1. Accountability

| Role | Held by | Duties |
|---|---|---|
| Data governance owner | Vinay Rongala | This charter, quarterly review, all §8 calendar items |
| Grievance Officer (DPDP §13) | Vinay Rongala | DSARs, complaints — 48h ack / 7d completion (runbook: docs/runbooks/dsar.md) |
| Data Fiduciary | Each clinic | Decides purpose; signs the DPA |
| Data Processor | Vachanam | Processes only per DPA; all controls below |

Structural rule: the platform super-admin role is **excluded from clinic PII routes in code** (backend/middleware/auth_middleware.py `forbid_admin`). Governance authority ≠ data access.

## 2. Data classification

| Class | Examples | Handling rules |
|---|---|---|
| **P1 — Patient PII** | name, phone, age/gender | Branch-scoped always; masked in logs (last-4); erased at 2y inactivity |
| **P2 — Health-adjacent** | complaint line, visit notes, follow-up Q&A, transcripts | Everything in P1 plus: never in notifications/calendar/logs; transcripts phone-masked + 90d; consent-gated calls |
| **P3 — Staff PII** | email, name, role | Deleted 30d after account removal |
| **O — Operational** | tokens, schedules, audit rows (IDs only) | Branch-scoped; audit append-only 7y |
| **BANNED** | call audio, medical records/diagnoses/prescriptions/labs, Aadhaar/PAN, patient payments | Never collected. A feature requiring them does not get built (CLAUDE.md product boundary). |

## 3. Lifecycle (enforced, not aspirational)

Collect minimum → use for booking/care purpose only → retain per table below → anonymise/delete by daily job (`backend/jobs/data_retention.py` — its actions are logged).

| Data | Retention | Mechanism |
|---|---|---|
| Patient identity (P1) | 2y after last activity | erased + `anonymized_at` stamped |
| Transcripts (P2) | 90d | text nulled |
| Visit notes + follow-up Q&A (P2) | with patient record | deleted / nulled |
| Consents | with patient record | pruned |
| Staff (P3) | removal + 30d | purged |
| Audit log (O) | 7y | deleted |
| Redis booking state | same day | TTL |

## 4. Access governance

- Role-based access, branch_id scoping on every read/write (RULE 1; cross-tenant attempts covered by automated tests on every change).
- JWT 8h hard expiry, revocation on logout (Redis-backed), rate-limited auth endpoints.
- Every significant action → append-only `audit_log` (IDs, never names).
- **Access recertification:** quarterly, the owner reviews `users` per clinic with the clinic owner (calendar §8).

## 5. Vendor (sub-processor) governance

- Canonical list with locations lives in the public privacy policy §6 and DPA §4.
- **Rule: policy updated BEFORE a new processor touches data** (followed for Soniox, 2026-07-10).
- Quarterly: re-verify each vendor's cert status (SOC 2 / ISO) and that the list matches reality (grep the codebase for new SDKs).
- Prefer India/near-India residency where a viable vendor exists; cross-border legality per DPDP §16 noted in the policy.

## 6. Consent governance

- `consents` table records type, method, `notice_version` per patient (RULE: notice text changes bump the version).
- Follow-up calls consent-gated at dispatch in code (FIXLOG #303) — withdrawal mechanically stops the phone ringing.
- Marketing consent (future): separate, never bundled — already promised in policy §4.

## 7. Incident & change governance

- Breach: docs/runbooks/breach-response.md — clinic notified ≤24h, Data Protection Board ≤72h; drill scheduled §8.
- DSAR: docs/runbooks/dsar.md — 48h ack / 7d completion.
- Change control: every data-touching change → FIXLOG row + regression test + full suite (docs/FIXLOG.md ritual); material policy changes → 30d notice per policy §12.

## 8. Compliance calendar

| When | What |
|---|---|
| Quarterly (Oct 2026, Jan/Apr/Jul 2027…) | Charter review · access recertification · vendor list re-verification · dependency audit |
| Twice yearly | Breach-response drill (tabletop; first: Oct 2026) |
| By 2027-Q1 | DPDP Rules readiness check: verifiable consent notice requirements (incl. multi-language notice obligations), Data Protection Board procedures |
| **2027-05-13** | DPDP Rules full-compliance deadline (notified 2025-11-14) |
| On SDF notification | Reassess Significant Data Fiduciary thresholds (currently far below) |

## 9. Known gaps (owned, dated — not hidden)

| Gap | Plan |
|---|---|
| No organisational ISO 27001 / SOC 2 for Vachanam itself | Roadmap post-revenue; until then pitch wording is "runs on certified infrastructure" only (docs/pitch/policy-benchmark-practo.md rules) |
| Access recertification is manual | Acceptable at current clinic count; automate (report of users per org emailed quarterly) when clinics > 20 |
| No formal DPIA | Not required at current scale/role; template to be adopted if SDF thresholds approach |
| Breach drill never yet run | First tabletop Oct 2026 (§8) |

---

*Related documents: [Privacy Policy](../legal/privacy-policy.md) · [DPA](../legal/data-processing-agreement.md) · [Data Handling](../legal/data-handling.md) · [DPDP gap analysis 2026-06-04](dpdp-gap-analysis-2026-06-04.md) · [Breach runbook](../runbooks/breach-response.md) · [DSAR runbook](../runbooks/dsar.md)*
