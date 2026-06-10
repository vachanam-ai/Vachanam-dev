import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  addStaff,
  fetchBranchSettings,
  fetchStaff,
  setBranchVoice,
  testCalendar,
  updateBranchSettings
} from "../api/client.js";
import { useAuth } from "../hooks/useAuth.jsx";
import { revealStagger } from "../lib/motion.js";
import VoicePicker from "../components/VoicePicker.jsx";

const SA_EMAIL = "vachanam-events@vachanam-498912.iam.gserviceaccount.com";

function Section({ title, sub, children }) {
  return (
    <section data-reveal className="card p-6">
      <h2 className="font-display text-lg font-semibold">{title}</h2>
      {sub && <p className="mt-0.5 font-ui text-sm text-slate">{sub}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

export default function Settings() {
  const { branchId } = useAuth();
  const qc = useQueryClient();
  const pageRef = useRef(null);

  const { data, isLoading } = useQuery({
    queryKey: ["branch-settings", branchId],
    queryFn: () => fetchBranchSettings(branchId),
    enabled: Boolean(branchId)
  });
  const { data: staff = [] } = useQuery({
    queryKey: ["staff", branchId],
    queryFn: () => fetchStaff(branchId),
    enabled: Boolean(branchId)
  });

  const [details, setDetails] = useState(null);
  const [calId, setCalId] = useState("");
  const [didInput, setDidInput] = useState("");
  const [newStaff, setNewStaff] = useState({ name: "", email: "", password: "", role: "receptionist" });

  useEffect(() => {
    if (data && details === null) {
      setDetails({ name: data.name ?? "", emergency_contact: data.emergency_contact ?? "" });
      setCalId(data.google_calendar_id ?? "");
      setDidInput(data.did_number ?? "");
    }
  }, [data, details]);

  useEffect(() => {
    if (data) revealStagger(pageRef.current);
  }, [Boolean(data)]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    mutationFn: (payload) => updateBranchSettings(branchId, payload),
    onSuccess: (d) => {
      qc.setQueryData(["branch-settings", branchId], (old) => ({ ...old, ...d }));
      toast.success("Saved");
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Save failed")
  });

  const voice = useMutation({
    mutationFn: (v) => setBranchVoice(branchId, v),
    onSuccess: (d) => {
      qc.setQueryData(["branch-settings", branchId], (old) => ({ ...old, ...d }));
      toast.success(`Voice set to ${d.tts_voice}`);
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not change voice")
  });

  const calTest = useMutation({
    mutationFn: () => testCalendar(branchId),
    onSuccess: (r) =>
      r.ok
        ? toast.success("Calendar connected — bookings will appear there")
        : toast.error(`Calendar test failed: ${r.detail ?? "no writer access"}`),
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Calendar test failed")
  });

  const invite = useMutation({
    mutationFn: () => addStaff(branchId, newStaff),
    onSuccess: (m) => {
      qc.invalidateQueries({ queryKey: ["staff", branchId] });
      setNewStaff({ name: "", email: "", password: "", role: "receptionist" });
      toast.success(`${m.role} account created — share the password with them`);
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not add member")
  });

  if (isLoading || details === null)
    return <p className="font-ui text-slate">Loading settings…</p>;

  const fetchedCal = data?.google_calendar_id ?? "";

  return (
    <div ref={pageRef} className="space-y-6">
      <div data-reveal>
        <p className="eyebrow">Clinic settings</p>
        <h1 className="section-title text-2xl">{data?.name}</h1>
      </div>

      <Section title="Clinic details" sub="Name patients hear on calls; emergency number the AI gives when asked.">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label">Clinic name</label>
            <input className="field" value={details.name}
              onChange={(e) => setDetails((d) => ({ ...d, name: e.target.value }))} />
          </div>
          <div>
            <label className="label">Emergency contact</label>
            <input className="field" value={details.emergency_contact} placeholder="+91 …"
              onChange={(e) => setDetails((d) => ({ ...d, emergency_contact: e.target.value }))} />
          </div>
        </div>
        <button className="btn-primary mt-4" disabled={save.isPending}
          onClick={() => save.mutate(details)}>
          Save details
        </button>
      </Section>

      <Section
        title="Phone line (DID)"
        sub="The Vachanam number patients call. Forward your existing clinic number to it and the AI answers every call."
      >
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-64">
            <label className="label">Your Vachanam number</label>
            <input className="field numeral" value={didInput} placeholder="+91 …"
              onChange={(e) => setDidInput(e.target.value)} />
          </div>
          <button className="btn-primary" disabled={save.isPending}
            onClick={() => save.mutate({ did_number: didInput })}>
            Save number
          </button>
          <a
            className="btn-gold"
            href={`mailto:hello@vachanam.in?subject=DID%20number%20request%20—%20${encodeURIComponent(data?.name ?? "clinic")}&body=Please%20assign%20a%20phone%20number%20for%20our%20clinic.`}
          >
            Request a number
          </a>
        </div>
        <ol className="mt-4 list-decimal space-y-1 pl-5 font-ui text-sm text-slate">
          <li>Request a number — we provision it on our telephony partner (1 business day).</li>
          <li>Enter it above and save.</li>
          <li>Set call forwarding from your clinic phone to this number (we send the exact steps).</li>
        </ol>
      </Section>

      <Section
        title="Google Calendar"
        sub="Every confirmed booking becomes an event on this calendar."
      >
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-72 flex-1">
            <label className="label">Calendar ID (usually your Gmail address)</label>
            <input className="field" value={calId} placeholder="clinic@gmail.com"
              onChange={(e) => setCalId(e.target.value)} />
          </div>
          <button className="btn-primary" disabled={save.isPending}
            onClick={() => save.mutate({ google_calendar_id: calId })}>
            Save
          </button>
          <button className="btn-ghost" disabled={calTest.isPending || !fetchedCal}
            onClick={() => calTest.mutate()}>
            {calTest.isPending ? "Testing…" : "Test connection"}
          </button>
        </div>
        <div className="mt-4 rounded-xl bg-teal-mint/70 p-4 font-ui text-sm">
          <p className="font-medium">One-time setup:</p>
          <p className="mt-1 text-ink-soft">
            Google Calendar → Settings → your calendar → <em>Share with specific people</em> → add
          </p>
          <code className="mt-1 block select-all break-all rounded bg-white px-2 py-1 text-xs">{SA_EMAIL}</code>
          <p className="mt-1 text-ink-soft">with permission <strong>“Make changes to events”</strong>, then hit Test.</p>
        </div>
      </Section>

      <Section title="Agent voice" sub="The voice patients hear. Applies from the next call.">
        <VoicePicker value={data?.tts_voice} onSelect={(v) => voice.mutate(v)} />
      </Section>

      <Section
        title="Team"
        sub="Reception sees the queue and registers walk-ins. Doctors see their own schedule."
      >
        <div className="space-y-2">
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
        <form
          className="mt-5 grid gap-3 border-t border-hairline pt-5 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            invite.mutate();
          }}
        >
          <div>
            <label className="label">Name</label>
            <input className="field" required value={newStaff.name}
              onChange={(e) => setNewStaff((s) => ({ ...s, name: e.target.value }))} />
          </div>
          <div>
            <label className="label">Email</label>
            <input className="field" type="email" required value={newStaff.email}
              onChange={(e) => setNewStaff((s) => ({ ...s, email: e.target.value }))} />
          </div>
          <div>
            <label className="label">Temporary password</label>
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
      </Section>
    </div>
  );
}
