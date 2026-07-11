import { useEffect, useRef, useState } from "react";
import {
  listTickets, getTicketMessages, replyToTicket, rateTicket, submitContact,
} from "../api/support";

const STATUS_LABEL = {
  ai_resolved: "Answered by assistant",
  open: "With our team",
  pending: "Awaiting your reply",
  resolved: "Resolved",
  closed: "Closed",
};

function Bubble({ side, tone, children }) {
  return (
    <div className={side === "right" ? "text-right" : "text-left"}>
      <span className={"inline-block max-w-[85%] rounded-2xl px-3 py-2 text-sm " +
        (tone === "user" ? "bg-teal text-white" :
         tone === "bot" ? "bg-teal-pale text-teal-deep" : "bg-teal-mint text-ink")}>
        {children}
      </span>
    </div>
  );
}

// ── Raise a ticket straight to a human ────────────────────────────────────────
function RaiseTicket({ onCreated }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ email: "", subject: "", body: "", category: "technical" });
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    try {
      // email is ignored server-side for authed users (uses the account email),
      // but the field is required by the API — send the account's implicitly.
      await submitContact({ ...form, email: form.email || "me@clinic" });
      setSent(true);
      setForm({ email: "", subject: "", body: "", category: "technical" });
      onCreated();
    } catch (x) { setErr(x.response?.data?.detail || "Could not send — email hello@vachanam.in"); }
  };
  return (
    <div className="rounded-2xl border border-hairline bg-surface/85 p-4">
      <button className="flex w-full items-center justify-between font-display text-lg font-semibold text-ink"
        onClick={() => { setOpen((o) => !o); setSent(false); }}>
        <span>Raise a ticket with our team</span>
        <span className="text-teal">{open ? "−" : "+"}</span>
      </button>
      {open && (sent ? (
        <p className="mt-3 rounded-xl border border-hairline bg-teal-mint p-3 text-sm">
          Ticket created — our team will reply here and by email.
        </p>
      ) : (
        <form onSubmit={submit} className="mt-3 grid gap-2">
          <input className="input" placeholder="Subject" required value={form.subject}
            onChange={(e) => setForm({ ...form, subject: e.target.value })} />
          <textarea className="input" rows={3} placeholder="Describe the issue (no patient names/phone/health details, please)"
            required value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} />
          <div className="flex gap-2">
            <select className="input w-auto" value={form.category}
              onChange={(e) => setForm({ ...form, category: e.target.value })}>
              <option value="technical">Technical</option>
              <option value="billing">Billing</option>
              <option value="onboarding">Onboarding</option>
              <option value="feature_request">Feature request</option>
              <option value="other">Other</option>
            </select>
            <button className="btn-primary">Create ticket</button>
          </div>
          {err && <p className="text-sm text-danger">{err}</p>}
        </form>
      ))}
    </div>
  );
}

function Thread({ ticket, onChanged }) {
  const [msgs, setMsgs] = useState([]);
  const [reply, setReply] = useState("");
  const [rated, setRated] = useState(false);
  const pollRef = useRef(null);

  const load = () => getTicketMessages(ticket.id).then(setMsgs).catch(() => setMsgs([]));
  useEffect(() => {
    load();
    pollRef.current = setInterval(load, 5000); // feels live when staff reply
    return () => clearInterval(pollRef.current);
    // eslint-disable-next-line
  }, [ticket.id]);

  const send = async () => {
    if (!reply.trim()) return;
    await replyToTicket(ticket.id, reply.trim());
    setReply("");
    await load();
    onChanged();
  };
  const rate = async (score) => { await rateTicket(ticket.id, score); setRated(true); };
  const resolved = ticket.status === "resolved" || ticket.status === "closed";

  return (
    <div className="space-y-2 rounded-b-2xl border border-t-0 border-hairline bg-surface/85 p-3">
      {msgs.map((m, i) => (
        <Bubble key={i} side={m.sender === "user" ? "right" : "left"} tone={m.sender}>{m.body}</Bubble>
      ))}
      {resolved && !rated && (
        <div className="flex items-center gap-2 text-sm text-ink-soft">
          Rate this help:
          {[1, 2, 3, 4, 5].map((n) => (
            <button key={n} className="text-lg hover:scale-110" onClick={() => rate(n)}>★</button>
          ))}
        </div>
      )}
      {rated && <p className="text-sm text-teal">Thanks for the feedback!</p>}
      <div className="flex gap-2">
        <input className="input flex-1" placeholder="Reply…" value={reply}
          onChange={(e) => setReply(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()} />
        <button className="btn-primary" onClick={send}>Send</button>
      </div>
    </div>
  );
}

export default function MyTickets() {
  const [tickets, setTickets] = useState([]);
  const [active, setActive] = useState(null);
  const load = () => listTickets().then(setTickets).catch(() => setTickets([]));
  useEffect(() => { load(); }, []);

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h1 className="font-display text-2xl font-semibold text-ink">Support</h1>
      <p className="text-ink-soft">Chat with the assistant any time using the button in the
        bottom-right corner. It answers instantly and logs a ticket here. Need a person? Raise
        a ticket below.</p>

      <RaiseTicket onCreated={load} />

      <h2 className="pt-2 font-display text-lg font-semibold text-ink">Your tickets</h2>
      {tickets.length === 0 && <p className="text-ink-soft">No tickets yet — chat with the assistant or raise one above.</p>}
      <ul className="space-y-2">
        {tickets.map((t) => (
          <li key={t.id}>
            <button
              className="w-full rounded-2xl border border-hairline bg-surface/85 p-3 text-left transition hover:bg-teal-mint"
              onClick={() => setActive(active === t.id ? null : t.id)}>
              <div className="flex items-center justify-between gap-2">
                <span className="truncate font-medium text-ink">{t.subject}</span>
                <span className="chip bg-teal-pale text-teal-deep whitespace-nowrap text-xs">
                  {STATUS_LABEL[t.status] || t.status}
                </span>
              </div>
              <div className="text-xs text-ink-soft">{new Date(t.created_at).toLocaleString()}</div>
            </button>
            {active === t.id && <Thread ticket={t} onChanged={load} />}
          </li>
        ))}
      </ul>
    </div>
  );
}
