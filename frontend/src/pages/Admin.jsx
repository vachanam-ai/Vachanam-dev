import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { addOwner, adminPing, fetchClients, fetchOwners } from "../api/client.js";
import { revealStagger } from "../lib/motion.js";

export default function Admin() {
  const pageRef = useRef(null);
  const qc = useQueryClient();
  const [newOwner, setNewOwner] = useState({ email: "", name: "", password: "" });
  const { data, error, isLoading } = useQuery({
    queryKey: ["admin-ping"],
    queryFn: adminPing,
    refetchInterval: 30_000
  });
  const { data: owners = [] } = useQuery({ queryKey: ["owners"], queryFn: fetchOwners });
  const { data: clients } = useQuery({ queryKey: ["clients"], queryFn: fetchClients, refetchInterval: 60_000 });

  const invite = useMutation({
    mutationFn: () =>
      addOwner({
        email: newOwner.email.trim(),
        name: newOwner.name.trim(),
        password: newOwner.password || null
      }),
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

  return (
    <div ref={pageRef} className="space-y-6">
      <div data-reveal>
        <p className="eyebrow">Vachanam operations</p>
        <h1 className="section-title text-2xl">Platform console</h1>
        <p className="mt-1 font-ui text-sm text-slate">
          DPDP boundary: this console never shows clinic patient data — operations and billing only.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <div data-reveal className="card p-5">
          <p className="eyebrow">API</p>
          <p className={`mt-2 font-display text-2xl font-semibold ${error ? "text-danger" : "text-teal-deep"}`}>
            {isLoading ? "…" : error ? "Unreachable" : "Healthy"}
          </p>
          {data?.ts && <p className="mt-1 font-ui text-xs text-slate">last ping {data.ts}</p>}
        </div>
        <div data-reveal className="card p-5">
          <p className="eyebrow">Clients</p>
          <p className="numeral mt-2 text-4xl text-teal-deep">{clients?.total_clients ?? "—"}</p>
          <p className="mt-1 font-ui text-xs text-slate">
            {clients ? `${clients.trialing} trial · ${clients.active} active · ${clients.paused} paused` : "loading…"}
          </p>
        </div>
        <div data-reveal className="card p-5">
          <p className="eyebrow">On trial</p>
          <p className="numeral mt-2 text-4xl text-gold-ink">{clients?.trialing ?? "—"}</p>
          <p className="mt-1 font-ui text-xs text-slate">convert before day 14</p>
        </div>
      </div>

      {/* Registered clinics + billing status */}
      <section data-reveal className="card overflow-hidden">
        <header className="flex items-center justify-between border-b border-hairline bg-teal-mint/60 px-5 py-3">
          <h2 className="font-display text-lg font-semibold">Registered clinics</h2>
          <span className="font-ui text-sm text-slate">{clients?.total_clients ?? 0} total</span>
        </header>
        {!clients ? (
          <p className="px-5 py-6 font-ui text-sm text-slate">Loading clients…</p>
        ) : clients.clients.length === 0 ? (
          <p className="px-5 py-6 font-ui text-sm text-slate">No clinics registered yet.</p>
        ) : (
          <div className="divide-y divide-hairline">
            {clients.clients.map((c) => (
              <div key={c.org_id} className="flex flex-wrap items-center gap-3 px-5 py-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate font-ui font-medium">{c.name}</p>
                  <p className="truncate font-ui text-xs text-slate">
                    {c.owner_email} · {c.owner_phone} · {c.branches} branch{c.branches === 1 ? "" : "es"}
                  </p>
                </div>
                <span className="chip-slot">{c.plan}</span>
                <span className={c.status === "trial" ? "chip-token" : c.status === "active" ? "chip-token" : "chip-danger"}>
                  {c.status}
                </span>
                <div className="w-24 text-right">
                  {c.status === "trial" && c.days_left != null ? (
                    <span className="font-ui text-sm text-gold-ink">{c.days_left}d left</span>
                  ) : (
                    <span className="font-ui text-xs text-slate">
                      {c.created_at ? new Date(c.created_at).toLocaleDateString("en-IN") : ""}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
        <p className="border-t border-hairline px-5 py-3 font-ui text-xs text-slate">
          Voice-minute usage + Razorpay invoice status attach here once the billing service ships.
        </p>
      </section>

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
