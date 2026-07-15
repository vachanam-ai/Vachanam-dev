import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { fetchTodayQueue, markAttended, markNoShow } from "../api/client.js";
import { useAuth } from "../hooks/useAuth.jsx";
import { countUp, pulseRow, revealStagger } from "../lib/motion.js";

function SummaryStat({ label, value, gold }) {
  const ref = useRef(null);
  useEffect(() => {
    countUp(ref.current, value ?? 0);
  }, [value]);
  return (
    <div data-reveal className="card flex-1 px-5 py-4">
      <p className="eyebrow">{label}</p>
      <p ref={ref} className={`numeral mt-1 text-4xl ${gold ? "text-gold-ink" : "text-teal-deep"}`}>
        0
      </p>
    </div>
  );
}

function StatusChip({ status, isUrgent }) {
  if (isUrgent) return <span className="chip-danger">urgent</span>;
  if (status === "attended") return <span className="chip-token">attended</span>;
  if (status === "no_show") return <span className="chip-danger">no-show</span>;
  return <span className="chip-muted">waiting</span>;
}

function PatientRow({ p, doctor, onAttend, onNoShow, busy }) {
  const rowRef = useRef(null);
  const settled = p.status === "attended" || p.status === "no_show";
  return (
    <div ref={rowRef} className={`ledger-row ${settled ? "opacity-55" : ""}`}>
      <div className="w-14 shrink-0 text-center">
        {doctor.booking_type === "token" ? (
          <span className="numeral text-2xl text-teal">{p.token_number ?? "—"}</span>
        ) : (
          <span className="numeral text-base text-gold-ink">
            {/* the SLOT time — confirmed_at is when the booking was MADE (UTC) */}
            {p.appointment_time ?? "—"}
          </span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate font-ui font-medium">{p.patient_name}</p>
        <StatusChip status={p.status} isUrgent={p.is_urgent} />
      </div>
      {!settled && (
        <div className="flex shrink-0 gap-2">
          <button
            disabled={busy}
            onClick={() => {
              pulseRow(rowRef.current);
              onAttend(p);
            }}
            className="btn-primary px-3 py-1.5 text-sm"
          >
            Attend
          </button>
          <button
            disabled={busy}
            onClick={() => onNoShow(p)}
            className="btn-danger px-3 py-1.5 text-sm"
          >
            No-show
          </button>
        </div>
      )}
    </div>
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
    onSettled: () => qc.invalidateQueries({ queryKey: ["queue", branchId] })
  });

  const attend = useMutation({
    mutationFn: ({ tokenId }) => markAttended(branchId, tokenId),
    ...optimistic("attended")
  });
  const noShow = useMutation({
    mutationFn: ({ tokenId }) => markNoShow(branchId, tokenId),
    ...optimistic("no_show")
  });

  if (!branchId)
    return <p className="font-ui text-slate">No branch linked to your account yet.</p>;
  if (isLoading) return <p className="font-ui text-slate">Opening today&rsquo;s ledger…</p>;
  if (error)
    return (
      <p className="font-ui text-danger">
        Couldn&rsquo;t load the queue — {error?.response?.data?.detail ?? "server unreachable"}.
      </p>
    );

  const s = data.summary;

  return (
    <div ref={pageRef} className="space-y-6">
      <div data-reveal className="flex items-end justify-between">
        <div>
          <p className="eyebrow">Today</p>
          <h1 className="section-title text-2xl">
            {new Date(data.date).toLocaleDateString("en-IN", {
              weekday: "long",
              day: "numeric",
              month: "long"
            })}
          </h1>
        </div>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row">
        <SummaryStat label="Booked" value={s.total} />
        <SummaryStat label="Attended" value={s.attended} />
        <SummaryStat label="Remaining" value={s.remaining} gold />
        <SummaryStat label="No-shows" value={s.no_show} />
      </div>

      {(role === "doctor"
        ? data.doctors.filter((d) => d.doctor_user_id === user?.user_id)
        : data.doctors
      ).map((d) => (
        <section key={d.doctor_id} data-reveal className="card overflow-hidden">
          <header className="flex items-center gap-3 border-b border-hairline bg-teal-mint/60 px-4 py-3">
            <h2 className="font-display text-lg font-semibold">{d.doctor_name}</h2>
            <span className={d.booking_type === "token" ? "chip-token" : "chip-slot"}>
              {d.booking_type === "token" ? "token queue" : "appointments"}
            </span>
            <span className="ml-auto font-ui text-sm text-slate">
              {d.patients.filter((p) => p.status === "attended").length}/{d.patients.length} seen
            </span>
          </header>
          {d.patients.length === 0 ? (
            <p className="px-4 py-6 font-ui text-sm text-slate">No bookings yet for this doctor.</p>
          ) : (
            d.patients.map((p) => (
              <PatientRow
                key={p.appointment_id}
                p={p}
                doctor={d}
                busy={attend.isPending || noShow.isPending}
                onAttend={(pt) => attend.mutate({ tokenId: pt.appointment_id })}
                onNoShow={(pt) => noShow.mutate({ tokenId: pt.appointment_id })}
              />
            ))
          )}
        </section>
      ))}
    </div>
  );
}
