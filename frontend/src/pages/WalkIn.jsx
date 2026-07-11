import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, fetchDoctors } from "../api/client.js";
import { useAuth } from "../hooks/useAuth.jsx";
import { revealStagger } from "../lib/motion.js";

/** Build HH:MM choices from a doctor's working window + slot duration. */
function slotChoices(doctor) {
  if (!doctor?.working_hours_start || !doctor?.working_hours_end) return [];
  const [sh, sm] = doctor.working_hours_start.split(":").map(Number);
  const [eh, em] = doctor.working_hours_end.split(":").map(Number);
  const step = doctor.slot_duration_minutes || 15;
  const out = [];
  for (let m = sh * 60 + sm; m + step <= eh * 60 + em; m += step) {
    out.push(
      `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`
    );
  }
  return out;
}

export default function WalkIn() {
  const { branchId } = useAuth();
  const qc = useQueryClient();
  const pageRef = useRef(null);

  const [doctorId, setDoctorId] = useState("");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [complaint, setComplaint] = useState("");
  const [slot, setSlot] = useState("");
  const [urgent, setUrgent] = useState(false);
  const [receipt, setReceipt] = useState(null);

  const { data: doctors = [], isLoading } = useQuery({
    queryKey: ["doctors", branchId],
    queryFn: () => fetchDoctors(branchId),
    enabled: Boolean(branchId)
  });

  // DoctorOut carries no status field (router returns this branch's doctors);
  // only filter if a status is actually present.
  const active = useMemo(
    () => (Array.isArray(doctors) ? doctors : doctors?.doctors ?? []).filter(
      (d) => !d.status || d.status === "active"
    ),
    [doctors]
  );
  const doctor = active.find((d) => d.id === doctorId || d.doctor_id === doctorId);
  const isSlotDoctor = doctor?.booking_type === "appointment";
  const slots = useMemo(() => slotChoices(doctor), [doctor]);

  useEffect(() => {
    revealStagger(pageRef.current);
  }, []);

  const book = useMutation({
    mutationFn: () =>
      api
        .post(`/queue/${branchId}/walkin`, {
          doctor_id: doctorId,
          patient_name: name.trim(),
          patient_phone: phone.trim() || null,
          complaint: complaint.trim() || null,
          appointment_time: isSlotDoctor ? slot : null,
          is_urgent: urgent
        })
        .then((r) => r.data),
    onSuccess: (data) => {
      setReceipt(data);
      qc.invalidateQueries({ queryKey: ["queue", branchId] });
      setName(""); setPhone(""); setComplaint(""); setSlot(""); setUrgent(false);
      toast.success(
        data.booking_type === "token"
          ? `Token ${data.token_number} — ${data.patient_name}`
          : `${data.appointment_time} booked — ${data.patient_name}`
      );
    },
    onError: (e) =>
      toast.error(e?.response?.data?.detail ?? "Booking failed — try again")
  });

  const canSubmit =
    doctorId && name.trim().length >= 2 && (!isSlotDoctor || slot) && !book.isPending;

  return (
    <div ref={pageRef} className="mx-auto max-w-3xl space-y-6">
      <div data-reveal>
        <p className="eyebrow">Front desk</p>
        <h1 className="section-title text-2xl">Walk-in registration</h1>
      </div>

      <div className="grid gap-6 md:grid-cols-[1fr_280px]">
        <form
          data-reveal
          className="card space-y-5 p-6"
          onSubmit={(e) => {
            e.preventDefault();
            if (canSubmit) book.mutate();
          }}
        >
          <div>
            <label className="label">Doctor</label>
            <div className="grid gap-2 sm:grid-cols-2">
              {isLoading && <p className="font-ui text-sm text-slate">Loading doctors…</p>}
              {active.map((d) => {
                const id = d.id ?? d.doctor_id;
                const selected = doctorId === id;
                return (
                  <button
                    type="button"
                    key={id}
                    onClick={() => { setDoctorId(id); setSlot(""); }}
                    className={`rounded-xl border px-4 py-3 text-left transition ${
                      selected
                        ? "border-teal bg-teal-mint shadow-card"
                        : "border-hairline bg-surface hover:border-teal-light/60"
                    }`}
                  >
                    <p className="font-ui font-medium">{d.name}</p>
                    <span className={d.booking_type === "token" ? "chip-token mt-1" : "chip-slot mt-1"}>
                      {d.booking_type === "token" ? "token queue" : "time slots"}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="label">Patient name</label>
              <input className="field" value={name} onChange={(e) => setName(e.target.value)}
                placeholder="Lakshmi Devi" required minLength={2} />
            </div>
            <div>
              <label className="label">Phone (optional)</label>
              <input className="field" value={phone} onChange={(e) => setPhone(e.target.value)}
                placeholder="+91 …" inputMode="tel" />
            </div>
          </div>

          <div>
            <label className="label">Complaint (optional)</label>
            <input className="field" value={complaint} onChange={(e) => setComplaint(e.target.value)}
              placeholder="tooth pain, cleaning, report collection…" />
          </div>

          {isSlotDoctor && (
            <div>
              <label className="label">Time slot</label>
              {slots.length === 0 ? (
                <p className="font-ui text-sm text-slate">No working hours configured for this doctor.</p>
              ) : (
                <div className="flex max-h-40 flex-wrap gap-2 overflow-y-auto pr-1">
                  {slots.map((t) => (
                    <button type="button" key={t} onClick={() => setSlot(t)}
                      className={`rounded-lg border px-3 py-1.5 font-ui text-sm tabular-nums transition ${
                        slot === t
                          ? "border-gold bg-gold-soft text-gold-ink"
                          : "border-hairline bg-surface hover:border-gold/60"
                      }`}>
                      {t}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          <label className="flex cursor-pointer items-center gap-2 font-ui text-sm">
            <input type="checkbox" checked={urgent} onChange={(e) => setUrgent(e.target.checked)}
              className="h-4 w-4 accent-teal" />
            Mark urgent
          </label>

          <button type="submit" disabled={!canSubmit} className="btn-primary w-full py-3">
            {book.isPending
              ? "Booking…"
              : isSlotDoctor
                ? slot ? `Book ${slot}` : "Pick a slot"
                : "Assign next token"}
          </button>
        </form>

        {/* Receipt — the thing the receptionist reads out loud */}
        <aside data-reveal className="card h-fit p-6 text-center">
          <p className="eyebrow">Last booking</p>
          {receipt ? (
            <>
              <p className="numeral mt-3 text-7xl text-teal-deep">
                {receipt.booking_type === "token" ? receipt.token_number : receipt.appointment_time}
              </p>
              <p className="mt-2 font-display text-lg">{receipt.patient_name}</p>
              <p className="font-ui text-sm text-slate">{receipt.doctor_name}</p>
            </>
          ) : (
            <p className="mt-6 font-ui text-sm text-slate">
              Token number or slot time appears here after booking.
            </p>
          )}
        </aside>
      </div>
    </div>
  );
}
