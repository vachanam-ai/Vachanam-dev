import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import gsap from "gsap";
import { getKb, sendChat, submitContact } from "../api/support";
import { chatErrorMessage, TypedText, TypingDots } from "../components/ChatBits.jsx";
import ThemeToggle from "../components/ThemeToggle.jsx";
import Turnstile, { TURNSTILE_ON } from "../components/Turnstile.jsx";

/** Tiny markdown renderer for KB bodies: **bold** → <strong>, rest as-is
 *  (bullets already read naturally as "- x" lines). */
function mdLite(text) {
  return text.split(/\*\*(.+?)\*\*/g).map((seg, i) =>
    i % 2 ? <strong key={i} className="font-semibold text-ink">{seg}</strong> : seg
  );
}

export default function Help() {
  const [kb, setKb] = useState("");
  const [filter, setFilter] = useState("");
  const [q, setQ] = useState("");
  const [msgs, setMsgs] = useState([]); // {role:'user'|'bot', content, typed}
  const [ticketId, setTicketId] = useState(null);
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);
  const pageRef = useRef(null);

  useEffect(() => {
    getKb().then((d) => setKb(d.markdown || "")).catch(() => setKb(""));
  }, []);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs, busy]);
  const scrollToEnd = () => endRef.current?.scrollIntoView({ behavior: "auto" });
  const markTyped = (i) =>
    setMsgs((m) => m.map((msg, j) => (j === i ? { ...msg, typed: true } : msg)));

  // "## Section" → accordion items.
  const sections = useMemo(() => {
    return kb
      .split(/\n(?=## )/)
      .map((s) => s.trim())
      .filter(Boolean)
      .map((p) => {
        const [first, ...rest] = p.split("\n");
        return { title: first.replace(/^#+\s*/, ""), body: rest.join("\n").trim() };
      })
      .filter((s) => s.body);
  }, [kb]);
  const shown = filter
    ? sections.filter((s) =>
        (s.title + " " + s.body).toLowerCase().includes(filter.toLowerCase()))
    : sections;

  // One orchestrated entrance once the KB has landed (keyed on load, not
  // mount — a mount-only reveal misses late content, FIXLOG #334).
  useEffect(() => {
    if (!sections.length || !pageRef.current) return undefined;
    const mm = gsap.matchMedia();
    mm.add(
      { reduce: "(prefers-reduced-motion: reduce)", ok: "(prefers-reduced-motion: no-preference)" },
      (ctx) => {
        if (ctx.conditions.reduce) return;
        gsap.fromTo(
          pageRef.current.querySelectorAll("[data-help-reveal]"),
          { opacity: 0, y: 16 },
          { opacity: 1, y: 0, duration: 0.5, ease: "power3.out", stagger: 0.06, clearProps: "transform" }
        );
      }
    );
    return () => mm.revert();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sections.length]);

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
      setMsgs((m) => [...m, { role: "bot", content: res.answer, typed: false }]);
    } catch (err) {
      setMsgs((m) => [...m, { role: "bot", content: chatErrorMessage(err), typed: true }]);
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

  return (
    <div ref={pageRef} className="min-h-[100dvh] bg-cream text-ink">
      <header className="border-b border-hairline">
        <div className="mx-auto flex h-14 max-w-3xl items-center px-4">
          <Link to="/" className="font-brand text-xl text-teal">Vachanam</Link>
          <div className="ml-auto"><ThemeToggle /></div>
        </div>
      </header>

      <main className="mx-auto max-w-3xl space-y-8 px-4 py-8">
        <div data-help-reveal>
          <h1 className="font-display text-2xl font-semibold">Help &amp; support</h1>
          <p className="text-ink-soft">Search our guides or ask the assistant anything about Vachanam.</p>
        </div>

        <section className="space-y-3">
          <input
            data-help-reveal
            className="input"
            placeholder="Search help articles…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          {shown.length === 0 && (
            <p className="rounded-2xl border border-hairline bg-surface/85 p-4 text-sm text-ink-soft">
              No articles found — try the assistant below.
            </p>
          )}
          <div className="space-y-2">
            {shown.map((s) => (
              <details key={s.title} data-help-reveal
                className="group rounded-2xl border border-hairline bg-surface/85 open:shadow-card">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 font-medium [&::-webkit-details-marker]:hidden">
                  <span>{s.title}</span>
                  <span className="shrink-0 text-lg leading-none text-teal transition-transform duration-200 group-open:rotate-45">+</span>
                </summary>
                <div className="whitespace-pre-wrap px-4 pb-4 text-sm leading-relaxed text-ink-soft">
                  {mdLite(s.body)}
                </div>
              </details>
            ))}
          </div>
        </section>

        <section className="space-y-3" data-help-reveal>
          <h2 className="font-display text-lg font-semibold">Ask the assistant</h2>
          <div className="rounded-2xl border border-hairline bg-surface/85 shadow-card">
            <div className="h-80 space-y-2 overflow-y-auto p-3">
              {msgs.length === 0 && (
                <p className="text-sm text-ink-soft">
                  Ask about pricing, setup, languages, data safety, or a call that didn't work.
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
                    {m.role === "bot" ? (
                      <TypedText text={m.content} done={m.typed !== false}
                        onTick={scrollToEnd} onDone={() => markTyped(i)} />
                    ) : (
                      m.content
                    )}
                  </span>
                </div>
              ))}
              {busy && <TypingDots />}
              <div ref={endRef} />
            </div>
            <form onSubmit={ask} className="flex gap-2 border-t border-hairline p-2.5">
              <input
                className="input flex-1"
                placeholder="Type your question…"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
              <button className="btn-primary" disabled={busy || !q.trim()}>{busy ? "…" : "Send"}</button>
            </form>
          </div>
          {TURNSTILE_ON && <Turnstile />}
          <p className="text-xs text-ink-soft">
            Please don't share patient names, phone numbers, or health details here.
          </p>
        </section>

        <section className="space-y-3" data-help-reveal>
          <h2 className="font-display text-lg font-semibold">Contact us / book a demo</h2>
          {sent ? (
            <p className="rounded-2xl border border-hairline bg-teal-mint p-4 text-sm">
              Thanks — we've got your message and will reply by email soon.
            </p>
          ) : (
            <form onSubmit={submitC}
              className="grid gap-2 rounded-2xl border border-hairline bg-surface/85 p-5 shadow-card sm:grid-cols-2">
              <p className="text-sm text-ink-soft sm:col-span-2">
                Tell us about your clinic — we'll show you Vachanam answering a live call in Telugu.
              </p>
              <input className="input" placeholder="Your name" value={contact.name}
                onChange={(e) => setContact({ ...contact, name: e.target.value })} />
              <input className="input" placeholder="Email" required type="email" value={contact.email}
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

        <footer className="border-t border-hairline pt-4 text-sm text-ink-soft" data-help-reveal>
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
