import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  addStaff,
  changePlan,
  createPaymentOrder,
  deleteAccount,
  fetchBranchSettings,
  fetchDoctors,
  fetchPlan,
  fetchStaff,
  removeStaff,
  getBranchFaq,
  getBranchVoices,
  saveBranchFaq,
  setBranchVoice,
  testCalendar,
  updateBranchSettings,
  verifyPayment
} from "../api/client.js";

const PLAN_LABELS = { lite: "Lite · ₹1,999/mo", solo: "Starter · ₹5,999/mo", clinic: "Clinic · ₹9,999/mo", multi: "Multi · ₹17,999/mo" };
const PLAN_PRICES = { lite: 1999, solo: 5999, clinic: 9999, multi: 17999 };

// Razorpay checkout script — loaded on demand, once.
function loadRazorpay() {
  return new Promise((resolve, reject) => {
    if (window.Razorpay) return resolve();
    const s = document.createElement("script");
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.onload = resolve;
    s.onerror = () => reject(new Error("Could not load the payment window — check your connection"));
    document.body.appendChild(s);
  });
}
import { useAuth } from "../hooks/useAuth.jsx";

const SA_EMAIL = "vachanam-events@vachanam-498912.iam.gserviceaccount.com";
// Runtime deployment flag: build with VITE_WHATSAPP_LIVE=true only after Meta
// onboarding is available. The backend independently enforces credentials and plan.
const WHATSAPP_LIVE = import.meta.env.VITE_WHATSAPP_LIVE === "true";

// Static fallback for the language dropdown — the set is fixed metadata
// (mirrors agent/i18n/languages.py). Used when the API response omits
// allowed_languages (e.g. an older/not-yet-restarted backend) so the picker
// never renders empty. The backend still validates the chosen code on PATCH.
const LANGUAGES = [
  { code: "te", name: "Telugu", native_name: "తెలుగు" },
  { code: "en", name: "English", native_name: "English" },
  { code: "hi", name: "Hindi", native_name: "हिन्दी" },
  { code: "ta", name: "Tamil", native_name: "தமிழ்" },
  { code: "kn", name: "Kannada", native_name: "ಕನ್ನಡ" },
  { code: "ml", name: "Malayalam", native_name: "മലയാളം" },
  { code: "mr", name: "Marathi", native_name: "मराठी" },
  { code: "bn", name: "Bengali", native_name: "বাংলা" }
];

/* Setup checklist derived from live data — the owner's map through onboarding. */
function checklist(data, calOk) {
  return [
    { id: "details", label: "Clinic details", done: Boolean(data?.emergency_contact && data?.clinic_phone) },
    { id: "doctors", label: "Add doctors", done: (data?.doctors_count ?? 0) > 0 },
    { id: "calendar", label: "Connect calendar", done: calOk === true },
    { id: "phone", label: "Phone number", done: Boolean(data?.did_number) },
    { id: "team", label: "Add reception", done: (data?.staff_count ?? 0) > 1 }
  ];
}

function Section({ id, title, sub, done, children }) {
  return (
    <section id={id} className="card scroll-mt-24 p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-lg font-semibold">{title}</h2>
          {sub && <p className="mt-0.5 font-ui text-sm text-slate">{sub}</p>}
        </div>
        {done !== undefined && (
          <span className={done ? "chip-token shrink-0" : "chip-muted shrink-0"}>
            {done ? "done" : "pending"}
          </span>
        )}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function InfoBox({ title, children }) {
  return (
    <div className="mt-4 rounded-xl border border-teal-pale bg-teal-mint/70 p-4 font-ui text-sm">
      {title && <p className="font-medium">{title}</p>}
      <div className="mt-1 space-y-1 text-ink-soft">{children}</div>
    </div>
  );
}

export default function Settings() {
  const { branchId, user, logout } = useAuth();
  const qc = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["branch-settings", branchId],
    queryFn: () => fetchBranchSettings(branchId),
    enabled: Boolean(branchId)
  });
  const { data: staff = [] } = useQuery({
    queryKey: ["staff", branchId],
    queryFn: () => fetchStaff(branchId),
    enabled: Boolean(branchId)
  });
  // Doctors, to offer as the "Which doctor" dropdown when creating a doctor
  // login. A doctor account links to an existing Doctor row — only those
  // without a login yet (user_id null) are selectable.
  const { data: doctors = [] } = useQuery({
    queryKey: ["doctors", branchId],
    queryFn: () => fetchDoctors(branchId),
    enabled: Boolean(branchId)
  });
  const unlinkedDoctors = doctors.filter((d) => !d.user_id);

  const [form, setForm] = useState(null);
  const [calOk, setCalOk] = useState(null);
  const [newStaff, setNewStaff] = useState({ name: "", email: "", password: "", role: "receptionist", doctor_id: "" });

  useEffect(() => {
    if (data && form === null) {
      setForm({
        name: data.name ?? "",
        address: data.address ?? "",
        city: data.city ?? "",
        clinic_phone: data.clinic_phone ?? "",
        emergency_contact: data.emergency_contact ?? "",
        google_calendar_id: data.google_calendar_id ?? "",
        did_number: data.did_number ?? ""
      });
    }
  }, [data, form]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const save = useMutation({
    mutationFn: (payload) => updateBranchSettings(branchId, payload),
    onSuccess: (d) => {
      qc.setQueryData(["branch-settings", branchId], d);
      if (d.did_wired === true) toast.success("Saved — number is wired and live");
      else if (d.did_wired === false)
        toast.warning("Saved. Number stored but telephony wiring pending — we've been notified.");
      else toast.success("Saved");
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Save failed")
  });

  const voice = useMutation({
    mutationFn: (v) => setBranchVoice(branchId, v),
    onSuccess: (d) => {
      qc.setQueryData(["branch-settings", branchId], d);
      toast.success(`Voice set to ${d.tts_voice}`);
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not change voice")
  });

  const language = useMutation({
    mutationFn: (lang) => setBranchVoice(branchId, null, lang),
    onSuccess: (d) => {
      qc.setQueryData(["branch-settings", branchId], d);
      const opt = (d.allowed_languages?.length ? d.allowed_languages : LANGUAGES).find(
        (l) => l.code === d.language
      );
      toast.success(`Language set to ${opt?.name ?? d.language}`);
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not change language")
  });

  // Plan & billing — current plan + any scheduled change. Refetches every
  // minute so cycle-end / days-left stay live without a reload (#353).
  const plan = useQuery({ queryKey: ["plan"], queryFn: fetchPlan, refetchInterval: 60_000 });
  const planChange = useMutation({
    mutationFn: (p) => changePlan(p),
    onSuccess: (d) => {
      qc.setQueryData(["plan"], d);
      if (d.pending_plan)
        toast.success(`Plan changes to ${d.pending_plan} on ${d.pending_plan_effective}`);
      else toast.success("Scheduled change cancelled");
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not change plan")
  });

  // Real payment: server-priced Razorpay order → checkout modal → server-side
  // signature verify → webhook is the authoritative activation (this refetch
  // just picks the new status up for the UI).
  const [paying, setPaying] = useState(false);
  const payNow = async () => {
    const planKey = plan.data?.plan ?? "clinic";
    setPaying(true);
    try {
      await loadRazorpay();
      const order = await createPaymentOrder(planKey);
      await new Promise((resolve, reject) => {
        const rzp = new window.Razorpay({
          key: order.key_id,
          order_id: order.order_id,
          amount: order.amount,
          currency: order.currency,
          name: "Vachanam",
          description: `${PLAN_LABELS[planKey]} subscription`,
          prefill: { email: user?.email ?? "" },
          theme: { color: "#0f766e" },
          modal: { ondismiss: () => reject(new Error("Payment window closed")) },
          handler: async (resp) => {
            try {
              await verifyPayment({
                razorpay_order_id: resp.razorpay_order_id,
                razorpay_payment_id: resp.razorpay_payment_id,
                razorpay_signature: resp.razorpay_signature
              });
              toast.success("Payment received — your plan is active. Welcome aboard!");
              plan.refetch();
              resolve();
            } catch (e) {
              reject(new Error(e?.response?.data?.detail ?? "Payment verification failed — if money was deducted it activates automatically in a minute"));
            }
          }
        });
        rzp.open();
      });
    } catch (e) {
      if (e?.message !== "Payment window closed") toast.error(e?.message ?? "Payment failed");
    } finally {
      setPaying(false);
    }
  };

  // Soniox voice catalog for the clinic's language (drives the picker).
  const voices = useQuery({
    queryKey: ["branch-voices", branchId, data?.language],
    queryFn: () => getBranchVoices(branchId, data?.language),
    enabled: !!branchId && !!data,
    staleTime: 5 * 60 * 1000
  });

  // Clinic FAQ the agent answers on calls. Pre-seed the editor with the
  // standard Indian-clinic template when the clinic hasn't saved one yet.
  const [faqRows, setFaqRows] = useState(null); // null until loaded
  const faqQuery = useQuery({
    queryKey: ["branch-faq", branchId],
    queryFn: () => getBranchFaq(branchId),
    enabled: Boolean(branchId)
  });
  useEffect(() => {
    if (faqQuery.data && faqRows === null) {
      setFaqRows(
        faqQuery.data.faq?.length ? faqQuery.data.faq : faqQuery.data.template
      );
    }
    // GET failed (network blip / redeploy): fall back to an empty editor so
    // Save is never silently stuck disabled forever (faqRows stayed null).
    if (faqQuery.isError && faqRows === null) setFaqRows([{ q: "", a: "" }]);
  }, [faqQuery.data, faqQuery.isError, faqRows]);
  const faqSave = useMutation({
    mutationFn: () => saveBranchFaq(branchId, faqRows ?? []),
    onSuccess: (d) => {
      qc.setQueryData(["branch-faq", branchId], d);
      toast.success("FAQ saved — the agent will answer these from the next call");
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not save the FAQ")
  });

  const calTest = useMutation({
    mutationFn: () => testCalendar(branchId),
    onSuccess: (r) => {
      setCalOk(r.ok);
      r.ok
        ? toast.success("Calendar connected — bookings will appear there")
        : toast.error(`Calendar test failed: ${r.detail ?? "no writer access yet"}`);
    },
    onError: (e) => {
      setCalOk(false);
      toast.error(e?.response?.data?.detail ?? "Calendar test failed");
    }
  });

  const invite = useMutation({
    mutationFn: () => addStaff(branchId, newStaff),
    onSuccess: (m) => {
      qc.invalidateQueries({ queryKey: ["staff", branchId] });
      qc.invalidateQueries({ queryKey: ["branch-settings", branchId] });
      setNewStaff({ name: "", email: "", password: "", role: "receptionist" });
      toast.success(`${m.role} account created — share the login with them`);
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not add member")
  });

  // Remove a staff login (owner only; doctor rows unlink, records stay).
  const fireStaff = useMutation({
    mutationFn: (userId) => removeStaff(branchId, userId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["staff", branchId] });
      toast.success("Login removed");
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not remove the login")
  });

  // DPDP erasure: delete the whole clinic, then sign out to the landing page.
  const [delConfirm, setDelConfirm] = useState("");
  const nukeClinic = useMutation({
    mutationFn: () => deleteAccount(
      delConfirm.trim().toUpperCase() === "DELETE"
        ? { confirm: "DELETE" }
        : { password: delConfirm }
    ),
    onSuccess: () => {
      toast.success("Clinic deleted — goodbye");
      logout();
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not delete the clinic")
  });

  if (error)
    return (
      <p className="font-ui text-danger">
        Settings failed to load — {error?.response?.data?.detail ?? "is the backend running?"}
      </p>
    );
  if (isLoading || form === null)
    return <p className="font-ui text-slate">Loading settings…</p>;

  const steps = checklist(data, calOk);
  const doneCount = steps.filter((s) => s.done).length;

  return (
    <div className="space-y-6">
      {/* Header + setup progress */}
      <div className="card p-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="eyebrow">Clinic setup</p>
            <h1 className="section-title text-2xl">{data?.name}</h1>
          </div>
          <p className="font-ui text-sm text-slate">
            <span className="numeral text-2xl text-teal-deep">{doneCount}</span>
            <span className="text-lg text-slate">/{steps.length}</span> steps complete
          </p>
        </div>
        <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-teal-pale">
          <div className="h-full rounded-full bg-teal transition-all duration-700"
            style={{ width: `${(doneCount / steps.length) * 100}%` }} />
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {steps.map((s, i) => (
            <a key={s.id} href={`#${s.id}`}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-ui text-xs font-medium transition ${
                s.done
                  ? "border-teal-pale bg-teal-mint text-teal-deep"
                  : "border-hairline bg-surface text-slate hover:border-teal-light/50"
              }`}>
              <span className={`grid h-4 w-4 place-items-center rounded-full text-[10px] ${s.done ? "bg-teal text-white" : "bg-slate-light/30"}`}>
                {s.done ? "✓" : i + 1}
              </span>
              {s.label}
            </a>
          ))}
        </div>
      </div>

      {/* Plan & billing — anniversary cycles: your 30 days start the day you pay. */}
      <Section id="plan" title="Plan & billing"
        sub="Your billing cycle starts the day you pay and runs 30 days. Plan switches take effect from your next cycle, so you never lose minutes you've already paid for.">
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <label className="label">Plan</label>
            <select className="field min-w-[220px]" value={plan.data?.plan ?? "clinic"}
              disabled={planChange.isPending}
              onChange={(e) => planChange.mutate(e.target.value)}>
              <option value="lite">{PLAN_LABELS.lite}</option>
              <option value="solo">{PLAN_LABELS.solo}</option>
              <option value="clinic">{PLAN_LABELS.clinic}</option>
              <option value="multi">{PLAN_LABELS.multi}</option>
            </select>
          </div>
          <span className={plan.data?.status === "active" ? "chip-token" : "chip-muted"}>
            {plan.data?.status ?? "—"}
          </span>
          {(() => {
            const p = plan.data;
            if (!p) return null;
            // Days left computed against NOW on every render; the 60s plan
            // refetch keeps this live. Backend enforces the same 3-day
            // window server-side, so the UI lock is honest, not decorative.
            const daysLeft = p.cycle_end
              ? Math.ceil((new Date(p.cycle_end) - Date.now()) / 86400000)
              : null;
            const payable =
              p.status !== "active" || !p.cycle_end || daysLeft <= 3;
            const fmt = (d) => new Date(d).toLocaleDateString("en-IN",
              { day: "numeric", month: "short", year: "numeric" });
            return (
              <>
                {p.last_payment_date && (
                  <span className="font-ui text-sm text-slate">
                    Last paid <strong className="text-ink">{fmt(p.last_payment_date)}</strong>
                  </span>
                )}
                {p.cycle_end && p.status === "active" && (
                  <span className="font-ui text-sm text-slate">
                    Renews <strong className="text-ink">{fmt(p.cycle_end)}</strong>
                    {daysLeft > 0 && (
                      <> · <strong className="text-ink">{daysLeft}</strong> day{daysLeft === 1 ? "" : "s"} left</>
                    )}
                  </span>
                )}
                {payable ? (
                  <button type="button" className="btn-primary" disabled={paying} onClick={payNow}>
                    {paying ? "Opening payment…"
                      : `${p.status !== "active" ? "Activate"
                          : p.cycle_end ? "Renew" : "Pay"} — ₹${(p.next_base_rupees || PLAN_PRICES[p.plan] || 0).toLocaleString("en-IN")}${p.is_offer ? " (offer)" : ""}${p.status === "active" && p.cycle_end ? " + usage" : ""}`}
                  </button>
                ) : (
                  <span className="chip-muted" title="Renewal opens 3 days before your cycle ends">
                    Paid — renewal opens {fmt(new Date(new Date(p.cycle_end) - 3 * 86400000))}
                  </span>
                )}
                {p.is_offer && (
                  <span className="font-ui text-xs font-semibold text-amber-800">
                    Offer price — first 3 months (regular ₹{(PLAN_PRICES[p.plan] ?? 0).toLocaleString("en-IN")}/mo)
                  </span>
                )}
              </>
            );
          })()}
        </div>
        {plan.data?.status === "active" && !plan.data.cycle_end && (
          <p className="mt-2 font-ui text-xs text-slate">
            Your line is active without a paid cycle. Paying starts your 30-day billing cycle today.
          </p>
        )}
        {plan.data && plan.data.status !== "active" && (
          <p className="mt-2 font-ui text-xs text-slate">
            UPI, card or netbanking via Razorpay. Your line activates the moment payment succeeds,
            and your 30-day cycle starts today.
          </p>
        )}
        {plan.data?.pending_plan && (
          <InfoBox title="Scheduled change">
            Switching to <strong>{plan.data.pending_plan}</strong> on{" "}
            <strong>{plan.data.pending_plan_effective}</strong>. Pick your current plan to cancel.
          </InfoBox>
        )}
        {/* #358: GSTIN field removed on Vinay's call ("complicates things") —
            the /api/billing/gstin endpoint stays for TD-038. */}
        <p className="mt-3 font-ui text-xs text-slate">
          A detailed receipt (PDF attached) is emailed to you after every successful payment.
        </p>
      </Section>

      {/* 1 — Clinic details */}
      <Section id="details" title="1 · Clinic details" done={steps[0].done}
        sub="What patients hear and where they find you.">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label">Clinic name (spoken by the AI)</label>
            <input className="field" value={form.name} onChange={set("name")} />
          </div>
          <div>
            <label className="label">City</label>
            <input className="field" value={form.city} onChange={set("city")} placeholder="City" />
          </div>
          <div className="sm:col-span-2">
            <label className="label">Address</label>
            <input className="field" value={form.address} onChange={set("address")}
              placeholder="Shop 4, Ayyappa Society, Madhapur" />
          </div>
          <div>
            <label className="label">Clinic's existing phone</label>
            <input className="field" value={form.clinic_phone} onChange={set("clinic_phone")}
              placeholder="+91 …" inputMode="tel" />
            <p className="mt-1 font-ui text-xs text-slate">
              The number patients already call — it will forward to your AI line.
            </p>
          </div>
          <div>
            <label className="label">Emergency contact</label>
            <input className="field" value={form.emergency_contact} onChange={set("emergency_contact")}
              placeholder="+91 …" inputMode="tel" />
            <p className="mt-1 font-ui text-xs text-slate">
              Given to patients who urgently ask for a human. Usually the owner's mobile.
            </p>
          </div>
        </div>
        <button className="btn-primary mt-4" disabled={save.isPending}
          onClick={() =>
            save.mutate({
              name: form.name, address: form.address, city: form.city,
              clinic_phone: form.clinic_phone, emergency_contact: form.emergency_contact
            })}>
          Save details
        </button>
      </Section>

      {/* 2 — Doctors */}
      <Section id="doctors" title="2 · Doctors" done={steps[1].done}
        sub={`${data?.doctors_count ?? 0} configured. The AI books patients against these profiles.`}>
        <InfoBox title="Two booking styles — pick per doctor:">
          <p><strong>Token queue</strong> — numbered line for high-volume OP (the AI announces "your token number is 8"). Set a daily limit.</p>
          <p><strong>Time slots</strong> — fixed appointment times. Set working hours, days, and slot length.</p>
        </InfoBox>
        <a href="/my-schedule" className="btn-primary mt-4 inline-flex">Manage doctors →</a>
      </Section>

      {/* 3 — Calendar */}
      <Section id="calendar" title="3 · Google Calendar" done={steps[2].done}
        sub="Every confirmed booking becomes an event the doctor can see on their phone.">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-72 flex-1">
            <label className="label">Calendar ID (usually the clinic Gmail)</label>
            <input className="field" value={form.google_calendar_id} onChange={set("google_calendar_id")}
              placeholder="yourclinic@gmail.com" />
          </div>
          <button className="btn-primary" disabled={save.isPending}
            onClick={() => save.mutate({ google_calendar_id: form.google_calendar_id })}>
            Save
          </button>
          <button className="btn-ghost" disabled={calTest.isPending || !data?.google_calendar_id}
            onClick={() => calTest.mutate()}>
            {calTest.isPending ? "Testing…" : "Test connection"}
          </button>
        </div>
        <InfoBox title="One-time share (2 minutes):">
          <p>1. Open Google Calendar → ⚙ Settings → <em>Settings for my calendars</em> → your calendar.</p>
          <p>2. <em>Share with specific people</em> → <em>Add people</em> → paste:</p>
          <code className="block select-all break-all rounded bg-surface px-2 py-1 text-xs">{SA_EMAIL}</code>
          <p>3. Permission: <strong>"Make changes to events"</strong> → Send → come back and press <em>Test connection</em>.</p>
        </InfoBox>
      </Section>

      {/* 4 — Phone number */}
      <Section id="phone" title="4 · Phone number (AI line)" done={steps[3].done}
        sub="The number your AI answers. Your existing clinic number forwards to it — patients notice nothing.">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-64">
            <label className="label">Your Vachanam number</label>
            <input className="field numeral" value={form.did_number} onChange={set("did_number")}
              placeholder="+91 80XXXXXXXX" inputMode="tel" />
          </div>
          <button className="btn-primary" disabled={save.isPending}
            onClick={() => save.mutate({ did_number: form.did_number })}>
            Save & activate
          </button>
        </div>
        <InfoBox title="How to get a number (choose one):">
          <p><strong>We provision it (recommended):</strong>{" "}
            <a className="text-teal underline underline-offset-2"
              href={`mailto:hello@vachanam.in?subject=Number%20request%20—%20${encodeURIComponent(data?.name ?? "clinic")}`}>
              request a number
            </a>{" "}
            — we buy a local number on our telephony partner and send it to you (1 business day).
          </p>
          <p><strong>You buy it:</strong> purchase a DID on Vobiz (console.vobiz.ai), point it at our SIP endpoint
            (we send exact settings), then paste the number above.</p>
          <p className="pt-1"><strong>After saving:</strong> we wire it to the voice system automatically — you'll
            see "number is wired and live". Then set call forwarding from your clinic phone to this number
            (*21*number# on most Indian carriers, or ask your operator for "unconditional call forwarding").</p>
        </InfoBox>
      </Section>

      {/* WhatsApp is exposed only by the deployment feature flag. */}
      {WHATSAPP_LIVE && (
      <Section id="whatsapp" title="WhatsApp"
        sub="Booking confirmations, reminders and post-visit rating asks on your clinic's own WhatsApp number.">
        {data?.whatsapp_linked ? (
          <p className="font-ui text-sm">
            <span className="chip bg-teal-mint text-teal">Linked</span>{" "}
            Your WhatsApp number is connected — patients get confirmations and
            can reply here.
          </p>
        ) : (
          <p className="font-ui text-sm text-slate">
            Not linked yet. We connect your clinic's WhatsApp number together
            with you (about 15 minutes, you keep using your WhatsApp app) —{" "}
            <a className="text-teal underline underline-offset-2"
              href={`mailto:hello@vachanam.in?subject=WhatsApp%20setup%20—%20${encodeURIComponent(data?.name ?? "clinic")}`}>
              request setup
            </a>.
          </p>
        )}
      </Section>
      )}

      {/* 5 — Language */}
      <Section id="language" title="Agent language"
        sub="The language the AI speaks and understands on calls. Applies from the next call.">
        <select
          className="field"
          value={data?.language ?? "te"}
          onChange={(e) => language.mutate(e.target.value)}
          disabled={language.isPending}
        >
          {(data?.allowed_languages?.length ? data.allowed_languages : LANGUAGES).map((l) => (
            <option key={l.code} value={l.code}>
              {l.native_name} ({l.name})
            </option>
          ))}
        </select>
        <p className="mt-2 font-ui text-xs text-slate">
          Each language has its own AI flow. Telugu is fully tuned; other languages are a first
          pass and being refined.
        </p>
      </Section>

      {/* 6 — Voice (cloning REMOVED 2026-07-24 — catalog voices only) */}
      <Section id="voice" title="Agent voice"
        sub="Pick the voice your AI agent speaks with. Applies from the next call.">
        <select
          className="field mt-1"
          value={data?.tts_voice ?? ""}
          onChange={(e) => voice.mutate(e.target.value)}
          disabled={voice.isPending || voices.isLoading}
        >
          <option value="">Default voice for this language</option>
          {(voices.data?.voices ?? []).map((v) => (
            <option key={v.voice_id} value={v.voice_id}>
              {v.display_name}
              {v.gender ? ` · ${v.gender}` : ""}
            </option>
          ))}
        </select>
        {voices.isError && (
          <p className="mt-2 font-ui text-xs text-danger">
            Couldn’t load voices — try again shortly.
          </p>
        )}
      </Section>

      {/* Clinic FAQ — the agent answers these on calls */}
      <Section id="faq" title="Clinic FAQ"
        sub="Answers your AI agent gives when callers ask about fees, timings, parking, insurance, reports and more. Leave a row blank to skip it.">
        <div className="space-y-3">
          {(faqRows ?? []).map((row, i) => (
            <div key={i} className="rounded-xl border border-hairline p-3">
              <div className="flex items-start justify-between gap-2">
                <input className="field flex-1 !py-1.5 text-sm font-medium"
                  value={row.q}
                  placeholder="Question callers ask…"
                  onChange={(e) => {
                    const next = [...faqRows];
                    next[i] = { ...next[i], q: e.target.value };
                    setFaqRows(next);
                  }} />
                <button type="button" className="btn-ghost shrink-0 px-2 py-1 text-xs"
                  onClick={() => setFaqRows(faqRows.filter((_, j) => j !== i))}>
                  Remove
                </button>
              </div>
              <textarea className="field mt-2 min-h-[60px] text-sm"
                value={row.a}
                placeholder="Your clinic's answer (spoken by the agent)…"
                onChange={(e) => {
                  const next = [...faqRows];
                  next[i] = { ...next[i], a: e.target.value };
                  setFaqRows(next);
                }} />
            </div>
          ))}
          <div className="flex flex-col gap-2 sm:flex-row">
            <button type="button" className="btn-ghost flex-1 min-h-[44px]"
              onClick={() => setFaqRows([...(faqRows ?? []), { q: "", a: "" }])}>
              + Add a question
            </button>
            <button type="button" className="btn-primary flex-1 min-h-[44px]"
              disabled={faqSave.isPending || faqRows === null}
              onClick={() => faqSave.mutate()}>
              {faqSave.isPending ? "Saving…" : "Save FAQ"}
            </button>
          </div>
          {(faqQuery.data?.asked?.length ?? 0) > 0 && (
            <div className="mt-4 border-t border-hairline pt-4">
              <p className="font-ui text-sm font-medium">Callers recently asked (not in your FAQ)</p>
              <p className="mt-0.5 font-ui text-xs text-slate">
                The agent told them the clinic will get back after checking with the doctor.
                Add an answer above so it's answered on the next call.
              </p>
              <ul className="mt-2 space-y-1">
                {faqQuery.data.asked.map((a, i) => (
                  <li key={i} className="flex items-center justify-between gap-2">
                    <span className="font-ui text-sm">{a.question}</span>
                    <button type="button" className="btn-ghost shrink-0 px-2 py-1 text-xs"
                      onClick={() =>
                        setFaqRows([...(faqRows ?? []), { q: a.question, a: "" }])
                      }>
                      + Add to FAQ
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </Section>

      {/* 6 — Team */}
      <Section id="team" title="5 · Team" done={steps[4].done}
        sub="Reception runs the queue and walk-ins on their phone. Doctors see their own day.">
        <div className="space-y-1">
          {staff.map((m) => (
            <div key={m.user_id} className="ledger-row !px-0">
              <div className="min-w-0 flex-1">
                <p className="truncate font-ui font-medium">{m.name ?? m.email}</p>
                <p className="truncate font-ui text-xs text-slate">{m.email}</p>
              </div>
              <span className="chip-token">{m.role}</span>
              {m.role !== "org_admin" && m.user_id !== user?.user_id && (
                <button type="button" className="ml-2 font-ui text-xs text-danger underline-offset-2 hover:underline"
                  disabled={fireStaff.isPending}
                  onClick={() => {
                    if (window.confirm(`Remove ${m.name ?? m.email}'s login? Their clinic records stay; only the login is deleted.`))
                      fireStaff.mutate(m.user_id);
                  }}>
                  Remove
                </button>
              )}
            </div>
          ))}
        </div>
        <form className="mt-5 grid gap-3 border-t border-hairline pt-5 sm:grid-cols-2"
          onSubmit={(e) => { e.preventDefault(); invite.mutate(); }}>
          <div>
            <label className="label">{newStaff.role === "doctor" ? "Which doctor" : "Name"}</label>
            {newStaff.role === "doctor" ? (
              <select className="field" required value={newStaff.doctor_id}
                onChange={(e) => {
                  const doc = doctors.find((d) => d.id === e.target.value);
                  setNewStaff((s) => ({ ...s, doctor_id: e.target.value, name: doc?.name ?? "" }));
                }}>
                <option value="">Select a doctor…</option>
                {unlinkedDoctors.map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
            ) : (
              <input className="field" required value={newStaff.name}
                onChange={(e) => setNewStaff((s) => ({ ...s, name: e.target.value }))} />
            )}
          </div>
          <div>
            <label className="label">Email (their login)</label>
            <input className="field" type="email" required value={newStaff.email}
              onChange={(e) => setNewStaff((s) => ({ ...s, email: e.target.value }))} />
          </div>
          <div>
            <label className="label">Temporary password (8+ chars)</label>
            <input className="field" required minLength={8} value={newStaff.password}
              onChange={(e) => setNewStaff((s) => ({ ...s, password: e.target.value }))} />
          </div>
          <div>
            <label className="label">Role</label>
            <select className="field" value={newStaff.role}
              onChange={(e) => setNewStaff((s) => ({ ...s, role: e.target.value, name: "", doctor_id: "" }))}>
              <option value="receptionist">Receptionist</option>
              <option value="doctor">Doctor</option>
            </select>
          </div>
          <button className="btn-primary sm:col-span-2" disabled={invite.isPending}>
            {invite.isPending ? "Creating…" : "Add team member"}
          </button>
        </form>
        {newStaff.role === "doctor" && unlinkedDoctors.length === 0 && (
          <p className="mt-2 font-ui text-sm text-slate">
            Every doctor already has a login. Add the doctor first under
            Settings → Doctors, then create their account here.
          </p>
        )}
        <InfoBox>
          <p>A doctor login is linked to an existing doctor — pick them from the list so their
            schedule, queue and treatments show only their own patients. Share the email + temporary
            password; they sign in here (or "Continue with Google" with the same email). Reception lands
            on the Queue, doctors on their schedule.</p>
        </InfoBox>
      </Section>

      {/* DPDP erasure (Vinay 2026-07-17): the fiduciary can close the account
          and erase everything — patients, bookings, notes, logins, billing. */}
      <Section id="danger" title="Delete clinic"
        sub="Permanently erase this clinic and ALL its data — patients, bookings, treatment notes, logins, billing. This cannot be undone.">
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="label">Your password (or type DELETE if you sign in with Google)</label>
            <input className="field" type="password" value={delConfirm}
              onChange={(e) => setDelConfirm(e.target.value)} placeholder="Password or DELETE" />
          </div>
          <div className="flex items-end">
            <button type="button"
              className="w-full rounded-xl border border-danger px-4 py-2 font-ui text-sm font-semibold text-danger transition hover:bg-danger hover:text-white disabled:opacity-50"
              disabled={nukeClinic.isPending || !delConfirm.trim()}
              onClick={() => {
                if (window.confirm("This erases the ENTIRE clinic — every patient, booking and login. Absolutely sure?"))
                  nukeClinic.mutate();
              }}>
              {nukeClinic.isPending ? "Deleting…" : "Delete clinic permanently"}
            </button>
          </div>
        </div>
      </Section>
    </div>
  );
}
