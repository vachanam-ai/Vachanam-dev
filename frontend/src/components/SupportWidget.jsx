import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { sendChat } from "../api/support";

/** Floating support chatbot — a launcher bubble (bottom-right) that opens a
 *  small chat window. Grounded assistant; every chat auto-logs a ticket the
 *  clinic can follow up on under Support. Shown app-wide except full-screen
 *  kiosk routes. */
export default function SupportWidget() {
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [msgs, setMsgs] = useState([]);
  const [ticketId, setTicketId] = useState(null);
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, open]);

  // Hide on the waiting-room TV board (public kiosk, no chrome).
  if (pathname.startsWith("/tv/")) return null;

  const ask = async (e) => {
    e.preventDefault();
    const question = q.trim();
    if (!question || busy) return;
    setBusy(true);
    const history = msgs.map((m) => ({ role: m.role, content: m.content }));
    setMsgs((m) => [...m, { role: "user", content: question }]);
    setQ("");
    try {
      const res = await sendChat({ question, history, ticketId });
      setTicketId(res.ticket_id);
      setMsgs((m) => [...m, { role: "bot", content: res.answer }]);
    } catch {
      setMsgs((m) => [...m, { role: "bot", content: "Something went wrong — email hello@vachanam.in and we'll help." }]);
    } finally { setBusy(false); }
  };

  return (
    <>
      {/* Chat panel */}
      {open && (
        <div className="fixed bottom-24 right-4 z-50 flex h-[30rem] w-[22rem] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-2xl border border-hairline bg-surface shadow-card">
          <div className="flex items-center gap-2 bg-teal px-4 py-3 text-white">
            <div className="grid h-8 w-8 place-items-center rounded-full bg-white/20 font-brand">V</div>
            <div className="leading-tight">
              <p className="text-sm font-semibold">Vachanam Assistant</p>
              <p className="text-[11px] text-white/80">Usually replies instantly</p>
            </div>
            <button className="ml-auto text-white/90 hover:text-white" aria-label="Close chat"
              onClick={() => setOpen(false)}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                strokeWidth="2" strokeLinecap="round"><line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" /></svg>
            </button>
          </div>

          <div className="flex-1 space-y-2 overflow-y-auto bg-cream/40 p-3">
            {msgs.length === 0 && (
              <p className="text-sm text-ink-soft">Hi! Ask me anything about Vachanam — pricing, setup, your plan, a call that didn't work.</p>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={m.role === "user" ? "text-right" : "text-left"}>
                <span className={"inline-block max-w-[85%] rounded-2xl px-3 py-2 text-sm " +
                  (m.role === "user" ? "bg-teal text-white" : "bg-teal-mint text-ink")}>
                  {m.content}
                </span>
              </div>
            ))}
            <div ref={endRef} />
          </div>

          <form onSubmit={ask} className="flex items-center gap-2 border-t border-hairline p-2.5">
            <input className="input flex-1" placeholder="Type your question…" value={q}
              onChange={(e) => setQ(e.target.value)} />
            <button
              className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-teal text-white transition hover:brightness-110 disabled:opacity-40"
              disabled={busy || !q.trim()} aria-label="Send"
            >
              {busy ? (
                <span className="text-xs">…</span>
              ) : (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                  <path d="M2.01 21 23 12 2.01 3 2 10l15 2-15 2z" />
                </svg>
              )}
            </button>
          </form>
          <Link to="/tickets" onClick={() => setOpen(false)}
            className="border-t border-hairline py-2 text-center text-xs text-teal hover:underline">
            View all my tickets
          </Link>
        </div>
      )}

      {/* Launcher bubble */}
      <button
        aria-label={open ? "Close support chat" : "Open support chat"}
        onClick={() => setOpen((o) => !o)}
        className="fixed bottom-6 right-6 z-50 grid h-14 w-14 place-items-center rounded-full bg-teal text-white shadow-card transition hover:brightness-110">
        {open ? (
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2" strokeLinecap="round"><polyline points="6 9 12 15 18 9" /></svg>
        ) : (
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.8-.9L3 21l1.9-5.7a8.5 8.5 0 0 1-.9-3.8A8.38 8.38 0 0 1 12.5 3 8.38 8.38 0 0 1 21 11.5z" />
          </svg>
        )}
      </button>
    </>
  );
}
