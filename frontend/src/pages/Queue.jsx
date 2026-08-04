import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { fetchTodayQueue, markAttended, markNoShow } from "../api/client.js";
import { useAuth } from "../hooks/useAuth.jsx";
import { pulseRow, revealStagger } from "../lib/motion.js";
import PageHeader, { StatRow } from "../components/PageHeader.jsx";

const slotLabel = (p, doctor) =>
  doctor.booking_type === "token"
    ? `Token ${p.token_number ?? "—"}`
    : (p.appointment_time
        ? new Date(`2000-01-01T${p.appointment_time}`).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })
        : "—");

function PatientCard({ p, doctor, col, onAttend, onNoShow, busy }) {
  const ref = useRef(null);
  return (
    <div ref={ref} data-reveal className="card p-3.5">
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 flex-1 truncate font-ui text-sm font-semibold text-ink">{p.patient_name}</p>
        {p.is_urgent && col === "waiting" && <span className="tag tag-crit shrink-0">urgent</span>}
        {col === "seen" && <span className="tag tag-good shrink-0">seen</span>}
        {col === "missed" && <span className="tag tag-crit shrink-0">no-show</span>}
      </div>
      {p.complaint && <p className="mt-1.5 line-clamp-2 font-ui text-xs leading-relaxed text-slate">{p.complaint}</p>}
      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="chip-count">{slotLabel(p, doctor)}</span>
        <span className="min-w-0 truncate font-ui text-xs text-slate">{doctor.doctor_name}</span>
      </div>
      {col === "waiting" && (
        <div className="mt-3 flex gap-2">
          <button disabled={busy} onClick={() => { pulseRow(ref.current); onAttend(p); }}
            className="btn-primary flex-1 px-3 py-1.5 text-xs">Attend</button>
          <button disabled={busy} onClick={() => onNoShow(p)}
            className="btn-danger flex-1 px-3 py-1.5 text-xs">No-show</button>
        </div>
      )}
    </div>
  );
}

function Column({ title, tone, cards, ...rest }) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <h2 className="font-ui text-base font-semibold text-ink">{title}</h2>
        <span className={`chip-count ${tone === "good" ? "!text-good" : tone === "crit" ? "!text-danger" : ""}`}>{cards.length}</span>
      </div>
      {cards.length === 0
        ? <p className="rounded-xl border border-dashed border-hairline px-3 py-6 text-center font-ui text-xs text-slate">Nothing here</p>
        : cards.map(({ p, doctor }) => (
            <PatientCard key={p.appointment_id} p={p} doctor={doctor} {...rest} />
          ))}
    </section>
  );
}

export default function Queue() {
  const { branchId, role, user } = useAuth();
  const qc = useQueryClient();
  const pageRef = useRef(null);

  // day = null means "the branch's today", which the server decides — the
  // browser's clock may be in another timezone. Stepping off today matters
  // because a doctor can publish a week of sessions at once, and those
  // bookings were invisible here until the morning they happened.
  const [day, setDay] = useState(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["queue", branchId, day],
    queryFn: () => fetchTodayQueue(branchId, day),
    enabled: Boolean(branchId),
    // Only today's board is a live desk view; past/future days are static.
    refetchInterval: day ? false : 20_000,
    placeholderData: (prev) => prev
  });

  // Anchored on the day the SERVER reported, so stepping from "today" starts
  // from the branch's date rather than the browser's.
  const shiftDay = (delta) => {
    const base = new Date(`${data?.date ?? new Date().toISOString().slice(0, 10)}T00:00:00`);
    base.setDate(base.getDate() + delta);
    setDay(`${base.getFullYear()}-${String(base.getMonth() + 1).padStart(2, "0")}-${String(base.getDate()).padStart(2, "0")}`);
  };

  // Depend on `data`, NOT Boolean(data). Cards render at opacity 0 until this
  // marks them revealed (index.css: [data-reveal]:not([data-revealed])), and
  // Boolean(data) flips false->true exactly once. With placeholderData keeping
  // `data` truthy forever, every card that mounted LATER — a booking arriving
  // on the 20s refetch, or the whole board after stepping to another day —
  // never got revealed and stayed permanently invisible. The page looked stuck
  // (Vinay 2026-08-04). revealStagger only touches :not([data-revealed]), so
  // re-running it per refetch is idempotent and cheap.
  useEffect(() => {
    if (data) revealStagger(pageRef.current);
  }, [data]);

  const queueKey = ["queue", branchId, day];
  const optimistic = (statusValue) => ({
    onMutate: async ({ tokenId }) => {
      await qc.cancelQueries({ queryKey: queueKey });
      const prev = qc.getQueryData(queueKey);
      qc.setQueryData(queueKey, (old) =>
        old && {
          ...old,
          doctors: old.doctors.map((d) => ({
            ...d,
            patients: d.patients.map((p) =>
              p.appointment_id === tokenId ? { ...p, status: statusValue } : p
            )
          }))
        }
      );
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      qc.setQueryData(queueKey, ctx.prev);
      toast.error("Update failed — queue restored");
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: queueKey });
      qc.invalidateQueries({ queryKey: ["analytics"] });
    }
  });

  const attend = useMutation({ mutationFn: ({ tokenId }) => markAttended(branchId, tokenId), ...optimistic("attended") });
  const noShow = useMutation({ mutationFn: ({ tokenId }) => markNoShow(branchId, tokenId), ...optimistic("no_show") });

  if (!branchId) return <p className="font-ui text-slate">No branch linked to your account yet.</p>;
  if (isLoading) return <p className="font-ui text-slate">Opening today&rsquo;s ledger…</p>;
  if (error)
    return <p className="font-ui text-danger">Couldn&rsquo;t load the queue — {error?.response?.data?.detail ?? "server unreachable"}.</p>;

  const s = data.summary;
  const doctors = role === "doctor"
    ? data.doctors.filter((d) => d.doctor_user_id === user?.user_id)
    : data.doctors;

  // Flatten every doctor's patients into one board, split by outcome.
  const all = doctors.flatMap((d) => d.patients.map((p) => ({ p, doctor: d })));
  const waiting = all.filter((x) => x.p.status !== "attended" && x.p.status !== "no_show");
  const seen = all.filter((x) => x.p.status === "attended");
  const missed = all.filter((x) => x.p.status === "no_show");

  const busy = attend.isPending || noShow.isPending;
  const actions = {
    busy,
    onAttend: (pt) => attend.mutate({ tokenId: pt.appointment_id }),
    onNoShow: (pt) => noShow.mutate({ tokenId: pt.appointment_id })
  };

  return (
    <div ref={pageRef} className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <PageHeader eyebrow={day ? "Day view" : "Today"}
          title={new Date(`${data.date}T00:00:00`).toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })}
          sub={`${doctors.length} ${doctors.length === 1 ? "doctor" : "doctors"} on the desk`} />
        <div className="flex items-center gap-2">
          <button className="btn-ghost px-3 py-1.5 text-sm" onClick={() => shiftDay(-1)}>← Prev</button>
          {day && <button className="btn-ghost px-3 py-1.5 text-sm" onClick={() => setDay(null)}>Today</button>}
          <button className="btn-ghost px-3 py-1.5 text-sm" onClick={() => shiftDay(1)}>Next →</button>
        </div>
      </div>

      <StatRow items={[
        { label: "Booked", value: s.total },
        { label: "Attended", value: s.attended },
        { label: "Remaining", value: s.remaining, tone: "gold" },
        { label: "No-shows", value: s.no_show }
      ]} />

      {all.length === 0 ? (
        <p className="card px-5 py-10 text-center font-ui text-sm text-slate">
          No bookings on this day. Use Prev/Next to check the days a doctor has published.
        </p>
      ) : (
        <div className="grid gap-5 md:grid-cols-3">
          <Column title="Waiting" col="waiting" cards={waiting} {...actions} />
          <Column title="Seen" tone="good" col="seen" cards={seen} {...actions} />
          <Column title="No-show" tone="crit" col="missed" cards={missed} {...actions} />
        </div>
      )}
    </div>
  );
}
