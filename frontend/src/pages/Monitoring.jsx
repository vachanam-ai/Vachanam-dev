import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchAdminMonitoring, fetchHealthBoard } from "../api/client.js";

const pct = (v) => (v == null ? "—" : `${Math.round(v * 100)}%`);
const num = (v) => (v == null ? "—" : v);

/* #306 live health board. The watchdog (backend/watchdog.py) checks every 60s
   and AUTO-REMEDIATES (Fly restart, requeue, clean self-restart) — this board
   is its face: component states from Redis + the incident/action feed. */
const COMP_LABELS = {
  agent: "Voice agent (Fly)",
  redis: "Redis (Upstash)",
  database: "Database (Neon)",
  api_memory: "API memory",
  calendar_queue: "Calendar queue",
};

function ago(epoch) {
  if (!epoch) return "";
  const s = Math.max(0, Math.round(Date.now() / 1000 - epoch));
  if (s < 90) return `${s}s`;
  if (s < 5400) return `${Math.round(s / 60)}m`;
  return `${Math.round(s / 3600)}h`;
}

function HealthBoard() {
  const { data: hb } = useQuery({
    queryKey: ["health-board"],
    queryFn: fetchHealthBoard,
    refetchInterval: 10_000,
  });
  const comps = hb?.components ?? {};
  const anyDown = Object.values(comps).some((c) => c.status === "down");
  return (
    <section className="card overflow-hidden">
      <header className={`flex items-center justify-between border-b border-hairline px-5 py-3 ${anyDown ? "bg-red-50" : "bg-teal-mint/60"}`}>
        <h2 className="font-display text-lg font-semibold">Live health · watchdog</h2>
        <span className={`rounded-full px-3 py-0.5 font-ui text-xs font-semibold ${anyDown ? "bg-red-600 text-white" : "bg-teal text-white"}`}>
          {anyDown ? "ATTENTION" : "ALL SYSTEMS OK"}
        </span>
      </header>
      <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-5">
        {Object.entries(COMP_LABELS).map(([key, label]) => {
          const c = comps[key];
          const st = c?.status ?? "unknown";
          const color = st === "ok" ? "bg-emerald-500" : st === "down" ? "bg-red-500" : "bg-gray-300";
          return (
            <div key={key} className="rounded-xl border border-hairline bg-surface px-3 py-2">
              <div className="flex items-center gap-2">
                <span className={`h-2.5 w-2.5 rounded-full ${color} ${st === "down" ? "animate-pulse" : ""}`} />
                <p className="font-ui text-xs font-semibold">{label}</p>
              </div>
              <p className="mt-1 font-ui text-[11px] leading-snug text-slate">
                {c ? c.detail : "no data yet"}
                {c?.since ? ` · ${ago(c.since)}` : ""}
              </p>
              {c?.action && st === "down" && (
                <p className="mt-1 font-ui text-[11px] font-medium text-amber-700">⚙ {c.action}</p>
              )}
            </div>
          );
        })}
      </div>
      {(hb?.incidents?.length ?? 0) > 0 && (
        <div className="border-t border-hairline px-5 py-3">
          <p className="eyebrow mb-2">Incidents &amp; automatic actions</p>
          <ul className="max-h-48 space-y-1 overflow-y-auto">
            {hb.incidents.map((i, idx) => (
              <li key={idx} className="font-ui text-xs text-slate">
                <span className={i.action.endsWith("resolved") ? "text-emerald-700" : "text-red-700"}>
                  {i.action.replace("watchdog.", "").replace(".", " ")}
                </span>
                {" — "}{i.detail}
                {i.action_taken && <span className="text-amber-700"> · action: {i.action_taken}</span>}
                {i.at && <span className="text-slate/60"> · {new Date(i.at).toLocaleString()}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function Stat({ label, value, sub }) {
  return (
    <div className="rounded-xl border border-hairline bg-surface px-4 py-3">
      <p className="eyebrow">{label}</p>
      <p className="numeral mt-1 text-3xl text-teal-deep">{value}</p>
      {sub && <p className="mt-1 font-ui text-xs text-slate">{sub}</p>}
    </div>
  );
}

/* Platform-wide monitoring + feedback loop for super_admin. Polls every 30s
   for a near-realtime view. AGGREGATES ONLY — no clinic patient data, no
   transcripts ever cross this boundary (enforced server-side, RULE 1). */
export default function Monitoring() {
  const [days, setDays] = useState(30);
  const { data: m, isLoading } = useQuery({
    queryKey: ["admin-monitoring", days],
    queryFn: () => fetchAdminMonitoring(days),
    refetchInterval: 30_000
  });

  if (isLoading) return <p className="font-ui text-slate">Reading the platform…</p>;

  const maxDay = Math.max(1, ...(m?.daily ?? []).map((d) => d.calls));
  const maxTag = Math.max(1, ...(m?.tag_frequencies ?? []).map((t) => t.count));

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="eyebrow">Platform health</p>
          <h1 className="section-title text-2xl">Monitoring &amp; feedback loop</h1>
          <p className="font-ui text-xs text-slate mt-1">
            Live across every clinic · refreshes automatically · no patient data shown
          </p>
        </div>
        <div className="flex gap-1">
          {[7, 30, 90].map((d) => (
            <button key={d} onClick={() => setDays(d)}
              className={`rounded-full px-3 py-1 font-ui text-xs font-medium transition-[background-color,transform] duration-150 ease-out active:scale-[0.97] ${
                days === d ? "bg-teal text-white" : "bg-surface text-slate hover:bg-teal-pale"
              }`}>
              {d}d
            </button>
          ))}
        </div>
      </div>

      <HealthBoard />

      {/* KPI tiles */}
      <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Calls" value={num(m?.total_calls)} sub={`${days} days`} />
        <Stat label="Booked" value={pct(m?.conversion_rate)} sub={`${m?.booked ?? 0} bookings`} />
        <Stat label="Abandoned" value={pct(m?.abandon_rate)} sub="held, not confirmed" />
        <Stat label="Human asked" value={num(m?.transfers)} sub="transfer requests" />
        <Stat label="Judge score" value={m?.avg_judge_score ?? "—"} sub={`${m?.judged ?? 0} judged`} />
        <Stat label="Avg length"
          value={m?.avg_duration_seconds ? `${Math.round(m.avg_duration_seconds)}s` : "—"}
          sub={`${m?.avg_turns ?? "—"} turns`} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Issue tags — what the judge flags most */}
        <section className="card overflow-hidden">
          <header className="border-b border-hairline bg-teal-mint/60 px-5 py-3">
            <h2 className="font-display text-lg font-semibold">What to improve</h2>
          </header>
          <div className="px-5 py-4 space-y-2">
            {(m?.tag_frequencies ?? []).length === 0 ? (
              <p className="font-ui text-sm text-slate">No judged calls yet.</p>
            ) : (
              m.tag_frequencies.map((t) => (
                <div key={t.tag} className="flex items-center gap-3">
                  <span className="w-44 shrink-0 font-ui text-sm text-slate">
                    {t.tag.replace(/_/g, " ")}
                  </span>
                  <div className="h-2 flex-1 rounded-full bg-teal-pale">
                    <div className="h-2 rounded-full bg-teal"
                      style={{ width: `${(t.count / maxTag) * 100}%` }} />
                  </div>
                  <span className="w-8 text-right font-ui text-xs text-slate">{t.count}</span>
                </div>
              ))
            )}
          </div>
        </section>

        {/* Daily call volume */}
        <section className="card overflow-hidden">
          <header className="border-b border-hairline bg-teal-mint/60 px-5 py-3">
            <h2 className="font-display text-lg font-semibold">Daily calls</h2>
          </header>
          <div className="flex items-end gap-1 px-5 py-4" style={{ height: "140px" }}>
            {(m?.daily ?? []).map((d) => (
              <div key={d.date} className="flex flex-1 flex-col items-center justify-end gap-1" title={`${d.date}: ${d.calls} calls, ${d.booked} booked`}>
                <div className="w-full rounded-t bg-teal-pale" style={{ height: `${(d.calls / maxDay) * 100}%` }}>
                  <div className="w-full rounded-t bg-teal" style={{ height: `${d.calls ? (d.booked / d.calls) * 100 : 0}%` }} />
                </div>
              </div>
            ))}
          </div>
          <p className="px-5 pb-3 font-ui text-xs text-slate">Bar = calls · filled = booked</p>
        </section>
      </div>

      {/* Per-clinic rollup */}
      <section className="card overflow-hidden">
        <header className="border-b border-hairline bg-teal-mint/60 px-5 py-3">
          <h2 className="font-display text-lg font-semibold">By clinic</h2>
        </header>
        <div className="overflow-x-auto">
          <table className="w-full text-left font-ui text-sm">
            <thead className="text-xs uppercase tracking-wide text-slate">
              <tr className="border-b border-hairline">
                <th className="px-5 py-2">Clinic</th>
                <th className="px-5 py-2 text-right">Calls</th>
                <th className="px-5 py-2 text-right">Booked</th>
                <th className="px-5 py-2 text-right">Abandoned</th>
                <th className="px-5 py-2 text-right">Judge</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-hairline">
              {(m?.by_clinic ?? []).length === 0 ? (
                <tr><td colSpan={5} className="px-5 py-4 text-slate">No calls yet.</td></tr>
              ) : (
                m.by_clinic.map((c) => (
                  <tr key={c.name}>
                    <td className="px-5 py-2 font-medium text-teal-deep">{c.name}</td>
                    <td className="px-5 py-2 text-right">{c.calls}</td>
                    <td className="px-5 py-2 text-right">{pct(c.conversion_rate)}</td>
                    <td className="px-5 py-2 text-right">{pct(c.abandon_rate)}</td>
                    <td className="px-5 py-2 text-right">{c.avg_judge_score ?? "—"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
