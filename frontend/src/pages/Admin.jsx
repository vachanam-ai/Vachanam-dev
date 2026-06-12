import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import gsap from "gsap";
import { toast } from "sonner";
import {
  addOwner,
  adminPing,
  fetchAdminOverview,
  fetchOwners,
  setOrgHardBlock,
  setOrgPlan,
  setOrgStatus
} from "../api/client.js";
import { pulseRow, revealStagger } from "../lib/motion.js";

const inr = (v) =>
  "₹" + Math.round(v ?? 0).toLocaleString("en-IN");

/* Animated numeral — counts up once data lands; respects reduced motion. */
function Numeral({ value, format = (v) => Math.round(v).toLocaleString("en-IN"), className = "" }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || value == null) return;
    const mm = gsap.matchMedia();
    mm.add(
      { motionOK: "(prefers-reduced-motion: no-preference)", reduce: "(prefers-reduced-motion: reduce)" },
      (ctx) => {
        if (ctx.conditions.reduce) {
          el.textContent = format(value);
          return;
        }
        const obj = { v: 0 };
        gsap.to(obj, {
          v: value,
          duration: 0.9,
          ease: "power2.out",
          onUpdate: () => {
            el.textContent = format(obj.v);
          }
        });
      }
    );
    return () => mm.revert();
  }, [value]);
  return <span ref={ref} className={className}>—</span>;
}

function GrowthChip({ pct }) {
  if (pct == null) return <span className="font-ui text-xs text-slate">no baseline</span>;
  const up = pct >= 0;
  return (
    <span className={`font-ui text-xs font-semibold ${up ? "text-teal-deep" : "text-danger"}`}>
      {up ? "▲" : "▼"} {Math.abs(pct)}% vs last month
    </span>
  );
}

/* 6-month money + minutes chart: revenue/expense bars, minutes as a line. */
function MoneyTrend({ monthly }) {
  const ref = useRef(null);
  const W = 560, H = 150, PAD = 8;
  const pts = monthly ?? [];
  const maxMoney = Math.max(1, ...pts.map((p) => Math.max(p.revenue, p.expense)));
  const maxMin = Math.max(1, ...pts.map((p) => p.minutes));
  const bw = pts.length ? (W - PAD * 2) / pts.length : 0;

  useEffect(() => {
    const el = ref.current;
    if (!el || !pts.length) return;
    const mm = gsap.matchMedia();
    mm.add("(prefers-reduced-motion: no-preference)", () => {
      gsap.fromTo(
        el.querySelectorAll("[data-bar]"),
        { scaleY: 0, transformOrigin: "bottom" },
        { scaleY: 1, duration: 0.5, ease: "power3.out", stagger: 0.04 }
      );
      gsap.fromTo(
        el.querySelector("[data-minline]"),
        { autoAlpha: 0 },
        { autoAlpha: 1, duration: 0.6, delay: 0.45, ease: "power1.out" }
      );
    });
    return () => mm.revert();
  }, [monthly]);

  if (!pts.length) return null;
  const minPath = pts
    .map((p, i) => {
      const x = PAD + i * bw + bw / 2;
      const y = H - PAD - (p.minutes / maxMin) * (H - PAD * 2 - 14);
      return `${i === 0 ? "M" : "L"}${x},${y}`;
    })
    .join(" ");

  return (
    <svg ref={ref} viewBox={`0 0 ${W} ${H + 18}`} className="w-full" role="img"
      aria-label="Revenue, expense and minutes by month">
      {pts.map((p, i) => {
        const x = PAD + i * bw;
        const rh = (p.revenue / maxMoney) * (H - PAD * 2 - 14);
        const eh = (p.expense / maxMoney) * (H - PAD * 2 - 14);
        const tip = `${p.month} — revenue ${inr(p.revenue)} · expense ${inr(p.expense)} · ${Math.round(p.minutes)} min · +${p.new_clients} clients`;
        return (
          <g key={p.month}>
            {/* full-column hover target so the numbers show anywhere over the month */}
            <rect x={x} y={0} width={bw} height={H} fill="transparent">
              <title>{tip}</title>
            </rect>
            <rect data-bar x={x + bw * 0.16} y={H - PAD - rh} width={bw * 0.28} height={Math.max(rh, 1)}
              rx="2" className="fill-teal-deep">
              <title>{tip}</title>
            </rect>
            <rect data-bar x={x + bw * 0.52} y={H - PAD - eh} width={bw * 0.28} height={Math.max(eh, 1)}
              rx="2" className="fill-gold-ink opacity-70">
              <title>{tip}</title>
            </rect>
            <text x={x + bw / 2} y={H + 12} textAnchor="middle" className="fill-slate font-ui text-[9px]">
              {p.month.slice(5)}
            </text>
          </g>
        );
      })}
      <path data-minline d={minPath} fill="none" strokeWidth="2" strokeDasharray="5 4"
        className="stroke-[#155e75]" pointerEvents="none" />
    </svg>
  );
}

function UsageBar({ row }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const mm = gsap.matchMedia();
    mm.add("(prefers-reduced-motion: no-preference)", () => {
      gsap.fromTo(el, { scaleX: 0, transformOrigin: "left" },
        { scaleX: 1, duration: 0.6, ease: "power3.out" });
    });
    return () => mm.revert();
  }, [row.pct_used]);
  const tone = row.exhausted ? "bg-danger" : row.approaching_limit ? "bg-gold-ink" : "bg-teal-deep";
  return (
    <div title={`${row.minutes_used} of ${row.minutes_included} min used (${row.pct_used}%) · ${row.minutes_left} left`}>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-hairline">
        <div ref={ref} className={`h-full rounded-full ${tone}`} style={{ width: `${row.pct_used}%` }} />
      </div>
      <p className="mt-1 font-ui text-[11px] text-slate">
        {row.minutes_used} / {row.minutes_included} min · {row.minutes_left} left
        {row.exhausted && <span className="ml-1 font-semibold text-danger">exhausted</span>}
        {!row.exhausted && row.approaching_limit && (
          <span className="ml-1 font-semibold text-gold-ink">approaching limit</span>
        )}
      </p>
    </div>
  );
}

function ClinicRow({ row, onAction }) {
  const ref = useRef(null);
  const act = (fn, label) =>
    onAction(fn, label, () => pulseRow(ref.current));
  return (
    <div ref={ref} className="grid items-center gap-3 px-5 py-3 md:grid-cols-[minmax(0,1.4fr)_repeat(3,minmax(0,1fr))_auto]">
      <div className="min-w-0">
        <p className="truncate font-ui font-medium">
          {row.name}
          {row.blocked_now && <span className="ml-2 rounded bg-danger/10 px-1.5 py-0.5 font-ui text-[10px] font-semibold text-danger">CALLS BLOCKED</span>}
        </p>
        <p className="truncate font-ui text-xs text-slate">
          {row.owner_phone} · {row.owner_email} · {row.branches} branch{row.branches === 1 ? "" : "es"} · {row.dids} DID
        </p>
        <div className="mt-1 flex items-center gap-2">
          <span className="chip-slot">{row.plan}</span>
          <span className={row.status === "active" ? "chip-token" : row.status === "trial" ? "chip-slot" : "chip-danger"}>
            {row.status}{row.status === "trial" && row.trial_days_left != null ? ` · ${row.trial_days_left}d` : ""}
          </span>
        </div>
      </div>
      <UsageBar row={row} />
      <div className="font-ui text-sm">
        <p>rev <span className="font-semibold text-teal-deep">{inr(row.revenue_month)}</span></p>
        <p>exp <span className="font-semibold text-gold-ink">{inr(row.expense_month)}</span></p>
        <p className={row.profit_month >= 0 ? "text-teal-deep" : "text-danger"}>
          profit <span className="font-semibold">{inr(row.profit_month)}</span>
        </p>
      </div>
      <div className="font-ui text-sm">
        <p><span className="font-semibold">{row.calls_month}</span> calls</p>
        <p><span className="font-semibold">{row.voice_bookings_month}</span> AI bookings</p>
      </div>
      <div className="flex flex-col gap-1.5">
        {row.status === "paused" ? (
          <button className="btn-primary !px-3 !py-1 text-xs"
            onClick={() => act(() => setOrgStatus(row.org_id, "active"), `${row.name} resumed`)}>
            Resume
          </button>
        ) : (
          <button className="rounded border border-danger px-3 py-1 font-ui text-xs font-semibold text-danger transition-transform active:scale-[0.97]"
            onClick={() => act(() => setOrgStatus(row.org_id, "paused"), `${row.name} paused`)}>
            Pause service
          </button>
        )}
        <select
          className="rounded border border-hairline px-2 py-1 font-ui text-xs"
          value={row.plan}
          onChange={(e) => act(() => setOrgPlan(row.org_id, e.target.value), `${row.name} → ${e.target.value}`)}
        >
          <option value="solo">solo</option>
          <option value="clinic">clinic</option>
          <option value="multi">multi</option>
        </select>
        <label className="flex items-center gap-1.5 font-ui text-[11px] text-slate">
          <input type="checkbox" checked={row.hard_block}
            onChange={(e) => act(() => setOrgHardBlock(row.org_id, e.target.checked),
              `${row.name} hard-block ${e.target.checked ? "ON" : "off"}`)} />
          hard-block at limit
        </label>
      </div>
    </div>
  );
}

export default function Admin() {
  const pageRef = useRef(null);
  const qc = useQueryClient();
  const [newOwner, setNewOwner] = useState({ email: "", name: "", password: "" });

  const { data: ping, error: pingError, isLoading: pingLoading } = useQuery({
    queryKey: ["admin-ping"], queryFn: adminPing, refetchInterval: 30_000
  });
  const { data: owners = [] } = useQuery({ queryKey: ["owners"], queryFn: fetchOwners });
  const { data: ov } = useQuery({
    queryKey: ["admin-overview"], queryFn: fetchAdminOverview, refetchInterval: 60_000
  });

  const orgAction = useMutation({
    mutationFn: ({ fn }) => fn(),
    onSuccess: (_d, { label, pulse }) => {
      qc.invalidateQueries({ queryKey: ["admin-overview"] });
      pulse?.();
      toast.success(label);
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Action failed")
  });
  const onAction = (fn, label, pulse) => orgAction.mutate({ fn, label, pulse });

  const invite = useMutation({
    mutationFn: () =>
      addOwner({ email: newOwner.email.trim(), name: newOwner.name.trim(), password: newOwner.password || null }),
    onSuccess: (o) => {
      qc.invalidateQueries({ queryKey: ["owners"] });
      setNewOwner({ email: "", name: "", password: "" });
      toast.success(`${o.email} is now a Vachanam owner`);
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not add owner")
  });

  useEffect(() => {
    revealStagger(pageRef.current);
  }, []);

  const approaching = useMemo(
    () => (ov?.clients ?? []).filter((c) => c.approaching_limit || c.exhausted),
    [ov]
  );

  return (
    <div ref={pageRef} className="space-y-6">
      <div data-reveal>
        <p className="eyebrow">Vachanam operations</p>
        <h1 className="section-title text-2xl">Platform console</h1>
        <p className="mt-1 font-ui text-sm text-slate">
          DPDP boundary: this console never shows clinic patient data — operations and billing only.
        </p>
      </div>

      {/* Hero business stats */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <div data-reveal className="card p-5">
          <p className="eyebrow">Clients</p>
          <p className="numeral mt-2 text-4xl text-teal-deep"><Numeral value={ov?.clients_total} /></p>
          <p className="mt-1">
            <GrowthChip pct={ov?.clients_growth_pct} />
          </p>
          <p className="font-ui text-xs text-slate">+{ov?.clients_new_this_month ?? 0} this month</p>
        </div>
        <div data-reveal className="card p-5">
          <p className="eyebrow">Minutes · month</p>
          <p className="numeral mt-2 text-4xl text-teal-deep"><Numeral value={ov?.minutes_this_month} /></p>
          <p className="mt-1"><GrowthChip pct={ov?.minutes_growth_pct} /></p>
          <p className="font-ui text-xs text-slate">{Math.round(ov?.minutes_all_time ?? 0).toLocaleString("en-IN")} min all-time</p>
        </div>
        <div data-reveal className="card p-5">
          <p className="eyebrow">Revenue · month</p>
          <p className="numeral mt-2 text-4xl text-teal-deep">
            <Numeral value={ov?.revenue_month} format={(v) => inr(v)} />
          </p>
        </div>
        <div data-reveal className="card p-5">
          <p className="eyebrow">Expense · month</p>
          <p className="numeral mt-2 text-4xl text-gold-ink">
            <Numeral value={ov?.expense_month} format={(v) => inr(v)} />
          </p>
        </div>
        <div data-reveal className="card p-5">
          <p className="eyebrow">Profit · month</p>
          <p className={`numeral mt-2 text-4xl ${(ov?.profit_month ?? 0) >= 0 ? "text-teal-deep" : "text-danger"}`}>
            <Numeral value={ov?.profit_month} format={(v) => inr(v)} />
          </p>
        </div>
        <div data-reveal className="card p-5">
          <p className="eyebrow">Today</p>
          <p className="numeral mt-2 text-4xl text-teal-deep"><Numeral value={ov?.calls_today} /></p>
          <p className="font-ui text-xs text-slate">
            calls · {ov?.voice_bookings_month ?? 0} AI bookings this month ·{" "}
            <span className={pingError ? "text-danger" : "text-teal-deep"}>
              API {pingLoading ? "…" : pingError ? "down" : "healthy"}
            </span>
          </p>
        </div>
      </div>

      {/* Money trend */}
      <section data-reveal className="card p-5">
        <div className="flex items-center justify-between">
          <h2 className="font-display text-lg font-semibold">Revenue vs expense · 6 months</h2>
          <p className="font-ui text-xs text-slate">
            <span className="mr-3"><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-teal-deep" />revenue</span>
            <span className="mr-3"><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-gold-ink opacity-70" />expense</span>
            <span><span className="mr-1 inline-block h-0.5 w-4 align-middle border-t-2 border-dashed border-[#155e75]" />minutes</span>
          </p>
        </div>
        <MoneyTrend monthly={ov?.monthly} />
      </section>

      {/* Approaching limit */}
      {approaching.length > 0 && (
        <section data-reveal className="card border-l-4 border-gold-ink p-5">
          <h2 className="font-display text-lg font-semibold">Approaching their minutes</h2>
          <div className="mt-2 space-y-1">
            {approaching.map((c) => (
              <p key={c.org_id} className="font-ui text-sm">
                <span className="font-medium">{c.name}</span>{" "}
                <span className={c.exhausted ? "font-semibold text-danger" : "text-gold-ink"}>
                  {c.exhausted ? "EXHAUSTED" : `${c.pct_used}% used`}
                </span>{" "}
                <span className="text-slate">— {c.minutes_left} min left of {c.minutes_included} ({c.plan})</span>
              </p>
            ))}
          </div>
        </section>
      )}

      {/* Clinic business ledger */}
      <section data-reveal className="card overflow-hidden">
        <header className="flex items-center justify-between border-b border-hairline bg-teal-mint/60 px-5 py-3">
          <h2 className="font-display text-lg font-semibold">Clinics — usage, money, controls</h2>
          <span className="font-ui text-sm text-slate">{ov?.clients_total ?? 0} total</span>
        </header>
        {!ov ? (
          <p className="px-5 py-6 font-ui text-sm text-slate">Loading…</p>
        ) : ov.clients.length === 0 ? (
          <p className="px-5 py-6 font-ui text-sm text-slate">No clinics registered yet.</p>
        ) : (
          <div className="divide-y divide-hairline">
            {ov.clients.map((row) => (
              <ClinicRow key={row.org_id} row={row} onAction={onAction} />
            ))}
          </div>
        )}
      </section>

      {/* Payments */}
      <section data-reveal className="card overflow-hidden">
        <header className="border-b border-hairline bg-teal-mint/60 px-5 py-3">
          <h2 className="font-display text-lg font-semibold">Payments</h2>
        </header>
        {!ov || ov.payments.length === 0 ? (
          <p className="px-5 py-6 font-ui text-sm text-slate">
            No billing cycles yet — rows appear here once Razorpay billing ships.
          </p>
        ) : (
          <div className="divide-y divide-hairline">
            {ov.payments.map((p, i) => (
              <div key={i} className="flex flex-wrap items-center gap-3 px-5 py-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate font-ui font-medium">{p.org_name}</p>
                  <p className="font-ui text-xs text-slate">
                    {p.cycle_start} → {p.cycle_end} · {p.minutes_used} min · {p.plan}
                    {p.invoice_number ? ` · ${p.invoice_number}` : ""}
                  </p>
                </div>
                <span className="font-ui font-semibold">{inr(p.amount)}</span>
                <span className={p.status === "paid" ? "chip-token" : p.status === "failed" ? "chip-danger" : "chip-slot"}>
                  {p.status}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Owners */}
      <section data-reveal className="card p-6">
        <h2 className="font-display text-lg font-semibold">Vachanam owners</h2>
        <p className="font-ui text-sm text-slate">
          Platform-level access. Owners can add other owners — clinics never can.
        </p>
        <div className="mt-4 space-y-1">
          {owners.map((o) => (
            <div key={o.user_id} className="ledger-row !px-0">
              <div className="min-w-0 flex-1">
                <p className="truncate font-ui font-medium">{o.name ?? o.email}</p>
                <p className="truncate font-ui text-xs text-slate">{o.email}</p>
              </div>
              <span className="chip-slot">owner</span>
            </div>
          ))}
        </div>
        <form
          className="mt-5 grid gap-3 border-t border-hairline pt-5 sm:grid-cols-3"
          onSubmit={(e) => {
            e.preventDefault();
            invite.mutate();
          }}
        >
          <div>
            <label className="label">Name</label>
            <input className="field" required value={newOwner.name}
              onChange={(e) => setNewOwner((s) => ({ ...s, name: e.target.value }))} />
          </div>
          <div>
            <label className="label">Email</label>
            <input className="field" type="email" required value={newOwner.email}
              onChange={(e) => setNewOwner((s) => ({ ...s, email: e.target.value }))} />
          </div>
          <div>
            <label className="label">Password (optional — Google works too)</label>
            <input className="field" minLength={8} value={newOwner.password} placeholder="leave blank for Google-only"
              onChange={(e) => setNewOwner((s) => ({ ...s, password: e.target.value }))} />
          </div>
          <button className="btn-primary sm:col-span-3" disabled={invite.isPending}>
            {invite.isPending ? "Adding…" : "Add owner"}
          </button>
        </form>
      </section>
    </div>
  );
}
