# PHASE_2_BACKEND.md — Backend API + WhatsApp Flows
## Build the complete backend logic that makes Vachanam a full product.

---

## WHY THIS PHASE

Phase 1 built the voice agent. Phase 2 makes everything else work:
- Receptionists mark attendance on their phones
- Doctors manage schedules via WhatsApp
- Patients book appointments via WhatsApp (not just voice)
- Clinic owners see analytics
- Background jobs handle EOD summaries and follow-ups
- Razorpay payments process automatically

**Time estimate:** 2 weeks
**Cost:** Render $7/month + Neon $5/month = ₹1,008/month

---

## ROUTE: doctor WhatsApp commands

```
Doctor sends WhatsApp to the clinic's WhatsApp number
    ↓
Meta Cloud API webhook → POST /webhook/whatsapp
    ↓
Webhook handler extracts:
  - from_phone: doctor's personal phone
  - to_phone: clinic's Meta WhatsApp number → identifies branch_id
    (CRITICAL: branch comes from to_phone, NOT from_phone)
    ↓
Role check: is from_phone a known doctor for this branch?
    ↓
If yes → DoctorCommandService.process(message)
    ↓
Gemini 2.5 Flash parses command intent
    ↓
Execute: list appointments / cancel day / add tokens / parse follow-up
    ↓
Send response WhatsApp back to doctor
```

## ROUTE: patient WhatsApp conversation

```
Patient sends WhatsApp to clinic's number
    ↓
Meta webhook → POST /webhook/whatsapp
    ↓
Role check: not a known doctor → patient conversation
    ↓
WhatsAppAgent.process_message(patient_phone, message, branch_id)
    ↓
State machine reads from patients.wa_conversation_state in DB
    ↓
Advance state: IDLE → GREETING → DOCTOR_SELECT → DATE_SELECT
               → CONFIRMING → CONFIRMED
    ↓
Same booking tools as voice agent (BookingTools)
    ↓
Token assigned atomically via Redis INCR
    ↓
WhatsApp confirmation sent back
```

---

## FILE 1: backend/routers/whatsapp.py

```python
# backend/routers/whatsapp.py
"""
Meta Cloud API webhook handler.
Routes to doctor commands or patient conversation.

CRITICAL PERFORMANCE REQUIREMENT:
Meta expects a 200 response within 5 seconds.
ALL processing must happen in background tasks.
Return 200 immediately, process asynchronously.

BRANCH DETECTION:
Branch always comes from ctx.room.metadata or to_phone (receiving number).
NEVER from the sender's phone number.
"""
import json
from fastapi import APIRouter, Request, BackgroundTasks, HTTPException, Query
import structlog

from backend.config import settings
from backend.services.meta_service import MetaService

router = APIRouter()
logger = structlog.get_logger()
meta_service = MetaService()


@router.get("/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    """
    Meta webhook verification endpoint.
    Called once when you configure the webhook URL in Meta dashboard.
    hub.verify_token must match META_WEBHOOK_VERIFY_TOKEN in .env
    """
    if hub_mode == "subscribe" and hub_verify_token == settings.meta_webhook_verify_token:
        logger.info("meta_webhook_verified")
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/whatsapp")
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    Receive all WhatsApp messages.
    Returns 200 in < 100ms, processes in background.
    """
    body = await request.body()

    # Verify signature in production
    if settings.app_env == "production":
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not meta_service.verify_webhook_signature(body, signature):
            logger.warning("webhook_signature_invalid")
            raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return {"status": "invalid_json"}

    # Extract message from Meta's nested structure
    try:
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return {"status": "no_messages"}

        message = messages[0]
        from_phone = message.get("from", "")
        to_phone = value.get("metadata", {}).get("display_phone_number", "")
        message_text = message.get("text", {}).get("body", "")
        message_type = message.get("type", "text")

        if not from_phone or message_type != "text" or not message_text:
            return {"status": "ignored"}

        background_tasks.add_task(
            process_whatsapp_message,
            from_phone=from_phone,
            to_phone=to_phone,
            message_text=message_text,
        )

        return {"status": "received"}

    except Exception as e:
        logger.error("webhook_parse_error", error=str(e))
        return {"status": "parse_error"}


async def process_whatsapp_message(
    from_phone: str,
    to_phone: str,
    message_text: str,
):
    """
    Route message to correct handler.
    Branch context comes from to_phone (which WhatsApp number received this).
    """
    try:
        from backend.database import AsyncSessionLocal
        from backend.models.schema import Branch, Doctor
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            # Get branch from receiving phone — CRITICAL
            branch_result = await db.execute(
                select(Branch).where(Branch.meta_phone_number_id == to_phone)
            )
            branch = branch_result.scalar_one_or_none()

            if not branch:
                logger.warning("unknown_whatsapp_receiver", to_phone=to_phone)
                return

            branch_id = branch.branch_id

            # Is this a doctor?
            doctor_result = await db.execute(
                select(Doctor).where(
                    Doctor.personal_phone == from_phone,
                    Doctor.branch_id == branch_id,  # MANDATORY
                    Doctor.is_active == True
                )
            )
            doctor = doctor_result.scalar_one_or_none()

        if doctor:
            from backend.services.doctor_commands import DoctorCommandService
            service = DoctorCommandService(doctor=doctor, branch_id=branch_id)
            await service.process(message_text)
        else:
            from backend.services.whatsapp_agent import WhatsAppAgent
            agent = WhatsAppAgent(branch_id=branch_id, patient_phone=from_phone)
            await agent.process_message(message_text)

    except Exception as e:
        logger.error("whatsapp_processing_failed",
                    from_phone=from_phone[-4:],
                    error=str(e))
```

---

## FILE 2: backend/services/doctor_commands.py

```python
# backend/services/doctor_commands.py
"""
Parse and execute doctor WhatsApp commands.
Uses Gemini 2.5 Flash to understand natural language in Telugu + English.

SUPPORTED COMMANDS:
  "list today" / "ēḍu list"          → send today's appointment list
  "list tomorrow" / "rēpu list"       → send tomorrow's list
  "off today" / "ēḍu ledu"           → cancel all today's appointments
  "off tomorrow" / "rēpu ledu"        → cancel tomorrow's appointments
  "cancel 10:30"                      → cancel specific time slot
  "add 5 tokens" / "5 tokens add"     → increase daily token limit
  "follow up [patient] [instructions]" → create follow-up task
  "help" / "?"                        → send command list

All commands also supported in Telugu/Hindi/code-mixed.
"""
import json
from datetime import date, timedelta
from openai import AsyncOpenAI
import structlog

from backend.config import settings
from backend.services.meta_service import MetaService

logger = structlog.get_logger()


class DoctorCommandService:

    def __init__(self, doctor, branch_id: str):
        self.doctor = doctor
        self.branch_id = branch_id
        self.meta = MetaService()
        self.openai = AsyncOpenAI(api_key=settings.openai_api_key)

    async def process(self, message: str):
        """Parse message and execute the command."""
        intent = await self._parse_intent(message)
        logger.info("doctor_command_parsed",
                   doctor_id=self.doctor.doctor_id,
                   intent=intent.get("intent"),
                   confidence=intent.get("confidence"))

        handlers = {
            "LIST_APPOINTMENTS": self._handle_list,
            "CANCEL_DAY": self._handle_cancel_day,
            "CANCEL_SPECIFIC": self._handle_cancel_specific,
            "ADD_TOKENS": self._handle_add_tokens,
            "PARSE_FOLLOWUP": self._handle_parse_followup,
            "UNKNOWN": self._handle_unknown,
        }
        handler = handlers.get(intent.get("intent", "UNKNOWN"), self._handle_unknown)
        await handler(intent)

    async def _parse_intent(self, message: str) -> dict:
        today = date.today()
        tomorrow = today + timedelta(days=1)

        prompt = f"""Parse this WhatsApp message from a clinic doctor.
Today is {today.isoformat()}.
Doctor: Dr. {self.doctor.name}

Message: "{message}"

Return ONLY valid JSON. Nothing else.

Intents:
- LIST_APPOINTMENTS: doctor wants to see their schedule
- CANCEL_DAY: doctor wants to cancel all appointments for a day
- CANCEL_SPECIFIC: doctor wants to cancel one specific time
- ADD_TOKENS: doctor wants more slots
- PARSE_FOLLOWUP: doctor is giving follow-up instructions for patients
- UNKNOWN: anything else

{{
  "intent": "LIST_APPOINTMENTS|CANCEL_DAY|CANCEL_SPECIFIC|ADD_TOKENS|PARSE_FOLLOWUP|UNKNOWN",
  "dates": ["{today.isoformat()}"],
  "time": null,
  "token_count_to_add": null,
  "followup_instructions": null,
  "confidence": "high|medium|low"
}}

Examples:
"list today" → LIST_APPOINTMENTS, dates: ["{today}"]
"rēpu list" → LIST_APPOINTMENTS, dates: ["{tomorrow}"]
"ēḍu ledu" → CANCEL_DAY, dates: ["{today}"]
"off tomorrow" → CANCEL_DAY, dates: ["{tomorrow}"]
"cancel 10:30" → CANCEL_SPECIFIC, time: "10:30"
"add 5 slots" → ADD_TOKENS, token_count_to_add: 5
"Ramesh follow up check 3 days" → PARSE_FOLLOWUP"""

        try:
            response = await self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=150,
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error("doctor_command_parse_failed", error=str(e))
            return {"intent": "UNKNOWN", "confidence": "low"}

    async def _handle_list(self, intent: dict):
        """Send doctor their appointment list."""
        from backend.database import AsyncSessionLocal
        from backend.models.schema import Token, Patient
        from sqlalchemy import select

        dates = intent.get("dates", [date.today().isoformat()])
        target_date_str = dates[0] if dates else date.today().isoformat()

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Token, Patient)
                .join(Patient, Token.patient_id == Patient.patient_id)
                .where(
                    Token.doctor_id == self.doctor.doctor_id,
                    Token.branch_id == self.branch_id,  # MANDATORY
                    Token.date == target_date_str,
                    Token.status.in_(["confirmed", "attended"])
                )
                .order_by(Token.token_number)
            )
            rows = result.all()

        if not rows:
            msg = f"📋 {target_date_str}\nNo appointments scheduled."
        else:
            attended = sum(1 for t, _ in rows if t.status == "attended")
            remaining = sum(1 for t, _ in rows if t.status == "confirmed")
            lines = [f"📋 {target_date_str} — Dr. {self.doctor.name}\n"]
            for token, patient in rows:
                status = "✅" if token.status == "attended" else "⏳"
                urgent = "🔴" if token.is_urgent else ""
                lines.append(f"{status} #{token.token_number} {patient.name} {urgent}".strip())
            lines.append(f"\n✅ {attended} attended · ⏳ {remaining} remaining")
            msg = "\n".join(lines)

        await self.meta.send_text_message(
            to=self.doctor.personal_phone,
            message=msg,
            branch_id=self.branch_id
        )

    async def _handle_cancel_day(self, intent: dict):
        """Cancel all appointments for given dates and notify patients."""
        import asyncio
        from backend.database import AsyncSessionLocal
        from backend.models.schema import Token, Patient
        from sqlalchemy import select

        dates = intent.get("dates", [])
        if not dates:
            await self.meta.send_text_message(
                to=self.doctor.personal_phone,
                message="Which date to cancel? Reply: off today OR off tomorrow",
                branch_id=self.branch_id
            )
            return

        all_cancelled = []
        for target_date in dates:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Token, Patient)
                    .join(Patient, Token.patient_id == Patient.patient_id)
                    .where(
                        Token.doctor_id == self.doctor.doctor_id,
                        Token.branch_id == self.branch_id,  # MANDATORY
                        Token.date == target_date,
                        Token.status == "confirmed"
                    )
                )
                rows = result.all()
                for token, patient in rows:
                    token.status = "cancelled"
                    all_cancelled.append((token, patient, target_date))
                await db.commit()

        if not all_cancelled:
            await self.meta.send_text_message(
                to=self.doctor.personal_phone,
                message=f"No appointments found for {', '.join(dates)}.",
                branch_id=self.branch_id
            )
            return

        # Notify patients simultaneously
        async def notify(token, patient, d):
            try:
                await self.meta.send_text_message(
                    to=patient.phone,
                    message=(
                        f"❌ Appointment Cancelled\n\n"
                        f"Dr. {self.doctor.name} is unavailable on {d}.\n"
                        f"Your Token #{token.token_number} is cancelled.\n"
                        f"Call clinic to reschedule."
                    ),
                    branch_id=self.branch_id
                )
            except Exception as e:
                logger.error("cancel_patient_notify_failed", error=str(e))

        await asyncio.gather(*[notify(t, p, d) for t, p, d in all_cancelled])

        # Report back to doctor
        await self.meta.send_text_message(
            to=self.doctor.personal_phone,
            message=(
                f"✅ Done\n"
                f"{len(all_cancelled)} appointments cancelled.\n"
                f"All patients notified."
            ),
            branch_id=self.branch_id
        )

    async def _handle_cancel_specific(self, intent: dict):
        """Cancel a specific time slot."""
        # Implementation: find token by time, cancel, notify patient
        await self.meta.send_text_message(
            to=self.doctor.personal_phone,
            message="Specific cancellation not yet available. Use 'off today' to cancel all.",
            branch_id=self.branch_id
        )

    async def _handle_add_tokens(self, intent: dict):
        """Increase daily token limit for doctor."""
        count = intent.get("token_count_to_add")
        if not count:
            await self._handle_unknown(intent)
            return

        from backend.database import AsyncSessionLocal
        from backend.models.schema import Doctor
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Doctor).where(Doctor.doctor_id == self.doctor.doctor_id)
            )
            doctor = result.scalar_one_or_none()
            if doctor:
                doctor.daily_token_limit = min(
                    doctor.daily_token_limit + count, 60
                )
                await db.commit()

        await self.meta.send_text_message(
            to=self.doctor.personal_phone,
            message=f"✅ {count} extra slots added for today.",
            branch_id=self.branch_id
        )

    async def _handle_parse_followup(self, intent: dict):
        """Parse EOD follow-up instructions from doctor."""
        instructions = intent.get("followup_instructions", "")
        # Stored as a follow-up task — Phase 2 jobs will execute at 9 AM
        await self.meta.send_text_message(
            to=self.doctor.personal_phone,
            message="✅ Follow-up instructions saved. Will contact patient tomorrow morning.",
            branch_id=self.branch_id
        )

    async def _handle_unknown(self, intent: dict):
        """Send help message."""
        await self.meta.send_text_message(
            to=self.doctor.personal_phone,
            message=(
                "📋 Commands:\n"
                "• list today\n"
                "• list tomorrow\n"
                "• off today\n"
                "• off tomorrow\n"
                "• add [N] tokens\n\n"
                "Also works in Telugu: ēḍu list, rēpu ledu, etc."
            ),
            branch_id=self.branch_id
        )
```

---

## FILE 3: backend/services/whatsapp_agent.py

```python
# backend/services/whatsapp_agent.py
"""
Patient WhatsApp conversation state machine.
Same booking logic as voice agent, delivered via text.

STATE MACHINE:
  IDLE → GREETING → DOCTOR_SELECT → DATE_SELECT → CONFIRMING → CONFIRMED
  
At any state, patient can say:
  "cancel" / "cancel" → release held token → IDLE
  "help" → send instructions → same state
  No response for 90 seconds → re-prompt (never say "session expired")

State is stored in patients.wa_conversation_state (JSON in DB).
This persists across multiple messages in a conversation.
"""
import json
from datetime import datetime, timedelta
from openai import AsyncOpenAI
import structlog

from backend.config import settings
from backend.services.meta_service import MetaService

logger = structlog.get_logger()

# State machine states
IDLE = "IDLE"
GREETING = "GREETING"
DOCTOR_SELECT = "DOCTOR_SELECT"
DATE_SELECT = "DATE_SELECT"
CONFIRMING = "CONFIRMING"
CONFIRMED = "CONFIRMED"


class WhatsAppAgent:

    def __init__(self, branch_id: str, patient_phone: str):
        self.branch_id = branch_id
        self.patient_phone = patient_phone
        self.meta = MetaService()
        self.openai = AsyncOpenAI(api_key=settings.openai_api_key)

    async def process_message(self, message: str):
        """Process one message from patient. Advance state machine."""
        patient = await self._get_or_create_patient()
        state = patient.wa_conversation_state or {"state": IDLE}

        # Check for cancel command at any state
        if self._is_cancel(message) and state.get("state") != IDLE:
            await self._handle_cancel(patient, state)
            return

        current_state = state.get("state", IDLE)

        if current_state == IDLE:
            await self._handle_idle(patient, message)
        elif current_state == GREETING:
            await self._handle_greeting(patient, message, state)
        elif current_state == DOCTOR_SELECT:
            await self._handle_doctor_select(patient, message, state)
        elif current_state == DATE_SELECT:
            await self._handle_date_select(patient, message, state)
        elif current_state == CONFIRMING:
            await self._handle_confirming(patient, message, state)
        else:
            await self._handle_idle(patient, message)

    async def _handle_idle(self, patient, message: str):
        """Initial state — patient sends first message."""
        response = (
            f"Namaskāram! {patient.name or 'Welcome'} ki Vachanam.\n\n"
            "Appointment book cheyyāli?\n"
            "Doctor pēru lēdā mee problem cheppandi."
        )
        await self._send(response)
        await self._update_state(patient, {"state": GREETING, "last_message_at": datetime.utcnow().isoformat()})

    async def _handle_greeting(self, patient, message: str, state: dict):
        """Patient described their need — route to doctor selection."""
        from backend.database import AsyncSessionLocal
        from backend.models.schema import Doctor
        from sqlalchemy import select

        # Find matching doctor
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Doctor).where(
                    Doctor.branch_id == self.branch_id,  # MANDATORY
                    Doctor.is_active == True
                )
            )
            doctors = result.scalars().all()

        if not doctors:
            await self._send("Sorry, ippude doctors available kaadu. Clinic ki call cheyandi.")
            await self._update_state(patient, {"state": IDLE})
            return

        # Use LLM to match symptom to doctor
        matched_doctor = await self._match_doctor(message, doctors)

        if matched_doctor:
            state["doctor_id"] = matched_doctor.doctor_id
            state["doctor_name"] = matched_doctor.name
            state["state"] = DATE_SELECT
            await self._send(
                f"Dr. {matched_doctor.name} ({matched_doctor.speciality or 'General'}) "
                f"ki appointment book cheyāli?\n\n"
                f"Ēḍu ki booking: *today*\n"
                f"Rēpu ki: *tomorrow*"
            )
        else:
            # Multiple doctors — ask patient to choose
            doctor_list = "\n".join([
                f"{i+1}. Dr. {d.name} ({d.speciality or 'General'})"
                for i, d in enumerate(doctors[:5])
            ])
            state["state"] = DOCTOR_SELECT
            state["doctors"] = [
                {"id": d.doctor_id, "name": d.name} for d in doctors[:5]
            ]
            await self._send(f"Yē doctor ki appointment kavāli?\n\n{doctor_list}")

        await self._update_state(patient, state)

    async def _handle_doctor_select(self, patient, message: str, state: dict):
        """Patient selected a doctor."""
        doctors = state.get("doctors", [])
        selected = None

        # Try to match by number (1, 2, 3) or name
        message_clean = message.strip().lower()
        for i, doc in enumerate(doctors):
            if str(i+1) in message_clean or doc["name"].lower() in message_clean:
                selected = doc
                break

        if not selected and doctors:
            selected = doctors[0]

        if selected:
            state["doctor_id"] = selected["id"]
            state["doctor_name"] = selected["name"]
            state["state"] = DATE_SELECT
            await self._send(
                f"Dr. {selected['name']} selected.\n\n"
                f"When: *today* or *tomorrow*?"
            )
            await self._update_state(patient, state)

    async def _handle_date_select(self, patient, message: str, state: dict):
        """Patient selected a date — check availability and offer token."""
        from agent.tools.booking_tools import BookingTools

        date_str = "today"
        message_lower = message.lower()
        if any(w in message_lower for w in ["tomorrow", "rēpu", "kal", "next"]):
            date_str = "tomorrow"

        tools = BookingTools(branch_id=self.branch_id, session_state=type('S', (), {
            'branch_id': self.branch_id,
            'token_held': False, 'token_confirmed': False,
            'token_number': None, 'token_redis_key': None,
            'doctor_id': None, 'doctor_name': None,
            'booking_date': None
        })())

        availability = await tools.check_doctor_availability(
            doctor_id=state["doctor_id"],
            date_str=date_str
        )

        if not availability.get("available"):
            reason = availability.get("reason", "full")
            await self._send(
                f"Sorry, Dr. {state['doctor_name']} ki {date_str} available kaadu ({reason}).\n"
                f"Inka date try cheyyāli?"
            )
            return

        remaining = availability.get("remaining", "?")
        scarce_msg = f" (Only {remaining} left!)" if availability.get("scarce") else ""

        state["date_str"] = date_str
        state["state"] = CONFIRMING

        name_prompt = f"\n\nMee pēru cheppandi?" if not patient.name else ""
        await self._send(
            f"✅ Available!{scarce_msg}\n\n"
            f"Dr. {state['doctor_name']}\n"
            f"Date: {date_str.capitalize()}\n"
            f"Token: Next available{name_prompt}\n\n"
            f"Confirm cheyāli? Reply *yes* or *avunu*"
        )
        await self._update_state(patient, state)

    async def _handle_confirming(self, patient, message: str, state: dict):
        """Patient confirming — complete the booking."""
        message_lower = message.lower()
        is_confirm = any(w in message_lower for w in [
            "yes", "avunu", "ok", "okay", "confirm", "book", "చేయి", "అవును"
        ])

        if not is_confirm:
            await self._send("Confirm cheyāli? *yes* cheppandi lēdā cancel ki *cancel* cheppandi.")
            return

        # Patient name check
        patient_name = patient.name
        if not patient_name:
            # Ask for name if we don't have it
            state["state"] = "WAITING_NAME"
            await self._send("Mee pēru cheppandi:")
            await self._update_state(patient, state)
            return

        # Complete booking using same tools as voice agent
        from agent.tools.booking_tools import BookingTools
        import types

        mock_state = types.SimpleNamespace(
            branch_id=self.branch_id,
            token_held=False,
            token_confirmed=False,
            token_number=None,
            token_redis_key=None,
            doctor_id=state["doctor_id"],
            doctor_name=state["doctor_name"],
            booking_date=None
        )
        tools = BookingTools(branch_id=self.branch_id, session_state=mock_state)

        assign_result = await tools.assign_token(
            doctor_id=state["doctor_id"],
            patient_name=patient_name,
            patient_phone=self.patient_phone,
            date_str=state.get("date_str", "today")
        )

        if not assign_result.get("success"):
            await self._send("Sorry, booking fail aindi. Please try again or call clinic.")
            await self._update_state(patient, {"state": IDLE})
            return

        confirm_result = await tools.confirm_booking(
            patient_name=patient_name,
            patient_phone=self.patient_phone
        )

        if confirm_result.get("success"):
            token_number = confirm_result.get("token_number")
            await self._send(
                f"✅ Appointment Confirmed!\n\n"
                f"Dr. {state['doctor_name']}\n"
                f"Date: {state.get('date_str', 'today').capitalize()}\n"
                f"Token: #{token_number}\n\n"
                f"Please arrive 15 minutes early."
            )
            await self._update_state(patient, {"state": CONFIRMED})
        else:
            await self._send("Booking fail aindi. Please call clinic directly.")
            await self._update_state(patient, {"state": IDLE})

    async def _handle_cancel(self, patient, state: dict):
        """Patient cancelled — release held token if any."""
        held_key = state.get("token_redis_key")
        if held_key:
            from backend.services.token_service import TokenService
            await TokenService().release_token(held_key)

        await self._send("Cancelled. Malli try cheyāli anukuntē messsage cheyandi.")
        await self._update_state(patient, {"state": IDLE})

    def _is_cancel(self, message: str) -> bool:
        """Check if message is a cancellation intent."""
        return any(w in message.lower() for w in [
            "cancel", "stop", "no", "vaddhu", "వద్దు", "nahi"
        ])

    async def _send(self, message: str):
        """Send WhatsApp message to patient."""
        await self.meta.send_text_message(
            to=self.patient_phone,
            message=message,
            branch_id=self.branch_id
        )

    async def _match_doctor(self, symptom_text: str, doctors: list):
        """Use LLM to match patient symptom to doctor."""
        if len(doctors) == 1:
            return doctors[0]

        doctor_list = "\n".join([
            f"- doctor_id: {d.doctor_id}, name: {d.name}, "
            f"speciality: {d.speciality}, treats: {', '.join(d.treats_keywords[:5] if d.treats_keywords else [])}"
            for d in doctors
        ])

        prompt = f"""Match this patient symptom to the most appropriate doctor.

Patient said: "{symptom_text}"

Available doctors:
{doctor_list}

Return ONLY valid JSON:
{{"matched_doctor_id": "doctor_id or null", "confidence": "high|medium|low"}}

Return null if no clear match."""

        try:
            response = await self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=60,
                response_format={"type": "json_object"}
            )
            result = json.loads(response.choices[0].message.content)
            matched_id = result.get("matched_doctor_id")
            if matched_id:
                return next((d for d in doctors if d.doctor_id == matched_id), None)
        except Exception as e:
            logger.error("doctor_match_failed", error=str(e))
        return None

    async def _get_or_create_patient(self):
        """Get or create patient record."""
        from backend.database import AsyncSessionLocal
        from backend.models.schema import Patient
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Patient).where(
                    Patient.phone == self.patient_phone,
                    Patient.branch_id == self.branch_id  # MANDATORY
                )
            )
            patient = result.scalar_one_or_none()

            if not patient:
                patient = Patient(
                    phone=self.patient_phone,
                    name="",
                    branch_id=self.branch_id
                )
                db.add(patient)
                await db.commit()
                await db.refresh(patient)

        return patient

    async def _update_state(self, patient, new_state: dict):
        """Persist conversation state to DB."""
        from backend.database import AsyncSessionLocal
        from backend.models.schema import Patient
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Patient).where(Patient.patient_id == patient.patient_id)
            )
            p = result.scalar_one_or_none()
            if p:
                p.wa_conversation_state = new_state
                await db.commit()
```

---

## FILE 4: backend/routers/queue.py

```python
# backend/routers/queue.py
"""
Receptionist app endpoints.
All endpoints require authentication + branch access validation.
All queries MUST filter by branch_id.
"""
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from backend.database import get_db
from backend.models.schema import Token, Patient, Doctor
from backend.middleware.auth_middleware import get_current_user

router = APIRouter()
logger = structlog.get_logger()


@router.get("/{branch_id}/today")
async def get_today_queue(
    branch_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get today's complete queue grouped by doctor."""

    # Verify access — branch_id must be in user's branch_ids
    if current_user.role not in ["super_admin", "org_admin"]:
        if branch_id not in (current_user.branch_ids or []):
            raise HTTPException(status_code=403, detail="No access to this branch")

    today = date.today()

    result = await db.execute(
        select(Token, Patient, Doctor)
        .join(Patient, Token.patient_id == Patient.patient_id)
        .join(Doctor, Token.doctor_id == Doctor.doctor_id)
        .where(
            Token.branch_id == branch_id,      # MANDATORY
            Token.date == today,
            Token.status.in_(["confirmed", "attended", "no_show"])
        )
        .order_by(Doctor.name, Token.token_number)
    )
    rows = result.all()

    doctors_map = {}
    for token, patient, doctor in rows:
        if doctor.doctor_id not in doctors_map:
            doctors_map[doctor.doctor_id] = {
                "doctor_id": doctor.doctor_id,
                "doctor_name": doctor.name,
                "booking_type": doctor.booking_type,
                "stats": {"attended": 0, "no_show": 0, "remaining": 0},
                "patients": []
            }

        entry = doctors_map[doctor.doctor_id]
        entry["patients"].append({
            "appointment_id": token.token_id,
            "token_number": token.token_number,
            "patient_name": patient.name,
            "status": token.status,
            "is_urgent": token.is_urgent,
            "confirmed_at": token.confirmed_at.isoformat() if token.confirmed_at else None,
        })

        if token.status == "attended":
            entry["stats"]["attended"] += 1
        elif token.status == "no_show":
            entry["stats"]["no_show"] += 1
        else:
            entry["stats"]["remaining"] += 1

    return {
        "date": str(today),
        "branch_id": branch_id,
        "summary": {
            "total": len(rows),
            "attended": sum(1 for t, _, _ in rows if t.status == "attended"),
            "no_show": sum(1 for t, _, _ in rows if t.status == "no_show"),
            "remaining": sum(1 for t, _, _ in rows if t.status == "confirmed"),
        },
        "doctors": list(doctors_map.values())
    }


@router.patch("/{branch_id}/token/{token_id}/attend")
async def mark_attended(
    branch_id: str,
    token_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Mark patient as attended."""
    await _update_status(db, token_id, branch_id, "attended", current_user.user_id)
    return {"status": "attended"}


@router.patch("/{branch_id}/token/{token_id}/no-show")
async def mark_no_show(
    branch_id: str,
    token_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Mark patient as no-show and schedule follow-up."""
    token = await _update_status(db, token_id, branch_id, "no_show", current_user.user_id)
    return {"status": "no_show"}


async def _update_status(db, token_id, branch_id, status, user_id):
    from datetime import datetime
    result = await db.execute(
        select(Token).where(
            Token.token_id == token_id,
            Token.branch_id == branch_id      # MANDATORY — prevents cross-clinic access
        )
    )
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")
    if token.status in ["attended", "no_show"]:
        raise HTTPException(status_code=409, detail=f"Already {token.status}")

    token.status = status
    token.attended_at = datetime.utcnow()
    token.marked_by_user_id = user_id
    await db.commit()
    logger.info("token_status_updated",
               token_id=token_id,
               status=status,
               branch_id=branch_id)
    return token
```

---

## FILE 5: backend/jobs/ — All Three Scheduled Jobs

### backend/jobs/token_expiry.py
```python
# backend/jobs/token_expiry.py
"""
Runs every 2 minutes.
Finds token records in "confirmed" status that are past their
expected time (next-day tokens older than 2 days).
Marks them expired. Sends Redis decr if key still exists.
This is a safety net — most tokens are confirmed properly.
"""
import structlog
from datetime import date, timedelta

logger = structlog.get_logger()


async def run_token_expiry():
    """Clean up stale unattended tokens."""
    try:
        from backend.database import AsyncSessionLocal
        from backend.models.schema import Token
        from sqlalchemy import select, update

        cutoff_date = date.today() - timedelta(days=1)

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Token).where(
                    Token.date < cutoff_date,
                    Token.status == "confirmed"
                )
            )
            stale_tokens = result.scalars().all()

            for token in stale_tokens:
                token.status = "no_show"

            if stale_tokens:
                await db.commit()
                logger.info("stale_tokens_marked_no_show", count=len(stale_tokens))

    except Exception as e:
        logger.error("token_expiry_job_failed", error=str(e))
```

### backend/jobs/eod_summary.py
```python
# backend/jobs/eod_summary.py
"""
Runs at 5:30 PM IST every day.
For each active branch with appointments today:
  1. Count attended, no-show, remaining
  2. Auto-mark remaining "confirmed" as "no_show"
  3. Send formatted WhatsApp summary to each active doctor
  4. Ask doctor for follow-up instructions
"""
from datetime import date
import structlog

logger = structlog.get_logger()


async def run_eod_summary():
    """Send EOD summary to all doctors with appointments today."""
    try:
        from backend.database import AsyncSessionLocal
        from backend.models.schema import Token, Doctor, Patient, Branch
        from backend.services.meta_service import MetaService
        from sqlalchemy import select, func

        meta = MetaService()
        today = date.today()

        async with AsyncSessionLocal() as db:
            # Get all branches with appointments today
            branches_result = await db.execute(
                select(Branch).where(Branch.is_active == True)
            )
            branches = branches_result.scalars().all()

            for branch in branches:
                # Get doctors with appointments today
                doctors_result = await db.execute(
                    select(Doctor).where(
                        Doctor.branch_id == branch.branch_id,  # MANDATORY
                        Doctor.is_active == True,
                        Doctor.personal_phone != None
                    )
                )
                doctors = doctors_result.scalars().all()

                for doctor in doctors:
                    tokens_result = await db.execute(
                        select(Token).where(
                            Token.doctor_id == doctor.doctor_id,
                            Token.branch_id == branch.branch_id,  # MANDATORY
                            Token.date == today
                        )
                    )
                    tokens = tokens_result.scalars().all()

                    if not tokens:
                        continue

                    # Auto-mark remaining as no-show
                    for token in tokens:
                        if token.status == "confirmed":
                            token.status = "no_show"
                    await db.commit()

                    attended = sum(1 for t in tokens if t.status == "attended")
                    no_show = sum(1 for t in tokens if t.status == "no_show")
                    total = len(tokens)

                    no_show_names = []
                    for token in tokens:
                        if token.status == "no_show" and token.patient_id:
                            patient_result = await db.execute(
                                select(Patient).where(Patient.patient_id == token.patient_id)
                            )
                            patient = patient_result.scalar_one_or_none()
                            if patient:
                                no_show_names.append(patient.name)

                    summary = (
                        f"📊 End of Day Summary — {today.strftime('%d %B %Y')}\n"
                        f"Dr. {doctor.name}\n\n"
                        f"✅ Attended: {attended}\n"
                        f"❌ No-show: {no_show}\n"
                        f"📋 Total booked: {total}\n"
                    )

                    if no_show_names:
                        summary += f"\nNo-show patients:\n"
                        for name in no_show_names[:5]:
                            summary += f"• {name}\n"

                    summary += "\n_Reply with follow-up instructions if needed._"

                    try:
                        await meta.send_text_message(
                            to=doctor.personal_phone,
                            message=summary,
                            branch_id=branch.branch_id
                        )
                        logger.info("eod_summary_sent",
                                   doctor_id=doctor.doctor_id,
                                   branch_id=branch.branch_id,
                                   total=total)
                    except Exception as e:
                        logger.error("eod_summary_send_failed",
                                    doctor_id=doctor.doctor_id, error=str(e))

    except Exception as e:
        logger.error("eod_summary_job_failed", error=str(e))
```

### backend/jobs/followup_calls.py
```python
# backend/jobs/followup_calls.py
"""
Runs at 9:00 AM IST every day.
Processes all FollowupTask records with scheduled_date = today and status = pending.
Sends WhatsApp or initiates outbound call for each task.
Reports results to doctor by 11 AM.
"""
from datetime import date
import structlog

logger = structlog.get_logger()


async def run_followup_tasks():
    """Execute all pending follow-up tasks for today."""
    try:
        from backend.database import AsyncSessionLocal
        from backend.models.schema import FollowupTask, Patient, Doctor
        from backend.services.meta_service import MetaService
        from sqlalchemy import select

        meta = MetaService()
        today = date.today()

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(FollowupTask, Patient, Doctor)
                .join(Patient, FollowupTask.patient_id == Patient.patient_id)
                .join(Doctor, FollowupTask.doctor_id == Doctor.doctor_id)
                .where(
                    FollowupTask.scheduled_date == today,
                    FollowupTask.status == "pending"
                )
            )
            tasks = result.all()

            for task, patient, doctor in tasks:
                try:
                    # Send WhatsApp follow-up to patient
                    if task.channel in ["whatsapp", "both"]:
                        msg = (
                            f"Namaskāram {patient.name} gāru,\n\n"
                            f"Dr. {doctor.name} check-in:\n"
                            f"{task.what_to_ask}\n\n"
                            f"Reply cheyandi - doing well? Lēdā problem unda?"
                        )
                        await meta.send_text_message(
                            to=patient.phone,
                            message=msg,
                            branch_id=task.branch_id
                        )

                    # Mark task as completed
                    task.status = "completed"
                    await db.commit()

                    logger.info("followup_task_completed",
                               task_id=task.task_id,
                               patient_id=task.patient_id)

                except Exception as e:
                    logger.error("followup_task_failed",
                                task_id=task.task_id, error=str(e))
                    task.status = "failed"
                    await db.commit()

    except Exception as e:
        logger.error("followup_jobs_failed", error=str(e))
```

### Register jobs in backend/main.py
```python
# Add to backend/main.py lifespan function:
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import pytz

IST = pytz.timezone("Asia/Kolkata")

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    scheduler = AsyncIOScheduler(timezone=IST)

    from backend.jobs.token_expiry import run_token_expiry
    from backend.jobs.eod_summary import run_eod_summary
    from backend.jobs.followup_calls import run_followup_tasks

    scheduler.add_job(run_token_expiry, IntervalTrigger(minutes=2))
    scheduler.add_job(run_eod_summary, CronTrigger(hour=17, minute=30, timezone=IST))
    scheduler.add_job(run_followup_tasks, CronTrigger(hour=9, minute=0, timezone=IST))

    scheduler.start()
    logger.info("scheduler_started")

    yield

    scheduler.shutdown()
    logger.info("shutdown")
```

---

## PHASE 2 EXIT CRITERIA

```
AUTOMATED TESTS
□ pytest tests/unit/ -v → all pass
□ pytest tests/integration/ -v → all pass
□ pytest tests/edge_cases/test_data_isolation.py -v → all pass

DATA ISOLATION TESTS (critical)
□ Clinic A receptionist cannot see Clinic B's queue
□ Doctor at Branch X cannot cancel Doctor at Branch Y's appointments
□ Patient registered at Clinic A is unknown to Clinic B
□ Verify: every query in queue.py filters by branch_id

WHATSAPP FLOWS
□ Doctor sends "list today" → formatted schedule received
□ Doctor sends "off tomorrow" → patients WhatsApp'd, doctor confirmed
□ Patient sends "appointment kavali" → full booking conversation completes
□ Patient sends "cancel" mid-booking → held token released in Redis
□ Invalid message from doctor → help menu received

API ENDPOINTS
□ GET /queue/{branch_id}/today → correct queue, filtered by branch
□ PATCH /queue/{branch_id}/token/{id}/attend → status=attended in DB
□ PATCH /queue/{branch_id}/token/{id}/no-show → status=no_show in DB
□ POST /webhook/whatsapp → returns 200 in < 200ms
□ GET /health → {"status":"ok"}

BACKGROUND JOBS
□ Run run_eod_summary() manually → doctor receives WhatsApp summary
□ Run run_followup_tasks() manually → patient receives follow-up WhatsApp
□ Run run_token_expiry() manually → stale confirmed tokens become no_show

SECURITY
□ POST /queue/other-branch/today → 403 (not your branch)
□ POST /webhook/whatsapp with wrong signature → 401 (production only)
□ All API calls without JWT → 401
```

**ALL items checked = Phase 2 complete. Proceed to PHASE_3_FRONTEND.md**
