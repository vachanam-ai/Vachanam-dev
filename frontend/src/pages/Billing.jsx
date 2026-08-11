import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Link, useSearchParams } from "react-router-dom";
import PageHeader from "../components/PageHeader.jsx";
import PlanAndPayment from "../components/PlanAndPayment.jsx";
import { revealStagger } from "../lib/motion.js";
import { cancelSubscription, fetchBillingSummary } from "../api/client.js";

/* Dedicated billing page (Vinay 2026-08-07: "this is money part right. so, i
   feel this way it will be better").

   Billing was a card buried in Settings, between the clinic's phone number and
   its greeting. Money deserves its own screen: what you are on, what you have
   used, what the next charge will be and why, and every past cycle.

   ONE rule drove the layout: never make the reader do arithmetic. Every figure
   is computed server-side (/api/billing/summary) and the next charge is shown
   as an itemised breakdown that adds up on screen, so the page can never
   disagree with the invoice. */

const money = (n) =>
  `₹${Number(n || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

const day = (iso) =>
  iso
    ? new Date(iso).toLocaleDateString("en-IN", {
        day: "numeric", month: "short", year: "numeric",
      })
    : "—";

const STATUS_CHIP = {
  paid: "chip-token",
  active: "chip-token",
  open: "chip-muted",
  invoiced: "chip-muted",
  failed: "chip-danger",
  paused: "chip-danger",
};

function Row({ label, value, hint, strong }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2">
      <div className="min-w-0">
        <p className={`font-ui text-sm ${strong ? "font-medium" : "text-slate"}`}>
          {label}
        </p>
        {hint && <p className="font-ui text-xs text-slate">{hint}</p>}
      </div>
      <p className={`shrink-0 tabular-nums ${strong ? "text-lg font-semibold" : "font-ui text-sm"}`}>
        {value}
      </p>
    </div>
  );
}

/** Minutes used against the plan's bucket. Turns amber past the bucket, because
    that is the moment the clinic starts paying per minute. */
function UsageBar({ used, included }) {
  if (!included) return null;
  const pct = Math.min(100, Math.round((used / included) * 100));
  const over = used > included;
  return (
    <div className="mt-3">
      <div className="h-2 w-full overflow-hidden rounded-full bg-line">
        <div
          className={`h-full rounded-full ${over ? "bg-gold" : "bg-teal"}`}
          style={{ width: `${over ? 100 : pct}%` }}
        />
      </div>
      <p className="mt-2 font-ui text-xs text-slate">
        {used.toLocaleString("en-IN")} of {included.toLocaleString("en-IN")} included
        minutes used{over ? " — extra minutes are billed at the rate below" : ` (${pct}%)`}
      </p>
    </div>
  );
}

export default function Billing() {
  const [searchParams] = useSearchParams();
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const cancelM = useMutation({
    mutationFn: (cancel) => cancelSubscription(cancel),
    onSuccess: (_d, cancel) => {
      setConfirming(false);
      qc.invalidateQueries({ queryKey: ["billing-summary"] });
      qc.invalidateQueries({ queryKey: ["plan"] });
      toast.success(
        cancel
          ? "Cancellation scheduled — you keep everything until your cycle ends."
          : "Cancellation withdrawn. Nothing changes.",
      );
    },
    onError: (e) =>
      toast.error(e?.response?.data?.detail ?? "Could not update the subscription"),
  });

  const q = useQuery({
    queryKey: ["billing-summary"],
    queryFn: fetchBillingSummary,
    refetchInterval: 60_000,
  });
  const d = q.data;

  // Without this the page is INVISIBLE, not empty (Vinay 2026-08-07: "billing
  // page is completely empty"). index.css pre-hides every [data-reveal] block
  // at opacity 0 until a reveal pass stamps [data-revealed] on it, and this
  // page marks its header and all five sections. Re-run when the query lands
  // as well as on mount: the cards only exist once `d` is set, so a
  // mount-only reveal would leave them hidden forever — the same failure
  // Availability hit on 2026-07-12 (FIXLOG #334).
  const pageRef = useRef(null);
  useEffect(() => {
    revealStagger(pageRef.current);
  }, [q.isLoading, q.isError, d, confirming]);

  return (
    <div ref={pageRef} className="space-y-6">
      <PageHeader
        eyebrow="Money"
        title="Billing"
        sub="Your plan, this month's usage, and every past cycle."
      >
        <Link to="/settings" className="btn-ghost">
          Clinic settings
        </Link>
      </PageHeader>

      {q.isLoading && <div className="card p-6 font-ui text-sm text-slate">Loading…</div>}
      {q.isError && (
        <div className="card p-6 font-ui text-sm">
          Could not load billing right now.{" "}
          <button className="underline" onClick={() => q.refetch()}>Try again</button>
        </div>
      )}

      {d && (
        <>
          <div className="grid gap-5 lg:grid-cols-3">
            {/* Plan */}
            <section data-reveal className="card p-6 lg:col-span-1">
              <p className="eyebrow">Current plan</p>
              <div className="mt-1 flex items-center gap-2">
                <h2 className="section-title text-xl">{d.plan_label}</h2>
                <span className={STATUS_CHIP[d.status] || "chip-muted"}>{d.status}</span>
              </div>
              {d.is_offer && (
                <p className="mt-2 font-ui text-xs text-slate">
                  Offer price — first 3 months
                </p>
              )}
              <p className="mt-3 font-ui text-sm text-slate">
                {d.has_billed ? (
                  <>Renews on <span className="font-medium text-ink">{day(d.cycle_end)}</span></>
                ) : (
                  <>
                    First charge on{" "}
                    <span className="font-medium text-ink">{day(d.cycle_end)}</span>. Your
                    usage below is already being counted.
                  </>
                )}
              </p>
              <a href="#plan-payment" className="btn-primary mt-4 inline-flex">
                Adjust plan
              </a>
            </section>

            {/* Usage */}
            <section data-reveal className="card p-6 lg:col-span-2">
              <p className="eyebrow">This cycle</p>
              <h2 className="section-title text-xl">Usage</h2>
              <p className="mt-1 font-ui text-xs text-slate">
                {d.cycle_start ? `${day(d.cycle_start)} — ${day(d.cycle_end)}` : "—"}
                {!d.has_billed && " · not invoiced yet"}
              </p>
              <UsageBar used={d.minutes_used} included={d.included_minutes} />
              <div className="mt-4 grid grid-cols-3 gap-4 border-t border-line pt-4">
                <div>
                  <p className="font-ui text-xs text-slate">Minutes used</p>
                  <p className="text-lg font-semibold tabular-nums">
                    {d.minutes_used.toLocaleString("en-IN")}
                  </p>
                </div>
                <div>
                  <p className="font-ui text-xs text-slate">Extra minutes</p>
                  <p className="text-lg font-semibold tabular-nums">
                    {d.overage_minutes.toLocaleString("en-IN")}
                  </p>
                </div>
                <div>
                  <p className="font-ui text-xs text-slate">Extra cost</p>
                  <p className="text-lg font-semibold tabular-nums">
                    {money(d.overage_amount)}
                  </p>
                </div>
              </div>
            </section>
          </div>

          {/* Next charge — itemised so it adds up on screen */}
          <section data-reveal className="card p-6">
            <p className="eyebrow">Next charge</p>
            <h2 className="section-title text-xl">What you will pay</h2>
            <div className="mt-3 divide-y divide-line">
              {d.base_next > 0 && (
                <Row label={`${d.next_plan_label} plan`} value={money(d.base_next)} />
              )}
              {d.whatsapp_addon_amount > 0 && (
                <Row label="WhatsApp add-on" value={money(d.whatsapp_addon_amount)} />
              )}
              {d.overage_minutes > 0 && (
                <Row
                  label="Extra minutes"
                  hint={`${d.overage_minutes.toLocaleString("en-IN")} × ₹${d.overage_rate}/min`}
                  value={money(d.overage_amount)}
                />
              )}
              {d.gst_amount > 0 && <Row label="GST (18%)" value={money(d.gst_amount)} />}
              <Row label="Total" value={money(d.total_next)} strong />
            </div>
            <p className="mt-3 font-ui text-xs text-slate">
              {d.cancellation_effective
                ? "No plan renewal will be charged. Any current-cycle extra minutes remain payable."
                : d.autopay_enabled
                  ? "Plan and WhatsApp charges renew automatically. Extra voice minutes are invoiced separately."
                  : "Paid manually each cycle - the button is below."}
            </p>
          </section>

          {/* Plan & payment — moved here from Settings (Vinay 2026-08-09).
              Anchored so "Adjust plan" above scrolls to it instead of leaving
              the page. */}
          <div>
            <PlanAndPayment initialPlan={searchParams.get("plan")} />
          </div>

          {/* History */}
          <section data-reveal className="card p-6">
            <p className="eyebrow">History</p>
            <h2 className="section-title text-xl">Past cycles</h2>
            {d.history.length === 0 ? (
              <p className="mt-3 font-ui text-sm text-slate">
                Nothing billed yet — your first cycle will appear here.
              </p>
            ) : (
              <div className="mt-3 overflow-x-auto">
                <table className="w-full min-w-[640px] text-left">
                  <thead>
                    <tr className="font-ui text-xs uppercase tracking-wide text-slate">
                      <th className="py-2 pr-4 font-medium">Cycle</th>
                      <th className="py-2 pr-4 font-medium">Plan</th>
                      <th className="py-2 pr-4 text-right font-medium">Minutes</th>
                      <th className="py-2 pr-4 text-right font-medium">Extra</th>
                      <th className="py-2 pr-4 text-right font-medium">Total</th>
                      <th className="py-2 font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody className="font-ui text-sm">
                    {d.history.map((c) => (
                      <tr key={`${c.cycle_start}-${c.cycle_end}`} className="border-t border-line">
                        <td className="py-3 pr-4 whitespace-nowrap">
                          {day(c.cycle_start)} — {day(c.cycle_end)}
                          {c.invoice_number && (
                            <span className="block text-xs text-slate">{c.invoice_number}</span>
                          )}
                        </td>
                        <td className="py-3 pr-4 capitalize">{c.plan}</td>
                        <td className="py-3 pr-4 text-right tabular-nums">
                          {(c.minutes_used || 0).toLocaleString("en-IN")}
                        </td>
                        <td className="py-3 pr-4 text-right tabular-nums">
                          {c.overage_minutes ? money(c.overage_amount) : "—"}
                        </td>
                        <td className="py-3 pr-4 text-right font-medium tabular-nums">
                          {money(c.total)}
                        </td>
                        <td className="py-3">
                          <span className={STATUS_CHIP[c.status] || "chip-muted"}>
                            {c.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          {/* Leaving. Placed last and styled quietly: available, not inviting. */}
          <section data-reveal className="card p-6">
            <p className="eyebrow">Leaving</p>
            <h2 className="section-title text-xl">Cancel your subscription</h2>

            {d.cancellation_effective ? (
              <>
                <p className="mt-2 font-ui text-sm">
                  Your subscription ends on{" "}
                  <span className="font-medium">{day(d.cancellation_effective)}</span>. Until
                  then everything keeps working exactly as it does now.
                </p>
                {!d.autopay_enabled && (
                  <button
                    className="btn-primary mt-4"
                    disabled={cancelM.isPending}
                    onClick={() => cancelM.mutate(false)}
                  >
                    Keep my subscription
                  </button>
                )}
                {d.autopay_enabled && (
                  <p className="mt-2 font-ui text-xs text-slate">
                    Razorpay does not reactivate a scheduled cancellation. You can
                    enable a new mandate after this subscription ends.
                  </p>
                )}
              </>
            ) : (
              <>
                <p className="mt-2 font-ui text-sm text-slate">
                  You have already paid for this cycle, so nothing stops today — any change
                  takes effect on{" "}
                  <span className="font-medium text-ink">{day(d.cycle_end)}</span>, when your
                  current cycle ends.
                </p>

                {d.plan !== "wa" && (
                  <div className="mt-4 rounded-lg border border-line p-4">
                    <p className="font-ui text-sm font-medium">
                      Only want to stop the phone line?
                    </p>
                    <p className="mt-1 font-ui text-sm text-slate">
                      Switch to the WhatsApp-only plan instead and keep booking patients on
                      chat. You keep your patients, doctors and history.
                    </p>
                    <Link to="/billing?plan=wa#plan-payment" className="btn-ghost mt-3 inline-flex">
                      Review WhatsApp-only switch
                    </Link>
                  </div>
                )}

                {!confirming ? (
                  <button className="btn-ghost mt-4" onClick={() => setConfirming(true)}>
                    Cancel everything
                  </button>
                ) : (
                  <div className="mt-4 rounded-lg border border-line p-4">
                    <p className="font-ui text-sm">
                      Cancel completely on {day(d.cycle_end)}? Your AI line stops answering
                      after that date. Your data stays and you can come back any time.
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button
                        className="btn-danger"
                        disabled={cancelM.isPending}
                        onClick={() => cancelM.mutate(true)}
                      >
                        {cancelM.isPending ? "Scheduling…" : "Yes, cancel"}
                      </button>
                      <button className="btn-ghost" onClick={() => setConfirming(false)}>
                        Never mind
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
          </section>
        </>
      )}
    </div>
  );
}
