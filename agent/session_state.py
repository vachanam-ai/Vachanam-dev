from dataclasses import dataclass
from uuid import UUID


@dataclass
class SessionState:
    """Per-call state. One instance per LiveKit room. Never shared between calls."""

    # Branch and doctor resolved at call start
    branch_id: UUID | None = None
    doctor_id: UUID | None = None
    patient_name: str | None = None
    patient_phone: str | None = None
    complaint: str | None = None

    # Token / slot tracking
    token_held: bool = False
    token_confirmed: bool = False
    token_redis_key: str | None = None
    token_number: int | None = None
    appointment_time: str | None = None  # "HH:MM" for appointment-type

    # Consent and follow-ups
    followup_consent: bool = False

    # Call type and rebook context
    call_type: str = "inbound_booking"  # inbound_booking | followup | cancellation_notify
    is_rebook: bool = False
    cancelled_token_id: UUID | None = None

    # Solo plan 4-minute cap
    elapsed_seconds: int = 0
    plan: str | None = None  # solo | clinic | multi

    # Logging
    livekit_room_id: str | None = None
