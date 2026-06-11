import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { addOwner, adminPing, fetchOwners } from "../api/client.js";
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
          <p className="numeral mt-2 text-4xl text-teal-deep">—</p>
          <p className="mt-1 font-ui text-xs text-slate">org/billing roll-up lands with the billing service</p>
        </div>
        <div data-reveal className="card p-5">
          <p className="eyebrow">Voice minutes (month)</p>
          <p className="numeral mt-2 text-4xl text-teal-deep">—</p>
          <p className="mt-1 font-ui text-xs text-slate">wired to call ledger after Fly.io deploy</p>
        </div>
      </div>

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
