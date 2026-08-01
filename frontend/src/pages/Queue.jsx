import { useEffect, useRef } from "react";
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

  const { data, isLoading, error } = useQuery({
    queryKey: ["queue", branchId],
    queryFn: () => fetchTodayQueue(branchId),
    enabled: Boolean(branchId),
    refetchInterval: 20_000
  });

  useEffect(() => {
    if (data) revealStagger(pageRef.current);
  }, [Boolean(data)]); // eslint-disable-line react-hooks/exhaustive-deps

  const optimistic = (statusValue) => ({
    onMutate: async ({ tokenId }) => {
      await qc.cancelQueries({ queryKey: ["queue", branchId] });
      const prev = qc.getQueryData(["queue", branchId]);
      qc.setQueryData(["queue", branchId], (old) =>
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
      qc.setQueryData(["queue", branchId], ctx.prev);
      toast.error("Update failed — queue restored");
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["queue", branchId] });
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
      <PageHeader eyebrow="Today"
        title={new Date(data.date).toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })}
        sub={`${doctors.length} ${doctors.length === 1 ? "doctor" : "doctors"} on the desk`} />

      <StatRow items={[
        { label: "Booked", value: s.total },
        { label: "Attended", value: s.attended },
        { label: "Remaining", value: s.remaining, tone: "gold" },
        { label: "No-shows", value: s.no_show }
      ]} />

      {all.length === 0 ? (
        <p className="card px-5 py-10 text-center font-ui text-sm text-slate">No bookings yet today.</p>
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
