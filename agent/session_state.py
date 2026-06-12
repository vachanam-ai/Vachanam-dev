from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class SessionState:
    """Per-call state. One instance per voice session. Never shared between calls."""

    # Branch and doctor resolved at call start
    branch_id: UUID | None = None
    doctor_id: UUID | None = None
    patient_name: str | None = None
    patient_phone: str | None = None
    complaint: str | None = None

    # Cached branch context (set in on_enter to avoid repeated DB lookups)
    emergency_contact: str | None = None

    # Token / slot tracking
    token_held: bool = False
    token_confirmed: bool = False
    token_redis_key: str | None = None
    token_number: int | None = None
    appointment_time: str | None = None  # "HH:MM" for appointment-type

    # Consent and follow-ups
    followup_consent: bool = False

    # Call type and rebook context
    call_type: str = "inbound_booking"  # inbound_booking | reminder | cascade_rebook
    is_rebook: bool = False
    cancelled_token_id: UUID | None = None
    followup_task_id: UUID | None = None  # cascade_rebook: mark completed on confirm

    # Solo plan 4-minute cap
    elapsed_seconds: int = 0
    plan: str | None = None  # solo | clinic | multi
    call_start: datetime | None = None  # set at entrypoint, used for cap enforcement
    solo_warning_sent: bool = False  # gate the 4-minute warning to fire only once

    # Logging
    session_id: str | None = None
