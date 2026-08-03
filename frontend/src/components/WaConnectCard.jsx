import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  connectWa,
  disconnectWa,
  fetchWaConnection,
  fetchWaSignupConfig,
} from "../api/client.js";
import useEmbeddedSignup from "../hooks/useEmbeddedSignup.js";

// One button. The clinic owner presses Connect, walks through Meta's own
// popup with the number they ALREADY use for the clinic, and comes back
// connected — no phone_number_id, no WABA id, no token typed anywhere.
//
// The failure messages below are deliberately specific. "Could not connect"
// sends an owner to us with nothing to act on; "your browser blocked the
// popup" they can fix themselves in five seconds.
const ERRORS = {
  not_configured:
    "WhatsApp sign-up isn't configured on the server yet — this is on us, not you.",
  cancelled: "Sign-up was closed before it finished — nothing was changed.",
  incomplete:
    "You authorised Vachanam but didn't finish picking a number, so nothing was connected. Press Connect to pick up where you left off.",
  sdk_blocked:
    "Your browser blocked Meta's sign-up script — usually an ad blocker or a strict network. Disable it for this page and try again.",
};

export default function WaConnectCard({ branchId }) {
  const qc = useQueryClient();
  const { launch, launching } = useEmbeddedSignup();

  const conn = useQuery({
    queryKey: ["wa-connection", branchId],
    queryFn: () => fetchWaConnection(branchId),
    enabled: Boolean(branchId),
  });
  const cfg = useQuery({
    queryKey: ["wa-signup-config", branchId],
    queryFn: () => fetchWaSignupConfig(branchId),
    enabled: Boolean(branchId),
  });

  const connect = useMutation({
    mutationFn: async () => {
      const c = cfg.data;
      const session = await launch({
        appId: c?.app_id,
        configId: c?.config_id,
        graphVersion: c?.graph_version,
      });
      return connectWa(branchId, session);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["wa-connection", branchId] });
      qc.invalidateQueries({ queryKey: ["wa-templates", branchId] });
      toast.success("WhatsApp connected — your clinic number is live.");
    },
    onError: (e) =>
      toast.error(ERRORS[e?.message] ?? e?.response?.data?.detail ?? "Could not connect WhatsApp."),
  });

  const remove = useMutation({
    mutationFn: () => disconnectWa(branchId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["wa-connection", branchId] });
      toast.success("WhatsApp disconnected.");
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not disconnect."),
  });

  if (conn.isLoading) {
    return <p className="font-ui text-sm text-slate">Checking WhatsApp connection…</p>;
  }

  const connected = Boolean(conn.data?.connected);
  const configured = cfg.data?.configured !== false;

  if (connected) {
    return (
      <div data-testid="wa-connected" className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="chip-token">connected</span>
          <span className="font-ui text-sm text-ink">
            {conn.data?.wa_verified_name || "Your WhatsApp Business number"}
          </span>
        </div>
        <p className="font-ui text-sm text-slate">
          Patients messaging this number reach your AI assistant. You can keep
          using WhatsApp on your own phone at the same time — messages appear in
          both places.
        </p>
        <button type="button" className="btn-ghost text-danger" disabled={remove.isPending}
          onClick={() => {
            if (window.confirm(
              "Disconnect WhatsApp? Patients messaging your number will stop getting replies until you reconnect.",
            )) remove.mutate();
          }}>
          {remove.isPending ? "Disconnecting…" : "Disconnect"}
        </button>
      </div>
    );
  }

  return (
    <div data-testid="wa-connect" className="space-y-3">
      <p className="font-ui text-sm text-slate">
        Connect the WhatsApp number your clinic already uses. Meta will ask you
        to confirm it — you won't need to copy any codes or IDs across.
      </p>
      <button type="button" className="btn-primary" data-testid="wa-connect-button"
        disabled={!configured || connect.isPending || launching}
        onClick={() => connect.mutate()}>
        {connect.isPending || launching ? "Opening WhatsApp…" : "Connect WhatsApp"}
      </button>
      {!configured && (
        <p className="font-ui text-xs text-danger">{ERRORS.not_configured}</p>
      )}
    </div>
  );
}
