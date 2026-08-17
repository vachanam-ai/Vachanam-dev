import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { CaretDown, ChatCircleDots, PaperPlaneRight, Sparkle, X } from "@phosphor-icons/react";
import { sendChat } from "../api/support";
import { useAuth } from "../hooks/useAuth.jsx";
import { chatErrorMessage, TypedText, TypingDots } from "./ChatBits.jsx";
import Turnstile, { TURNSTILE_ON } from "./Turnstile.jsx";

export default function SupportWidget() {
  const { user } = useAuth();
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]);
  const [ticketId, setTicketId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [captcha, setCaptcha] = useState("");
  const listRef = useRef(null);
  const needCaptcha = TURNSTILE_ON && !user;

  const scrollToEnd = (smooth) => {
    const list = listRef.current;
    if (list) list.scrollTo({ top: list.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  };
  useEffect(() => { scrollToEnd(true); }, [messages, open, busy]);
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  if (pathname.startsWith("/tv/")) return null;

  const markTyped = (index) => setMessages((items) => items.map((item, i) => i === index ? { ...item, typed: true } : item));
  const ask = async (event) => {
    event.preventDefault();
    const text = question.trim();
    if (!text || busy) return;
    setBusy(true);
    const history = messages.map((message) => ({ role: message.role, content: message.content }));
    setMessages((items) => [...items, { role: "user", content: text }]);
    setQuestion("");
    try {
      const response = await sendChat({ question: text, history, ticketId, captcha });
      setTicketId(response.ticket_id);
      setMessages((items) => [...items, { role: "bot", content: response.answer, typed: false }]);
    } catch (error) {
      setMessages((items) => [...items, { role: "bot", content: chatErrorMessage(error), typed: true }]);
    } finally { setBusy(false); }
  };

  return (
    <div className="support-widget">
      {open && (
        <section className="support-panel" aria-label="Vachanam support assistant">
          <header className="support-panel-head">
            <span className="support-agent-icon"><Sparkle size={19} weight="fill" /></span>
            <span><strong>Vachanam support</strong><small><i />Grounded product help</small></span>
            <button type="button" onClick={() => setOpen(false)} aria-label="Close chat"><X size={18} weight="bold" /></button>
          </header>
          <div ref={listRef} className="support-messages" aria-live="polite">
            {messages.length === 0 && (
              <div className="support-welcome"><ChatCircleDots size={25} weight="duotone" /><strong>How can we help?</strong><p>Ask about pricing, setup, your plan or a call that did not work.</p></div>
            )}
            {messages.map((message, index) => (
              <div key={index} className={`support-message ${message.role === "user" ? "is-user" : "is-bot"}`}>
                <span>{message.role === "bot" ? <TypedText text={message.content} done={message.typed !== false} onTick={() => scrollToEnd(false)} onDone={() => markTyped(index)} /> : message.content}</span>
              </div>
            ))}
            {busy && <TypingDots />}
          </div>
          {needCaptcha && <div className="support-captcha"><Turnstile onToken={setCaptcha} /></div>}
          <form onSubmit={ask} className="support-composer">
            <input className="field" aria-label="Support question" placeholder="Type your question…" value={question} onChange={(event) => setQuestion(event.target.value)} />
            <button type="submit" disabled={busy || !question.trim() || (needCaptcha && !captcha)} aria-label="Send"><PaperPlaneRight size={18} weight="fill" /></button>
          </form>
          <Link to="/tickets" onClick={() => setOpen(false)} className="support-tickets-link">Open support history <span>→</span></Link>
        </section>
      )}
      <button type="button" aria-label={open ? "Close support chat" : "Open support chat"} aria-expanded={open} onClick={() => setOpen((value) => !value)} className="support-launcher">
        {open ? <CaretDown size={24} weight="bold" /> : <ChatCircleDots size={27} weight="duotone" />}
        {!open && <span className="support-launcher-dot" />}
      </button>
    </div>
  );
}
