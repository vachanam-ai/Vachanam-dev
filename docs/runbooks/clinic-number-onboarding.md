# Clinic number onboarding — provision, verify, de-provision

**Owner:** Vinay · **Applies to:** every clinic, forever · **Last reviewed:** 2026-08-14

One process, unchanged from clinic 2 to clinic 2,000. Every step ends in a
check you can *see*, because each of the incidents below was caused by a step
that silently half-succeeded.

---

## The invariant this protects

**A dialled number resolves to exactly one clinic, or the call is refused.**
Never guessed, never defaulted. Three layers enforce it independently — do not
weaken any of them:

| Layer | Guarantee | Where |
|---|---|---|
| Postgres | `uq_branches_did_number` — unique partial index, one branch per DID | schema |
| Agent | `len(branches) != 1` → spoken notice, call ends (covers unknown **and** duplicate) | `agent.py` |
| Agent | fallback DID refused when more than one clinic exists | `agent.py` `did_fallback_refused` |
| Outbound | trunk must be branch-owned **and** carry that branch's DID | FIXLOG #518 |

If a change would make any of these "helpfully" pick a clinic instead of
refusing — stop. That is the cross-tenant leak, and DPDP makes it criminal.

---

## A. Buy the number (Vobiz)

1. **Buy a LOCAL DID for the clinic's own city.** Out-of-region numbers are
   test-only. Patients distrust an unfamiliar STD code.
2. **Run the pre-flight before promising a go-live date:**

   ```bash
   python scripts/check_vobiz_did_ready.py --did 91XXXXXXXXXX
   ```

   It hard-fails on the three upstream gates that are invisible from our
   dashboard and produce no useful error at call time — they cost hours on
   2026-06-06 ("you are not allowed to dial this number"):

   - account `is_verified` must be **true** (KYC)
   - DID `provider` must be **non-empty**
   - the number must not be **recycled** within 72h (it can still carry the
     previous owner's routing)

**Do not continue until this exits 0.** Every minute spent debugging LiveKit
while a Vobiz gate is closed is wasted.

---

## B. Create the clinic (app) — no number yet

3. Create the organisation + branch through the normal signup/admin flow.
   Set plan, timezone, language, doctors.
4. **Leave the DID empty for now.** A branch with no DID cannot receive calls
   and cannot collide with anything — a safe resting state.

---

## C. Wire inbound (receiving calls)

5. **Save the DID in Settings → clinic details.** Do NOT hand-edit LiveKit.

   Saving is what makes it safe. It:
   - normalises to E.164 (`normalize_did`) — a format difference otherwise
     fails branch resolution and kills *every* inbound call to that clinic
     (bug-bounty M11)
   - rejects a DID already owned by another branch — a shared DID means one
     clinic intercepts another's calls
   - calls `sync_did_to_inbound_trunk` and returns **`did_wired: true`**

6. **Check `did_wired: true` in the response.** If it is false or absent, the
   number is stored but not routed: the clinic hears nothing and you will
   debug the wrong layer.

7. Confirm the routing:

   ```bash
   python scripts/route_venkateshwara_tts_sandbox.py status
   ```

   Expect the new DID inside the **shared** inbound trunk, one dispatch rule,
   agent `vachanam-agent`.

> **Never use LiveKit `inbound_numbers` to route a DID.** It filters the
> CALLER (ANI), not the number dialled. It appears to work in testing and
> routes wrongly in production. One shared inbound trunk serves every clinic
> because the agent resolves the tenant from the dialled number (RULE 5). A
> separate inbound trunk is correct in exactly one case: that number must reach
> a *different agent* (e.g. the sandbox).

---

## D. Wire outbound (reminders and follow-ups)

8. **Create one outbound trunk for this clinic**, carrying only its DID:

   ```bash
   LIVEKIT_URL=... LIVEKIT_API_KEY=... LIVEKIT_API_SECRET=... \
   VOBIZ_SIP_DOMAIN=... VOBIZ_SIP_USERNAME=... VOBIZ_SIP_PASSWORD=... \
   DID_NUMBER=+9180XXXXXXXX \
   python -m scripts.create_vobiz_outbound_trunk
   ```

   It prints `ST_…`.

9. **Attach it to the branch:** `PATCH /branches/{branch_id}/telephony` with
   `{"outbound_trunk_id": "ST_…"}` (org_admin only; the SIP password is never
   returned by the API).

10. **Confirm `outbound_trunk_id` is non-NULL in the database.**

    NULL is not "not configured yet" — it is FIXLOG #518: both branches were
    NULL, both fell through to the platform trunk, and one clinic's reminder
    went out showing **another clinic's** caller ID. Outbound now fails closed
    on NULL, so the symptom is silence rather than a leak, but the clinic gets
    no reminders at all until this is set.

One trunk per clinic. A shared outbound trunk listing several DIDs would pass
the ownership check for every branch on it, which re-opens the ambiguity #518
closed.

---

## E. Prove it before handing over

Do all three. The third is the one people skip.

| # | Test | Pass |
|---|---|---|
| 1 | Call the DID | Agent answers with **this** clinic's greeting and doctors |
| 2 | Trigger a reminder | Caller ID shows **this** clinic's DID, not the platform's |
| 3 | Two simultaneous inbound calls | Both connect; neither gets a busy tone |

Test 1 proves branch resolution off the dialled number. Test 2 proves outbound
isolation. Test 3 matters when the clinic forwards from an existing landline —
a single POTS line forwards **one call at a time**, so concurrency is capped at
theirs no matter how many channels we provision. A busy tone on the second
caller is the exact missed-call problem we sell against.

---

## F. De-provisioning (removing a clinic or a number)

**Order matters.** Reverse of provisioning: stop the number first, delete the
record last. A DB row deleted while the DID is still on the inbound trunk
leaves a live number that fails closed with a "we couldn't identify the clinic"
notice — not a leak, but a bad answer to a real patient.

1. **Remove the DID from the shared inbound trunk** (the number stops ringing).
2. **Delete that clinic's outbound trunk** in LiveKit.
3. **Clear `did_number` and `outbound_trunk_id`** on the branch.
4. **Then** delete or deactivate the clinic.
5. Re-run `status` and confirm the DID appears nowhere.

If the number is being handed to a *different* clinic, also honour the 72h
recycle rule from step 2 before re-provisioning it.

---

## Scaling notes (why this process does not change)

- **Inbound stays one shared trunk** at any scale. The tenant comes from the
  dialled number, so N trunks would be N things to keep in sync for no gain.
- **Outbound stays one trunk per clinic** — that trunk *is* the caller
  identity boundary.
- **Channels are pooled, not per-clinic.** Trunking gain is large: ~426
  channels serve 1,000 clinics versus 3,000 if each had a dedicated pool.
- Past roughly 100 clinics, shard into **pools** (e.g. 10 carrier accounts of
  100 clinics) — about 24% more channels to cap blast radius at 10%. Never one
  account per clinic.
- Steps C and D must be **automated into onboarding** before ~20 clinics
  (TD-026). The process stays identical; only the hand that runs it changes.
