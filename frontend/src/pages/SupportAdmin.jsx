import { useEffect, useState } from "react";
import { useAuth } from "../hooks/useAuth.jsx";
import {
  adminListTickets, adminGetMessages, adminReply, adminPatchTicket, adminMacros,
  listStaff, createStaff, deleteStaff,
} from "../api/support";

const STATUSES = ["open", "pending", "resolved", "closed", "ai_resolved"];
const PRIORITIES = ["low", "normal", "high", "urgent"];

function Thread({ ticket, macros, onChanged }) {
  const [msgs, setMsgs] = useState([]);
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => adminGetMessages(ticket.id).then(setMsgs).catch(() => setMsgs([]));
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [ticket.id]);

  const send = async () => {
    if (!reply.trim() || busy) return;
    setBusy(true);
    try { await adminReply(ticket.id, reply.trim()); setReply(""); await load(); onChanged(); }
    finally { setBusy(false); }
  };
  const patch = async (p) => { await adminPatchTicket(ticket.id, p); onChanged(); };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <select className="input w-auto py-1" value={ticket.status}
          onChange={(e) => patch({ status: e.target.value })}>
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select className="input w-auto py-1" value={ticket.priority}
          onChange={(e) => patch({ priority: e.target.value })}>
          {PRIORITIES.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <span className="text-ink-soft">{ticket.email}</span>
      </div>

      <div className="max-h-72 space-y-2 overflow-y-auto rounded-xl border border-hairline bg-surface/85 p-3">
        {msgs.map((m, i) => (
          <div key={i} className={m.sender === "staff" ? "text-right" : "text-left"}>
            <span className={"inline-block max-w-[85%] rounded-2xl px-3 py-2 text-sm " +
              (m.sender === "staff" ? "bg-teal text-white" :
               m.sender === "bot" ? "bg-teal-pale text-teal-deep" : "bg-teal-mint text-ink")}>
              {m.body}
            </span>
          </div>
        ))}
      </div>

      {macros.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {macros.map((mc, i) => (
            <button key={i} className="chip bg-teal-pale text-teal-deep text-xs"
              onClick={() => setReply((r) => (r ? r + "\n\n" : "") + mc.body)}>
              {mc.label}
            </button>
          ))}
        </div>
      )}

      <div className="flex gap-2">
        <textarea className="input flex-1" rows={2} placeholder="Reply to the clinic…"
          value={reply} onChange={(e) => setReply(e.target.value)} />
        <button className="btn-primary" onClick={send} disabled={busy}>
          {busy ? "…" : "Reply"}
        </button>
      </div>
    </div>
  );
}

function StaffManager() {
  const [staff, setStaff] = useState([]);
  const [form, setForm] = useState({ email: "", name: "", password: "" });
  const [err, setErr] = useState("");
  const [allowed, setAllowed] = useState(true); // hide entirely if not a support admin
  const load = () =>
    listStaff().then((s) => { setStaff(s); setAllowed(true); })
      .catch((x) => { if (x.response?.status === 403) setAllowed(false); else setStaff([]); });
  useEffect(() => { load(); }, []);
  if (!allowed) return null;
  const add = async (e) => {
    e.preventDefault();
    setErr("");
    try { await createStaff(form); setForm({ email: "", name: "", password: "" }); load(); }
    catch (x) { setErr(x.response?.data?.detail || "Could not add"); }
  };
  return (
    <div className="space-y-3 rounded-2xl border border-hairline bg-surface/85 p-4">
      <h2 className="font-display text-lg font-semibold text-ink">Support team</h2>
      <ul className="space-y-1 text-sm">
        {staff.map((u) => (
          <li key={u.id} className="flex items-center justify-between">
            <span>{u.name} · <span className="text-ink-soft">{u.email}</span></span>
            <button className="btn-danger px-2 py-1 text-xs"
              onClick={() => deleteStaff(u.id).then(load)}>Remove</button>
          </li>
        ))}
        {staff.length === 0 && <li className="text-ink-soft">No support staff yet.</li>}
      </ul>
      <form onSubmit={add} className="grid gap-2 sm:grid-cols-4">
        <input className="input" placeholder="Name" value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <input className="input" placeholder="Email" value={form.email}
          onChange={(e) => setForm({ ...form, email: e.target.value })} />
        <input className="input" type="password" placeholder="Temp password" value={form.password}
          onChange={(e) => setForm({ ...form, password: e.target.value })} />
        <button className="btn-primary">Add staff</button>
      </form>
      {err && <p className="text-sm text-danger">{err}</p>}
    </div>
  );
}

export default function SupportAdmin() {
  const { role } = useAuth();
  const [tickets, setTickets] = useState([]);
  const [macros, setMacros] = useState([]);
  const [active, setActive] = useState(null);
  const [filter, setFilter] = useState("");

  const load = () =>
    adminListTickets(filter ? { status: filter } : {}).then(setTickets).catch(() => setTickets([]));
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [filter]);
  useEffect(() => { adminMacros().then(setMacros).catch(() => setMacros([])); }, []);

  const activeTicket = tickets.find((t) => t.id === active);

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="font-display text-2xl font-semibold text-ink">Support dashboard</h1>
        <select className="input w-auto py-1" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">Needs human</option>
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      <div className="grid gap-4 md:grid-cols-[1fr_1.4fr]">
        <ul className="space-y-2">
          {tickets.map((t) => (
            <li key={t.id}>
              <button
                className={"w-full rounded-2xl border p-3 text-left transition " +
                  (active === t.id ? "border-teal bg-teal-mint" : "border-hairline bg-surface/85 hover:bg-teal-mint")}
                onClick={() => setActive(t.id)}>
                <div className="flex justify-between gap-2">
                  <span className="truncate font-medium text-ink">{t.subject}</span>
                  <span className="chip bg-teal-pale text-teal-deep text-xs">{t.priority}</span>
                </div>
                <div className="text-xs text-ink-soft">
                  {t.status} · {t.org_id ? "clinic" : "lead"} · {new Date(t.created_at).toLocaleString()}
                </div>
              </button>
            </li>
          ))}
          {tickets.length === 0 && <li className="text-ink-soft">No tickets.</li>}
        </ul>

        <div className="rounded-2xl border border-hairline bg-surface/85 p-4">
          {activeTicket
            ? <Thread ticket={activeTicket} macros={macros} onChanged={load} />
            : <p className="text-ink-soft">Select a ticket to view the conversation.</p>}
        </div>
      </div>

      {(role === "super_admin" || role === "support") && <StaffManager />}
    </div>
  );
}
