import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  addStaff,
  cloneBranchVoice,
  deleteBranchVoiceClone,
  fetchBranchSettings,
  fetchStaff,
  getBranchVoices,
  setBranchVoice,
  testCalendar,
  updateBranchSettings
} from "../api/client.js";
import { useAuth } from "../hooks/useAuth.jsx";

const SA_EMAIL = "vachanam-events@vachanam-498912.iam.gserviceaccount.com";

// Static fallback for the language dropdown — the set is fixed metadata
// (mirrors agent/i18n/languages.py). Used when the API response omits
// allowed_languages (e.g. an older/not-yet-restarted backend) so the picker
// never renders empty. The backend still validates the chosen code on PATCH.
const LANGUAGES = [
  { code: "te", name: "Telugu", native_name: "తెలుగు" },
  { code: "hi", name: "Hindi", native_name: "हिन्दी" },
  { code: "ta", name: "Tamil", native_name: "தமிழ்" },
  { code: "kn", name: "Kannada", native_name: "ಕನ್ನಡ" },
  { code: "ml", name: "Malayalam", native_name: "മലയാളം" },
  { code: "mr", name: "Marathi", native_name: "मराठी" },
  { code: "bn", name: "Bengali", native_name: "বাংলা" },
  { code: "or", name: "Odia", native_name: "ଓଡ଼ିଆ" }
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
  const { branchId } = useAuth();
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

  const [form, setForm] = useState(null);
  const [calOk, setCalOk] = useState(null);
  const [newStaff, setNewStaff] = useState({ name: "", email: "", password: "", role: "receptionist" });

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

  // smallest.ai voice catalog for the clinic's language (drives the picker).
  const voices = useQuery({
    queryKey: ["branch-voices", branchId, data?.language],
    queryFn: () => getBranchVoices(branchId, data?.language),
    enabled: !!branchId && !!data,
    staleTime: 5 * 60 * 1000
  });

  const cloneFileRef = useRef(null);
  const [cloneName, setCloneName] = useState("");
  const clone = useMutation({
    mutationFn: ({ name, file }) => cloneBranchVoice(branchId, name, file),
    onSuccess: (d) => {
      qc.setQueryData(["branch-settings", branchId], d);
      setCloneName("");
      if (cloneFileRef.current) cloneFileRef.current.value = "";
      toast.success("Voice cloned and set as the clinic voice");
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Voice cloning failed")
  });
  const removeClone = useMutation({
    mutationFn: () => deleteBranchVoiceClone(branchId),
    onSuccess: (d) => {
      qc.setQueryData(["branch-settings", branchId], d);
      toast.success("Reverted to the default voice");
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not remove voice")
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
                  : "border-hairline bg-white text-slate hover:border-teal-light/50"
              }`}>
              <span className={`grid h-4 w-4 place-items-center rounded-full text-[10px] ${s.done ? "bg-teal text-white" : "bg-slate-light/30"}`}>
                {s.done ? "✓" : i + 1}
              </span>
              {s.label}
            </a>
          ))}
        </div>
      </div>

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
          <code className="block select-all break-all rounded bg-white px-2 py-1 text-xs">{SA_EMAIL}</code>
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
            see "number is wired and live". Then set call forwarding from{" "}
            {form.clinic_phone || "your clinic phone"} to this number (*21*number# on most Indian carriers, or ask
            your operator for "unconditional call forwarding").</p>
        </InfoBox>
      </Section>

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

      {/* 6 — Voice */}
      <Section id="voice" title="Agent voice"
        sub="The smallest.ai voice patients hear. Pick one, or clone your own. Applies from the next call.">
        {data?.tts_voice?.startsWith("voice_") ? (
          <div className="mb-3 flex items-center justify-between rounded-xl bg-teal-mint/40 p-3">
            <p className="font-ui text-sm">
              Using your <strong>cloned voice</strong>.
            </p>
            <button type="button" className="btn-ghost min-h-[44px]"
              onClick={() => removeClone.mutate()} disabled={removeClone.isPending}>
              Use a standard voice
            </button>
          </div>
        ) : (
          <select
            className="field"
            value={data?.tts_voice ?? ""}
            onChange={(e) => voice.mutate(e.target.value)}
            disabled={voice.isPending || voices.isLoading}
          >
            <option value="">Default voice for this language</option>
            {(voices.data?.voices ?? []).map((v) => (
              <option key={v.voice_id} value={v.voice_id}>
                {v.display_name}{v.gender ? ` · ${v.gender}` : ""}
              </option>
            ))}
          </select>
        )}
        {voices.isError && (
          <p className="mt-2 font-ui text-xs text-danger">
            Couldn’t load voices from smallest.ai — check the API key.
          </p>
        )}

        {/* Voice cloning */}
        <div className="mt-4 rounded-xl border border-hairline p-4">
          <p className="font-ui text-sm font-medium">Clone a voice</p>
          <p className="mt-1 font-ui text-xs text-slate">
            Upload a clear 5–15 second sample (WAV/MP3). The AI will speak in that voice.
          </p>
          <div className="mt-3 space-y-2">
            <input
              className="field"
              placeholder="Voice name (e.g. Dr Srinivas)"
              value={cloneName}
              onChange={(e) => setCloneName(e.target.value)}
            />
            <input ref={cloneFileRef} type="file" accept="audio/*" className="field" />
            <button
              type="button"
              className="btn-primary w-full min-h-[44px]"
              disabled={clone.isPending}
              onClick={() => {
                const file = cloneFileRef.current?.files?.[0];
                if (!cloneName.trim()) return toast.error("Give the voice a name");
                if (!file) return toast.error("Choose an audio sample");
                clone.mutate({ name: cloneName.trim(), file });
              }}
            >
              {clone.isPending ? "Cloning…" : "Clone & use this voice"}
            </button>
          </div>
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
            </div>
          ))}
        </div>
        <form className="mt-5 grid gap-3 border-t border-hairline pt-5 sm:grid-cols-2"
          onSubmit={(e) => { e.preventDefault(); invite.mutate(); }}>
          <div>
            <label className="label">Name</label>
            <input className="field" required value={newStaff.name}
              onChange={(e) => setNewStaff((s) => ({ ...s, name: e.target.value }))} />
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
              onChange={(e) => setNewStaff((s) => ({ ...s, role: e.target.value }))}>
              <option value="receptionist">Receptionist</option>
              <option value="doctor">Doctor</option>
            </select>
          </div>
          <button className="btn-primary sm:col-span-2" disabled={invite.isPending}>
            {invite.isPending ? "Creating…" : "Add team member"}
          </button>
        </form>
        <InfoBox>
          <p>Share the email + temporary password with them. They sign in at this site — reception lands on
            the Queue, doctors on their schedule. They can also use "Continue with Google" if the Google
            account has the same email.</p>
        </InfoBox>
      </Section>
    </div>
  );
}
