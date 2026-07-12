import ThemeToggle from "../components/ThemeToggle.jsx";
import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import gsap from "gsap";
import VoicePicker from "../components/VoicePicker.jsx";
import { API_BASE } from "../api/client.js";

const PLANS = [
  {
    name: "Starter",
    key: "solo",
    price: "₹5,999",
    per: "/month + ₹5/min after",
    tagline: "Solo practitioners",
    points: ["≈250 calls included (700 min)", "1 doctor · 1 AI phone number", "Telugu voice agent", "Token booking + calendar", "Reminder calls + receptionist app"]
  },
  {
    name: "Clinic",
    key: "clinic",
    price: "₹9,999",
    per: "/month + ₹5/min after",
    tagline: "Growing clinics, up to 5 doctors",
    popular: true,
    points: ["≈540 calls included (1,500 min)", "5 doctors", "Telugu + Hindi + English", "AI speaks in YOUR cloned voice", "Treatment follow-up calls", "Owner analytics"]
  },
  {
    name: "Multi",
    key: "multi",
    price: "₹17,999",
    per: "/month + ₹5/min after",
    tagline: "Multi-specialty, unlimited doctors",
    points: ["≈1,080 calls included (3,000 min)", "Unlimited doctors", "All 8 Indian languages", "Your voice in every language", "Multi-doctor routing", "CSV exports"]
  }
];

const STEPS = [
  ["Patient calls", "Your existing number forwards to your Vachanam AI line."],
  ["AI answers in your language", "Understands the problem, matches the right doctor."],
  ["Token assigned", "Atomic numbering — two callers can never get the same token."],
  ["Everyone notified", "Calendar event created. Your front desk sees it instantly."]
];

export default function Landing() {
  const heroRef = useRef(null);
  const rootRef = useRef(null);

  useEffect(() => {
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

  return (
    <div ref={rootRef} className="overflow-x-clip">
      {/* Nav */}
      <header className="sticky top-0 z-40 border-b border-hairline bg-cream/80 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4">
          <span className="font-brand text-2xl text-teal">Vachanam</span>
          <nav className="hidden items-center gap-6 font-ui text-sm md:flex">
            <a href="#how" className="text-ink-soft hover:text-teal">How it works</a>
            <a href="#voices" className="text-ink-soft hover:text-teal">Voices</a>
            <a href="#pricing" className="text-ink-soft hover:text-teal">Pricing</a>
            <Link to="/help" className="text-ink-soft hover:text-teal">Help</Link>
          </nav>
          <div className="flex items-center gap-3">
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
              languages, books the right doctor, assigns the token, updates your calendar —
              in under four minutes, around the clock.
            </p>
            <div data-hero className="mt-8 flex flex-wrap items-center gap-4">
              <a href="#pricing" className="btn-primary px-6 py-3">Start 14-day free trial</a>
              <a href="#voices" className="btn-ghost px-6 py-3">Hear the voices</a>
            </div>
            <p data-hero className="mt-4 font-ui text-xs text-slate">
              No credit card · 300 free minutes (≈100 calls) · cancel anytime
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
      <section className="border-y border-hairline bg-[#0e4a49] text-white">
        <div className="mx-auto grid max-w-6xl grid-cols-2 gap-6 px-4 py-10 text-center md:grid-cols-4">
          {[["20–30%", "calls missed by busy clinics"], ["₹3,000+", "lost revenue every day"], ["< 4 min", "average booking call"], ["24×7", "your line never sleeps"]].map(([n, l]) => (
            <div key={l}>
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

      {/* Languages */}
      <section id="voices" data-section className="border-y border-hairline bg-teal-mint/50 py-20">
        <div className="mx-auto max-w-6xl px-4">
          <p data-item className="eyebrow">Speaks your patients&rsquo; language</p>
          <h2 data-item className="mt-2 font-display text-3xl font-semibold tracking-tight sm:text-4xl">
            Eight languages. One warm AI agent.
          </h2>
          <p data-item className="mt-3 max-w-2xl font-ui text-ink-soft">
            Telugu, Hindi, Tamil, Kannada, Malayalam, Marathi, Bengali, Odia — natural pace,
            warm tone. Tap any to hear exactly what your patients will hear. Want your own
            voice? Clinics can clone it.
          </p>
          <div data-item className="mt-8">
            <VoicePicker />
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" data-section className="mx-auto max-w-6xl px-4 py-20">
        <p data-item className="eyebrow">Pricing</p>
        <h2 data-item className="mt-2 font-display text-3xl font-semibold tracking-tight sm:text-4xl">
          Pays for itself with two saved patients a day
        </h2>
        <div className="mt-10 grid gap-6 lg:grid-cols-3">
          {PLANS.map((p) => (
            <div
              key={p.name}
              data-item
              className={`card relative flex flex-col p-7 ${p.popular ? "border-teal shadow-lift ring-1 ring-teal/30" : ""}`}
            >
              {p.popular && (
                <span className="absolute -top-3 left-6 rounded-full bg-gold px-3 py-1 font-ui text-xs font-semibold text-gold-ink">
                  Most popular
                </span>
              )}
              <h3 className="font-display text-xl font-semibold">{p.name}</h3>
              <p className="font-ui text-sm text-slate">{p.tagline}</p>
              <p className="mt-4">
                <span className="numeral text-4xl text-teal-deep">{p.price}</span>
                <span className="font-ui text-sm text-slate"> {p.per}</span>
              </p>
              <ul className="mt-5 flex-1 space-y-2.5">
                {p.points.map((pt) => (
                  <li key={pt} className="flex items-start gap-2 font-ui text-sm">
                    <span className="mt-0.5 text-teal">✓</span> {pt}
                  </li>
                ))}
              </ul>
              <Link to={`/register?plan=${p.key}`} className={p.popular ? "btn-primary mt-6 w-full" : "btn-ghost mt-6 w-full"}>
                Start free trial
              </Link>
            </div>
          ))}
        </div>
        <p data-item className="mt-6 text-center font-ui text-xs text-slate">
          14-day trial · no card · 300 minutes (≈100 calls) · payment link arrives only when you&rsquo;re ready
          <br />
          All prices exclude 18% GST.
        </p>
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
          <Link to="/register" className="btn-gold inline-flex px-8 py-3">Start free trial</Link>
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
