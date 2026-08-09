import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  connectWa,
  connectWaManual,
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

// Fallback path. Embedded Signup can't run until our Meta app is published
// Live, and a clinic on a partner-managed WABA may never see that popup — so
// the card also accepts the three values Meta's own API Setup screen shows.
// Collapsed by default: the popup is the path almost every clinic should take.
function ManualConnect({ branchId, onConnected }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    waba_id: "", phone_number_id: "", access_token: "",
  });

  const connect = useMutation({
    mutationFn: () => connectWaManual(branchId, form),
    onSuccess: () => {
      setForm({ waba_id: "", phone_number_id: "", access_token: "" });
      setOpen(false);
      onConnected();
      toast.success("WhatsApp connected.");
    },
    onError: (e) =>
      toast.error(e?.response?.data?.detail ?? "Could not connect with those details."),
  });

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const numeric = (v) => /^\d+$/.test(v.trim());
  const ready =
    numeric(form.waba_id) && numeric(form.phone_number_id)
    && form.access_token.trim().length >= 20;

  if (!open) {
    return (
      <button type="button" data-testid="wa-manual-toggle"
        className="font-ui text-xs font-medium text-slate underline-offset-2 hover:underline"
        onClick={() => setOpen(true)}>
        Enter the details manually instead
      </button>
    );
  }

  return (
    <form data-testid="wa-manual-form" className="space-y-3 border-t border-hairline pt-4"
      onSubmit={(e) => { e.preventDefault(); connect.mutate(); }}>
      <p className="font-ui text-xs text-slate">
        From Meta's <strong className="text-ink">WhatsApp → API Setup</strong> page.
        The token is stored encrypted and is never shown again.
      </p>
      <label className="block font-ui text-xs font-medium text-ink">
        WhatsApp Business Account ID
        <input className="input mt-1" inputMode="numeric" autoComplete="off"
          data-testid="wa-manual-waba" value={form.waba_id} onChange={set("waba_id")} />
      </label>
      <label className="block font-ui text-xs font-medium text-ink">
        Phone number ID
        <input className="input mt-1" inputMode="numeric" autoComplete="off"
          data-testid="wa-manual-phone" value={form.phone_number_id}
          onChange={set("phone_number_id")} />
      </label>
      <label className="block font-ui text-xs font-medium text-ink">
        Access token
        {/* type=password so a token never sits in plain view during a screen
            share or a support call — the one place it exists in the browser. */}
        <input className="input mt-1" type="password" autoComplete="off"
          data-testid="wa-manual-token" value={form.access_token}
          onChange={set("access_token")} />
      </label>
      <div className="flex items-center gap-3">
        <button type="submit" className="btn-primary" data-testid="wa-manual-submit"
          disabled={!ready || connect.isPending}>
          {connect.isPending ? "Connecting…" : "Connect"}
        </button>
        <button type="button" className="btn-ghost" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </form>
  );
}

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
      <ManualConnect branchId={branchId} onConnected={() => {
        qc.invalidateQueries({ queryKey: ["wa-connection", branchId] });
        qc.invalidateQueries({ queryKey: ["wa-templates", branchId] });
      }} />
    </div>
  );
}
