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

    # iter1 #11: count of "different_person" (family) bookings confirmed on THIS
    # call. Capped so a hijacked/looping LLM can't mass-book under one caller-ID.
    different_person_bookings: int = 0

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

    # Quality / feedback-loop signals (written to CallLog at call end).
    language: str | None = None          # clinic voice language code
    # Caller's mapped spoken language (Patient.preferred_language). Loaded at
    # call start; updated by the switch_language tool; confirm_booking persists
    # it on a patient row created later in the same call.
    preferred_language: str | None = None
    transfer_requested: bool = False     # set when request_human_transfer fires
    fail_reason: str | None = None       # set by tools on a known miss (out_of_scope, no_slot, ...)

    # Durable metering: CallLog row inserted at call start (TD-027/F6) so a
    # killed worker that never runs the shutdown callback still leaves a record.
    call_log_id: UUID | None = None
