import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchAnalytics, fetchCallQuality, fetchTodayQueue } from "../api/client.js";
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

/* Compact call-quality stat — smaller sibling of Hero, count-up on the value. */
function QStat({ label, value, sub, suffix = "" }) {
  const ref = useRef(null);
  useEffect(() => {
    countUp(ref.current, value ?? 0, { duration: 1.0, suffix });
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="rounded-xl border border-hairline bg-white px-4 py-3">
      <p className="eyebrow">{label}</p>
      <p ref={ref} className="numeral mt-1 text-3xl text-teal-deep">0</p>
      {sub && <p className="mt-1 font-ui text-xs text-slate">{sub}</p>}
    </div>
  );
}

/* 14-day stacked bars (attended / no-show / cancelled) + show-rate line.
   Motion (GSAP, Emil Kowalski principles): bars grow from their baseline
   (origin-aware transform, not opacity-only), staggered left→right so the
   eye reads time; the show-rate line draws itself after the bars land.
   power3.out = fast start, soft landing — interruptible, never bouncy. */
function TrendChart({ daily, calls }) {
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
        svg.querySelectorAll("polyline").forEach((line, i) => {
          if (line.getAttribute("stroke-dasharray")) {
            // dashed calls line: dash-draw would erase its pattern — fade it
            gsap.fromTo(line, { autoAlpha: 0 }, { autoAlpha: 0.85, duration: 0.6, delay: 0.6 });
            return;
          }
          const len = line.getTotalLength();
          gsap.fromTo(
            line,
            { strokeDasharray: len, strokeDashoffset: len },
            { strokeDashoffset: 0, duration: 0.8, ease: "power2.inOut", delay: 0.4 + i * 0.15 }
          );
        });
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
  // Calls-answered line shares the chart (incorporated, per Vinay) on its own
  // implicit scale so a quiet day still shows shape.
  const maxCalls = Math.max(1, ...(calls ?? []).map((c) => c.calls));
  const callPts = (calls ?? [])
    .map((c, i) => `${x(i) + BW / 2},${H - PAD - (c.calls / maxCalls) * (H - PAD * 2) * 0.9}`)
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
      {callPts && (
        <polyline points={callPts} fill="none" stroke="#155e75" strokeWidth="2"
          strokeDasharray="5 4" strokeLinecap="round" opacity="0.85" />
      )}
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

/* Minutes-used donut: GSAP sweeps the arc, count-up in the middle. */
function MinutesDonut({ minutes }) {
  const arcRef = useRef(null);
  const R = 54, C = 2 * Math.PI * R;
  const frac = Math.min((minutes?.used ?? 0) / Math.max(minutes?.included ?? 1, 1), 1);
  useEffect(() => {
    if (!arcRef.current) return;
    let mm;
    import("gsap").then(({ gsap }) => {
      mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        gsap.fromTo(
          arcRef.current,
          { strokeDashoffset: C },
          { strokeDashoffset: C * (1 - frac), duration: 1.1, ease: "power3.out", delay: 0.2 }
        );
      });
      mm.add("(prefers-reduced-motion: reduce)", () => {
        gsap.set(arcRef.current, { strokeDashoffset: C * (1 - frac) });
      });
    });
    return () => mm?.revert();
  }, [frac]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="flex items-center gap-5">
      <svg viewBox="0 0 140 140" className="h-36 w-36 shrink-0" role="img" aria-label="Voice minutes used">
        <circle cx="70" cy="70" r={R} fill="none" stroke="#d8ece7" strokeWidth="14" />
        <circle ref={arcRef} cx="70" cy="70" r={R} fill="none" stroke="#0e7490" strokeWidth="14"
          strokeLinecap="round" strokeDasharray={C} strokeDashoffset={C}
          transform="rotate(-90 70 70)" />
        <text x="70" y="66" textAnchor="middle" className="fill-teal-deep" fontSize="22"
          fontWeight="600" fontFamily="ui-sans-serif">{minutes?.pct ?? 0}%</text>
        <text x="70" y="84" textAnchor="middle" className="fill-slate" fontSize="10"
          fontFamily="ui-sans-serif">of plan</text>
      </svg>
      <div className="font-ui text-sm">
        <p className="numeral text-3xl text-teal-deep">{minutes?.used ?? 0}<span className="text-base text-slate"> min</span></p>
        <p className="mt-1 text-slate">of {minutes?.included ?? 0} included this month</p>
        <p className="mt-2 text-xs text-slate">AI call minutes across all numbers</p>
      </div>
    </div>
  );
}

/* Busiest weekdays: 7 bars, tallest = peak day. */
function WeekdayBars({ load }) {
  const wrapRef = useRef(null);
  const max = Math.max(1, ...(load ?? []).map((w) => w.bookings));
  const peak = (load ?? []).reduce((a, b) => (b.bookings > (a?.bookings ?? -1) ? b : a), null);
  useEffect(() => {
    if (!wrapRef.current) return;
    let mm;
    import("gsap").then(({ gsap }) => {
      mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        gsap.fromTo(
          wrapRef.current.querySelectorAll("[data-wbar]"),
          { scaleY: 0, transformOrigin: "center bottom" },
          { scaleY: 1, duration: 0.5, ease: "power3.out", stagger: 0.05 }
        );
      });
    });
    return () => mm?.revert();
  }, [load]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div>
      <div ref={wrapRef} className="flex h-28 items-end gap-2">
        {(load ?? []).map((w) => (
          <div key={w.weekday} className="flex flex-1 flex-col items-center gap-1.5">
            <div data-wbar
              className={`w-full rounded-t-md ${w === peak && w.bookings > 0 ? "bg-teal" : "bg-teal-light/50"}`}
              style={{ height: `${(w.bookings / max) * 100}%`, minHeight: w.bookings ? 6 : 2 }}
              title={`${w.weekday}: ${w.bookings} bookings`} />
            <span className={`font-ui text-[10px] ${w === peak && w.bookings > 0 ? "font-semibold text-teal-deep" : "text-slate"}`}>
              {w.weekday}
            </span>
          </div>
        ))}
      </div>
      {peak?.bookings > 0 && (
        <p className="mt-2 font-ui text-xs text-slate">
          Busiest day: <b className="text-teal-deep">{peak.weekday}</b> ({peak.bookings} bookings)
        </p>
      )}
    </div>
  );
}

function Legend() {
  const items = [
    ["#0e7490", "Seen"],
    ["#99d6cc", "Upcoming"],
    ["#d97706", "No-show"],
    ["#cbd5d1", "Cancelled"],
    ["#b7791f", "Show-rate line"],
    ["#155e75", "Calls answered (dashed)"]
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

const fmtDay = (iso) =>
  new Date(iso + "T00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" });

/* Collapse per-date leave rows into "Dr X on leave from A to B" ranges. */
function groupLeave(rows) {
  const groups = [];
  for (const l of rows) {
    const last = groups[groups.length - 1];
    const prevDate = last && new Date(last.to + "T00:00");
    const isNext =
      last && last.doctor === l.doctor_name &&
      (new Date(l.date + "T00:00") - prevDate) / 86400000 === 1;
    if (isNext) {
      last.to = l.date;
      last.coversToday = last.coversToday || l.is_today;
      last.reason = last.reason || l.reason;
    } else {
      groups.push({
        doctor: l.doctor_name, from: l.date, to: l.date,
        reason: l.reason, coversToday: l.is_today
      });
    }
  }
  return groups;
}

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
  const { data: cq } = useQuery({
    queryKey: ["call-quality", branchId, days],
    queryFn: () => fetchCallQuality(branchId, days),
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

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <Hero label="Bookings today" value={s.total} sub="voice + walk-in" />
        <Hero label="Calls answered" value={an?.calls_today ?? 0} sub="AI picked up today" />
        <Hero label="Patients seen" value={s.attended} />
        <Hero label="In queue now" value={s.remaining} gold />
        <Hero label="Show rate today" value={todayRate ?? 100} suffix="%"
          sub={todayRate === null ? "no outcomes marked yet" : "seen vs missed"} />
        <Hero label={`Attendance · ${days}d`}
          value={an?.attendance_rate != null ? Math.round(an.attendance_rate * 100) : 100}
          suffix="%" sub="attended of seen-or-missed" />
      </div>

      {/* Minutes + busiest weekdays */}
      <div className="grid gap-6 lg:grid-cols-2">
        <section data-reveal className="card overflow-hidden">
          <header className="border-b border-hairline bg-teal-mint/60 px-5 py-3">
            <h2 className="font-display text-lg font-semibold">Voice minutes · this month</h2>
          </header>
          <div className="px-5 py-4"><MinutesDonut minutes={an?.minutes} /></div>
        </section>
        <section data-reveal className="card overflow-hidden">
          <header className="border-b border-hairline bg-teal-mint/60 px-5 py-3">
            <h2 className="font-display text-lg font-semibold">Busiest days · {days}d</h2>
          </header>
          <div className="px-5 py-4"><WeekdayBars load={an?.weekday_load} /></div>
        </section>
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
          {an?.daily?.length ? <TrendChart daily={an.daily} calls={an.calls_daily} /> : (
            <p className="font-ui text-sm text-slate">Charts appear after your first bookings.</p>
          )}
          <Legend />
        </div>
      </section>

      {/* Call quality — how the AI receptionist is actually performing */}
      <section data-reveal className="card overflow-hidden">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-hairline bg-teal-mint/60 px-5 py-3">
          <h2 className="font-display text-lg font-semibold">Call quality · {days}d</h2>
          <span className="font-ui text-xs text-slate">{cq?.total_calls ?? 0} calls</span>
        </header>
        {cq && cq.total_calls > 0 ? (
          <div className="px-5 py-4 space-y-4">
            <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-5">
              <QStat label="Booked" value={Math.round((cq.conversion_rate ?? 0) * 100)} suffix="%"
                sub={`${cq.booked} of ${cq.total_calls}`} />
              <QStat label="Abandoned" value={Math.round((cq.abandon_rate ?? 0) * 100)} suffix="%"
                sub="held, never confirmed" />
              <QStat label="Human asked" value={cq.transfers} sub="transfer requests" />
              <QStat label="Avg turns" value={cq.avg_turns ?? 0} sub="patient replies/call" />
              <QStat label="Avg length"
                value={cq.avg_duration_seconds ? Math.round(cq.avg_duration_seconds) : 0}
                suffix="s" sub="per call" />
            </div>
            {(cq.failures ?? []).length > 0 && (
              <div>
                <p className="font-ui text-xs uppercase tracking-wide text-slate mb-2">
                  Why calls didn&rsquo;t book
                </p>
                <div className="flex flex-wrap gap-2">
                  {cq.failures.map((f) => (
                    <span key={f.reason}
                      className="rounded-full bg-teal-pale px-3 py-1 font-ui text-xs text-slate">
                      {f.reason.replace(/_/g, " ")} · {f.count}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <p className="px-5 py-4 font-ui text-sm text-slate">
            Call-quality insights appear after your first AI calls.
          </p>
        )}
      </section>

      {/* Doctors on leave — today highlighted; receptionist marks leave, owner sees it here */}
      {(an?.on_leave ?? []).length > 0 && (
        <section data-reveal className="card overflow-hidden border-amber-200/70">
          <header className="flex items-center justify-between border-b border-hairline bg-amber-50/70 px-5 py-3">
            <h2 className="font-display text-lg font-semibold">Doctors on leave</h2>
            <span className="font-ui text-xs text-slate">next 30 days</span>
          </header>
          <div className="divide-y divide-hairline">
            {groupLeave(an.on_leave).map((g) => (
              <div key={`${g.doctor}-${g.from}`} className="flex items-center justify-between px-5 py-3">
                <div className="flex items-center gap-2.5">
                  {/* dot = real semantic state: leave covers TODAY, patients being called */}
                  {g.coversToday && <span className="h-2 w-2 rounded-full bg-amber-500" aria-label="on leave today" />}
                  <p className="font-ui text-sm font-medium">{g.doctor}</p>
                  {g.reason && <span className="font-ui text-xs text-slate">· {g.reason}</span>}
                </div>
                <p className={`font-ui text-sm ${g.coversToday ? "font-semibold text-amber-700" : "text-slate"}`}>
                  {g.from === g.to ? fmtDay(g.from) : `${fmtDay(g.from)} to ${fmtDay(g.to)}`}
                  {g.coversToday && " · patients being informed by call"}
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
          {[...(an?.by_doctor ?? [])].sort((a, b) => b.booked - a.booked).map((d, i, arr) => (
            <div key={d.doctor_name} className="ledger-row relative">
              {i === 0 && d.booked > 0 && (
                <span className="absolute right-5 top-1.5 rounded-full bg-teal-mint px-2 py-0.5 font-ui text-[10px] font-semibold text-teal-deep">
                  most patients
                </span>
              )}
              {i === arr.length - 1 && arr.length > 1 && d.booked < arr[0].booked && (
                <span className="absolute right-5 top-1.5 rounded-full bg-amber-50 px-2 py-0.5 font-ui text-[10px] font-semibold text-amber-700">
                  needs attention
                </span>
              )}
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
