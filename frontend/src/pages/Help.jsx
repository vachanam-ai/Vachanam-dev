import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { getKb, sendChat, submitContact } from "../api/support";
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

  // Contact / demo form → a support ticket (a lead when logged out).
  const [contact, setContact] = useState({ name: "", email: "", subject: "", body: "", category: "sales_demo" });
  const [sent, setSent] = useState(false);
  const [cErr, setCErr] = useState("");
  const submitC = async (e) => {
    e.preventDefault();
    setCErr("");
    try { await submitContact(contact); setSent(true); }
    catch (x) { setCErr(x.response?.data?.detail || "Could not send — email hello@vachanam.in"); }
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

        <section className="space-y-3">
          <h2 className="font-display text-lg font-semibold">Contact us / book a demo</h2>
          {sent ? (
            <p className="rounded-2xl border border-hairline bg-teal-mint p-4 text-sm">
              Thanks — we've got your message and will reply by email soon.
            </p>
          ) : (
            <form onSubmit={submitC} className="grid gap-2 sm:grid-cols-2">
              <input className="input" placeholder="Your name" value={contact.name}
                onChange={(e) => setContact({ ...contact, name: e.target.value })} />
              <input className="input" placeholder="Email" required value={contact.email}
                onChange={(e) => setContact({ ...contact, email: e.target.value })} />
              <input className="input sm:col-span-2" placeholder="Subject" required value={contact.subject}
                onChange={(e) => setContact({ ...contact, subject: e.target.value })} />
              <textarea className="input sm:col-span-2" rows={3} placeholder="How can we help?"
                required value={contact.body}
                onChange={(e) => setContact({ ...contact, body: e.target.value })} />
              <select className="input" value={contact.category}
                onChange={(e) => setContact({ ...contact, category: e.target.value })}>
                <option value="sales_demo">Book a demo</option>
                <option value="billing">Billing</option>
                <option value="technical">Technical</option>
                <option value="onboarding">Onboarding</option>
                <option value="other">Other</option>
              </select>
              <button className="btn-primary sm:col-span-1">Send</button>
              {cErr && <p className="text-sm text-danger sm:col-span-2">{cErr}</p>}
            </form>
          )}
        </section>

        <footer className="border-t border-hairline pt-4 text-sm text-ink-soft">
          Live status:{" "}
          <a className="text-teal hover:underline" href="https://stats.uptimerobot.com"
            target="_blank" rel="noreferrer">status.vachanam.in</a>
          {" · "}Email us at{" "}
          <a className="text-teal hover:underline" href="mailto:hello@vachanam.in">hello@vachanam.in</a>
        </footer>
      </main>
    </div>
  );
}
