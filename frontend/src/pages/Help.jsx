import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { getKb, sendChat } from "../api/support";
import ThemeToggle from "../components/ThemeToggle.jsx";

export default function Help() {
  const [kb, setKb] = useState("");
  const [filter, setFilter] = useState("");
  const [q, setQ] = useState("");
  const [msgs, setMsgs] = useState([]); // {role:'user'|'bot', content}
  const [ticketId, setTicketId] = useState(null);
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);

  useEffect(() => {
    getKb().then((d) => setKb(d.markdown || "")).catch(() => setKb(""));
  }, []);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs]);

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
      setMsgs((m) => [
        ...m,
        { role: "bot", content: "Something went wrong — email hello@vachanam.in and we'll help." },
      ]);
    } finally {
      setBusy(false);
    }
  };

  // Client-side section search (corpus is small).
  const shown = filter
    ? kb
        .split(/\n(?=## )/)
        .filter((s) => s.toLowerCase().includes(filter.toLowerCase()))
        .join("\n")
    : kb;

  return (
    <div className="min-h-[100dvh] bg-cream text-ink">
      <header className="border-b border-hairline">
        <div className="mx-auto flex h-14 max-w-3xl items-center px-4">
          <Link to="/" className="font-brand text-xl text-teal">Vachanam</Link>
          <div className="ml-auto"><ThemeToggle /></div>
        </div>
      </header>

      <main className="mx-auto max-w-3xl space-y-8 px-4 py-8">
        <div>
          <h1 className="font-display text-2xl font-semibold">Help &amp; support</h1>
          <p className="text-ink-soft">Search our guides or ask the assistant anything about Vachanam.</p>
        </div>

        <section className="space-y-3">
          <input
            className="input"
            placeholder="Search help articles…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <article className="whitespace-pre-wrap rounded-2xl border border-hairline bg-surface/85 p-4 text-sm leading-relaxed">
            {shown || "No articles found."}
          </article>
        </section>

        <section className="space-y-3">
          <h2 className="font-display text-lg font-semibold">Ask the assistant</h2>
          <div className="h-80 space-y-2 overflow-y-auto rounded-2xl border border-hairline bg-surface/85 p-3">
            {msgs.length === 0 && (
              <p className="text-sm text-ink-soft">
                Ask about pricing, setup, languages, or a call that didn't work.
              </p>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={m.role === "user" ? "text-right" : "text-left"}>
                <span
                  className={
                    "inline-block max-w-[85%] rounded-2xl px-3 py-2 text-sm " +
                    (m.role === "user" ? "bg-teal text-white" : "bg-teal-mint text-ink")
                  }
                >
                  {m.content}
                </span>
              </div>
            ))}
            <div ref={endRef} />
          </div>
          <form onSubmit={ask} className="flex gap-2">
            <input
              className="input flex-1"
              placeholder="Type your question…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <button className="btn-primary" disabled={busy}>{busy ? "…" : "Send"}</button>
          </form>
          <p className="text-xs text-ink-soft">
            Please don't share patient names, phone numbers, or health details here.
          </p>
        </section>
      </main>
    </div>
  );
}
