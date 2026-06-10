import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { fetchDoctors, fetchTodayQueue, stopWalkinsToday } from "../api/client.js";
import { useAuth } from "../hooks/useAuth.jsx";
import { revealStagger } from "../lib/motion.js";

export default function DoctorSchedule() {
  const { branchId, user } = useAuth();
  const qc = useQueryClient();
  const pageRef = useRef(null);

  const { data: doctorsRaw } = useQuery({
    queryKey: ["doctors", branchId],
    queryFn: () => fetchDoctors(branchId),
    enabled: Boolean(branchId)
  });
  const { data: queue } = useQuery({
    queryKey: ["queue", branchId],
    queryFn: () => fetchTodayQueue(branchId),
    enabled: Boolean(branchId),
    refetchInterval: 30_000
  });

  const doctors = Array.isArray(doctorsRaw) ? doctorsRaw : doctorsRaw?.doctors ?? [];
  // A doctor user sees their own card (matched by linked user) or all if unmatched
  const mine =
    doctors.filter((d) => d.user_id === user?.user_id || d.invited_email === user?.email);
  const visible = mine.length ? mine : doctors;

  useEffect(() => {
    if (doctors.length) revealStagger(pageRef.current);
  }, [doctors.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const stop = useMutation({
    mutationFn: (doctorId) => stopWalkinsToday(doctorId, branchId),
    onSuccess: () => {
      toast.success("Walk-ins closed for today");
      qc.invalidateQueries({ queryKey: ["doctors", branchId] });
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not close walk-ins")
  });

  return (
    <div ref={pageRef} className="space-y-6">
      <div data-reveal>
        <p className="eyebrow">Doctor</p>
        <h1 className="section-title text-2xl">My schedule</h1>
      </div>

      {visible.map((d) => {
        const id = d.id ?? d.doctor_id;
        const todayEntry = queue?.doctors?.find((q) => q.doctor_id === id);
        const waiting = todayEntry?.patients?.filter((p) => p.status === "confirmed").length ?? 0;
        return (
          <section key={id} data-reveal className="card p-6">
            <div className="flex flex-wrap items-start gap-4">
              <div className="min-w-0 flex-1">
                <h2 className="font-display text-xl font-semibold">{d.name}</h2>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <span className={d.booking_type === "token" ? "chip-token" : "chip-slot"}>
                    {d.booking_type === "token" ? "token queue" : "appointments"}
                  </span>
                  {d.working_hours_start && (
                    <span className="font-ui text-sm text-slate tabular-nums">
                      {d.working_hours_start}–{d.working_hours_end}
                    </span>
                  )}
                </div>
              </div>
              <div className="text-center">
                <p className="numeral text-5xl text-teal-deep">{waiting}</p>
                <p className="font-ui text-xs uppercase tracking-[0.14em] text-slate">waiting now</p>
              </div>
            </div>

            {d.booking_type === "token" && (
              <div className="mt-5 border-t border-hairline pt-4">
                <button
                  onClick={() => stop.mutate(id)}
                  disabled={stop.isPending}
                  className="btn-gold"
                >
                  Stop walk-ins for today
                </button>
                <p className="mt-2 font-ui text-xs text-slate">
                  Patients already holding tokens keep them; the desk can&rsquo;t add new walk-ins.
                </p>
              </div>
            )}
          </section>
        );
      })}

      {visible.length === 0 && (
        <p className="font-ui text-sm text-slate">No doctor profile linked to your account yet.</p>
      )}
    </div>
  );
}
