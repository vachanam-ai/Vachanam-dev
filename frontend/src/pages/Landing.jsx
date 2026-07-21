import ThemeToggle from "../components/ThemeToggle.jsx";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { submitContact } from "../api/support";
import Turnstile, { TURNSTILE_ON } from "../components/Turnstile.jsx";
import gsap from "gsap";
import VoicePicker from "../components/VoicePicker.jsx";
import { API_BASE } from "../api/client.js";

// #391 launch offer (Vinay 2026-07-17): actual price struck through, offer
// price for the first 3 months shown big. Source of truth: billing_math
// OFFER_PRICES — keep in sync (guarded by tests/unit/test_launch_offer.py).
// 2026-07-21: 14-day trial, then acquisition price for the first 3 paid months;
// standard list price thereafter. Keep in sync with billing_math.OFFER_PRICES.
const PLANS = [
  {
    name: "Starter",
    key: "solo",
    price: "₹3,999",
    actual: "₹5,999",
    per: "/month + ₹5/min after",
    tagline: "Small clinics, up to 3 doctors",
    points: ["≈250 calls included (700 min)", "3 doctors · 1 AI phone number", "All 8 Indian languages", "AI speaks in YOUR cloned voice", "Token booking + calendar", "Reminder calls + receptionist app"]
  },
  {
    name: "Clinic",
    key: "clinic",
    price: "₹6,999",
    actual: "₹9,999",
    per: "/month + ₹5/min after",
    tagline: "Growing clinics, up to 5 doctors",
    popular: true,
    points: ["≈540 calls included (1,500 min)", "5 doctors", "All 8 Indian languages", "AI speaks in YOUR cloned voice", "WhatsApp confirmations + reminders", "Treatment follow-up calls", "Owner analytics"]
  },
  {
    name: "Multi",
    key: "multi",
    price: "₹11,999",
    actual: "₹17,999",
    per: "/month + ₹5/min after",
    tagline: "Multi-specialty, unlimited doctors",
    points: ["≈1,080 calls included (3,000 min)", "Unlimited doctors", "All 8 Indian languages", "Your voice in every language", "WhatsApp confirmations + reminders", "Multi-doctor routing", "Branch-level analytics"]
  }
];

const STEPS = [
  ["Patient calls", "Your existing number forwards to your Vachanam AI line."],
  ["AI answers in your language", "Understands the problem, matches the right doctor."],
  ["Token assigned", "Atomic numbering. Two callers can never get the same token."],
  ["Everyone notified", "Calendar event created. Your front desk sees it instantly."]
];

export default function Landing() {
  const heroRef = useRef(null);
  const rootRef = useRef(null);

  // #426 founding trial: live slot count gates every free-trial claim on the
  // page. null / fetch-failure / 0 → no claim shown (never advertise what we
  // can't grant). Backend: GET /auth/founding-slots.
  // trial_for_all → every clinic gets it (no counter); else slots_left>0.
  const [slotsLeft, setSlotsLeft] = useState(null);
  const [trialForAll, setTrialForAll] = useState(false);
  useEffect(() => {
    fetch(`${API_BASE}/auth/founding-slots`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!d) return;
        setSlotsLeft(d.slots_left);
        setTrialForAll(Boolean(d.trial_for_all));
      })
      .catch(() => {});
  }, []);
  const trialOn = trialForAll || slotsLeft > 0;

  useEffect(() => {
    // Respect prefers-reduced-motion: content is visible without gsap.
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const ctx = gsap.context(() => {
      gsap.fromTo(
        "[data-hero]",
        { opacity: 0, y: 26 },
        { opacity: 1, y: 0, duration: 0.8, ease: "power3.out", stagger: 0.12 }
      );
      // Scroll-triggered section reveals without the plugin: IntersectionObserver
      document.querySelectorAll("[data-section]").forEach((el) => {
        const io = new IntersectionObserver(
          ([e]) => {
            if (e.isIntersecting) {
              gsap.fromTo(
                el.querySelectorAll("[data-item]"),
                { opacity: 0, y: 20 },
                { opacity: 1, y: 0, duration: 0.6, ease: "power3.out", stagger: 0.08 }
              );
              io.disconnect();
            }
          },
          { threshold: 0.2 }
        );
        io.observe(el);
      });
    }, rootRef);
    return () => ctx.revert();
  }, []);

  // Book-a-demo lead (same /support/contact pipeline + category as Help's form)
  const [demo, setDemo] = useState({ clinic: "", name: "", phone: "", body: "" });
  const [demoSent, setDemoSent] = useState(false);
  const [demoBusy, setDemoBusy] = useState(false);
  const [demoTouched, setDemoTouched] = useState(false);
  const [demoCaptcha, setDemoCaptcha] = useState("");
  const [dErr, setDErr] = useState("");
  const submitDemo = async (e) => {
    e.preventDefault();
    setDErr("");
    setDemoBusy(true);
    try {
      await submitContact({
        name: demo.name,
        phone: demo.phone,
        subject: `Demo request — ${demo.clinic}`.slice(0, 200),
        body: demo.body.trim() || "Please call me to arrange a demo.",
        category: "sales_demo",
      }, demoCaptcha);
      setDemoSent(true);
    } catch (x) {
      setDErr(x.response?.data?.detail === "captcha_failed"
        ? "Please tick the verification box below, then send again."
        : x.response?.data?.detail || "Could not send — email hello@vachanam.in");
    } finally { setDemoBusy(false); }
  };

  return (
    <div ref={rootRef} className="overflow-x-clip">
      {/* Nav */}
      <header className="sticky top-0 z-40 border-b border-hairline bg-cream/80 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4">
          <a href="/" className="font-brand text-2xl text-teal"
            onClick={(e) => { e.preventDefault(); window.scrollTo({ top: 0, behavior: "smooth" }); }}>
            Vachanam
          </a>
          <nav className="hidden items-center gap-6 font-ui text-sm md:flex">
            <a href="#how" className="text-ink-soft hover:text-teal">How it works</a>
            <a href="#voices" className="text-ink-soft hover:text-teal">Voices</a>
            <a href="#pricing" className="text-ink-soft hover:text-teal">Pricing</a>
            <a href="#demo" className="text-ink-soft hover:text-teal">Book a demo</a>
            <Link to="/help" className="text-ink-soft hover:text-teal">Help</Link>
          </nav>
          <div className="flex items-center gap-3">
            {/* Desktop nav is hidden below md — Help must survive on mobile
                (Vinay mobile report 2026-07-14). */}
            <Link to="/help" className="font-ui text-sm text-ink-soft hover:text-teal md:hidden">Help</Link>
            <ThemeToggle />
            <Link to="/login" className="btn-primary px-5 py-2 text-sm">Clinic sign in</Link>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section ref={heroRef} className="relative">
        <div
          className="pointer-events-none absolute inset-0 -z-10"
          style={{
            background:
              "radial-gradient(900px 480px at 75% -5%, rgba(0,143,143,.12), transparent 60%), radial-gradient(700px 420px at 5% 30%, rgba(240,198,116,.10), transparent 55%)"
          }}
        />
        <div className="mx-auto grid max-w-6xl gap-12 px-4 py-20 lg:grid-cols-[1.15fr_1fr] lg:py-28">
          <div>
            <p data-hero className="eyebrow">AI voice agent &amp; receptionist for Indian clinics</p>
            <h1 data-hero className="mt-4 font-display text-5xl font-semibold leading-[1.05] tracking-tight sm:text-6xl">
              Every missed call is a
              <span className="relative whitespace-nowrap">
                <em className="px-2 not-italic text-teal"> patient lost.</em>
              </span>
              <br />
              We answer every one.
            </h1>
            <p data-hero className="mt-6 max-w-xl font-ui text-lg text-ink-soft">
              Vachanam picks up your clinic&rsquo;s calls in natural Telugu and 7 more Indian
              languages, books the right doctor, assigns the token, updates your calendar,
              all in under four minutes, around the clock.
            </p>
            <div data-hero className="mt-8 flex flex-wrap items-center gap-4">
              {trialOn ? (
                <Link to="/register" className="btn-primary px-6 py-3">Start free trial</Link>
              ) : (
                <a href="#pricing" className="btn-primary px-6 py-3">Get started</a>
              )}
              <a href="#demo" className="btn-gold px-6 py-3">Book a demo</a>
              <a href="#voices" className="btn-ghost px-6 py-3">Hear the voices</a>
            </div>
            {/* Trial claims gated on live slots (#426) — guarded by
                test_no_free_trial_claims_on_landing. */}
            <p data-hero className="mt-4 font-ui text-xs text-slate">
              {trialOn ? (
                <>
                  <span className="font-semibold text-gold-ink">
                    14-day free trial
                  </span>
                  {" · "}no credit card{" · "}cancel anytime
                  {!trialForAll && slotsLeft != null && (
                    <> · <span className="numeral">{slotsLeft}</span> {slotsLeft === 1 ? "slot" : "slots"} left</>
                  )}
                </>
              ) : (
                <>Keep your existing number · live the same day · cancel anytime</>
              )}
            </p>
          </div>

          {/* Live call vignette */}
          <div data-hero className="relative">
            <div className="card relative z-10 rotate-1 p-6">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-2">
                  <span className="relative flex h-2.5 w-2.5">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-teal/60" />
                    <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-teal" />
                  </span>
                  <span className="eyebrow">Live call</span>
                </span>
                <span className="numeral text-sm text-slate">0:42</span>
              </div>

              <div className="mt-5 space-y-4 font-ui text-sm">
                {[
                  ["Patient", "“My tooth is hurting — can I come in tomorrow?”", false],
                  ["Vachanam AI", "“Of course. Dr. Srinivas can see you tomorrow morning. May I have your name?”", true],
                  ["Patient", "“Lakshmi.”", false],
                  ["Vachanam AI", null, true],
                ].map(([who, line, isAgent], i) => (
                  <div key={i} className="flex gap-3">
                    <span
                      className={`mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs font-semibold ${
                        isAgent ? "bg-teal text-white" : "bg-teal-mint text-teal-deep"
                      }`}
                    >
                      {isAgent ? "AI" : "P"}
                    </span>
                    <div>
                      <p
                        className={`font-ui text-[11px] font-semibold uppercase tracking-wide ${
                          isAgent ? "text-teal" : "text-slate"
                        }`}
                      >
                        {who}
                      </p>
                      {line ? (
                        <p className="mt-0.5 text-ink-soft">{line}</p>
                      ) : (
                        <p className="mt-0.5 text-ink-soft">
                          “Thank you, Lakshmi. Your token number is{" "}
                          <span className="numeral font-semibold text-teal-deep">8</span>. See you tomorrow morning!”
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>

              <p className="mt-5 border-t border-hairline pt-3 font-ui text-[11px] text-slate">
                A real booking call — spoken in Telugu, shown here in English.
              </p>
            </div>
            <div className="card absolute -bottom-8 -left-6 z-20 -rotate-2 px-5 py-4">
              <p className="eyebrow">Token assigned</p>
              <p className="numeral text-5xl text-teal-deep">8</p>
            </div>
            <div className="absolute -right-4 -top-6 z-0 h-40 w-40 rounded-full bg-gold-soft blur-2xl" />
          </div>
        </div>
      </section>

      {/* Stats strip */}
      <section data-section className="border-y border-hairline bg-[#0e4a49] text-white">
        <div className="mx-auto grid max-w-6xl grid-cols-2 gap-6 px-4 py-10 text-center md:grid-cols-4">
          {[["20-30%", "calls missed by busy clinics"], ["₹3,000+", "lost revenue every day"], ["< 4 min", "average booking call"], ["24×7", "your line never sleeps"]].map(([n, l]) => (
            <div key={l} data-item>
              <p className="numeral text-3xl text-gold sm:text-4xl">{n}</p>
              <p className="mt-1 font-ui text-xs text-[#cfe8e5]/80">{l}</p>
            </div>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section id="how" data-section className="mx-auto max-w-6xl px-4 py-20">
        <p data-item className="eyebrow">How it works</p>
        <h2 data-item className="mt-2 font-display text-3xl font-semibold tracking-tight sm:text-4xl">
          From ring to booked, hands-free
        </h2>
        <div className="mt-10 grid gap-6 md:grid-cols-4">
          {STEPS.map(([t, d], i) => (
            <div key={t} data-item className="card relative p-6">
              <span className="numeral absolute -top-4 left-5 grid h-9 w-9 place-items-center rounded-full bg-teal text-lg text-white shadow-card">
                {i + 1}
              </span>
              <h3 className="mt-3 font-display text-lg font-semibold">{t}</h3>
              <p className="mt-2 font-ui text-sm text-slate">{d}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Feature bento — the product beyond "answer the phone" */}
      <section id="features" data-section className="mx-auto max-w-6xl px-4 pb-20">
        <h2 data-item className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">
          Beyond answering the phone
        </h2>
        <div className="mt-10 grid gap-5 md:grid-cols-6">
          <div data-item className="card p-7 md:col-span-4 border-teal/30 bg-teal-mint/60">
            <h3 className="font-display text-xl font-semibold text-teal-deep">Treatment follow-up calls</h3>
            <p className="mt-2 max-w-lg font-ui text-sm text-ink-soft">
              After a visit, your doctor writes one line of advice. Vachanam calls the
              patient, delivers it in their language, asks how recovery is going, and
              brings the answer back to the doctor. Patients feel cared for; you never
              dial a number.
            </p>
            <div className="mt-5 inline-flex items-center gap-2 rounded-full border border-teal/30 bg-surface/70 px-4 py-2 font-ui text-xs text-teal-deep">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-teal/60" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-teal" />
              </span>
              &ldquo;Doctor asked me to check: how is the swelling today?&rdquo;
            </div>
          </div>
          <div data-item className="card p-7 md:col-span-2">
            <h3 className="font-display text-lg font-semibold">Your own voice</h3>
            <p className="mt-2 font-ui text-sm text-slate">
              Record 15 seconds. The AI answers in your clinic&rsquo;s own voice,
              in every language your patients speak.
            </p>
          </div>
          <div data-item className="card p-7 md:col-span-2">
            <h3 className="font-display text-lg font-semibold">Reminder calls</h3>
            <p className="mt-2 font-ui text-sm text-slate">
              Every booking gets a call before the visit. No-shows drop; your day
              stays predictable.
            </p>
          </div>
          <div data-item className="card p-7 md:col-span-2">
            <h3 className="font-display text-lg font-semibold">Receptionist app</h3>
            <p className="mt-2 font-ui text-sm text-slate">
              Your front desk sees the day&rsquo;s tokens and marks arrivals on any
              phone. No new hardware, nothing to install.
            </p>
          </div>
          <div data-item className="card p-7 md:col-span-2 border-gold/40 bg-gold-soft/50">
            <h3 className="font-display text-lg font-semibold text-gold-ink">Owner dashboard</h3>
            <p className="mt-2 font-ui text-sm text-ink-soft">
              Calls answered, bookings made, minutes used, busiest hours. The whole
              clinic at a glance.
            </p>
          </div>
        </div>
      </section>

      {/* Languages */}
      <section id="voices" data-section className="border-y border-hairline bg-teal-mint/50 py-20">
        <div className="mx-auto max-w-6xl px-4">
          <p data-item className="eyebrow">Speaks your patients&rsquo; language</p>
          <h2 data-item className="mt-2 font-display text-3xl font-semibold tracking-tight sm:text-4xl">
            Eight languages. One warm AI agent.
          </h2>
          <p data-item className="mt-3 max-w-2xl font-ui text-ink-soft">
            Telugu, Hindi, Tamil, Kannada, Malayalam, Marathi, Bengali, Odia. Natural pace,
            warm tone. Tap any to hear exactly what your patients will hear. Want your own
            voice? Clinics can clone it.
          </p>
          <div data-item className="mt-8">
            <VoicePicker />
          </div>
        </div>
      </section>

      {/* Trust — claims mirror docs/support/KNOWLEDGE.md (#420); don't overclaim */}
      <section id="trust" data-section className="mx-auto max-w-6xl px-4 py-20">
        <h2 data-item className="max-w-2xl font-display text-3xl font-semibold tracking-tight sm:text-4xl">
          Patient data is sacred. We treat it that way.
        </h2>
        <div className="mt-10 grid gap-x-10 gap-y-8 border-t border-hairline pt-8 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["DPDP Act 2023", "Built as a Data Processor under India's data protection law, with a signed processing agreement for every clinic."],
            ["Isolated by clinic", "Your patients exist only inside your clinic's account. Never shared, never sold, never used to train AI."],
            ["No call recordings", "Calls are not recorded. Only masked transcripts are kept, and they are deleted after 90 days."],
            ["Encrypted throughout", "TLS on every call and page, AES-256 at rest. Payments run through Razorpay; card numbers never touch us."],
          ].map(([t, d]) => (
            <div key={t} data-item>
              <h3 className="font-display text-lg font-semibold text-teal-deep">{t}</h3>
              <p className="mt-2 font-ui text-sm text-slate">{d}</p>
            </div>
          ))}
        </div>
        <p data-item className="mt-8 font-ui text-sm text-ink-soft">
          The full picture, in plain words:{" "}
          <a href={`${API_BASE}/data-handling`} className="font-semibold text-teal underline-offset-4 hover:underline">
            How we handle your data
          </a>
        </p>
      </section>

      {/* Pricing */}
      <section id="pricing" data-section className="border-t border-hairline mx-auto max-w-6xl px-4 py-20">
        <p data-item className="eyebrow">Pricing</p>
        <h2 data-item className="mt-2 font-display text-3xl font-semibold tracking-tight sm:text-4xl">
          Pays for itself with two saved patients a day
        </h2>
        {/* Lite: entry tier, deliberately small and set apart from the main plans */}
        <div data-item className="mt-8 flex flex-col gap-3 rounded-xl border border-hairline bg-mist/40 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="font-ui text-sm">
              <span className="font-semibold">Lite · <span className="mr-1 text-slate line-through">₹1,999</span><span className="numeral text-teal-deep">₹1,799</span>/mo</span>
              <span className="text-slate"> + ₹5/min after</span>
            </p>
            <p className="font-ui text-xs text-slate">
              For low-volume clinics: ≈55 calls (150 min), 3 doctors, all 8 languages, your cloned voice, reminder + treatment follow-up calls.
            </p>
          </div>
          <Link to="/register?plan=lite" className="btn-ghost shrink-0 px-5 py-2 text-sm">
            Start with Lite
          </Link>
        </div>
        <div className="mt-6 grid gap-6 lg:grid-cols-3">
          {PLANS.map((p) => (
            <div
              key={p.name}
              data-item
              className={`card relative flex flex-col p-7 ${p.popular ? "border-teal shadow-lift ring-1 ring-teal/30" : ""}`}
            >
              {p.popular && (
                <span className="absolute -top-3 left-6 rounded-full bg-gold px-3 py-1 font-ui text-xs font-semibold text-black">
                  Most popular
                </span>
              )}
              <h3 className="font-display text-xl font-semibold">{p.name}</h3>
              <p className="font-ui text-sm text-slate">{p.tagline}</p>
              <p className="mt-4">
                <span className="mr-2 font-ui text-lg text-slate line-through">{p.actual}</span>
                <span className="numeral text-4xl text-teal-deep">{p.price}</span>
                <span className="font-ui text-sm text-slate"> {p.per}</span>
              </p>
              <p className="mt-1 font-ui text-xs font-semibold text-gold-ink">Offer price — first 3 paid months</p>
              {trialOn && (
                <p className="mt-1 font-ui text-xs font-semibold text-teal">
                  Start with a 14-day free trial
                </p>
              )}
              <ul className="mt-5 flex-1 space-y-2.5">
                {p.points.map((pt) => (
                  <li key={pt} className="flex items-start gap-2 font-ui text-sm">
                    <span className="mt-0.5 text-teal">✓</span> {pt}
                  </li>
                ))}
              </ul>
              <Link to={`/register?plan=${p.key}`} className={p.popular ? "btn-primary mt-6 w-full" : "btn-ghost mt-6 w-full"}>
                Get started
              </Link>
            </div>
          ))}
        </div>
        <p data-item className="mt-6 text-center font-ui text-xs text-slate">
          {trialOn
            ? <>Every new clinic starts with a 14-day free trial · no credit card · cancel anytime</>
            : <>Go live the same day · cancel anytime</>}
          <br />
          Offer starts after the trial. Standard price applies from month 4 · ₹5/min beyond included minutes.
        </p>
      </section>

      {/* FAQ — native <details>, answers match product truth (no-trial, #418 unknown-info, pilot) */}
      <section id="faq" data-section className="mx-auto max-w-3xl px-4 pb-20">
        <h2 data-item className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">
          Questions clinics ask us
        </h2>
        <div data-item className="mt-8 divide-y divide-hairline border-y border-hairline">
          {[
            ["Do I need a new phone number?",
             "No. Your existing clinic number forwards to your Vachanam AI line. Patients dial the number they already know; the only change is that someone always answers."],
            ["Is there a free trial?",
             trialOn
               ? "Yes. Every new clinic gets a 14-day free trial with 300 minutes (≈100 calls) included — no credit card needed. After the trial, you continue on your chosen plan; cancel anytime."
               : "You can see everything live on a free demo call before paying, and cancel anytime after you start."],
            ["What if the AI doesn't know an answer?",
             "It never guesses. It tells the patient the clinic will check and get back, logs the question for your staff, and moves on. You see every logged question on your dashboard."],
            ["Does it give medical advice?",
             "Never. Vachanam books appointments, sends reminders and relays your doctor's own follow-up instructions. Diagnosis and advice stay with your doctors."],
            ["How fast can we go live?",
             "The same day. Choose a plan, forward your number, add your doctors and timings. We walk you through it on a call."],
            ["What happens after my included minutes?",
             "Every extra minute is ₹5, on every plan. Your dashboard always shows remaining minutes, so there are no surprises on the invoice."],
          ].map(([q, a]) => (
            <details key={q} className="group py-4">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-display text-lg font-semibold [&::-webkit-details-marker]:hidden">
                {q}
                <span className="shrink-0 text-teal transition-transform group-open:rotate-45" aria-hidden="true">+</span>
              </summary>
              <p className="mt-3 max-w-2xl font-ui text-sm leading-relaxed text-ink-soft">{a}</p>
            </details>
          ))}
        </div>
      </section>

      {/* Book a demo — phone-first lead, same pipeline as Help's demo form
          (Vinay 2026-07-19: "add book demo thing in this home page"). */}
      <section id="demo" className="border-t border-hairline bg-teal-mint/40 py-16">
        <div className="mx-auto max-w-xl px-4">
          <p className="eyebrow text-center">See it answer a real call</p>
          <h2 className="mt-2 text-center font-display text-3xl font-semibold tracking-tight">
            Book a free demo
          </h2>
          <p className="mt-3 text-center font-ui text-sm text-ink-soft">
            Leave your number — we call you, show Vachanam booking a live appointment
            in your language, and answer everything. 15 minutes, no commitment.
          </p>
          {demoSent ? (
            <div className="card mt-8 px-6 py-8 text-center">
              <p className="font-display text-xl font-semibold text-teal-deep">Thank you! 🙏</p>
              <p className="mt-2 font-ui text-sm text-ink-soft">
                We got your request — expect a call within one working day.
              </p>
            </div>
          ) : (
            <form onSubmit={submitDemo} className="card mt-8 space-y-3 px-6 py-6"
              onFocus={() => setDemoTouched(true)}>
              <input className="input w-full" placeholder="Clinic name" required
                value={demo.clinic} onChange={(e) => setDemo({ ...demo, clinic: e.target.value })} />
              <div className="grid gap-3 sm:grid-cols-2">
                <input className="input w-full" placeholder="Your name" required
                  value={demo.name} onChange={(e) => setDemo({ ...demo, name: e.target.value })} />
                <input className="input w-full" type="tel" placeholder="Phone number" required
                  value={demo.phone} onChange={(e) => setDemo({ ...demo, phone: e.target.value })} />
              </div>
              <textarea className="input w-full" rows="2"
                placeholder="Anything specific to show? (optional)"
                value={demo.body} onChange={(e) => setDemo({ ...demo, body: e.target.value })} />
              {TURNSTILE_ON && demoTouched && <Turnstile onToken={setDemoCaptcha} />}
              {dErr && <p className="font-ui text-sm text-danger">{dErr}</p>}
              <button className="btn-primary w-full py-3"
                disabled={demoBusy || (TURNSTILE_ON && !demoCaptcha)}>
                {demoBusy ? "Sending…" : "Book my demo"}
              </button>
            </form>
          )}
        </div>
      </section>

      {/* Closing CTA */}
      <section className="border-t border-hairline bg-[#0e4a49] py-16 text-center text-white">
        <p className="font-brand text-3xl text-gold">Vachanam</p>
        <h2 className="mx-auto mt-4 max-w-2xl font-display text-3xl font-semibold tracking-tight">
          Healing starts with being heard.
        </h2>
        <p className="mt-3 font-ui text-[#cfe8e5]/85">
          <a href="mailto:hello@vachanam.in" className="underline-offset-4 hover:underline">hello@vachanam.in</a>
          {" · "}India
        </p>
        <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
          <Link to="/register" className="btn-gold inline-flex px-8 py-3">Get started</Link>
          <a href="mailto:hello@vachanam.in?subject=Talk%20to%20Vachanam" className="btn inline-flex border border-white/30 px-8 py-3 text-white hover:bg-surface/10">
            Talk to us
          </a>
        </div>
        <p className="mt-8 font-ui text-xs text-[#cfe8e5]/70">
          © 2026 Vachanam · All rights reserved ·{" "}
          <a href={`${API_BASE}/privacy`} className="underline-offset-4 hover:underline">Privacy</a>
          {" · "}
          <a href={`${API_BASE}/terms`} className="underline-offset-4 hover:underline">Terms</a>
          {" · "}
          <a href={`${API_BASE}/data-handling`} className="underline-offset-4 hover:underline">How we handle your data</a>
          {" · "}
          <a href={`${API_BASE}/refunds`} className="underline-offset-4 hover:underline">Refunds & cancellation</a>
        </p>
      </section>
    </div>
  );
}
