import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  confirmWaPayment,
  connectWa,
  disconnectWa,
  fetchWaConnection,
  fetchWaSignupConfig,
  retryWaSync,
} from "../api/client.js";
import useEmbeddedSignup from "../hooks/useEmbeddedSignup.js";
import { useActionDialog } from "./ActionDialog.jsx";

const ERRORS = {
  not_configured: "WhatsApp sign-up is not configured on the server yet.",
  cancelled: "Sign-up was closed before it finished. Nothing was changed.",
  incomplete: "Meta did not return the selected number. Please run sign-up again.",
  sdk_blocked: "Your browser blocked Meta's sign-up script. Disable the blocker for this page and retry.",
};

export default function WaConnectCard({ branchId }) {
  const qc = useQueryClient();
  const ask = useActionDialog();
  const { launch, launching } = useEmbeddedSignup();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["wa-connection", branchId] });
    qc.invalidateQueries({ queryKey: ["wa-templates", branchId] });
    qc.invalidateQueries({ queryKey: ["branch-settings", branchId] });
  };

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
    mutationFn: async (mode) => {
      const config = cfg.data;
      const session = await launch({
        appId: config?.app_id,
        configId: config?.config_id,
        graphVersion: config?.graph_version,
        featureType: mode === "coexistence" ? config?.feature_type : undefined,
      });
      return connectWa(branchId, session);
    },
    onSuccess: () => {
      refresh();
      toast.success("WhatsApp connected. Complete Meta's payment step below.");
    },
    onError: (error) => toast.error(
      ERRORS[error?.message] ?? error?.response?.data?.detail ?? "Could not connect WhatsApp.",
    ),
  });

  const confirmPayment = useMutation({
    mutationFn: () => confirmWaPayment(branchId),
    onSuccess: () => { refresh(); toast.success("Payment-method step confirmed."); },
    onError: (error) => toast.error(error?.response?.data?.detail ?? "Could not save confirmation."),
  });

  const retrySync = useMutation({
    mutationFn: () => retryWaSync(branchId),
    onSuccess: () => { refresh(); toast.success("WhatsApp synchronization restarted."); },
    onError: (error) => toast.error(error?.response?.data?.detail ?? "Could not restart synchronization."),
  });

  const remove = useMutation({
    mutationFn: () => disconnectWa(branchId),
    onSuccess: (result) => {
      qc.cancelQueries({ queryKey: ["wa-chats", branchId] });
      qc.cancelQueries({ queryKey: ["wa-chat", branchId] });
      qc.removeQueries({ queryKey: ["wa-chats", branchId] });
      qc.removeQueries({ queryKey: ["wa-chat", branchId] });
      qc.setQueryData(["wa-connection", branchId], { ...result, connected: false });
      refresh();
      toast.success("WhatsApp disconnected.");
    },
    onError: (error) => toast.error(error?.response?.data?.detail ?? "Could not disconnect."),
  });

  if (conn.isLoading) return <p className="font-ui text-sm text-slate">Checking WhatsApp connection…</p>;

  const connected = Boolean(conn.data?.connected);
  const configured = cfg.data?.configured !== false;
  const onboarding = conn.data?.onboarding || {};
  const sync = onboarding.sync || {};
  const syncError = [sync.contacts, sync.history].some((item) => item?.status === "error");
  const syncRunning = onboarding.mode === "coexistence" && !syncError
    && [sync.contacts, sync.history].some((item) => item?.status === "requested");
  const tokenExpiry = onboarding.token_expires_at
    ? new Date(onboarding.token_expires_at).getTime() : null;
  const tokenExpired = tokenExpiry && tokenExpiry <= Date.now();
  const tokenExpiringSoon = tokenExpiry && !tokenExpired
    && tokenExpiry <= Date.now() + 7 * 24 * 60 * 60 * 1000;

  if (connected) {
    return (
      <div data-testid="wa-connected" className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="chip-token">connected</span>
          <span className="font-ui text-sm text-ink">
            {conn.data?.wa_verified_name || "Your WhatsApp Business number"}
          </span>
          {onboarding.mode === "coexistence" && <span className="chip-muted">Business app + API</span>}
        </div>

        {(tokenExpired || tokenExpiringSoon) && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
            <p className="font-ui text-sm font-semibold text-ink">
              {tokenExpired ? "WhatsApp authorization expired" : "WhatsApp authorization expires soon"}
            </p>
            <p className="mt-1 font-ui text-xs text-slate">
              Run Meta sign-up again to renew this clinic's business integration token.
            </p>
            <button type="button" className="btn-secondary mt-3"
              disabled={connect.isPending || launching}
              onClick={() => connect.mutate(onboarding.mode || "coexistence")}>
              Reconnect with Meta
            </button>
          </div>
        )}

        {onboarding.payment_status !== "confirmed" && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
            <p className="font-ui text-sm font-semibold text-ink">Add the clinic's payment method in Meta</p>
            <p className="mt-1 font-ui text-xs text-slate">
              Meta bills Cloud API messages directly to the clinic. Vachanam never receives the card details.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <a className="btn-primary" href={onboarding.payment_method_url}
                target="_blank" rel="noreferrer">Open WhatsApp Manager</a>
              <button type="button" className="btn-secondary"
                disabled={confirmPayment.isPending}
                onClick={() => confirmPayment.mutate()}>
                I added the payment method
              </button>
            </div>
          </div>
        )}

        {syncError && (
          <div className="rounded-xl border border-danger/30 bg-danger/5 p-4">
            <p className="font-ui text-sm font-semibold text-ink">Business app synchronization needs attention</p>
            <button type="button" className="btn-secondary mt-3"
              disabled={retrySync.isPending} onClick={() => retrySync.mutate()}>
              Retry synchronization
            </button>
          </div>
        )}
        {syncRunning && (
          <p className="font-ui text-xs text-slate">
            Meta is synchronizing permitted contacts and recent chat history. The clinic can keep using its WhatsApp Business app.
          </p>
        )}

        <button type="button" className="btn-ghost text-danger" disabled={remove.isPending}
          onClick={async () => {
            const confirmed = await ask({
              title: "Disconnect WhatsApp?",
              description: "New messages and automations will stop, and stored WhatsApp conversations will be removed from Vachanam.",
              confirmLabel: "Disconnect",
              tone: "danger",
            });
            if (confirmed) remove.mutate();
          }}>
          {remove.isPending ? "Disconnecting…" : "Disconnect"}
        </button>
      </div>
    );
  }

  return (
    <div data-testid="wa-connect" className="space-y-3">
      <p className="font-ui text-sm text-slate">
        Connect an existing WhatsApp Business app number or add a new Cloud API number through Meta's official Embedded Signup v4 flow.
      </p>
      <button type="button" className="btn-primary" data-testid="wa-connect-button"
        disabled={!configured || connect.isPending || launching}
        onClick={() => connect.mutate("coexistence")}>
        {connect.isPending || launching ? "Opening Meta…" : "Connect existing WhatsApp Business app"}
      </button>
      <button type="button" className="btn-secondary"
        disabled={!configured || connect.isPending || launching}
        onClick={() => connect.mutate("cloud_api")}>
        Set up a new Cloud API number
      </button>
      {!configured && <p className="font-ui text-xs text-danger">{ERRORS.not_configured}</p>}
      <p className="font-ui text-xs text-slate">
        Requires WhatsApp Business app 2.24.17 or newer for an existing app number. Meta may temporarily unlink companion devices during setup.
      </p>
    </div>
  );
}
