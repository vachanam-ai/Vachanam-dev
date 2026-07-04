import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

const API_BASE = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");

/**
 * Waiting-room TV board (PUBLIC — no login; open /tv/<branchId> on the TV
 * browser). Token doctors only. Shows zero patient PII: doctor name,
 * now-serving token, waiting count. Polls every 10s; keeps the last good
 * data on a failed poll so the screen never flashes an error mid-clinic.
 */
export default function TvDisplay() {
  const { branchId } = useParams();
  const [data, setData] = useState(null);
  const [clock, setClock] = useState(new Date());

  useEffect(() => {
    let alive = true;
    const load = () =>
      fetch(`${API_BASE}/queue/${branchId}/display`)
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => alive && d && setData(d))
        .catch(() => {}); // keep last good board
    load();
    const poll = setInterval(load, 10000);
    const tick = setInterval(() => setClock(new Date()), 1000);
    return () => {
      alive = false;
      clearInterval(poll);
      clearInterval(tick);
    };
  }, [branchId]);

  return (
    <div className="min-h-dvh bg-slate-950 text-white flex flex-col">
      <header className="flex items-baseline justify-between px-10 py-6 border-b border-slate-800">
        <h1 className="text-4xl font-semibold tracking-wide">
          {data?.clinic_name || " "}
        </h1>
        <div className="text-3xl tabular-nums text-slate-300">
          {clock.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
        </div>
      </header>

      <main className="flex-1 grid gap-8 p-10 content-start"
        style={{ gridTemplateColumns: "repeat(auto-fit, minmax(24rem, 1fr))" }}>
        {(data?.doctors || []).map((d) => (
          <section key={d.doctor_name}
            className="rounded-3xl bg-slate-900 border border-slate-800 p-8 text-center">
            <h2 className="text-3xl text-teal-300 mb-6 truncate">{d.doctor_name}</h2>
            <p className="text-2xl text-slate-400 uppercase tracking-widest">Now serving</p>
            <p className="font-bold tabular-nums leading-none my-4 text-[10rem]">
              {d.now_serving ?? "—"}
            </p>
            <p className="text-3xl text-slate-300">
              {d.waiting} waiting
            </p>
          </section>
        ))}
        {data && data.doctors.length === 0 && (
          <p className="text-4xl text-slate-500 text-center col-span-full mt-24">
            No queue today
          </p>
        )}
      </main>
    </div>
  );
}
