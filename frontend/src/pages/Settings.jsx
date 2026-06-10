import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "../api/client.js";
import { useAuth } from "../hooks/useAuth.jsx";
import { revealStagger } from "../lib/motion.js";
import VoicePicker from "../components/VoicePicker.jsx";

export default function Settings() {
  const { branchId } = useAuth();
  const qc = useQueryClient();
  const pageRef = useRef(null);

  const { data, isLoading } = useQuery({
    queryKey: ["branch-settings", branchId],
    queryFn: () => api.get(`/branches/${branchId}/settings`).then((r) => r.data),
    enabled: Boolean(branchId)
  });

  useEffect(() => {
    if (data) revealStagger(pageRef.current);
  }, [Boolean(data)]); // eslint-disable-line react-hooks/exhaustive-deps

  const setVoice = useMutation({
    mutationFn: (tts_voice) =>
      api.patch(`/branches/${branchId}/voice`, { tts_voice }).then((r) => r.data),
    onSuccess: (d) => {
      qc.setQueryData(["branch-settings", branchId], d);
      toast.success(`Voice set to ${d.tts_voice} — next call uses it`);
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not change voice")
  });

  if (isLoading) return <p className="font-ui text-slate">Loading settings…</p>;

  return (
    <div ref={pageRef} className="space-y-8">
      <div data-reveal>
        <p className="eyebrow">Clinic settings</p>
        <h1 className="section-title text-2xl">{data?.name}</h1>
      </div>

      <section data-reveal className="space-y-4">
        <div>
          <h2 className="font-display text-lg font-semibold">Agent voice</h2>
          <p className="font-ui text-sm text-slate">
            The voice patients hear when they call. Changes apply from the next call.
          </p>
        </div>
        <VoicePicker
          value={data?.tts_voice}
          onSelect={(v) => setVoice.mutate(v)}
        />
      </section>

      <section data-reveal className="card p-5">
        <h2 className="font-display text-lg font-semibold">Phone line</h2>
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          <div>
            <p className="label">Clinic AI number (DID)</p>
            <p className="numeral text-xl text-teal-deep">{data?.did_number ?? "not assigned"}</p>
          </div>
          <div>
            <p className="label">Emergency contact</p>
            <p className="numeral text-xl text-teal-deep">{data?.emergency_contact ?? "—"}</p>
          </div>
        </div>
        <p className="mt-3 font-ui text-xs text-slate">
          Number provisioning and change requests are handled during onboarding — DID
          self-service arrives with the onboarding flow.
        </p>
      </section>
    </div>
  );
}
