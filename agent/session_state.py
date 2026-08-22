from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass
class SessionState:
    """Per-call state. One instance per voice session. Never shared between calls."""

    # Branch and doctor resolved at call start
    branch_id: UUID | None = None
    doctor_id: UUID | None = None
    # Latest doctor the CALLER named explicitly. This outranks a stale UUID the
    # model may carry from an earlier doctor in the same conversation. It is
    # cleared only when the caller gives a new complaint for deterministic
    # routing, never by an LLM-authored tool argument.
    caller_named_doctor_id: UUID | None = None
    patient_name: str | None = None
    # Exact name the caller introduced for the patient in this call. This is
    # independent of an LLM tool argument and prevents "Asha" becoming "Usha"
    # at the booking boundary.
    caller_patient_name: str | None = None
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
    # Exact failed booking request offered as a clinic message. It is armed
    # only after a verified booking/calendar non-result; a following caller
    # yes lets take_message persist this server-bound snapshot rather than a
    # model paraphrase. Cleared on use or refusal.
    pending_clinic_message: str | None = None
    # Most recent caller-authored clinic question/message candidate.  This is
    # deliberately separate from the model's tool argument: if the agent
    # restates the content and the caller answers "yes", the durable write can
    # still use the caller's exact words instead of accepting a model rewrite.
    relay_snapshot_text: str | None = None
    relay_snapshot_kind: str | None = None  # "question" | "message" | "content"

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
    # Exact deterministic mutation acknowledgement most recently derived from
    # a committed database result.  The final TTS firewall permits a success
    # claim only when the complete utterance equals this receipt; model-authored
    # paraphrases never inherit trust from a prior write.
    verified_mutation_speech: str | None = None
    verified_mutation_action: str | None = None
    # One-use receipts already spoken during this call. Retaining their compact
    # keys prevents an exact old acknowledgement from being replayed later.
    consumed_mutation_receipts: dict[str, str] = field(default_factory=dict)
    # Read-only booking lookup currently executing. Caller probes such as
    # "hello?" must not supersede and discard its eventual database answer.
    booking_lookup_in_flight: bool = False
    booking_lookup_utterance: str | None = None
    read_in_flight_count: int = 0
    read_owed_utterance: str | None = None
    # Set from the finalized caller turn before Gemini runs.  This closes the
    # tool-omission path: mutable appointment/availability/queue assertions are
    # held at TTS even when the model never calls the required read tool.
    # Clarification questions remain allowed until a read actually returns.
    mutable_read_intent: str | None = None
    mutable_read_utterance: str | None = None
    # A successful tool return still owes patient-facing speech. Keep this
    # armed until a safe TTS chunk leaves the final boundary; otherwise an
    # empty post-tool model response turns into "hello, are you there?".
    read_answer_owed: bool = False
    # Exact deterministic read speech (lookup/FAQ/schedule) may contain Latin
    # patient/doctor entities inside an Indic sentence. It is trusted only for
    # one exact TTS occurrence, then cleared.
    verified_read_speech: str | None = None
    consumed_read_receipts: set[str] = field(default_factory=set)
    # Stable server-result facts that a model-rendered read answer must contain
    # before it can settle the owed-answer latch.
    read_result_evidence: tuple[str, ...] = ()
    read_fallback_task: object | None = field(
        default=None, repr=False, compare=False
    )
    # A direct timeout/dependency failure already gave this caller turn its
    # terminal answer. Keep the final TTS boundary closed to any model output
    # that finishes late; the next committed caller turn clears this latch.
    read_terminal_failure_armed: bool = False
    read_terminal_failure_delivered: bool = False
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
    # Latest date/time selected by the caller for a new booking. A bare
    # one-to-eleven clock deliberately keeps both AM/PM candidates until the
    # exact spoken confirmation narrows it; model/tool arguments are never the
    # source of these receipts.
    caller_booking_times: tuple[str, ...] = ()
    caller_booking_date: str | None = None
    # Backward-compatible exact-time mirror used by older tests/call paths.
    # New mutation guards use ``caller_booking_times``.
    caller_booking_time: str | None = None
    # Rescheduling has a separate destination receipt so "move it to five"
    # cannot be rewritten by the model as six, and cannot overwrite a separate
    # in-progress new-family booking.
    caller_reschedule_times: tuple[str, ...] = ()
    caller_reschedule_date: str | None = None
    # Date/time identifying the existing appointment the caller referred to
    # (for example "cancel the five PM appointment").
    caller_existing_times: tuple[str, ...] = ()
    caller_existing_date: str | None = None
    # A booking request is not the final write authorization. This latch is
    # armed only after the receptionist audibly asks the one complete booking
    # confirmation question and the caller affirmatively answers it.
    booking_confirmation_granted: bool = False
    cancellation_confirmation_granted: bool = False
    # A guard demanding a question is not proof the caller heard one. These
    # server-built snapshots are armed only when the deterministic question is
    # queued to TTS, then spent by the immediately following affirmative turn.
    booking_confirmation_snapshot: dict[str, object] = field(
        default_factory=dict
    )
    cancellation_confirmation_snapshot: dict[str, str | None] = field(
        default_factory=dict
    )
    # Exact identity-scoped rows most recently returned by find_my_bookings.
    # Cancel/reschedule must choose from this ledger; a model-invented UUID is
    # never a mutation target.
    verified_booking_choices: dict[str, dict] = field(default_factory=dict)
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
    # An explicit request ("English please", "Hindi mein baat karo") locks the
    # call to that language. Soniox may transcribe borrowed words or a sentence
    # in another script; that is content, not permission to undo the choice.
    explicit_language_lock: str | None = None
    # Language switching is an infrastructure decision. Native scripts are
    # unambiguous in one turn; English needs two clear, complete turns so a few
    # borrowed words do not flip a Telugu/Hindi call. The streak is shared
    # across Agent handoffs because SessionState lives for the whole call.
    language_candidate: str | None = None
    language_candidate_turns: int = 0
    transfer_requested: bool = False     # set when request_human_transfer fires
    fail_reason: str | None = None       # set by tools on a known miss (out_of_scope, no_slot, ...)
    # Set when find_my_bookings runs — the caller is on the EXISTING-booking
    # (reschedule/cancel) track, not a NEW booking. Suppresses the #279 upfront
    # "you already have an appointment" surface in check_availability, which
    # otherwise flags the very booking being MOVED and dead-ends the reschedule
    # (FIXLOG #281, live call 2026-07-06).
    existing_booking_intent: bool = False

    # ANI can be spoofed. Inbound callers must also name a patient stored on
    # that branch+number before any booking is read or changed. Outbound calls
    # are verified because Vachanam dialled the stored number itself.
    identity_verified: bool = False
    # Exact patient rows authorized by the spoken-name check. A shared family
    # phone must never turn one matched name into access to every family member.
    verified_patient_ids: set[UUID] = field(default_factory=set)

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
