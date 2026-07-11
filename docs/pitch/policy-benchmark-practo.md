# Privacy Documentation Benchmark — Vachanam vs Practo-class Platforms

*Internal reference for pitches, 2026-07-11. Practo entries are based on their public materials (privacy policy, security page, published certifications) — their site blocks automated retrieval, so verify specifics before quoting them in writing.*

## Why Practo is the benchmark

Practo is the privacy bar most Indian doctors know: ISO 27001-certified organisation, AWS-hosted, prominent "we don't sell your data" positioning, published grievance-officer process under the IT Act / DPDP regime. If our documents stand next to theirs credibly, the data-safety objection is answered.

## Document-structure comparison

| Element (Practo-class standard) | Practo | Vachanam | Where |
|---|---|---|---|
| Plain-language privacy policy, public URL | ✅ | ✅ | api.vachanam.in/privacy |
| At-a-glance summary table | ➖ (long legal prose) | ✅ | Policy header |
| Full processor/sub-processor list with locations | ➖ (categories, not names) | ✅ named, per-vendor, with links | Policy §6 |
| Dedicated security section | ✅ (separate security page) | ✅ | Policy §7 |
| Concrete retention table with periods | Partial | ✅ per-data-type, software-enforced | Policy §8 |
| Data-principal rights + named Grievance Officer | ✅ | ✅ (48h ack / 7-day completion) | Policy §9 |
| Children's data section | ✅ | ✅ | Policy §10 |
| Data Processing Agreement offered to clinics | Enterprise only | ✅ every clinic | api.vachanam.in/dpa |
| Plain-language data-lifecycle document | ➖ | ✅ | api.vachanam.in/data-handling |
| Doctor-facing pitch answering "is it safe?" | Sales deck | ✅ | api.vachanam.in/data-safety |

## Substance comparison (the honest part)

| Dimension | Practo | Vachanam | Pitch angle |
|---|---|---|---|
| Scope of data held | Full health profiles, consultations, orders, payments | Name + phone + complaint line + token | We never build the honeypot |
| Org certification | ISO 27001 | None yet (roadmap) — infra vendors are SOC 2 / ISO certified | Don't overclaim; lead with architecture, not badges |
| Call recordings | n/a for their core products | Never stored, by design | Strongest single line for doctors |
| Cross-clinic identity | Platform-wide patient accounts | Impossible by design | Their patients stay THEIR patients |
| Retention | Policy statements | Daily software job, periods public | "Enforced by code, not PDF" |
| DPDP roles | Fiduciary for consumer app | Processor; clinic stays Fiduciary | Doctor keeps legal ownership |

## Rules when pitching

1. Never claim ISO/SOC certification for Vachanam itself — say "runs entirely on SOC 2 / ISO-certified infrastructure."
2. Never disparage Practo — "different job, different data footprint" framing wins.
3. Every claim must trace to a public doc URL or code-enforced behaviour; if a doctor's IT person asks, we can show the mechanism.
