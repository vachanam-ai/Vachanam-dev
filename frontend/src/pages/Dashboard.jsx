import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchTodayQueue } from "../api/client.js";
import { useAuth } from "../hooks/useAuth.jsx";
import { countUp, revealStagger } from "../lib/motion.js";

function Hero({ label, value, sub, gold }) {
  const ref = useRef(null);
  useEffect(() => {
    countUp(ref.current, value ?? 0, { duration: 1.1 });
  }, [value]);
  return (
    <div data-reveal className="card px-6 py-5">
      <p className="eyebrow">{label}</p>
      <p ref={ref} className={`numeral mt-1 text-5xl ${gold ? "text-gold-ink" : "text-teal-deep"}`}>0</p>
      {sub && <p className="mt-1 font-ui text-xs text-slate">{sub}</p>}
    </div>
  );
}

export default function Dashboard() {
  const { branchId } = useAuth();
  const pageRef = useRef(null);

  const { data, isLoading } = useQuery({
    queryKey: ["queue", branchId],
    queryFn: () => fetchTodayQueue(branchId),
    enabled: Boolean(branchId),
    refetchInterval: 60_000
  });

  useEffect(() => {
    if (data) revealStagger(pageRef.current);
  }, [Boolean(data)]); // eslint-disable-line react-hooks/exhaustive-deps

  if (isLoading) return <p className="font-ui text-slate">Reading today&rsquo;s ledger…</p>;

  const s = data?.summary ?? { total: 0, attended: 0, no_show: 0, remaining: 0 };
  const showRate = s.total ? Math.round(((s.attended + s.remaining) / s.total) * 100) : 100;

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
        <Hero label="Show rate" value={showRate} sub="% of bookings honoured" />
      </div>

      {/* Per-doctor load — token vs slot types visible at a glance */}
      <section data-reveal className="card overflow-hidden">
        <header className="border-b border-hairline bg-teal-mint/60 px-5 py-3">
          <h2 className="font-display text-lg font-semibold">Doctor load</h2>
        </header>
        {(data?.doctors ?? []).map((d) => {
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
        {(data?.doctors ?? []).length === 0 && (
          <p className="px-5 py-6 font-ui text-sm text-slate">No doctors configured yet.</p>
        )}
      </section>

      <p data-reveal className="font-ui text-xs text-slate">
        Weekly trends, call minutes, and revenue analytics arrive with the analytics service —
        this view reads live queue data today.
      </p>
    </div>
  );
}
