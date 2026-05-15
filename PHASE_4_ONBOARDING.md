# PHASE_4_ONBOARDING.md — Automated Clinic Onboarding
## Zero manual work from you. Clinic goes live in under 30 seconds.
## Read CLAUDE.md before starting. Phase 3 exit criteria must all be checked first.

---

## WHY AUTOMATION IS NON-NEGOTIABLE

Manual onboarding at scale:
- 10 clients × 2 hours/client = 20 hours of your time per month
- Error-prone: wrong DID, wrong webhook, wrong calendar
- You become the bottleneck — sales can't outpace setup
- Clients wait, get frustrated, may cancel

Automated onboarding:
- Razorpay fires webhook → clinic live in 30 seconds
- Zero errors: programmatic API calls, retried on failure
- Scales to 100 clients with same effort as 1
- You get a WhatsApp notification, nothing else needed

**This phase is what makes Vachanam a scalable SaaS business.**

---

## TIME ESTIMATE AND COST

**Time:** 1 week
**One-time setup cost:** ₹0
**Per clinic cost:** ₹1,000 Vobiz DID + ~₹500 Sarvam credits absorbed during trial

---

## WHAT HAPPENS IN 30 SECONDS

```
T+0s:   Clinic completes payment on vachanam.in (Razorpay)
        Razorpay fires webhook to POST /onboard/webhook/razorpay

T+1s:   Webhook handler verifies HMAC signature
        Extracts subscription_id from payload
        Returns HTTP 200 immediately
        Spawns background task: provision_new_clinic()

T+7s:   Vobiz Partner API → create_customer()
        Sub-account created for this clinic

T+9s:   Vobiz → fund_wallet(₹500)
        Clinic's Vobiz wallet funded (covers first few days of calls)

T+12s:  Vobiz → buy_number(country="IN")
        Indian DID number provisioned (e.g. +914012345678)
        Cost: ₹1,000/month (charged monthly to clinic's Vobiz wallet)

T+14s:  Vobiz → configure_inbound(webhook_url)
        When patient calls DID → Vobiz POSTs to our server
        URL: https://vachanam-backend.onrender.com/calls/inbound/{branch_id}

T+17s:  Google Calendar API → create calendar for each doctor
        Calendar name: "Dr. {name} — {clinic_name} Appointments"

T+20s:  Google Calendar API → share each calendar with doctor's Gmail
        Doctor can see all their appointments in Google Calendar

T+23s:  Neon DB → activate org and branch
        branch.vobiz_did = "+914012345678"
        branch.is_active = True
        org.is_active = True

T+26s:  Meta Cloud API → WhatsApp to clinic owner
        "You're live! Dial **21*+914012345678# to activate call forwarding."

T+27s:  Meta Cloud API → WhatsApp to ADMIN_PHONE (you)
        "New client: Clinic Name — Plan Clinic ₹7,999"

T+30s:  Clinic dials USSD code on existing phone
        Call forwarding activated — AI answering calls
```

---

## PRE-REQUISITES BEFORE WRITING CODE

```
□ Vobiz Partner API approved (email support@vobiz.ai)
  Required env vars: VOBIZ_PARTNER_AUTH_ID, VOBIZ_PARTNER_AUTH_TOKEN

□ Razorpay plans created in dashboard:
  Required env vars: RAZORPAY_PLAN_SOLO_ID, RAZORPAY_PLAN_CLINIC_ID, RAZORPAY_PLAN_MULTI_ID
  Plan 1: Name="Solo", Period=monthly, Interval=1, Amount=199900 paise
  Plan 2: Name="Clinic", Period=monthly, Interval=1, Amount=799900 paise
  Plan 3: Name="Multi", Period=monthly, Interval=1, Amount=1699900 paise

□ Google service account with Calendar API enabled
  Required file: google-service-account.json
  Required env var: GOOGLE_CALENDAR_SERVICE_EMAIL

□ Signup form built at vachanam.in/signup (collects clinic name, owner phone,
  doctor names + emails, owner email, selected plan)
  On form submit → create pending org + branch in DB → redirect to Razorpay
```

---

## DATABASE: Signup Flow Pre-Population

When clinic submits the signup form, create pending records BEFORE payment:

```python
# backend/routers/onboarding.py — signup endpoint
@router.post("/signup")
async def create_pending_clinic(
    clinic_name: str,
    owner_email: str,
    owner_phone: str,
    plan: str,                   # "solo" | "clinic" | "multi"
    doctors: list[dict],         # [{"name": "Dr. X", "email": "x@gmail.com"}]
    city: str = "Hyderabad",
    db: AsyncSession = Depends(get_db)
):
    """
    Create pending org, branch, and doctors in DB.
    Returns Razorpay subscription URL for payment.
    Called from vachanam.in/signup form submit.
    """
    plan_prices = {"solo": 199900, "clinic": 799900, "multi": 1699900}
    plan_ids = {
        "solo": settings.razorpay_plan_solo_id,
        "clinic": settings.razorpay_plan_clinic_id,
        "multi": settings.razorpay_plan_multi_id,
    }

    if plan not in plan_prices:
        raise HTTPException(400, "Invalid plan")

    import razorpay
    rz_client = razorpay.Client(
        auth=(settings.razorpay_key_id, settings.razorpay_key_secret)
    )

    # Create Razorpay subscription
    subscription = rz_client.subscription.create({
        "plan_id": plan_ids[plan],
        "total_count": 12,              # 12 months
        "quantity": 1,
        "customer_notify": 1,
    })

    from datetime import datetime, timedelta

    # Create pending org
    org = Organisation(
        name=clinic_name,
        owner_email=owner_email,
        owner_phone=owner_phone,
        plan=plan,
        plan_price_paise=plan_prices[plan],
        is_active=False,               # Activated after payment
        is_trial=True,
        trial_ends_at=datetime.utcnow() + timedelta(days=14),
        razorpay_subscription_id=subscription["id"]
    )
    db.add(org)
    await db.flush()

    # Create branch
    branch = Branch(
        org_id=org.org_id,
        name=clinic_name,
        city=city,
        is_active=False,
        primary_language="te-IN",
    )
    db.add(branch)
    await db.flush()

    # Create doctors
    max_doctors = {"solo": 1, "clinic": 3, "multi": 6}[plan]
    for i, doc_data in enumerate(doctors[:max_doctors]):
        doctor = Doctor(
            branch_id=branch.branch_id,
            name=doc_data.get("name", f"Doctor {i+1}"),
            email=doc_data.get("email"),
            personal_phone=doc_data.get("phone"),
            speciality=doc_data.get("speciality"),
            treats_keywords=doc_data.get("keywords", []),
            booking_type="token",
            daily_token_limit=30,
        )
        db.add(doctor)

    await db.commit()

    logger.info("pending_clinic_created",
               org_id=org.org_id,
               plan=plan,
               subscription_id=subscription["id"])

    return {
        "subscription_id": subscription["id"],
        "payment_url": f"https://rzp.io/l/{subscription['short_url']}",
        "message": "Redirect user to payment_url"
    }
```

---

## FILE 1: backend/services/calendar_service.py

```python
# backend/services/calendar_service.py
"""
Google Calendar API wrapper.
Service account acts on behalf of the clinic's doctors.

SETUP REQUIRED:
1. Create service account in Google Cloud Console
2. Enable Google Calendar API
3. Download JSON key → save as google-service-account.json
4. Service account email: vachanam-calendar@xxx.iam.gserviceaccount.com

HOW IT WORKS:
Service account creates calendars.
We share each calendar with the doctor's Gmail.
Doctor sees their appointments appear in their own Google Calendar.
Doctor does not need to log into Vachanam to see their schedule.
"""
import asyncio
from datetime import date, datetime, timedelta
from typing import Optional
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from tenacity import retry, stop_after_attempt, wait_exponential
import structlog

from backend.config import settings

logger = structlog.get_logger()

SCOPES = ['https://www.googleapis.com/auth/calendar']


def _get_calendar_service():
    """Get authenticated Google Calendar service."""
    creds = Credentials.from_service_account_file(
        settings.google_application_credentials,
        scopes=SCOPES
    )
    return build('calendar', 'v3', credentials=creds)


class CalendarService:

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def create_doctor_calendar(
        self,
        doctor_name: str,
        branch_name: str
    ) -> str:
        """
        Create a new Google Calendar for one doctor.
        Returns the calendar ID.

        Calendar is owned by the service account.
        Will be shared with the doctor's Gmail separately.
        """
        def _create():
            service = _get_calendar_service()
            calendar = service.calendars().insert(body={
                "summary": f"Dr. {doctor_name} — {branch_name}",
                "description": f"Appointment calendar for Dr. {doctor_name} at {branch_name}. Managed by Vachanam.",
                "timeZone": "Asia/Kolkata",
            }).execute()
            return calendar["id"]

        cal_id = await asyncio.get_event_loop().run_in_executor(None, _create)
        logger.info("calendar_created",
                   doctor_name=doctor_name,
                   calendar_id=cal_id)
        return cal_id

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def share_calendar(
        self,
        calendar_id: str,
        doctor_email: str,
        role: str = "writer"
    ) -> bool:
        """
        Share calendar with doctor's Gmail account.
        Role "writer" allows doctor to add notes but not delete appointments.
        Role "reader" is read-only.
        """
        def _share():
            service = _get_calendar_service()
            rule = {
                "scope": {"type": "user", "value": doctor_email},
                "role": role,
            }
            service.acl().insert(calendarId=calendar_id, body=rule).execute()
            return True

        await asyncio.get_event_loop().run_in_executor(None, _share)
        logger.info("calendar_shared",
                   calendar_id=calendar_id,
                   doctor_email=doctor_email)
        return True

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5))
    async def create_token_event(
        self,
        calendar_id: str,
        date: date,
        token_number: int,
        patient_name: str,
        patient_phone_last4: str,
        duration_minutes: int = 15
    ) -> Optional[str]:
        """
        Create appointment event in doctor's calendar.
        Returns event ID for future reference (cancellation).

        Event title format: "#8 — Ravi Kumar (****1234)"
        This is minimal — no health information in calendar.
        """
        def _create():
            service = _get_calendar_service()
            # Default: 9 AM + (token_number - 1) * duration_minutes
            # This spaces out tokens across the morning
            start_hour = 9
            start_minute = (token_number - 1) * duration_minutes % 60
            start_hour += ((token_number - 1) * duration_minutes) // 60

            start_dt = datetime(
                date.year, date.month, date.day,
                min(start_hour, 18), start_minute
            )
            end_dt = start_dt + timedelta(minutes=duration_minutes)

            event = {
                "summary": f"#{token_number} — {patient_name} (****{patient_phone_last4})",
                "start": {
                    "dateTime": start_dt.isoformat(),
                    "timeZone": "Asia/Kolkata"
                },
                "end": {
                    "dateTime": end_dt.isoformat(),
                    "timeZone": "Asia/Kolkata"
                },
                "reminders": {"useDefault": False},
            }
            result = service.events().insert(
                calendarId=calendar_id,
                body=event
            ).execute()
            return result["id"]

        try:
            event_id = await asyncio.get_event_loop().run_in_executor(None, _create)
            logger.info("calendar_event_created",
                       calendar_id=calendar_id,
                       token_number=token_number,
                       event_id=event_id)
            return event_id
        except Exception as e:
            logger.error("calendar_event_failed", error=str(e))
            return None  # Calendar failure is not fatal

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5))
    async def delete_event(self, calendar_id: str, event_id: str) -> bool:
        """Cancel appointment — delete calendar event."""
        def _delete():
            service = _get_calendar_service()
            service.events().delete(
                calendarId=calendar_id,
                eventId=event_id
            ).execute()
            return True

        try:
            await asyncio.get_event_loop().run_in_executor(None, _delete)
            logger.info("calendar_event_deleted",
                       calendar_id=calendar_id,
                       event_id=event_id)
            return True
        except HttpError as e:
            if e.resp.status == 404:
                logger.warning("calendar_event_not_found", event_id=event_id)
                return True  # Already deleted — success
            logger.error("calendar_delete_failed", error=str(e))
            return False

    async def get_available_slots(
        self,
        doctor_id: str,
        branch_id: str,
        booking_date: date,
        doctor
    ) -> list[str]:
        """
        Get available time slots for slot-based doctors.
        Checks existing calendar events and returns open slots.
        Used by check_doctor_availability tool for slot bookings.
        """
        if not doctor.calendar_id:
            return []

        def _get_busy():
            service = _get_calendar_service()
            start = datetime(
                booking_date.year, booking_date.month, booking_date.day,
                int(doctor.hours_start.split(':')[0]),
                int(doctor.hours_start.split(':')[1])
            )
            end = datetime(
                booking_date.year, booking_date.month, booking_date.day,
                int(doctor.hours_end.split(':')[0]),
                int(doctor.hours_end.split(':')[1])
            )
            body = {
                "timeMin": start.isoformat() + "+05:30",
                "timeMax": end.isoformat() + "+05:30",
                "items": [{"id": doctor.calendar_id}]
            }
            result = service.freebusy().query(body=body).execute()
            busy = result.get("calendars", {}).get(doctor.calendar_id, {}).get("busy", [])
            return busy

        try:
            busy_slots = await asyncio.get_event_loop().run_in_executor(None, _get_busy)
            # Calculate available slots
            all_slots = []
            start_h, start_m = map(int, doctor.hours_start.split(':'))
            end_h, end_m = map(int, doctor.hours_end.split(':'))
            current = datetime(booking_date.year, booking_date.month, booking_date.day,
                              start_h, start_m)
            end = datetime(booking_date.year, booking_date.month, booking_date.day,
                          end_h, end_m)

            while current < end:
                slot_end = current + timedelta(minutes=doctor.slot_duration_mins)
                slot_str = current.strftime("%I:%M %p")

                # Check if this slot overlaps with any busy period
                is_busy = any(
                    current.isoformat() + "+05:30" < b["end"] and
                    slot_end.isoformat() + "+05:30" > b["start"]
                    for b in busy_slots
                )
                if not is_busy:
                    all_slots.append(slot_str)
                current = slot_end

            return all_slots[:5]  # Return next 5 available

        except Exception as e:
            logger.error("get_slots_failed", error=str(e))
            return []
```

---

## FILE 2: backend/services/vobiz_partner.py

(Already in PHASE_3_TO_5.md — copy it here for standalone reference)

Full implementation in the combined file. Key methods:
- `create_customer(name, email)` → returns auth_id, auth_token
- `fund_wallet(customer_auth_id, amount=500)` → bool
- `buy_number(customer_auth_id, country="IN")` → phone number string
- `configure_inbound(customer_auth_id, number, branch_id)` → bool
- `get_wallet_balance(customer_auth_id)` → int (rupees)

---

## FILE 3: backend/services/onboarding_service.py

Full implementation in PHASE_3_TO_5.md.

Key function: `provision_new_clinic(subscription_id, plan_id)`

Error handling principle:
- Any step fails → log error + alert you via WhatsApp + raise
- You then do that step manually for the affected clinic
- All other clinics unaffected

---

## FILE 4: backend/jobs/wallet_monitor.py

```python
# backend/jobs/wallet_monitor.py
"""
Runs every hour.
Checks Vobiz wallet balance for each active clinic.
Alerts you if balance drops below ₹200 (less than ~5 hours of calls).
The clinic's Razorpay subscription auto-renews DID monthly.
But outbound call minutes deplete the wallet separately.
"""
from datetime import datetime
import structlog

logger = structlog.get_logger()

LOW_BALANCE_THRESHOLD_RUPEES = 200


async def run_wallet_monitor():
    """Check all active clinic Vobiz wallet balances."""
    try:
        from backend.database import AsyncSessionLocal
        from backend.models.schema import Branch, Organisation
        from backend.services.vobiz_partner import VobizPartnerService
        from backend.services.meta_service import MetaService
        from backend.config import settings
        from sqlalchemy import select

        vobiz = VobizPartnerService()
        meta = MetaService()

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Branch, Organisation)
                .join(Organisation, Branch.org_id == Organisation.org_id)
                .where(
                    Branch.is_active == True,
                    Branch.vobiz_auth_id != None
                )
            )
            rows = result.all()

        low_balance_clinics = []
        for branch, org in rows:
            try:
                balance = await vobiz.get_wallet_balance(branch.vobiz_auth_id)
                if balance < LOW_BALANCE_THRESHOLD_RUPEES:
                    low_balance_clinics.append({
                        "name": org.name,
                        "balance": balance,
                        "phone": org.owner_phone
                    })
                    logger.warning("low_vobiz_balance",
                                  org=org.name,
                                  balance=balance)
            except Exception as e:
                logger.error("wallet_check_failed",
                           org=org.name, error=str(e))

        if low_balance_clinics:
            alert_msg = "⚠️ Low Vobiz Balance Alert:\n\n"
            for c in low_balance_clinics:
                alert_msg += f"• {c['name']}: ₹{c['balance']} remaining\n"
            alert_msg += "\nAction: Top up via Vobiz Partner dashboard"

            await meta.send_text_message(
                to=settings.admin_phone,
                message=alert_msg,
                branch_id=None
            )

    except Exception as e:
        logger.error("wallet_monitor_failed", error=str(e))
```

Register in main.py scheduler:
```python
from backend.jobs.wallet_monitor import run_wallet_monitor
scheduler.add_job(run_wallet_monitor, IntervalTrigger(hours=1))
```

---

## RAZORPAY: Subscription Plans Setup

```python
# One-time setup script: scripts/create_razorpay_plans.py
# Run this ONCE to create plans. Copy the plan IDs to .env.

import razorpay
import os

client = razorpay.Client(auth=(
    os.environ["RAZORPAY_KEY_ID"],
    os.environ["RAZORPAY_KEY_SECRET"]
))

plans = [
    {
        "period": "monthly",
        "interval": 1,
        "item": {
            "name": "Vachanam Solo",
            "amount": 199900,       # ₹1,999 in paise
            "currency": "INR",
            "description": "1 doctor, pay-per-minute voice AI"
        }
    },
    {
        "period": "monthly",
        "interval": 1,
        "item": {
            "name": "Vachanam Clinic",
            "amount": 799900,       # ₹7,999 in paise
            "currency": "INR",
            "description": "3 doctors, 2100 min/month included"
        }
    },
    {
        "period": "monthly",
        "interval": 1,
        "item": {
            "name": "Vachanam Multi",
            "amount": 1699900,      # ₹16,999 in paise
            "currency": "INR",
            "description": "6 doctors, 4200 min/month included"
        }
    },
]

for plan_data in plans:
    plan = client.plan.create(plan_data)
    print(f"{plan_data['item']['name']}: {plan['id']}")
    print(f"  → Add to .env: RAZORPAY_PLAN_XXX_ID={plan['id']}")
```

Run:
```bash
python scripts/create_razorpay_plans.py
# Copy output plan IDs to .env
```

---

## TESTING THE COMPLETE ONBOARDING FLOW

```python
# tests/integration/test_onboarding.py
"""
Test the complete automated onboarding flow.
Requires: valid Vobiz Partner credentials, real Google service account.
Mark as @pytest.mark.integration — not run in CI by default.
"""
import pytest
import json
import hmac
import hashlib


@pytest.mark.asyncio
@pytest.mark.integration
async def test_full_provisioning_flow():
    """
    End-to-end provisioning test.
    Creates a real clinic in all systems and verifies.
    Clean up after test.
    """
    from backend.services.onboarding_service import provision_new_clinic
    from backend.database import AsyncSessionLocal
    from backend.models.schema import Organisation, Branch, Doctor
    from sqlalchemy import select

    TEST_SUBSCRIPTION_ID = "test_sub_" + str(int(time.time()))

    # Pre-create pending org
    async with AsyncSessionLocal() as db:
        org = Organisation(
            name="Test Clinic Automated",
            owner_email="test@testclinic.com",
            owner_phone="+919999999999",
            plan="clinic",
            plan_price_paise=799900,
            is_active=False,
            razorpay_subscription_id=TEST_SUBSCRIPTION_ID
        )
        db.add(org)
        await db.flush()

        branch = Branch(
            org_id=org.org_id,
            name="Test Clinic Automated",
            is_active=False
        )
        db.add(branch)
        await db.flush()

        doctor = Doctor(
            branch_id=branch.branch_id,
            name="Dr. Test",
            email="doctor@testclinic.com",
            is_active=True
        )
        db.add(doctor)
        await db.commit()

    # Run provisioning
    import time
    start = time.time()
    await provision_new_clinic(TEST_SUBSCRIPTION_ID, "plan_clinic")
    duration = time.time() - start

    # Verify timing (< 35 seconds)
    assert duration < 35, f"Provisioning took {duration:.1f}s — too slow"

    # Verify DB state
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Branch).where(
                Branch.org_id == org.org_id
            )
        )
        updated_branch = result.scalar_one()
        assert updated_branch.is_active is True, "Branch not activated"
        assert updated_branch.vobiz_did is not None, "DID not provisioned"
        assert updated_branch.vobiz_auth_id is not None, "Vobiz auth_id missing"
        assert updated_branch.calendar_ids, "Calendars not created"

    print(f"✅ Full provisioning completed in {duration:.1f}s")

    # CLEANUP — remove test data (don't leave test clinics in production)
    # Vobiz: delete sub-account via Partner API
    # Google: delete calendar via Calendar API
    # DB: delete test org
```

---

## PHASE 4 EXIT CRITERIA

```
SETUP VERIFICATION
□ VOBIZ_PARTNER_AUTH_ID and VOBIZ_PARTNER_AUTH_TOKEN set in .env
□ Razorpay plans created, IDs set in .env
□ Google service account file exists and has Calendar API access
□ Razorpay webhook URL configured in Razorpay dashboard:
  URL: https://vachanam-backend.onrender.com/onboard/webhook/razorpay
  Events: subscription.activated, subscription.halted, subscription.cancelled

AUTOMATED ONBOARDING TEST
□ Run: python scripts/create_razorpay_plans.py → plan IDs printed
□ POST /onboard/webhook/razorpay with test subscription.activated payload
  → Provisioning completes in < 35 seconds
  → Vobiz sub-account appears in Partner dashboard
  → DID number provisioned (verify in Vobiz Partner portal)
  → Inbound webhook configured (call the DID → agent answers)
  → Google Calendar created (visible at calendar.google.com with service account)
  → Doctor's Gmail received calendar share invitation
  → Branch.is_active = True in DB
  → Branch.vobiz_did = "+91XXXXXXXXXX" in DB
  → Clinic owner WhatsApp received with correct USSD code
  → Your ADMIN_PHONE received "New client!" WhatsApp

USSD TEST (manual)
□ Dial **21*+91{DID}# on test phone
□ Call the test phone from another phone
□ AI answers in Telugu within 2 rings
□ Complete test booking end-to-end

PAYMENT FAILURE TEST
□ POST /onboard/webhook/razorpay with subscription.halted payload
  → org.is_active = False in DB
  → Clinic owner receives suspension WhatsApp

WALLET MONITORING
□ run_wallet_monitor() with mock balance < ₹200
  → Your phone receives low balance alert
□ run_wallet_monitor() with mock balance > ₹200
  → No alert (no false positives)

EDGE CASES
□ Vobiz create_customer() fails on first call → retries 3 times
□ Vobiz buy_number() returns no Indian DID available → alert sent to you
□ Google Calendar API quota exceeded → provisioning logs error + alerts you
□ duplicate subscription.activated webhook → second run is idempotent
  (branch already has vobiz_did → skip Vobiz step, log and return)
```

**ALL items checked = Phase 4 complete. Proceed to PHASE_5_PRODUCTION.md**
