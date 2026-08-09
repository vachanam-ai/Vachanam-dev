import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  changePlan,
  createPaymentOrder,
  createWhatsappAddonOrder,
  fetchPlan,
  verifyPayment,
} from "../api/client.js";
import { useAuth } from "../hooks/useAuth.jsx";

/* Every control that takes money, in one place (Vinay 2026-08-09: "migrate
   entire billing to billing page. all billings. (now, if i click adjust it is
   navigating to settings page)").

   Changing plan and paying used to live in a Settings card wedged between the
   clinic's phone number and its greeting, so the Billing page could only link
   away to them — a money page whose primary action was "go somewhere else".
   Lifted out as a component rather than pasted into Billing so Settings shrinks
   by the same amount it moves, and there is exactly one implementation of the
   Razorpay flow to keep correct. */

const PLAN_LABELS = {
  lite: "Lite · ₹1,999/mo",
  solo: "Starter · ₹5,999/mo",
  clinic: "Clinic · ₹9,999/mo",
  multi: "Multi · ₹17,999/mo",
  wa: "WhatsApp · ₹1,499/mo",
};
const PLAN_PRICES = { lite: 1999, solo: 5999, clinic: 9999, multi: 17999, wa: 1499 };

// Razorpay checkout script — loaded on demand, once.
function loadRazorpay() {
  return new Promise((resolve, reject) => {
    if (window.Razorpay) return resolve();
    const s = document.createElement("script");
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.onload = resolve;
    s.onerror = () =>
      reject(new Error("Could not load the payment window — check your connection"));
    document.body.appendChild(s);
  });
}

const fmt = (d) =>
  new Date(d).toLocaleDateString("en-IN", {
    day: "numeric", month: "short", year: "numeric",
  });

export default function PlanAndPayment() {
  const qc = useQueryClient();
  const { user } = useAuth();

  // Refetches every minute so cycle-end / days-left stay live without a
  // reload (#353).
  const plan = useQuery({
    queryKey: ["plan"], queryFn: fetchPlan, refetchInterval: 60_000,
  });

  const planChange = useMutation({
    mutationFn: (p) => changePlan(p),
    onSuccess: (d) => {
      qc.setQueryData(["plan"], d);
      // The billing summary prices the NEXT charge off the plan, so it is
      // stale the moment the plan changes.
      qc.invalidateQueries({ queryKey: ["billing-summary"] });
      if (d.pending_plan)
        toast.success(`Plan changes to ${d.pending_plan} on ${d.pending_plan_effective}`);
      else toast.success("Scheduled change cancelled");
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not change plan"),
  });

  const refresh = () => {
    plan.refetch();
    qc.invalidateQueries({ queryKey: ["billing-summary"] });
  };

  /** Server-priced Razorpay order → checkout modal → server-side signature
      verify. The WEBHOOK is the authoritative activation; this refetch only
      picks the new status up for the UI. */
  const checkout = async (order, description, done) => {
    await new Promise((resolve, reject) => {
      const rzp = new window.Razorpay({
        key: order.key_id,
        order_id: order.order_id,
        amount: order.amount,
        currency: order.currency,
        name: "Vachanam",
        description,
        prefill: { email: user?.email ?? "" },
        theme: { color: "#1b1b1a" },
        modal: { ondismiss: () => reject(new Error("Payment window closed")) },
        handler: async (resp) => {
          try {
            await verifyPayment({
              razorpay_order_id: resp.razorpay_order_id,
              razorpay_payment_id: resp.razorpay_payment_id,
              razorpay_signature: resp.razorpay_signature,
            });
            toast.success(done);
            refresh();
            resolve();
          } catch (e) {
            reject(new Error(
              e?.response?.data?.detail
              ?? "Payment verification failed — if money was deducted it activates automatically in a minute",
            ));
          }
        },
      });
      rzp.open();
    });
  };

  const [paying, setPaying] = useState(false);
  const payNow = async () => {
    const planKey = plan.data?.plan ?? "clinic";
    setPaying(true);
    try {
      await loadRazorpay();
      await checkout(
        await createPaymentOrder(planKey),
        `${PLAN_LABELS[planKey]} subscription`,
        "Payment received — your plan is active. Welcome aboard!",
      );
    } catch (e) {
      if (e?.message !== "Payment window closed") toast.error(e?.message ?? "Payment failed");
    } finally {
      setPaying(false);
    }
  };

  // Deliberately NOT a second Razorpay subscription: this charges ₹1,499 once
  // for the remainder of the cycle, and from the next renewal the amount rides
  // on the plan invoice (Vinay: "from next month on entire billing should come
  // together").
  const [buyingWa, setBuyingWa] = useState(false);
  const buyWhatsapp = async () => {
    setBuyingWa(true);
    try {
      await loadRazorpay();
      await checkout(
        await createWhatsappAddonOrder(),
        "WhatsApp add-on",
        "WhatsApp is on — patients can message your clinic number.",
      );
    } catch (e) {
      if (e?.message !== "Payment window closed") toast.error(e?.message ?? "Payment failed");
    } finally {
      setBuyingWa(false);
    }
  };

  const p = plan.data;
  // Days left computed against NOW on every render; the 60s refetch keeps it
  // live. The backend enforces the same 3-day window, so the UI lock is
  // honest, not decorative.
  const daysLeft = p?.cycle_end
    ? Math.ceil((new Date(p.cycle_end) - Date.now()) / 86400000)
    : null;
  const payable = p && (p.status !== "active" || !p.cycle_end || daysLeft <= 3);

  return (
    <section data-reveal className="card p-6">
      <p className="eyebrow">Plan &amp; payment</p>
      <h2 className="section-title text-xl">Change plan or pay</h2>
      <p className="mt-1 font-ui text-sm text-slate">
        Your billing cycle starts the day you pay and runs 30 days. Plan switches take
        effect from your next cycle, so you never lose minutes you have already paid for.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <div>
          <label className="label">Plan</label>
          <select className="field min-w-[220px]" value={p?.plan ?? "clinic"}
            disabled={planChange.isPending || plan.isLoading}
            onChange={(e) => planChange.mutate(e.target.value)}>
            <option value="lite">{PLAN_LABELS.lite}</option>
            <option value="solo">{PLAN_LABELS.solo}</option>
            <option value="clinic">{PLAN_LABELS.clinic}</option>
            <option value="multi">{PLAN_LABELS.multi}</option>
          </select>
        </div>
        <span className={p?.status === "active" ? "chip-token" : "chip-muted"}>
          {p?.status ?? "—"}
        </span>
        {p?.last_payment_date && (
          <span className="font-ui text-sm text-slate">
            Last paid <strong className="text-ink">{fmt(p.last_payment_date)}</strong>
          </span>
        )}
        {p?.cycle_end && p.status === "active" && (
          <span className="font-ui text-sm text-slate">
            Renews <strong className="text-ink">{fmt(p.cycle_end)}</strong>
            {daysLeft > 0 && (
              <> · <strong className="text-ink">{daysLeft}</strong> day{daysLeft === 1 ? "" : "s"} left</>
            )}
          </span>
        )}
        {p && (payable ? (
          <button type="button" className="btn-primary" disabled={paying} onClick={payNow}>
            {paying ? "Opening payment…"
              : `${p.status !== "active" ? "Activate" : p.cycle_end ? "Renew" : "Pay"} — ₹${(p.next_base_rupees || PLAN_PRICES[p.plan] || 0).toLocaleString("en-IN")}${p.is_offer ? " (offer)" : ""}${p.status === "active" && p.cycle_end ? " + usage" : ""}`}
          </button>
        ) : (
          <span className="chip-muted" title="Renewal opens 3 days before your cycle ends">
            Paid — renewal opens {fmt(new Date(new Date(p.cycle_end) - 3 * 86400000))}
          </span>
        ))}
        {p?.is_offer && (
          <span className="font-ui text-xs font-semibold text-amber-800">
            Offer price — first 3 months (regular ₹{(PLAN_PRICES[p.plan] ?? 0).toLocaleString("en-IN")}/mo)
          </span>
        )}
      </div>

      {p?.status === "active" && !p.cycle_end && (
        <p className="mt-2 font-ui text-xs text-slate">
          Your line is active without a paid cycle. Paying starts your 30-day billing cycle today.
        </p>
      )}
      {p && p.status !== "active" && (
        <p className="mt-2 font-ui text-xs text-slate">
          UPI, card or netbanking via Razorpay. Your line activates the moment payment
          succeeds, and your 30-day cycle starts today.
        </p>
      )}
      {p?.pending_plan && (
        <div className="mt-3 rounded-lg border border-line bg-surface-2 p-3">
          <p className="font-ui text-sm">
            <strong>Scheduled change.</strong> Switching to <strong>{p.pending_plan}</strong> on{" "}
            <strong>{p.pending_plan_effective}</strong>. Pick your current plan to cancel.
          </p>
        </div>
      )}

      {/* WhatsApp add-on. Four states, because selling a clinic something their
          plan already includes is worse than not selling it at all. */}
      {p && (
        <div className="mt-4 border-t border-hairline pt-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="font-ui text-sm font-medium text-ink">WhatsApp</p>
              <p className="mt-1 font-ui text-xs text-slate">
                {p.whatsapp_included
                  ? "Included in your plan — patients can message your clinic number."
                  : p.whatsapp_addon
                    ? "Active. From your next renewal it is billed together with your plan."
                    : p.whatsapp_included_pending
                      ? `Included from ${p.pending_plan_effective} when you move to ${p.pending_plan} — no need to buy it.`
                      : "Patients book, reschedule and ask questions over WhatsApp. ₹1,499/mo — charged now for this cycle, then billed with your plan."}
              </p>
            </div>
            {p.whatsapp_included || p.whatsapp_addon ? (
              <span className="chip whitespace-nowrap">on</span>
            ) : p.whatsapp_included_pending ? (
              <span className="chip whitespace-nowrap">from {p.pending_plan_effective}</span>
            ) : (
              <button className="btn-primary whitespace-nowrap px-4 py-2 text-sm"
                disabled={buyingWa || p.status !== "active"}
                onClick={buyWhatsapp}>
                {buyingWa ? "Opening…" : "Add WhatsApp · ₹1,499"}
              </button>
            )}
          </div>
          {p.status !== "active" && !p.whatsapp_included && !p.whatsapp_addon && (
            <p className="mt-2 font-ui text-xs text-slate">
              Activate your plan first — WhatsApp is billed alongside it.
            </p>
          )}
        </div>
      )}

      <p className="mt-3 font-ui text-xs text-slate">
        A detailed receipt (PDF attached) is emailed to you after every successful payment.
      </p>
    </section>
  );
}
