import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { adminPing } from "../api/client.js";
import { revealStagger } from "../lib/motion.js";

export default function Admin() {
  const pageRef = useRef(null);
  const { data, error, isLoading } = useQuery({
    queryKey: ["admin-ping"],
    queryFn: adminPing,
    refetchInterval: 30_000
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
    </div>
  );
}
