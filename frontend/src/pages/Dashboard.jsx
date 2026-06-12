import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchAnalytics, fetchTodayQueue } from "../api/client.js";
import { useAuth } from "../hooks/useAuth.jsx";
import { countUp, revealStagger } from "../lib/motion.js";

function Hero({ label, value, sub, gold, suffix = "" }) {
  const ref = useRef(null);
  useEffect(() => {
    countUp(ref.current, value ?? 0, { duration: 1.1, suffix });
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div data-reveal className="card px-6 py-5">
      <p className="eyebrow">{label}</p>
      <p ref={ref} className={`numeral mt-1 text-5xl ${gold ? "text-gold-ink" : "text-teal-deep"}`}>0</p>
      {sub && <p className="mt-1 font-ui text-xs text-slate">{sub}</p>}
    </div>
  );
}

/* 14-day stacked bars (attended / no-show / cancelled) + show-rate line.
   Motion (GSAP, Emil Kowalski principles): bars grow from their baseline
   (origin-aware transform, not opacity-only), staggered left→right so the
   eye reads time; the show-rate line draws itself after the bars land.
   power3.out = fast start, soft landing — interruptible, never bouncy. */
function TrendChart({ daily }) {
  const svgRef = useRef(null);
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    let mm;
    import("gsap").then(({ gsap }) => {
      // gsap.matchMedia: bars/line animate only when motion is welcome;
      // reduced-motion users get the chart instantly (gsap-core a11y rule).
      mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        gsap.fromTo(
          svg.querySelectorAll("rect"),
          { scaleY: 0, transformOrigin: "center bottom" },
          { scaleY: 1, duration: 0.55, ease: "power3.out", stagger: 0.018 }
        );
        const line = svg.querySelector("polyline");
        if (line) {
          const len = line.getTotalLength();
          gsap.fromTo(
            line,
            { strokeDasharray: len, strokeDashoffset: len },
            { strokeDashoffset: 0, duration: 0.8, ease: "power2.inOut", delay: 0.4 }
          );
        }
      });
    });
    return () => mm?.revert();
  }, [daily]);
  const W = 720, H = 220, PAD = 28, BW = Math.max(8, (W - PAD * 2) / Math.max(daily.length, 1) - 8);
  const maxBooked = Math.max(1, ...daily.map((d) => d.booked + d.cancelled));
  const x = (i) => PAD + i * ((W - PAD * 2) / Math.max(daily.length, 1)) + 4;
  const yh = (n) => (n / maxBooked) * (H - PAD * 2);
  const ratePts = daily
    .map((d, i) => (d.show_rate === null ? null : `${x(i) + BW / 2},${H - PAD - d.show_rate * (H - PAD * 2)}`))
    .filter(Boolean)
    .join(" ");
  return (
    <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Daily bookings and show rate">
      {[0.25, 0.5, 0.75, 1].map((g) => (
        <line key={g} x1={PAD} x2={W - PAD} y1={H - PAD - g * (H - PAD * 2)} y2={H - PAD - g * (H - PAD * 2)}
          stroke="#0f3d3a" strokeOpacity="0.08" strokeDasharray="3 5" />
      ))}
      {daily.map((d, i) => {
        const att = yh(d.attended), ns = yh(d.no_show), pend = yh(Math.max(d.booked - d.attended - d.no_show, 0)), can = yh(d.cancelled);
        let y = H - PAD;
        const seg = (h, fill, key, rx = 0) => {
          y -= h;
          return h > 0 ? <rect key={key} x={x(i)} y={y} width={BW} height={h} fill={fill} rx={rx} /> : null;
        };
        return (
          <g key={d.date}>
            {seg(att, "#0e7490", "a")}
            {seg(pend, "#99d6cc", "p")}
            {seg(ns, "#d97706", "n")}
            {seg(can, "#cbd5d1", "c", 2)}
            <title>{`${d.date}: ${d.booked} booked, ${d.attended} seen, ${d.no_show} no-show, ${d.cancelled} cancelled`}</title>
          </g>
        );
      })}
      {ratePts && <polyline points={ratePts} fill="none" stroke="#b7791f" strokeWidth="2.5" strokeLinecap="round" />}
      {daily.map((d, i) =>
        i % Math.ceil(daily.length / 7) === 0 ? (
          <text key={d.date} x={x(i) + BW / 2} y={H - 8} textAnchor="middle"
            className="fill-slate" fontSize="10" fontFamily="ui-sans-serif">
            {d.date.slice(5)}
          </text>
        ) : null
      )}
    </svg>
  );
}

function Legend() {
  const items = [
    ["#0e7490", "Seen"],
    ["#99d6cc", "Upcoming"],
    ["#d97706", "No-show"],
    ["#cbd5d1", "Cancelled"],
    ["#b7791f", "Show-rate line"]
  ];
  return (
    <div className="flex flex-wrap gap-4">
      {items.map(([c, l]) => (
        <span key={l} className="flex items-center gap-1.5 font-ui text-xs text-slate">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: c }} /> {l}
        </span>
      ))}
    </div>
  );
}

const SOURCE_LABEL = { voice: "AI voice calls", walk_in: "Walk-ins", whatsapp: "WhatsApp" };

export default function Dashboard() {
  const { branchId } = useAuth();
  const pageRef = useRef(null);
  const [days, setDays] = useState(14);

  const { data: queue, isLoading } = useQuery({
    queryKey: ["queue", branchId],
    queryFn: () => fetchTodayQueue(branchId),
    enabled: Boolean(branchId),
    refetchInterval: 60_000
  });
  const { data: an } = useQuery({
    queryKey: ["analytics", branchId, days],
    queryFn: () => fetchAnalytics(branchId, days),
    enabled: Boolean(branchId),
    refetchInterval: 120_000
  });

  useEffect(() => {
    if (queue) revealStagger(pageRef.current);
  }, [Boolean(queue)]); // eslint-disable-line react-hooks/exhaustive-deps

  if (isLoading) return <p className="font-ui text-slate">Reading today&rsquo;s ledger…</p>;

  const s = queue?.summary ?? { total: 0, attended: 0, no_show: 0, remaining: 0 };
  const seenSoFar = s.attended + s.no_show;
  const todayRate = seenSoFar ? Math.round((s.attended / seenSoFar) * 100) : null;
  const totalSource = Object.values(an?.by_source ?? {}).reduce((a, b) => a + b, 0);

  return (
    <div ref={pageRef} className="space-y-8">
      <div data-reveal>
        <p className="eyebrow">Clinic overview</p>
        <h1 className="section-title text-2xl">Today at a glance</h1>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Hero label="Bookings today" value={s.total} sub="voice + walk-in" />
        <Hero label="Patients seen" value={s.attended} />
        <Hero label="In queue now" value={s.remaining} gold />
        <Hero label="Show rate today" value={todayRate ?? 100} suffix="%"
          sub={todayRate === null ? "no outcomes marked yet" : "of seen-or-missed so far"} />
      </div>

      {/* Trend — bookings, outcomes, show rate over time */}
      <section data-reveal className="card overflow-hidden">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-hairline bg-teal-mint/60 px-5 py-3">
          <h2 className="font-display text-lg font-semibold">Bookings &amp; show rate</h2>
          <div className="flex gap-1">
            {[7, 14, 30].map((d) => (
              <button key={d} onClick={() => setDays(d)}
                className={`rounded-full px-3 py-1 font-ui text-xs font-medium transition-[background-color,transform] duration-150 ease-out active:scale-[0.97] ${
                  days === d ? "bg-teal text-white" : "bg-white text-slate hover:bg-teal-pale"
                }`}>
                {d}d
              </button>
            ))}
          </div>
        </header>
        <div className="space-y-3 px-5 py-4">
          {an?.daily?.length ? <TrendChart daily={an.daily} /> : (
            <p className="font-ui text-sm text-slate">Charts appear after your first bookings.</p>
          )}
          <Legend />
        </div>
      </section>

      {/* Doctors on leave — today highlighted; receptionist marks leave, owner sees it here */}
      {(an?.on_leave ?? []).length > 0 && (
        <section data-reveal className="card overflow-hidden border-amber-200/70">
          <header className="flex items-center justify-between border-b border-hairline bg-amber-50/70 px-5 py-3">
            <h2 className="font-display text-lg font-semibold">Doctors on leave</h2>
            <span className="font-ui text-xs text-slate">next 30 days</span>
          </header>
          <div className="divide-y divide-hairline">
            {an.on_leave.map((l) => (
              <div key={`${l.doctor_name}-${l.date}`} className="flex items-center justify-between px-5 py-3">
                <div className="flex items-center gap-2.5">
                  {/* dot = real semantic state: leave is TODAY, patients being called */}
                  {l.is_today && <span className="h-2 w-2 rounded-full bg-amber-500" aria-label="on leave today" />}
                  <p className="font-ui text-sm font-medium">{l.doctor_name}</p>
                  {l.reason && <span className="font-ui text-xs text-slate">· {l.reason}</span>}
                </div>
                <p className={`font-ui text-sm ${l.is_today ? "font-semibold text-amber-700" : "text-slate"}`}>
                  {l.is_today
                    ? "Today — patients being informed by call"
                    : new Date(l.date + "T00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" })}
                </p>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Where bookings come from */}
        <section data-reveal className="card overflow-hidden">
          <header className="border-b border-hairline bg-teal-mint/60 px-5 py-3">
            <h2 className="font-display text-lg font-semibold">Booking sources · {days}d</h2>
          </header>
          <div className="space-y-3 px-5 py-4">
            {Object.entries(an?.by_source ?? {}).map(([src, n]) => (
              <div key={src}>
                <div className="flex justify-between font-ui text-sm">
                  <span>{SOURCE_LABEL[src] ?? src}</span>
                  <span className="numeral text-teal-deep">{n}</span>
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-teal-pale">
                  <div className="h-full rounded-full bg-teal transition-all duration-700"
                    style={{ width: `${totalSource ? (n / totalSource) * 100 : 0}%` }} />
                </div>
              </div>
            ))}
            {!totalSource && <p className="font-ui text-sm text-slate">No bookings in this period yet.</p>}
            <p className="font-ui text-xs text-slate">
              New patients today: <b className="numeral">{an?.new_patients_today ?? 0}</b> · Pending
              today: <b className="numeral">{an?.pending_today ?? 0}</b>
            </p>
          </div>
        </section>

        {/* Per-doctor period performance */}
        <section data-reveal className="card overflow-hidden">
          <header className="border-b border-hairline bg-teal-mint/60 px-5 py-3">
            <h2 className="font-display text-lg font-semibold">Doctors · {days}d</h2>
          </header>
          {(an?.by_doctor ?? []).map((d) => (
            <div key={d.doctor_name} className="ledger-row">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="truncate font-ui font-medium">{d.doctor_name}</p>
                  <span className={d.booking_type === "token" ? "chip-token" : "chip-slot"}>
                    {d.booking_type === "token" ? "tokens" : "slots"}
                  </span>
                </div>
                <p className="mt-1 font-ui text-xs text-slate">
                  {d.attended} seen · {d.no_show} no-show
                </p>
              </div>
              <div className="shrink-0 text-right">
                <p className="numeral text-2xl text-teal-deep">{d.booked}</p>
                <p className="font-ui text-xs text-slate">
                  {d.show_rate === null ? "—" : `${Math.round(d.show_rate * 100)}% show`}
                </p>
              </div>
            </div>
          ))}
          {(an?.by_doctor ?? []).length === 0 && (
            <p className="px-5 py-6 font-ui text-sm text-slate">No bookings in this period yet.</p>
          )}
        </section>
      </div>

      {/* Live per-doctor queue (today) */}
      <section data-reveal className="card overflow-hidden">
        <header className="border-b border-hairline bg-teal-mint/60 px-5 py-3">
          <h2 className="font-display text-lg font-semibold">Doctor load · live today</h2>
        </header>
        {(queue?.doctors ?? []).map((d) => {
          const seen = d.patients.filter((p) => p.status === "attended").length;
          const pct = d.patients.length ? (seen / d.patients.length) * 100 : 0;
          return (
            <div key={d.doctor_id} className="ledger-row">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="truncate font-ui font-medium">{d.doctor_name}</p>
                  <span className={d.booking_type === "token" ? "chip-token" : "chip-slot"}>
                    {d.booking_type === "token" ? "tokens" : "slots"}
                  </span>
                </div>
                <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-teal-pale">
                  <div className="h-full rounded-full bg-teal transition-all duration-700"
                    style={{ width: `${pct}%` }} />
                </div>
              </div>
              <p className="numeral shrink-0 text-2xl text-teal-deep">
                {seen}<span className="text-base text-slate">/{d.patients.length}</span>
              </p>
            </div>
          );
        })}
        {(queue?.doctors ?? []).length === 0 && (
          <p className="px-5 py-6 font-ui text-sm text-slate">No doctors configured yet.</p>
        )}
      </section>
    </div>
  );
}
