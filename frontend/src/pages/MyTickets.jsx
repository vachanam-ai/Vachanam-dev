import { useEffect, useState } from "react";
import { listTickets, getTicketMessages } from "../api/support";

const STATUS_LABEL = {
  ai_resolved: "Answered by assistant",
  open: "With our team",
  pending: "Awaiting your reply",
  resolved: "Resolved",
  closed: "Closed",
};

export default function MyTickets() {
  const [tickets, setTickets] = useState([]);
  const [active, setActive] = useState(null);
  const [thread, setThread] = useState([]);

  useEffect(() => {
    listTickets().then(setTickets).catch(() => setTickets([]));
  }, []);
  useEffect(() => {
    if (active) getTicketMessages(active).then(setThread).catch(() => setThread([]));
    else setThread([]);
  }, [active]);

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h1 className="font-display text-2xl font-semibold text-ink">My support tickets</h1>
      {tickets.length === 0 && <p className="text-ink-soft">No tickets yet.</p>}
      <ul className="space-y-2">
        {tickets.map((t) => (
          <li key={t.id}>
            <button
              className="w-full rounded-2xl border border-hairline bg-surface/85 p-3 text-left transition hover:bg-teal-mint"
              onClick={() => setActive(active === t.id ? null : t.id)}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate font-medium text-ink">{t.subject}</span>
                <span className="chip bg-teal-pale text-teal-deep whitespace-nowrap text-xs">
                  {STATUS_LABEL[t.status] || t.status}
                </span>
              </div>
              <div className="text-xs text-ink-soft">
                {new Date(t.created_at).toLocaleString()}
              </div>
            </button>
            {active === t.id && (
              <div className="space-y-2 rounded-b-2xl border border-t-0 border-hairline bg-surface/85 p-3">
                {thread.map((m, i) => (
                  <div key={i} className={m.sender === "user" ? "text-right" : "text-left"}>
                    <span
                      className={
                        "inline-block max-w-[85%] rounded-2xl px-3 py-2 text-sm " +
                        (m.sender === "user" ? "bg-teal text-white" : "bg-teal-mint text-ink")
                      }
                    >
                      {m.body}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
