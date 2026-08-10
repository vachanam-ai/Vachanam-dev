import { useRef, useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import {
  ArrowRight, CalendarCheck, Check, CheckCircle, Database, FirstAidKit,
  GlobeHemisphereEast, Headset, LockKey, PhoneCall, ShieldCheck, Sparkle,
  Stethoscope, UserCircleCheck, WhatsappLogo,
} from "@phosphor-icons/react";
import ThemeToggle from "../components/ThemeToggle.jsx";
import VoicePicker from "../components/VoicePicker.jsx";
import Turnstile, { TURNSTILE_ON } from "../components/Turnstile.jsx";
import { submitContact } from "../api/support";
import { API_BASE } from "../api/client.js";
import {
  PLAN_CATALOG, VOICE_PLAN_KEYS, OVERAGE_RUPEES, WHATSAPP_ADDON_RUPEES,
  ADDITIONAL_BRANCH_RUPEES, ADDITIONAL_NUMBER_RUPEES, TRIAL_MINUTES,
} from "../lib/plans.js";

gsap.registerPlugin(ScrollTrigger, useGSAP);

const WORKFLOW = [
  { icon: PhoneCall, step: "01", title: "Every call is answered", text: "Your existing clinic number routes to a receptionist that is ready throughout the day." },
  { icon: Database, step: "02", title: "Facts come from your clinic", text: "Doctor, schedule and appointment answers are checked against your configured data before the agent responds." },
  { icon: CalendarCheck, step: "03", title: "The action is completed", text: "Bookings, cancellations and reschedules use deterministic tools, then confirm only the result that was actually saved." },
  { icon: WhatsappLogo, step: "04", title: "Everyone stays informed", text: "The dashboard updates immediately. Connected clinics can send confirmations and reminders in WhatsApp." },
];

const TRUST = [
  { icon: ShieldCheck, title: "Grounded by design", text: "Unknown clinic facts are never invented. Questions that need a doctor are captured for a real answer." },
  { icon: LockKey, title: "Clinic-isolated data", text: "Every patient, doctor and booking query stays inside the active clinic and branch." },
  { icon: UserCircleCheck, title: "Caller privacy", text: "Appointment lookups are scoped to the caller number. One family number can still book for multiple family members." },
  { icon: Stethoscope, title: "No medical improvisation", text: "Vachanam handles reception. Diagnosis, prescriptions and clinical advice stay with qualified doctors." },
];

const FAQ = [
  ["Do patients need a new number?", "No. You can forward the clinic number patients already know to the Vachanam line."],
  ["Can it handle changing doctor schedules?", "Yes. Each doctor can have multiple time windows and date-specific availability. The agent checks the configured date before answering."],
  ["What happens when it does not know an answer?", "It tells the caller the clinic will check, records the question with their name and number, and surfaces it for staff or the doctor."],
  ["Does it provide medical advice?", "No. It can relay clinic-approved information and doctor instructions, but it does not diagnose or prescribe."],
  ["What happens after the included minutes?", `Voice plans continue at ₹${OVERAGE_RUPEES} per minute. Usage and remaining minutes are visible in the clinic workspace.`],
  ["How quickly can we start?", "We configure the clinic, doctors, schedules and call routing with your team. A demo lets you validate the real flow before going live."],
];

function Brand() {
  return (
    <span className="marketing-brand">
      <span className="brand-symbol" aria-hidden><span /><span /><span /></span>
      <span><strong>Vachanam</strong><small>AI clinic receptionist</small></span>
    </span>
  );
}

function CheckItem({ children }) {
  return <li><span><Check size={14} weight="bold" /></span>{children}</li>;
}

export default function Landing() {
  const rootRef = useRef(null);
  const [slotsLeft, setSlotsLeft] = useState(null);
  const [trialForAll, setTrialForAll] = useState(false);
  const [demo, setDemo] = useState({ clinic: "", name: "", phone: "", body: "" });
  const [demoSent, setDemoSent] = useState(false);
  const [demoBusy, setDemoBusy] = useState(false);
  const [demoTouched, setDemoTouched] = useState(false);
  const [demoCaptcha, setDemoCaptcha] = useState("");
  const [demoError, setDemoError] = useState("");

  useEffect(() => {
    fetch(`${API_BASE}/auth/founding-slots`)
      .then((response) => response.ok ? response.json() : null)
      .then((data) => {
        if (!data) return;
        setSlotsLeft(data.slots_left);
        setTrialForAll(Boolean(data.trial_for_all));
      })
      .catch(() => {});
  }, []);
  const trialOn = trialForAll || slotsLeft > 0;

  useGSAP(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) return;
    gsap.from("[data-hero-copy] > *", { opacity: 0, y: 24, duration: .75, stagger: .09, ease: "power3.out" });
    gsap.from("[data-hero-visual]", { opacity: 0, x: 34, scale: .97, duration: .95, ease: "power3.out", delay: .12 });
    gsap.utils.toArray("[data-motion-section]").forEach((section) => {
      const targets = section.querySelectorAll("[data-motion-item]");
      gsap.from(targets, { scrollTrigger: { trigger: section, start: "top 78%", once: true }, opacity: 0, y: 26, duration: .65, stagger: .08, ease: "power3.out" });
    });
    gsap.to(".journey-line-fill", {
      scrollTrigger: { trigger: ".journey-grid", start: "top 72%", end: "bottom 58%", scrub: .35 },
      scaleY: 1, transformOrigin: "top",
    });
  }, { scope: rootRef });

  const submitDemo = async (event) => {
    event.preventDefault();
    setDemoError("");
    setDemoBusy(true);
    try {
      await submitContact({
        name: demo.name,
        phone: demo.phone,
        subject: `Demo request: ${demo.clinic}`.slice(0, 200),
        body: demo.body.trim() || "Please call me to arrange a demo.",
        category: "sales_demo",
      }, demoCaptcha);
      setDemoSent(true);
    } catch (error) {
      setDemoError(error.response?.data?.detail === "captcha_failed"
        ? "Please complete the verification and try again."
        : error.response?.data?.detail || "We could not send this. Email hello@vachanam.in instead.");
    } finally { setDemoBusy(false); }
  };

  return (
    <div ref={rootRef} className="marketing-page">
      <header className="marketing-nav-wrap">
        <nav className="marketing-nav" aria-label="Main navigation">
          <a href="#top" className="marketing-brand-link"><Brand /></a>
          <div className="marketing-nav-links">
            <a href="#workflow">How it works</a><a href="#voices">Languages</a>
            <a href="#pricing">Pricing</a><a href="#trust">Trust</a><Link to="/help">Help</Link>
          </div>
          <div className="marketing-nav-actions"><ThemeToggle /><Link to="/login" className="marketing-signin">Sign in</Link><a href="#demo" className="btn-primary">Book a demo</a></div>
        </nav>
      </header>

      <main id="top">
        <section className="marketing-hero">
          <div data-hero-copy className="marketing-hero-copy">
            <span className="marketing-kicker"><Sparkle size={15} weight="fill" />Reception that stays present</span>
            <h1>Your clinic answers with <em>clarity, warmth and proof.</em></h1>
            <p className="marketing-lede">Vachanam answers patient calls in familiar Indian languages, checks real clinic availability, and completes appointments without losing the conversation.</p>
            <div className="marketing-hero-actions">
              <a href="#demo" className="btn-primary">See a real call <ArrowRight size={18} weight="bold" /></a>
              <a href="#workflow" className="btn-ghost">Explore the workflow</a>
            </div>
            <div className="marketing-proof-row">
              <span><CheckCircle size={18} weight="fill" />Uses your existing number</span>
              <span><CheckCircle size={18} weight="fill" />Date-specific doctor schedules</span>
              <span><CheckCircle size={18} weight="fill" />Atomic appointment actions</span>
            </div>
            {trialOn && <p className="marketing-trial">14 days or {TRIAL_MINUTES} voice minutes, whichever comes first{!trialForAll && slotsLeft != null ? ` · ${slotsLeft} pilot slots left` : ""}</p>}
          </div>

          <figure data-hero-visual className="marketing-hero-visual">
            <div className="marketing-image-frame">
              <img src="/images/clinic-reception-hero.png" alt="A receptionist speaking with a patient in a contemporary Indian clinic" width="1536" height="1024" fetchPriority="high" />
            </div>
            <figcaption>
              <span className="visual-signal"><i /><i /><i /><i /><i /></span>
              <span><strong>One continuous reception flow</strong><small>Call, verify, act, confirm</small></span>
            </figcaption>
          </figure>
        </section>

        <section className="marketing-fact-band" aria-label="Product guarantees">
          <div><Headset size={24} weight="duotone" /><span><strong>Always available</strong><small>When your desk is busy</small></span></div>
          <div><GlobeHemisphereEast size={24} weight="duotone" /><span><strong>7 Indian languages</strong><small>One consistent workflow</small></span></div>
          <div><Database size={24} weight="duotone" /><span><strong>Database grounded</strong><small>No invented availability</small></span></div>
          <div><FirstAidKit size={24} weight="duotone" /><span><strong>Reception only</strong><small>Medical decisions stay human</small></span></div>
        </section>

        <section id="workflow" data-motion-section className="marketing-section journey-section">
          <div className="marketing-section-heading" data-motion-item>
            <span className="marketing-kicker">The operational journey</span>
            <h2>From the first ring to a verified result.</h2>
            <p>The agent speaks naturally. The important actions underneath are controlled, scoped and confirmed by software.</p>
          </div>
          <div className="journey-grid">
            <div className="journey-rail" aria-hidden><span className="journey-line-fill" /></div>
            {WORKFLOW.map(({ icon: Icon, step, title, text }) => (
              <article key={step} data-motion-item className="journey-card">
                <span className="journey-number">{step}</span>
                <span className="journey-icon"><Icon size={24} weight="duotone" /></span>
                <div><h3>{title}</h3><p>{text}</p></div>
              </article>
            ))}
          </div>
        </section>

        <section data-motion-section className="marketing-section">
          <div className="marketing-section-heading compact" data-motion-item>
            <span className="marketing-kicker">A complete front desk</span>
            <h2>Built around clinic reality, not a generic chatbot.</h2>
          </div>
          <div className="feature-bento">
            <article data-motion-item className="feature-card feature-primary">
              <span className="feature-icon"><CalendarCheck size={28} weight="duotone" /></span>
              <div><span>Appointment integrity</span><h3>Book, cancel and reschedule against the same source of truth.</h3><p>Multiple daily time windows, token capacity, date-specific schedules and family bookings from one number are handled in the booking layer.</p></div>
            </article>
            <article data-motion-item className="feature-card feature-saffron"><span className="feature-icon"><Stethoscope size={26} weight="duotone" /></span><h3>Questions for the doctor</h3><p>Unknown clinic questions become visible tasks with the patient name and number, ready for an answer and callback.</p></article>
            <article data-motion-item className="feature-card feature-indigo"><span className="feature-icon"><WhatsappLogo size={26} weight="duotone" /></span><h3>WhatsApp continuity</h3><p>Connected clinics can confirm bookings, reschedules, cancellations and reminders in the patient channel.</p></article>
            <article data-motion-item className="feature-card feature-wide"><span className="feature-quote">“</span><div><span>Conversation discipline</span><h3>Ragebait, interruptions and language changes do not change the receptionist’s role.</h3><p>Identity, privacy and action rules stay enforced even when a caller tries to pull the agent away from clinic work.</p></div></article>
          </div>
        </section>

        <section id="voices" data-motion-section className="voices-section">
          <div className="marketing-section-heading" data-motion-item><span className="marketing-kicker">Hear the experience</span><h2>A familiar voice in the patient’s language.</h2><p>Tap a language to hear the same clinic greeting. Language changes the conversation, not the rules behind it.</p></div>
          <div data-motion-item className="voice-surface"><VoicePicker /></div>
        </section>

        <section id="trust" data-motion-section className="marketing-section trust-section">
          <div className="trust-intro" data-motion-item><span className="marketing-kicker">Trust architecture</span><h2>The safest answer is the one the clinic can verify.</h2><p>Vachanam separates natural conversation from strict operational rules. The patient gets warmth without giving the model permission to invent facts or actions.</p><a href={`${API_BASE}/data-handling`}>How we handle your data <ArrowRight size={16} /></a></div>
          <div className="trust-grid">
            {TRUST.map(({ icon: Icon, title, text }) => <article key={title} data-motion-item><Icon size={25} weight="duotone" /><h3>{title}</h3><p>{text}</p></article>)}
          </div>
        </section>

        <section id="pricing" data-motion-section className="pricing-section">
          <div className="marketing-section-heading" data-motion-item><span className="marketing-kicker">Clear monthly plans</span><h2>Choose capacity, not a stripped-down receptionist.</h2><p>Every voice plan includes the core booking workflow and supported languages. Plans scale by minutes, doctors, branches and WhatsApp.</p></div>
          <div className="pricing-grid">
            {VOICE_PLAN_KEYS.map((key) => {
              const plan = PLAN_CATALOG[key];
              const whatsapp = key !== "solo";
              return (
                <article key={key} data-motion-item className={`pricing-card ${plan.popular ? "is-popular" : ""}`}>
                  {plan.popular && <span className="popular-label">Most popular</span>}
                  <div className="pricing-card-head"><h3>{plan.name}</h3><p>{plan.tagline}</p></div>
                  <p className="price"><sup>₹</sup>{plan.price.toLocaleString("en-IN")}<span>/month</span></p>
                  <ul>
                    <CheckItem>{plan.minutes.toLocaleString("en-IN")} voice minutes</CheckItem>
                    <CheckItem>{plan.doctors}</CheckItem><CheckItem>{plan.branches}</CheckItem>
                    <CheckItem>{whatsapp ? "WhatsApp included" : `WhatsApp add-on ₹${WHATSAPP_ADDON_RUPEES.toLocaleString("en-IN")}`}</CheckItem>
                    <CheckItem>Booking, cancellations and reschedules</CheckItem><CheckItem>All supported languages</CheckItem>
                  </ul>
                  <Link to={`/register?plan=${key}`} className={plan.popular ? "btn-primary" : "btn-ghost"}>Choose {plan.name}<ArrowRight size={17} /></Link>
                </article>
              );
            })}
          </div>
          <div data-motion-item className="pricing-notes">
            <div><WhatsappLogo size={22} weight="duotone" /><span><strong>WhatsApp only</strong><small>₹1,499/month · 3 doctors · 1 branch · no voice line</small></span><Link to="/register?plan=wa">Choose WhatsApp</Link></div>
            <p>Overage ₹{OVERAGE_RUPEES}/minute · Additional branch ₹{ADDITIONAL_BRANCH_RUPEES.toLocaleString("en-IN")}/month · Additional number ₹{ADDITIONAL_NUMBER_RUPEES.toLocaleString("en-IN")}/month</p>
          </div>
        </section>

        <section data-motion-section className="faq-section">
          <div className="marketing-section-heading compact" data-motion-item><span className="marketing-kicker">Practical answers</span><h2>What clinics ask before going live.</h2></div>
          <div className="faq-list" data-motion-item>
            {FAQ.map(([question, answer]) => <details key={question}><summary>{question}<span>+</span></summary><p>{answer}</p></details>)}
          </div>
        </section>

        <section id="demo" data-motion-section className="demo-section">
          <div className="demo-copy" data-motion-item><span className="marketing-kicker">Test the real workflow</span><h2>Let your team hear it before you decide.</h2><p>We will walk through a patient call, doctor availability and an appointment action using a clinic-shaped setup.</p><div className="demo-promise"><CheckCircle size={19} weight="fill" />15 minutes. No commitment.</div></div>
          <div data-motion-item className="demo-form-wrap">
            {demoSent ? <div className="demo-success"><CheckCircle size={36} weight="duotone" /><h3>Request received</h3><p>We will call within one working day to arrange the demo.</p></div> : (
              <form onSubmit={submitDemo} onFocus={() => setDemoTouched(true)}>
                <label><span>Clinic name</span><input className="field" required value={demo.clinic} onChange={(e) => setDemo({ ...demo, clinic: e.target.value })} autoComplete="organization" /></label>
                <div className="demo-form-row">
                  <label><span>Your name</span><input className="field" required value={demo.name} onChange={(e) => setDemo({ ...demo, name: e.target.value })} autoComplete="name" /></label>
                  <label><span>Phone number</span><input className="field" type="tel" required value={demo.phone} onChange={(e) => setDemo({ ...demo, phone: e.target.value })} autoComplete="tel" /></label>
                </div>
                <label><span>What should we demonstrate? <i>Optional</i></span><textarea className="field" rows="3" value={demo.body} onChange={(e) => setDemo({ ...demo, body: e.target.value })} /></label>
                {TURNSTILE_ON && demoTouched && <Turnstile onToken={setDemoCaptcha} />}
                {demoError && <p className="form-error" role="alert">{demoError}</p>}
                <button className="btn-primary" disabled={demoBusy || (TURNSTILE_ON && !demoCaptcha)}>{demoBusy ? "Sending…" : "Book my demo"}<ArrowRight size={17} /></button>
              </form>
            )}
          </div>
        </section>
      </main>

      <footer className="marketing-footer">
        <div><Brand /><p>Precise clinic reception with a human sense of care.</p></div>
        <div><strong>Product</strong><a href="#workflow">How it works</a><a href="#pricing">Pricing</a><Link to="/help">Help centre</Link></div>
        <div><strong>Company</strong><a href="mailto:hello@vachanam.in">hello@vachanam.in</a><a href={`${API_BASE}/privacy`}>Privacy</a><a href={`${API_BASE}/terms`}>Terms</a></div>
        <p>© 2026 Vachanam. Built for clinics in India.</p>
      </footer>
    </div>
  );
}
