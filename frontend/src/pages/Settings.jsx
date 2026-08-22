import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight, BookOpenText, Buildings, CalendarCheck, Check, CheckCircle,
  GearSix, MapPin, PhoneCall, ShieldWarning, Sparkle, Stethoscope,
  UsersThree, WhatsappLogo,
} from "@phosphor-icons/react";
import { toast } from "sonner";
import {
  addStaff,
  clearToken,
  deleteAccount,
  fetchBranchSettings,
  fetchDoctors,
  fetchPlan,
  fetchStaff,
  removeStaff,
  getBranchFaq,
  saveBranchFaq,
  testCalendar,
  updateBranchSettings
} from "../api/client.js";


// WA MVP1 Task 8: read-only connection status chip (Branch.wa_status, mm36).
// Linking is concierge-only (super_admin runs scripts/wa_link_branch.py) —
// no Connect button here yet, that ships with Task 9's Embedded Signup.
const WA_STATUS_LABEL = {
  none: { label: "Not connected", chip: "chip-muted" },
  connected: { label: "Connected", chip: "chip-token" },
  disconnected: { label: "Disconnected", chip: "chip-danger" },
  error: { label: "Connection error", chip: "chip-danger" }
};

import WaConnectCard from "../components/WaConnectCard.jsx";
import { useActionDialog } from "../components/ActionDialog.jsx";
import { useAuth } from "../hooks/useAuth.jsx";

const SA_EMAIL = "vachanam-events@vachanam-498912.iam.gserviceaccount.com";
// Runtime deployment flag: build with VITE_WHATSAPP_LIVE=true only after Meta
// onboarding is available. The backend independently enforces credentials and plan.
const WHATSAPP_LIVE = import.meta.env.VITE_WHATSAPP_LIVE === "true";

const prefersReducedMotion = () => !window.matchMedia || window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const SETUP_ICONS = {
  details: Buildings,
  doctors: Stethoscope,
  calendar: CalendarCheck,
  phone: PhoneCall,
  team: UsersThree,
};

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

function Section({ id, title, sub, done, tone, icon: Icon = GearSix, children }) {
  return (
    <section id={id}
      className={`settings-section settings-section-${id} scroll-mt-24 ${tone === "cream" ? "is-muted" : ""} ${tone === "danger" ? "is-danger" : ""}`}>
      <div className="settings-section-head">
        <span className="settings-section-icon" aria-hidden><Icon size={21} weight="duotone" /></span>
        <div>
          <h2>{title}</h2>
          {sub && <p>{sub}</p>}
        </div>
        {done !== undefined && (
          <span className={`settings-state ${done ? "is-done" : ""}`}>
            {done && <Check size={12} weight="bold" />}{done ? "Ready" : "Set up"}
          </span>
        )}
      </div>
      <div className="settings-section-body">{children}</div>
    </section>
  );
}

function InfoBox({ title, children }) {
  return (
    <div className="settings-info-box">
      {title && <p className="font-medium">{title}</p>}
      <div className="mt-1 space-y-1 text-ink-soft">{children}</div>
    </div>
  );
}

function ClinicCompanion({ message, progress, signal }) {
  const root = useRef(null);

  useEffect(() => {
    const doctor = root.current?.querySelector(".companion-doctor");
    if (!doctor || prefersReducedMotion()) return undefined;
    let frame;
    const onMove = (event) => {
      const nx = (event.clientX / window.innerWidth - .5) * 2;
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        doctor.style.transform = `translateX(${nx * 3}px) rotate(${nx * 2.2}deg)`;
      });
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("pointermove", onMove);
    };
  }, []);

  useEffect(() => {
    if (!signal || prefersReducedMotion()) return;
    root.current?.querySelector(".companion-doctor")?.animate?.(
      [{ scale: .96 }, { scale: 1 }],
      { duration: 280, easing: "cubic-bezier(.22,1,.36,1)" },
    );
    root.current?.querySelector(".companion-message")?.animate?.(
      [{ opacity: .55, transform: "translateY(4px)" }, { opacity: 1, transform: "none" }],
      { duration: 220, easing: "cubic-bezier(.22,1,.36,1)" },
    );
  }, [signal]);

  return (
    <div ref={root} className="clinic-companion" aria-live="polite">
      <div className="companion-message">
        <span><Sparkle size={13} weight="fill" /> Vaani</span>
        <p>{message}</p>
      </div>
      <img className={`companion-doctor ${progress === 100 ? "is-complete" : ""}`}
        src="/settings-doctor.png" alt="" aria-hidden />
    </div>
  );
}

export default function Settings() {
  const { branchId, user, logout } = useAuth();
  const ask = useActionDialog();
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
  const [companionMessage, setCompanionMessage] = useState("Let’s make your receptionist clinic-ready.");
  const [companionSignal, setCompanionSignal] = useState(0);
  const react = (message) => {
    setCompanionMessage(message);
    setCompanionSignal((value) => value + 1);
  };

  useEffect(() => {
    if (data && form === null) {
      setForm({
        name: data.name ?? "",
        address: data.address ?? "",
        city: data.city ?? "",
        google_review_url: data.google_review_url ?? "",
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
      react("Saved. I’ll use the updated information from the next patient conversation.");
      if (d.did_wired === true) toast.success("Saved — number is wired and live");
      else if (d.did_wired === false)
        toast.warning("Saved. Number stored but telephony wiring pending — we've been notified.");
      else toast.success("Saved");
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Save failed")
  });

  // Plan & billing — current plan + any scheduled change. Refetches every
  // minute so cycle-end / days-left stay live without a reload (#353).
  const plan = useQuery({ queryKey: ["plan"], queryFn: fetchPlan, refetchInterval: 60_000 });
  // The mutation and both Razorpay flows moved to
  // components/PlanAndPayment.jsx, rendered on /billing. The query stays:
  // the WhatsApp section reads whatsapp_included / whatsapp_addon off it.

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
      react("Knowledge added. I can now answer those questions with confidence.");
      toast.success("FAQ saved — the agent will answer these from the next call");
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not save the FAQ")
  });

  const calTest = useMutation({
    mutationFn: () => testCalendar(branchId),
    onSuccess: (r) => {
      setCalOk(r.ok);
      if (r.ok) react("Calendar connected. Confirmed appointments now have somewhere safe to land.");
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
      react(`${m.role === "doctor" ? "Doctor" : "Reception"} access is ready. Your care team is growing.`);
      toast.success(`${m.role} account created — share the login with them`);
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not add member")
  });

  // Remove a staff login (owner only; doctor rows unlink, records stay).
  const fireStaff = useMutation({
    mutationFn: (userId) => removeStaff(branchId, userId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["staff", branchId] });
      react("Access updated. Clinic records remain safely in place.");
      toast.success("Login removed");
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not remove the login")
  });

  // DPDP erasure: delete the whole clinic, then sign out to the landing page.
  const [delConfirm, setDelConfirm] = useState("");
  const deletionConfirmed = delConfirm.trim().toUpperCase() === "DELETE";
  const nukeClinic = useMutation({
    mutationFn: () => deleteAccount({ confirm: "DELETE" }),
    onSuccess: () => {
      toast.success("Clinic deleted — goodbye");
      // Clear locally before the best-effort remote logout. The user row no
      // longer exists, so /auth/logout is expected to return 401.
      clearToken();
      logout();
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not delete the clinic")
  });

  const steps = checklist(data, calOk);
  const doneCount = steps.filter((s) => s.done).length;
  const progress = Math.round((doneCount / steps.length) * 100);
  const nextStep = steps.find((step) => !step.done);

  if (error)
    return (
      <p className="font-ui text-danger">
        Settings failed to load — {error?.response?.data?.detail ?? "is the backend running?"}
      </p>
    );
  if (isLoading || form === null)
    return <p className="font-ui text-slate">Loading settings…</p>;

  return (
    <div className="settings-page">
      <header className="settings-masthead">
        <div className="settings-hero-copy">
          <p className="settings-kicker"><Sparkle size={13} weight="fill" /> {data?.name} · clinic launch studio</p>
          <h1>Build the receptionist<br /><span>patients remember.</span></h1>
          <p>Everything Vachanam says and does begins here. Shape your clinic’s identity, appointment flow, patient communication and care team from one calm workspace.</p>
          <div className="settings-capability-row" aria-label="Configured capabilities">
            <span><PhoneCall size={15} weight="duotone" /> Answers every call</span>
            <span><CalendarCheck size={15} weight="duotone" /> Books from live availability</span>
            <span><BookOpenText size={15} weight="duotone" /> Learns your clinic</span>
            <span><UsersThree size={15} weight="duotone" /> Keeps the care team in sync</span>
          </div>
          {nextStep ? (
            <a href={`#${nextStep.id}`} className="settings-next-action">
              Continue with {nextStep.label}<ArrowRight size={16} weight="bold" />
            </a>
          ) : (
            <span className="settings-launch-ready"><CheckCircle size={18} weight="fill" /> Clinic ready for patients</span>
          )}
        </div>
        <div className="settings-hero-side">
          <div className="settings-progress-orbit" style={{ "--progress": `${progress * 3.6}deg` }}
            aria-label={`${doneCount} of ${steps.length} setup tasks complete`}>
            <div><strong>{progress}<span>%</span></strong><small>clinic ready</small></div>
          </div>
          <ClinicCompanion message={companionMessage} progress={progress} signal={companionSignal} />
        </div>
      </header>

      <section className="settings-journey" aria-labelledby="setup-journey-heading">
        <div className="settings-journey-intro">
          <span>Onboarding</span>
          <h2 id="setup-journey-heading">Your path to the first perfect call</h2>
          <p>{doneCount === steps.length ? "The essentials are ready. Revisit any step whenever the clinic changes." : `${steps.length - doneCount} focused ${steps.length - doneCount === 1 ? "step" : "steps"} left before your clinic is fully ready.`}</p>
        </div>
        <div className="settings-journey-track">
          {steps.map((step, index) => {
            const Icon = SETUP_ICONS[step.id];
            return (
              <a key={step.id} href={`#${step.id}`} className={`settings-journey-card ${step.done ? "is-complete" : ""} ${nextStep?.id === step.id ? "is-next" : ""}`}>
                <span className="settings-journey-icon"><Icon size={19} weight="duotone" /></span>
                <small>0{index + 1}</small>
                <strong>{step.label}</strong>
                <em>{step.done ? "Ready" : nextStep?.id === step.id ? "Up next" : "To do"}</em>
              </a>
            );
          })}
        </div>
      </section>

      <div className="settings-workspace">
        <aside className="settings-rail">
          <div>
            <p>Capability map</p>
            <nav className="settings-checklist" aria-label="Clinic setup checklist">
              {steps.map((s, i) => (
                <a key={s.id} href={`#${s.id}`} className={s.done ? "is-complete" : ""}>
                  <span>{s.done ? <Check size={13} weight="bold" /> : i + 1}</span>
                  <strong>{s.label}</strong>
                  <small>{s.done ? "Ready" : "Needs attention"}</small>
                </a>
              ))}
              <a href="#faq">
                <span><BookOpenText size={14} weight="duotone" /></span>
                <strong>Clinic knowledge</strong>
                <small>What Vachanam knows</small>
              </a>
            </nav>
          </div>
          <div className="settings-rail-note">
            <Sparkle size={18} weight="duotone" />
            <strong>Grounded by design</strong>
            <p>Vachanam checks these details, doctors, schedules and answers before speaking to a patient.</p>
          </div>
        </aside>

        <main className="settings-panels">

      {/* Plan & billing MOVED to /billing (Vinay 2026-08-09: "migrate entire
          billing to billing page. all billings."). Settings keeps the `plan`
          query only — the WhatsApp section below gates on it. Clinic details
          is now full-width: it lost the card it used to sit beside. */}

      {/* 1 — Clinic details */}
      <div className="settings-content-heading"><span>01 · Foundation</span><h2>Give every conversation a reliable starting point.</h2><p>These details define how Vachanam introduces your clinic, finds the right doctor and completes appointments.</p></div>
      <Section id="details" title="Clinic identity" icon={MapPin} done={steps[0].done}
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
          <div className="sm:col-span-2">
            <label className="label">Google review link</label>
            <input className="field" value={form.google_review_url}
              onChange={set("google_review_url")}
              placeholder="https://g.page/r/.../review" inputMode="url" />
            <p className="mt-1 font-ui text-xs text-slate">
              Sent once after the receptionist marks a visit attended.
            </p>
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
              google_review_url: form.google_review_url,
              clinic_phone: form.clinic_phone, emergency_contact: form.emergency_contact
            })}>
          Save details
        </button>
      </Section>

      {/* Doctors + Google Calendar — side by side */}
      <div className="settings-pair-grid">
      <Section id="doctors" title="Doctors and availability" icon={Stethoscope} done={steps[1].done}
        sub={`${data?.doctors_count ?? 0} configured. The AI books patients against these profiles.`}>
        <InfoBox title="Two booking styles — pick per doctor:">
          <p><strong>Token queue</strong> — numbered line for high-volume OP (the AI announces "your token number is 8"). Set a daily limit.</p>
          <p><strong>Time slots</strong> — fixed appointment times. Set working hours, days, and slot length.</p>
        </InfoBox>
        <a href="/my-schedule" className="btn-primary mt-4 inline-flex">Manage doctors →</a>
      </Section>

      {/* 3 — Calendar */}
      <Section id="calendar" title="Calendar connection" icon={CalendarCheck} done={steps[2].done}
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
      </div>

      {/* Phone · Agent language · Agent voice — cream row, side by side */}
      <div className="settings-pair-grid settings-capability-group">
      <div className="settings-content-heading"><span>02 · Patient communication</span><h2>Choose how patients reach you and what happens next.</h2><p>Your AI line answers first. Connected channels keep confirmations, reminders and follow-ups moving.</p></div>
      <Section id="phone" title="AI phone line" icon={PhoneCall} done={steps[3].done}
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
      </Section>

      {/* Shown once the clinic actually HAS WhatsApp — bundled in the plan or
          bought as the add-on. Gating this on the build flag meant a clinic
          that had just paid ₹1,499 saw no way to connect until someone
          redeployed the frontend (same bug as the nav gate).

          Self-serve since 2026-08-04: the owner presses one button and walks
          through Meta's Embedded Signup with the number they already use. The
          old copy here asked them to EMAIL US to book a 15-minute concierge
          call, which does not survive contact with more than a handful of
          clinics. */}
      {(WHATSAPP_LIVE || plan.data?.whatsapp_included || plan.data?.whatsapp_addon) && (
      <Section id="whatsapp" title="WhatsApp continuity" icon={WhatsappLogo}
        sub="Booking confirmations, reminders and post-visit rating asks on your clinic's own WhatsApp number.">
        <WaConnectCard branchId={branchId} />
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label className="flex min-h-[72px] cursor-pointer items-center gap-3 rounded-xl border border-hairline bg-pill p-3">
            <input
              type="checkbox"
              className="h-5 w-5 accent-teal"
              checked={Boolean(data?.reminder_calls_enabled)}
              disabled={save.isPending || (data?.reminder_calls_enabled && !data?.whatsapp_reminder_ready)}
              onChange={(event) => save.mutate({ reminder_calls_enabled: event.target.checked })}
            />
            <span className="font-ui text-sm">
              <strong className="block">Also make reminder calls</strong>
              <span className="text-slate">
                {data?.whatsapp_reminder_ready
                  ? "Off = WhatsApp only; on = WhatsApp plus phone call."
                  : "Connect WhatsApp and approve the reminder template before switching calls off."}
              </span>
            </span>
          </label>
          <label className="flex min-h-[72px] cursor-pointer items-center gap-3 rounded-xl border border-hairline bg-pill p-3">
            <input
              type="checkbox"
              className="h-5 w-5 accent-teal"
              checked={Boolean(data?.followup_calls_enabled)}
              disabled={save.isPending || (data?.followup_calls_enabled && !data?.whatsapp_followup_ready)}
              onChange={(event) => save.mutate({ followup_calls_enabled: event.target.checked })}
            />
            <span className="font-ui text-sm">
              <strong className="block">Also make follow-up calls</strong>
              <span className="text-slate">
                {data?.whatsapp_followup_ready
                  ? "Off = WhatsApp only; on = WhatsApp plus phone call."
                  : "Connect WhatsApp and approve the follow-up template before switching calls off."}
              </span>
            </span>
          </label>
        </div>
      </Section>
      )}

      </div>

      {/* Clinic FAQ + Team — side by side, compact */}
      <div className="settings-knowledge-stack">
      {/* Clinic FAQ — the agent answers these on calls */}
      <div className="settings-content-heading"><span>03 · Knowledge and people</span><h2>Teach the receptionist. Invite the care team.</h2><p>Answers stay grounded in clinic-approved information, while each team member sees only the workspace they need.</p></div>
      <Section id="faq" title="Clinic knowledge" icon={BookOpenText}
        sub="Answers your AI agent gives when callers ask about fees, timings, parking, insurance, reports and more. Leave a row blank to skip it.">
        <div className="space-y-3">
          <div className="settings-faq-list">
          {(faqRows ?? []).map((row, i) => (
            <div key={i} className="settings-faq-card">
              <span className="settings-faq-index">FAQ {String(i + 1).padStart(2, "0")}</span>
              <label className="settings-faq-field is-question">
                <span><strong>Q</strong> Patient question</span>
                <textarea className="settings-faq-control" rows={2}
                  aria-label={`Patient question ${i + 1}`}
                  value={row.q}
                  placeholder="Question callers ask…"
                  onChange={(e) => {
                    const next = [...faqRows];
                    next[i] = { ...next[i], q: e.target.value };
                    setFaqRows(next);
                  }} />
              </label>
              <label className="settings-faq-field is-answer">
                <span><strong>A</strong> Approved answer</span>
                <textarea className="settings-faq-control" rows={2}
                  aria-label={`Approved answer ${i + 1}`}
                  value={row.a}
                  placeholder="Your clinic's answer (spoken by the agent)…"
                  onChange={(e) => {
                    const next = [...faqRows];
                    next[i] = { ...next[i], a: e.target.value };
                    setFaqRows(next);
                  }} />
              </label>
              <button type="button" className="settings-remove-action"
                onClick={() => setFaqRows(faqRows.filter((_, j) => j !== i))}>
                Remove
              </button>
            </div>
          ))}
          </div>
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
              <ul className="mt-2 max-h-36 space-y-1 overflow-y-auto pr-1">
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
      <Section id="team" title="Team access" icon={UsersThree} done={steps[4].done}
        sub="Reception runs the queue and walk-ins on their phone. Doctors see their own day.">
        <div className="settings-team-layout">
        <div className="settings-team-roster">
          <div className="settings-subhead"><span>Current team</span><strong>{staff.length} {staff.length === 1 ? "member" : "members"}</strong></div>
          {staff.length === 0 && <p className="settings-empty-note">The clinic owner will appear here after setup finishes.</p>}
          {staff.map((m) => (
            <div key={m.user_id} className="settings-team-member">
              <span className="settings-member-avatar" aria-hidden>{(m.name ?? m.email ?? "V").slice(0, 1).toUpperCase()}</span>
              <div className="min-w-0 flex-1">
                <p className="truncate font-ui font-medium">{m.name ?? m.email}</p>
                <p className="truncate font-ui text-xs text-slate">{m.email}</p>
              </div>
              <span className="chip-token">{m.role.replace("_", " ")}</span>
              {m.role !== "org_admin" && m.user_id !== user?.user_id && (
                <button type="button" className="ml-2 font-ui text-xs text-danger underline-offset-2 hover:underline"
                  disabled={fireStaff.isPending}
                  onClick={async () => {
                    const confirmed = await ask({
                      title: `Remove ${m.name ?? m.email}?`,
                      description: "Their clinic records stay. Only this person's login access is removed immediately.",
                      confirmLabel: "Remove login",
                      tone: "danger",
                    });
                    if (confirmed) fireStaff.mutate(m.user_id);
                  }}>
                  Remove
                </button>
              )}
            </div>
          ))}
        </div>
        <form className="settings-team-form"
          onSubmit={(e) => { e.preventDefault(); invite.mutate(); }}>
          <div className="settings-subhead sm:col-span-2"><span>Invite someone</span><strong>Private login</strong></div>
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
        </div>
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

      </div>

      {/* DPDP erasure (Vinay 2026-07-17): the fiduciary can close the account
          and erase everything — patients, bookings, notes, logins, billing. */}
      <Section id="danger" title="Account controls" icon={ShieldWarning} tone="danger"
        sub="Sensitive actions stay out of the way until you explicitly open them.">
        <details className="settings-danger-disclosure">
          <summary><span><strong>Delete clinic and all data</strong><small>Patients, bookings, notes, logins and billing</small></span><span>Open controls</span></summary>
        <div className="settings-danger-body grid gap-3 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="delete-clinic-confirmation">Type DELETE to permanently erase the clinic</label>
            <input id="delete-clinic-confirmation" className="field" type="text" autoComplete="off" value={delConfirm}
              onChange={(e) => setDelConfirm(e.target.value)} placeholder="DELETE" />
          </div>
          <div className="flex items-end">
            <button type="button"
              className="btn-danger w-full"
              disabled={nukeClinic.isPending || !deletionConfirmed}
              onClick={() => nukeClinic.mutate()}>
              {nukeClinic.isPending ? "Deleting…" : "Delete clinic permanently"}
            </button>
          </div>
        </div>
        </details>
      </Section>
        </main>
      </div>
    </div>
  );
}
