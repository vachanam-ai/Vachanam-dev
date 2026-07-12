"""DSAR CLI — Data Subject Access Request handler (TD-028, DPDP s.11-13).

The privacy policy commits to a 7-day SLA for access/correction/erasure/
consent-withdrawal. This tool makes each action a single repeatable command
instead of error-prone manual SQL (wrong branch_id under pressure = a
compliance incident).

Usage (run from repo root; uses DATABASE_URL from .env — PROD, be deliberate):
    python scripts/dsar.py --phone +919866... --branch <branch-uuid> --action export
    python scripts/dsar.py --phone ...        --branch <uuid> --action correct --name "New Name"
    python scripts/dsar.py --phone ...        --branch <uuid> --action delete
    python scripts/dsar.py --phone ...        --branch <uuid> --action withdraw

- export   → JSON to stdout: patient row, bookings, consent records,
             treatment notes, follow-up tasks. Redirect to a file to deliver.
- correct  → update the patient's stored name (--name required).
- delete   → full PII erasure via the SAME shared path the retention job and
             the Patients-page delete use (services/patient_erasure).
- withdraw → consent withdrawal: pending/in_progress follow-up tasks are
             completed so no further outbound calls happen; identity kept.
Every action writes an audit_log row (IDs only — RULE 9).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, ".")  # repo-root invocation


def _digits(phone: str) -> str:
    return "".join(c for c in phone if c.isdigit())[-10:]


async def _find_patients(db, branch_id: uuid.UUID, phone: str):
    from sqlalchemy import select

    from backend.models.schema import Patient

    last10 = _digits(phone)
    rows = (
        await db.execute(
            select(Patient).where(
                Patient.branch_id == branch_id,  # RULE 1: branch-scoped, always
                Patient.phone.like(f"%{last10}"),
            )
        )
    ).scalars().all()
    return rows


async def _export(db, branch_id: uuid.UUID, patients) -> dict:
    from sqlalchemy import select

    from backend.models.schema import Consent, FollowupTask, Token, TreatmentNote

    out: dict = {"generated_at": datetime.now(timezone.utc).isoformat(), "patients": []}
    for p in patients:
        tokens = (
            await db.execute(select(Token).where(Token.patient_id == p.id,
                                                 Token.branch_id == branch_id))
        ).scalars().all()
        notes = (
            await db.execute(select(TreatmentNote).where(
                TreatmentNote.patient_id == p.id, TreatmentNote.branch_id == branch_id))
        ).scalars().all()
        tasks = (
            await db.execute(select(FollowupTask).where(
                FollowupTask.patient_id == p.id, FollowupTask.branch_id == branch_id))
        ).scalars().all()
        consents = (
            await db.execute(select(Consent).where(
                Consent.branch_id == branch_id,
                Consent.patient_phone.like(f"%{_digits(p.phone or '')}")))
        ).scalars().all() if p.phone else []
        out["patients"].append({
            "patient": {"id": str(p.id), "name": p.name, "phone": p.phone,
                        "age": p.age, "gender": p.gender,
                        "created_at": p.created_at.isoformat() if p.created_at else None},
            "bookings": [{"token_number": t.token_number, "date": t.date.isoformat(),
                          "status": t.status,
                          "time": t.appointment_time.isoformat() if t.appointment_time else None}
                         for t in tokens],
            "treatment_notes": [{"visit_date": n.visit_date.isoformat() if n.visit_date else None,
                                 "steps_performed": n.steps_performed,
                                 "next_steps": n.next_steps} for n in notes],
            "followup_tasks": [{"status": t.status, "task_type": t.task_type,
                                "what_to_ask": t.what_to_ask,
                                "response_summary": t.response_summary} for t in tasks],
            "consent_records": [{"created_at": c.created_at.isoformat() if c.created_at else None,
                                 "notice_version": getattr(c, "notice_version", None)}
                                for c in consents],
        })
    return out


async def _audit(action: str, branch_id, patient_ids) -> None:
    from backend.services.audit_service import write_audit_row

    try:
        await write_audit_row(
            action=f"dsar.{action}", resource_type="patient",
            resource_id=",".join(str(i) for i in patient_ids)[:255] or "none",
            branch_id=branch_id, metadata={"tool": "scripts/dsar.py"}, success=True,
        )
    except Exception as e:  # noqa: BLE001 — audit best-effort for a CLI
        print(f"WARN: audit write failed: {e}", file=sys.stderr)


async def run(phone: str, branch: str, action: str, name: str | None = None) -> int:
    import backend.database as dbm

    branch_id = uuid.UUID(branch)
    async with dbm.AsyncSessionLocal() as db:
        patients = await _find_patients(db, branch_id, phone)
        if not patients:
            print("No patient found for that phone in that branch.", file=sys.stderr)
            return 1

        if action == "export":
            print(json.dumps(await _export(db, branch_id, patients),
                             ensure_ascii=False, indent=2))
        elif action == "correct":
            if not name:
                print("--name required for correct", file=sys.stderr)
                return 2
            for p in patients:
                p.name = name.strip()
            await db.commit()
            print(f"Corrected name on {len(patients)} record(s).")
        elif action == "delete":
            from backend.services.patient_erasure import erase_patient_pii

            for p in patients:
                await erase_patient_pii(db, p)
            await db.commit()
            print(f"Erased PII on {len(patients)} record(s) (shared erasure path).")
        elif action == "withdraw":
            from sqlalchemy import select

            from backend.models.schema import FollowupTask

            n = 0
            for p in patients:
                tasks = (
                    await db.execute(select(FollowupTask).where(
                        FollowupTask.patient_id == p.id,
                        FollowupTask.status.in_(["pending", "in_progress"])))
                ).scalars().all()
                for t in tasks:
                    t.status = "completed"
                    n += 1
            await db.commit()
            print(f"Consent withdrawn: {n} pending follow-up call(s) stopped. "
                  "Identity retained (use delete for erasure).")
        else:
            print(f"Unknown action {action}", file=sys.stderr)
            return 2

        await _audit(action, branch_id, [p.id for p in patients])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="DSAR handler (DPDP s.11-13)")
    ap.add_argument("--phone", required=True)
    ap.add_argument("--branch", required=True, help="branch UUID (RULE 1 scope)")
    ap.add_argument("--action", required=True,
                    choices=["export", "correct", "delete", "withdraw"])
    ap.add_argument("--name", help="new name (correct action)")
    a = ap.parse_args()
    return asyncio.run(run(a.phone, a.branch, a.action, a.name))


if __name__ == "__main__":
    raise SystemExit(main())
