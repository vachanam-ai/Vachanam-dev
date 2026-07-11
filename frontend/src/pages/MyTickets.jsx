import { useEffect, useRef, useState } from "react";
import { listTickets, getTicketMessages, replyToTicket, rateTicket } from "../api/support";

const STATUS_LABEL = {
  ai_resolved: "Answered by assistant",
  open: "With our team",
  pending: "Awaiting your reply",
  resolved: "Resolved",
  closed: "Closed",
};

function Thread({ ticket, onChanged }) {
  const [msgs, setMsgs] = useState([]);
  const [reply, setReply] = useState("");
  const [rated, setRated] = useState(false);
  const pollRef = useRef(null);

  const load = () => getTicketMessages(ticket.id).then(setMsgs).catch(() => setMsgs([]));
  useEffect(() => {
    load();
    // Poll every 5s so a staff reply appears without a refresh (feels live).
    pollRef.current = setInterval(load, 5000);
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
        <div key={i} className={m.sender === "user" ? "text-right" : "text-left"}>
          <span className={"inline-block max-w-[85%] rounded-2xl px-3 py-2 text-sm " +
            (m.sender === "user" ? "bg-teal text-white" :
             m.sender === "bot" ? "bg-teal-pale text-teal-deep" : "bg-teal-mint text-ink")}>
            {m.body}
          </span>
        </div>
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
      <h1 className="font-display text-2xl font-semibold text-ink">My support tickets</h1>
      {tickets.length === 0 && <p className="text-ink-soft">No tickets yet.</p>}
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
