import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchAnalytics, fetchCallQuality, fetchMessages, fetchRatingsSummary,
  fetchTodayQueue, resolveMessage,
} from "../api/client.js";
import TrendChart, { ChartLegend } from "../components/dash/TrendChart.jsx";
import { useAuth } from "../hooks/useAuth.jsx";
import { countUp, revealNow, revealStagger } from "../lib/motion.js";
import PageHeader, { StatRow } from "../components/PageHeader.jsx";

/* Sage stat band — exact port of the approved mockup: hatched-ghost + solid
   bar chart, radial-tick semicircle gauge, two arrow KPIs. */
function BandKpi({ k, cap }) {
  const ref = useRef(null);
  useEffect(() => { countUp(ref.current, k ?? 0); }, [k]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="kpi">
      <div ref={ref} className="k numeral">0</div>
      <div className="r">
        <div className="kcap">{cap}</div>
        <div className="arw">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M7 17 17 7M9 7h8v8" /></svg>
        </div>
      </div>
    </div>
  );
}

function StatBand({ title, weekday, pct, pctCap, waiting, booked }) {
  const days = weekday?.length ? weekday : [];
  const max = Math.max(1, ...days.map((w) => w.bookings));
  const frac = Math.min(Math.max((pct ?? 0) / 100, 0), 1);
  const N = 46, cx = 85, cy = 84, ri = 52, ro = 68;
  const ticks = Array.from({ length: N }, (_, i) => {
    const f = i / (N - 1), a = Math.PI - f * Math.PI, on = f <= frac;
    return { x1: cx + ri * Math.cos(a), y1: cy - ri * Math.sin(a), x2: cx + ro * Math.cos(a), y2: cy - ro * Math.sin(a), on };
  });
  return (
    <div data-reveal className="band">
      <div>
        <div className="bt">{title}</div>
        <div className="chartwrap">
          <div className="yax"><span>{max}</span><span>{Math.round(max / 2)}</span><span>0</span></div>
          <div className="chart">
            {days.map((w) => (
              <div className="day" key={w.weekday}>
                <div className="stack">
                  <div className="ghost" style={{ height: "100%" }} />
                  <div className="val" style={{ height: `${(w.bookings / max) * 100}%`, minHeight: w.bookings ? 4 : 0 }} />
                </div>
                <div className="dname">{w.weekday}</div>
              </div>
            ))}
            {days.length === 0 && <p className="self-center font-ui text-sm text-slate">No bookings yet this period.</p>}
          </div>
        </div>
      </div>
      <div className="gauge">
        <svg viewBox="0 0 170 94" role="img" aria-label={`${pctCap} ${Math.round(pct)}%`}>
          {ticks.map((t, i) => (
            <line key={i} x1={t.x1.toFixed(1)} y1={t.y1.toFixed(1)} x2={t.x2.toFixed(1)} y2={t.y2.toFixed(1)}
              stroke={t.on ? "rgb(var(--ink))" : "rgb(var(--slate-light))"} strokeWidth={t.on ? 2 : 1.4} strokeLinecap="round" />
          ))}
        </svg>
        <div className="pct numeral">{Math.round(pct)}%</div>
        <div className="cap">{pctCap}</div>
      </div>
      <BandKpi k={waiting} cap="Waiting now" />
      <BandKpi k={booked} cap="Booked today" />
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
    <div className="rounded-xl border border-hairline bg-surface px-4 py-3">
      <p className="eyebrow">{label}</p>
      <p ref={ref} className="numeral mt-1 text-3xl text-teal-deep">0</p>
      {sub && <p className="mt-1 font-ui text-xs text-slate">{sub}</p>}
    </div>
  );
}

/* Lifetime band — "since day one" counters, white numerals on deep teal. */
function LifetimeBand({ lifetime }) {
  const ref = useRef(null);
  // #355: renders only once analytics lands — reveals itself if the
  // page-level reveal already ran (idempotent either way).
  useEffect(() => {
    revealNow(ref.current);
  });
  const items = [
    ["bookings", "Bookings", lifetime?.bookings],
    ["calls", "Calls answered", lifetime?.calls],
    ["patients", "Patients", lifetime?.patients],
    ["minutes", "Voice minutes", lifetime?.minutes],
  ];
  return (
    <div ref={ref} data-reveal className="flex flex-wrap items-center gap-x-10 gap-y-3 rounded-2xl bg-sel px-6 py-4 text-sel-ink shadow-lift">
      <p className="eyebrow !text-sel-muted">Since day one</p>
      {items.map(([k, label, v]) => (
        <LifetimeStat key={k} label={label} value={v ?? 0} />
      ))}
    </div>
  );
}

function LifetimeStat({ label, value }) {
  const ref = useRef(null);
  useEffect(() => {
    countUp(ref.current, value ?? 0, { duration: 1.4 });
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <p className="font-ui text-sm text-sel-muted">
      <span ref={ref} className="numeral mr-1.5 text-2xl font-semibold text-sel-ink">0</span>
      {label}
    </p>
  );
}

/* This-month mini stats beside the minutes donut. */
function MonthBlock({ month }) {
  const rows = [
    ["Bookings", month?.bookings],
    ["Calls answered", month?.calls],
    ["New patients", month?.new_patients],
  ];
  return (
    <div className="space-y-2.5">
      {rows.map(([label, v]) => (
        <MonthRow key={label} label={label} value={v ?? 0} />
      ))}
    </div>
  );
}

function MonthRow({ label, value }) {
  const ref = useRef(null);
  useEffect(() => {
    countUp(ref.current, value ?? 0, { duration: 1.0 });
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="flex items-baseline justify-between rounded-lg bg-pill px-3 py-2">
      <span className="font-ui text-xs text-slate">{label}</span>
      <span ref={ref} className="numeral text-xl text-teal-deep">0</span>
    </div>
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
        <circle cx="70" cy="70" r={R} fill="none" className="stroke-line2" strokeWidth="14" />
        <circle ref={arcRef} cx="70" cy="70" r={R} fill="none" className="stroke-accent" strokeWidth="14"
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

/* Caller messages the agent took for the doctor (#349) — pending count badge,
   urgent flagged, done button. Hidden entirely when there are no messages. */
function MessagesCard({ branchId }) {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["messages", branchId],
    queryFn: () => fetchMessages(branchId),
    enabled: Boolean(branchId),
    refetchInterval: 60_000,
  });
  const done = useMutation({
    mutationFn: (id) => resolveMessage(branchId, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["messages", branchId] }),
  });
  const msgs = data?.messages ?? [];
  const ref = useRef(null);
  // #355: this card mounts only after ITS query resolves — it misses the
  // page-level reveal train, so it reveals itself (idempotent).
  useEffect(() => {
    if (msgs.length) revealNow(ref.current);
  });
  if (!msgs.length) return null;
  return (
    <section ref={ref} data-reveal className="card overflow-hidden">
      <header className="flex items-center gap-3 border-b border-hairline bg-pill px-5 py-3">
        <h2 className="font-display text-lg font-semibold">Messages for the doctor</h2>
        {data.pending > 0 && (
          <span className="chip bg-gold-soft text-gold-ink">{data.pending} pending</span>
        )}
      </header>
      <ul className="divide-y divide-hairline">
        {msgs.map((m) => (
          <li key={m.id} className={`flex items-start gap-3 px-5 py-3 ${m.status === "done" ? "opacity-50" : ""}`}>
            <div className="min-w-0 flex-1">
              <p className="font-ui text-sm text-ink">{m.message}</p>
              <p className="mt-1 font-ui text-xs text-slate">
                {m.urgent && <span className="chip-danger mr-2">urgent</span>}
                {m.patient_name || "Unknown caller"}
                {m.caller_phone ? ` · ${m.caller_phone}` : ""}
                {m.created_at ? ` · ${new Date(m.created_at).toLocaleString()}` : ""}
              </p>
            </div>
            {m.status === "pending" && (
              <button
                className="btn-ghost shrink-0 text-xs"
                disabled={done.isPending}
                onClick={() => done.mutate(m.id)}
              >
                Done
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function RatingsCard({ branchId }) {
  const { data } = useQuery({
    queryKey: ["ratings", branchId],
    queryFn: () => fetchRatingsSummary(branchId),
    enabled: Boolean(branchId),
    refetchInterval: 300_000,
  });
  const ref = useRef(null);
  useEffect(() => {
    if (data?.count) revealNow(ref.current);
  });
  if (!data?.count) return null; // hidden until the first WhatsApp rating
  const stars = "★".repeat(Math.round(data.avg)) + "☆".repeat(5 - Math.round(data.avg));
  return (
    <section ref={ref} data-reveal className="card flex items-center gap-4 px-5 py-4">
      <div>
        <p className="font-display text-2xl font-semibold text-gold-ink">{stars}</p>
        <p className="font-ui text-xs text-slate">Patient ratings on WhatsApp</p>
      </div>
      <div className="ml-auto text-right">
        <p className="font-display text-xl font-semibold">{data.avg}</p>
        <p className="font-ui text-xs text-slate">
          {data.count} rating{data.count === 1 ? "" : "s"}
          {data.low_count > 0 && (
            <span className="chip-danger ml-2">{data.low_count} low</span>
          )}
        </p>
      </div>
    </section>
  );
}

export default function Dashboard() {
  const { branchId } = useAuth();
  const pageRef = useRef(null);
  const [days, setDays] = useState(30);

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
    // Real-time feel (Vinay 2026-07-17): 60s while the tab is focused
    // (refetchIntervalInBackground stays off — an idle tab must let Neon
    // sleep, #299). Mutations that change the numbers invalidate directly.
    refetchInterval: 60_000
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
    <div ref={pageRef} className="space-y-6">
      <PageHeader eyebrow="Clinic overview" title="Today at a glance" />

      <StatBand
        title="Patient visits this week"
        weekday={an?.weekday_load}
        pct={an?.minutes?.pct ?? 0}
        pctCap="Plan minutes used"
        waiting={s.remaining}
        booked={s.total} />

      <StatRow items={[
        { label: "Calls answered", value: an?.calls_today ?? 0 },
        { label: "Patients seen", value: s.attended },
        { label: "Show rate today", value: `${todayRate ?? 100}%` },
        { label: `Attendance · ${days}d`, value: `${an?.attendance_rate != null ? Math.round(an.attendance_rate * 100) : 100}%` }
      ]} />

      {/* Caller messages awaiting a callback (#349) — hidden when empty */}
      <MessagesCard branchId={branchId} />
      <RatingsCard branchId={branchId} />

      {/* Lifetime totals — since day one */}
      {an?.lifetime && <LifetimeBand lifetime={an.lifetime} />}

      {/* Minutes + this month + busiest weekdays */}
      <div className="grid gap-6 lg:grid-cols-3">
        <section data-reveal className="card overflow-hidden">
          <header className="border-b border-hairline bg-pill px-5 py-3">
            <h2 className="font-display text-lg font-semibold">Voice minutes · this month</h2>
          </header>
          <div className="px-5 py-4"><MinutesDonut minutes={an?.minutes} /></div>
        </section>
        <section data-reveal className="card overflow-hidden">
          <header className="border-b border-hairline bg-pill px-5 py-3">
            <h2 className="font-display text-lg font-semibold">This month</h2>
          </header>
          <div className="px-5 py-4"><MonthBlock month={an?.month} /></div>
        </section>
        <section data-reveal className="card overflow-hidden">
          <header className="border-b border-hairline bg-pill px-5 py-3">
            <h2 className="font-display text-lg font-semibold">Busiest days · {days}d</h2>
          </header>
          <div className="px-5 py-4"><WeekdayBars load={an?.weekday_load} /></div>
        </section>
      </div>

      {/* Trend — bookings, outcomes, show rate over time */}
      <section data-reveal className="card overflow-hidden">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-hairline bg-pill px-5 py-3">
          <h2 className="font-display text-lg font-semibold">Bookings &amp; show rate</h2>
          <div className="flex gap-1">
            {[7, 30, 90].map((d) => (
              <button key={d} onClick={() => setDays(d)}
                className={`rounded-full px-3 py-1 font-ui text-xs font-medium transition-[background-color,transform] duration-150 ease-out active:scale-[0.97] ${
                  days === d ? "bg-accent text-accent-ink" : "border border-hairline text-slate hover:bg-pill"
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
          <ChartLegend />
        </div>
      </section>

      {/* Call quality — how the AI receptionist is actually performing */}
      <section data-reveal className="card overflow-hidden">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-hairline bg-pill px-5 py-3">
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
        <section data-reveal className="card overflow-hidden">
          <header className="flex items-center justify-between border-b border-hairline bg-warn/10 px-5 py-3">
            <h2 className="font-display text-lg font-semibold">Doctors on leave</h2>
            <span className="font-ui text-xs text-slate">next 30 days</span>
          </header>
          <div className="divide-y divide-hairline">
            {groupLeave(an.on_leave).map((g) => (
              <div key={`${g.doctor}-${g.from}`} className="flex items-center justify-between px-5 py-3">
                <div className="flex items-center gap-2.5">
                  {/* dot = real semantic state: leave covers TODAY, patients being called */}
                  {g.coversToday && <span className="h-2 w-2 rounded-full bg-warn" aria-label="on leave today" />}
                  <p className="font-ui text-sm font-medium">{g.doctor}</p>
                  {g.reason && <span className="font-ui text-xs text-slate">· {g.reason}</span>}
                </div>
                <p className={`font-ui text-sm ${g.coversToday ? "font-semibold text-warn" : "text-slate"}`}>
                  {g.from === g.to ? fmtDay(g.from) : `${fmtDay(g.from)} to ${fmtDay(g.to)}`}
                  {g.coversToday && " · patients being informed by call"}
                </p>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Booking sources · Doctors · Doctor load — side by side */}
      <div className="grid items-start gap-6 lg:grid-cols-3">
        {/* Where bookings come from */}
        <section data-reveal className="card overflow-hidden">
          <header className="border-b border-hairline bg-pill px-5 py-3">
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
          <header className="border-b border-hairline bg-pill px-5 py-3">
            <h2 className="font-display text-lg font-semibold">Doctors · {days}d</h2>
          </header>
          {[...(an?.by_doctor ?? [])].sort((a, b) => b.booked - a.booked).map((d, i, arr) => (
            <div key={d.doctor_name} className="ledger-row relative">
              {i === 0 && d.booked > 0 && (
                <span className="absolute right-5 top-1.5 tag tag-good">most patients</span>
              )}
              {i === arr.length - 1 && arr.length > 1 && d.booked < arr[0].booked && (
                <span className="absolute right-5 top-1.5 tag tag-warn">needs attention</span>
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

        {/* Live per-doctor queue (today) */}
        <section data-reveal className="card overflow-hidden">
          <header className="border-b border-hairline bg-pill px-5 py-3">
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
    </div>
  );
}
