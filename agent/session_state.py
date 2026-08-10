from dataclasses import dataclass, field
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
    # Per-CALL latch. token_confirmed is intentionally reset for every fresh
    # hold; this one remembers that at least one durable booking succeeded so a
    # later abandoned family booking cannot erase the earlier outcome.
    any_booking_confirmed: bool = False
    # Audit #9: which doctors got a CONFIRMED booking this call — the
    # follow-up teardown completes a next_visit_book task only when ITS
    # doctor is in here (a sibling's unrelated booking must not complete it).
    confirmed_doctor_ids: list = field(default_factory=list)
    # Audit #6: patient explicitly declined the follow-up visit → task
    # completes with a decline note instead of re-calling them.
    followup_declined: bool = False
    followup_decline_note: str = ""
    # Message safety net (2026-07-17 real call: agent PROMISED to inform the
    # doctor but never called take_message — message lost). Set on successful
    # take_message / log_clinic_question so teardown knows whether a spoken
    # delivery promise was actually backed by a recorded row.
    message_taken: bool = False
    question_logged: bool = False

    token_redis_key: str | None = None
    token_number: int | None = None
    # The latest finalized caller utterance is copied here before the LLM runs.
    # Mutation tools use it as a deterministic authorization boundary: an LLM
    # tool call alone is never proof that the caller asked to book/cancel.
    last_user_utterance: str | None = None
    # Which mutation the agent has just been told to ask the caller about:
    # "book" | "cancel" | "reschedule", else None.
    #
    # Set by the mutation guards themselves at the moment they raise the
    # "ask the caller first" ToolError, so a following "yes" is authorization
    # for THAT mutation. Replaces reading the phrasing back out of the
    # assistant's own transcript: those checks matched hardcoded strings
    # ('shall i book', 'रीशेड्यूल कर दूँ', ...) against text the LLM writes
    # freely in 7 languages, so any natural rephrasing — even दूँ vs दूं —
    # failed to match, the guard blocked again, and the agent re-asked the
    # same question forever (Vinay 2026-08-03: "switched to hindi and asked
    # to reschedule ... it is repeating n number of times", and booking
    # confirmations asked 3 times before a plain "yes" took).
    pending_confirmation: str | None = None
    # The caller has asked to book at some point in THIS call, and has not
    # withdrawn it. Consent for a booking, remembered.
    #
    # Vinay 2026-08-07: "we need shall i book once and only once before
    # booking." It was asked over and over because authorization was re-derived
    # from the LATEST utterance every time, so it evaporated the moment the
    # caller answered a question instead of repeating themselves:
    #
    #     "book an appointment tomorrow at 10"  -> authorized
    #     "your name and age?"
    #     "vinay, 28"                           -> no booking words: BLOCKED
    #                                           -> "shall I book?" -> loop
    #
    # They consented at turn one. A flag is how you remember that. Set on any
    # turn that asks to book, cleared by a flat refusal and after each booking
    # completes, so a second booking in the same call asks its own question.
    caller_asked_to_book: bool = False
    # The same memory for the other two mutations. Vinay 2026-08-07:
    # "reschedule call asking 2 times to confirm." confirm_booking got sticky
    # consent and these did not, so they kept the old shape: the caller says
    # "move it to 11", the model asks "shall I move it to 11?", and that
    # phrasing is not one of the five hardcoded strings
    # _last_assistant_requested_reschedule matches — so the first yes is
    # refused, the guard THEN arms pending_confirmation and orders a re-ask,
    # and the second yes works. Exactly two questions, every time.
    caller_asked_to_reschedule: bool = False
    caller_asked_to_cancel: bool = False
    # Which mutation the agent has STARTED and not yet finished: "book" |
    # "reschedule" | "cancel", else None. Set on entry to the tool, cleared the
    # moment the write succeeds and by a flat refusal.
    #
    # Vinay 2026-08-08: "call should never end before booking/rescheduling/
    # cancelling appointments. It should do the part else they can hang up."
    # The three caller_asked_to_* flags come from reading the caller's words,
    # and that reading is exactly what fails in Latin-script Telugu (#502) —
    # so a hangup guard resting only on them inherits the same blind spot. This
    # flag reads the AGENT's own behaviour instead: it does not care what
    # language anybody is speaking, only that a mutation was begun and never
    # finished. The two are kept together on purpose, one catching intent
    # stated before any tool ran, the other catching work already underway.
    mutation_in_flight: str | None = None
    # `time.monotonic()` of the last moment the CALLER started speaking. 0.0 =
    # they have not spoken yet.
    #
    # Vinay 2026-08-09, live call: he was asked "anything else?", answered, the
    # model called end_call, and while the goodbye was playing he asked about
    # the clinic's specialities. The question was transcribed and then dropped
    # ("skipping on_user_turn_completed, speech scheduling is paused") and the
    # line went down. end_call had already committed.
    #
    # This is the timestamp end_call compares against so it can ABORT a hangup
    # the caller talked over. It is set from the session's own VAD state change,
    # which keeps working after LiveKit stops scheduling new speech — the turn
    # pipeline is what pauses, not the audio.
    last_user_speech_at: float = 0.0
    # Exact durable booking created most recently in THIS call. If the caller
    # immediately says the booking was accidental, cancellation is pinned to
    # this id instead of trusting an older/arbitrary id selected by the LLM.
    last_confirmed_token_id: UUID | None = None
    appointment_time: str | None = None  # "HH:MM" for appointment-type
    # Exact stale-id recovery inside this call: old token id -> its current
    # replacement. Never guess by picking an arbitrary later appointment.
    booking_replacements: dict[str, str] = field(default_factory=dict)

    # Consent and follow-ups
    followup_consent: bool = False

    # A second Vachanam-style receptionist greeting on the caller channel means
    # two automated agents are talking. Keep answering clinic facts, but never
    # let that loop create/change/cancel appointments.
    peer_agent_detected: bool = False

    # Call type and rebook context
    call_type: str = "inbound_booking"  # inbound_booking | reminder | cascade_rebook
    is_rebook: bool = False
    cancelled_token_id: UUID | None = None
    followup_task_id: UUID | None = None  # cascade_rebook: mark completed on confirm
    # Inbound call answering a PENDING treatment follow-up: the greeting asked
    # the doctor's question, so the patient's reply must reach the doctor via
    # the teardown response_summary write-back (outbound calls carry task_id in
    # dispatch meta; inbound has no meta — this field is the inbound channel).
    followup_writeback_task_id: UUID | None = None

    # Solo plan 4-minute cap
    elapsed_seconds: int = 0
    plan: str | None = None  # solo | clinic | multi
    call_start: datetime | None = None  # set at entrypoint, used for cap enforcement
    solo_warning_sent: bool = False  # gate the 4-minute warning to fire only once

    # Logging
    session_id: str | None = None

    # Human intent used by call-quality analytics. Telephony ``call_type`` must
    # remain compatible with the legacy billing enum (for example
    # ``inbound_booking``), but a roster-only call is not a booking call. Keep
    # that distinction here instead of corrupting the billing classification.
    quality_intent: str | None = None
    # Deterministic fragment recovery varies the next prompt instead of
    # repeating the same "I couldn't hear" sentence in a loop.
    clarification_attempts: int = 0
    # A very short, cancellable grace period before replying to an obviously
    # incomplete fragment ("around—", "tomorrow—").  The shared state rather
    # than an Agent instance owns it so a language handoff can still cancel it
    # the instant VAD sees the caller continue.
    deferred_clarification_task: object | None = field(
        default=None, repr=False, compare=False
    )

    # Quality / feedback-loop signals (written to CallLog at call end).
    language: str | None = None          # clinic voice language code
    # Caller's mapped spoken language (Patient.preferred_language). Loaded at
    # call start; updated by the switch_language tool; confirm_booking persists
    # it on a patient row created later in the same call.
    preferred_language: str | None = None
    transfer_requested: bool = False     # set when request_human_transfer fires
    fail_reason: str | None = None       # set by tools on a known miss (out_of_scope, no_slot, ...)
    # Set when find_my_bookings runs — the caller is on the EXISTING-booking
    # (reschedule/cancel) track, not a NEW booking. Suppresses the #279 upfront
    # "you already have an appointment" surface in check_availability, which
    # otherwise flags the very booking being MOVED and dead-ends the reschedule
    # (FIXLOG #281, live call 2026-07-06).
    existing_booking_intent: bool = False

    # The verified incoming SIP number is the appointment authorization
    # boundary. Spoken-name matching is optional family-member disambiguation
    # and must never block lookup, cancellation, or rescheduling.
    identity_verified: bool = True

    # Set when the caller is booking for someone else (friend/family). Like the
    # flag above, it suppresses the caller's own ALREADY_BOOKED surface — a
    # friend's slot has nothing to do with the caller's own booking that day
    # (#296, live call 2026-07-08 13:46: agent told a friend-booker "YOU already
    # have an appointment" and refused).
    booking_for_other: bool = False

    # Durable metering: CallLog row inserted at call start (TD-027/F6) so a
    # killed worker that never runs the shutdown callback still leaves a record.
    call_log_id: UUID | None = None

    # WRAP-UP (prod 2026-07-27, Vinay: "at the end of call it is staying
    # end_of_turn"): the LLM finishes a terminal action (cancel/reschedule) and
    # says goodbye but does NOT call end_call, so the line sat open until the
    # 30s silence watchdog or the caller hung up — dead air after the call was
    # clearly done. Set True on a terminal confirm; the silence watchdog then
    # hangs up after a SHORT silence instead of the full 30s. Cleared the moment
    # the caller speaks again, so a caller who raises something new gets the full
    # window back (they are not done after all).
    closing: bool = False
