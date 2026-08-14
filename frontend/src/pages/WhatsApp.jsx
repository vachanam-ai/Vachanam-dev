import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import PageHeader from "../components/PageHeader.jsx";
import TemplateEditor from "../components/TemplateEditor.jsx";
import WaConnectCard from "../components/WaConnectCard.jsx";
import {
  createWaTemplate,
  deleteWaTemplate,
  fetchBranchSettings,
  fetchWaTemplates,
  installWaSystemTemplates,
} from "../api/client.js";
import { useAuth } from "../hooks/useAuth.jsx";
import { useConfirm } from "../components/ConfirmDialog.jsx";

// WA MVP1 Task 10 — option C (chosen over a card grid, which doesn't scale
// past ~15 templates, and a bare table, which reads like an admin console
// and gives no sense of what the patient actually receives): a template list
// on the left, a live phone preview on the right.
const SYSTEM_TEMPLATES = new Set([
  "booking_confirm", "appt_reminder", "rating_ask", "leave_rebook",
  "vachanam_booking_confirm", "vachanam_booking_reschedule",
  "vachanam_booking_cancel", "vachanam_appt_reminder",
  "vachanam_clinic_location", "vachanam_feedback",
  "vachanam_rating_ask", "vachanam_leave_rebook",
]);

const STATUS_CHIP = {
  APPROVED: "chip-token",
  REJECTED: "chip-danger",
  PENDING: "chip-muted",
  PENDING_DELETION: "chip-muted",
};

function StatusChip({ status }) {
  const cls = STATUS_CHIP[status] ?? "chip-muted";
  return <span className={cls}>{(status || "pending").toLowerCase()}</span>;
}

function TemplateRow({ branchId, t, onDeleted }) {
  const confirm = useConfirm();
  const qc = useQueryClient();
  const isSystem = SYSTEM_TEMPLATES.has(t.name);
  const remove = useMutation({
    mutationFn: () => deleteWaTemplate(branchId, t.name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["wa-templates", branchId] });
      toast.success("Template deleted");
      onDeleted?.();
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not delete this template"),
  });
  return (
    <div data-testid={`template-row-${t.name}`}
      className="flex items-center justify-between gap-3 px-5 py-3.5">
      <div className="min-w-0">
        <p className="truncate font-ui text-sm font-semibold text-ink">{t.name}</p>
        <p className="font-ui text-xs text-slate">
          {(t.category || "UTILITY").toLowerCase()} · {t.language || "en"}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <StatusChip status={t.status} />
        {isSystem ? (
          <span className="font-ui text-xs text-slate"
            title="Used for booking confirmations, reminders and rating asks — cannot be deleted">
            system
          </span>
        ) : (
          <button type="button"
            className="font-ui text-xs font-medium text-danger underline-offset-2 hover:underline"
            disabled={remove.isPending}
            onClick={async () => {
              if (await confirm({
                title: `Delete template “${t.name}”?`,
                body: "This cannot be undone. Messages already sent are unaffected.",
                confirmLabel: "Delete template",
                destructive: true,
              })) remove.mutate();
            }}>
            {remove.isPending ? "Deleting…" : "Delete"}
          </button>
        )}
      </div>
    </div>
  );
}

export default function WhatsApp() {
  const { branchId } = useAuth();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  // ?new=1 is how the top-bar "New template" action opens the editor — the URL
  // carries the intent, so the chrome and this page share no state. Stripped on
  // close/submit so a refresh doesn't reopen an editor the owner dismissed.
  const creating = params.get("new") === "1";
  const setCreating = (open) =>
    setParams(open ? { new: "1" } : {}, { replace: true });

  const { data: branch } = useQuery({
    queryKey: ["branch-settings", branchId],
    queryFn: () => fetchBranchSettings(branchId),
    enabled: Boolean(branchId),
  });

  const { data: templates = [], isLoading, error } = useQuery({
    queryKey: ["wa-templates", branchId],
    queryFn: () => fetchWaTemplates(branchId),
    enabled: Boolean(branchId),
  });

  const create = useMutation({
    mutationFn: (payload) => createWaTemplate(branchId, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["wa-templates", branchId] });
      toast.success("Template submitted — Meta review usually takes minutes to a day.");
      setCreating(false);
    },
    onError: (e) => toast.error(e?.response?.data?.detail ?? "Could not submit this template"),
  });

  const installSystem = useMutation({
    mutationFn: () => installWaSystemTemplates(branchId),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["wa-templates", branchId] });
      const failed = result?.errors?.length ?? 0;
      if (failed) {
        toast.error(
          failed + " required template" + (failed === 1 ? "" : "s") + " need retry.",
        );
      } else if (result?.created?.length) {
        toast.success("Required patient templates submitted to Meta for review.");
      } else {
        toast.success("All required patient templates are already installed.");
      }
    },
    onError: (e) => toast.error(
      e?.response?.data?.detail ?? "Could not install required templates",
    ),
  });

  const notConnected = branch && branch.whatsapp_status !== "connected";

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="WhatsApp" title="Message templates"
        sub="Meta reviews every template before it can be sent to patients — usually minutes to a day.">
        <div className="flex flex-wrap gap-2">
          {!notConnected && (
            <button type="button" className="btn-secondary"
              disabled={installSystem.isPending}
              onClick={() => installSystem.mutate()}>
              {installSystem.isPending ? "Installing..." : "Install required templates"}
            </button>
          )}
          <button type="button" className="btn-primary" onClick={() => setCreating(!creating)}>
            {creating ? "Cancel" : "+ New template"}
          </button>
        </div>
      </PageHeader>

      {/* Connection first: a template the clinic can't submit is a dead end,
          so the one action that unblocks everything leads the page. */}
      <div className="card p-5">
        <h2 className="mb-3 font-ui text-sm font-semibold text-ink">
          Your WhatsApp number
        </h2>
        <WaConnectCard branchId={branchId} />
      </div>

      {notConnected && (
        <div className="rounded-xl border border-teal-pale bg-pill p-4 font-ui text-sm text-ink-soft">
          Templates created here can't be submitted to Meta until your WhatsApp
          Business Account is connected above. You can still draft and preview
          them below.
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        {/* Left — the list */}
        <div className="card divide-y divide-hairline overflow-hidden">
          {isLoading && <p className="p-5 font-ui text-sm text-slate">Loading templates…</p>}
          {error && (
            <p className="p-5 font-ui text-sm text-danger">
              {error?.response?.data?.detail ?? "Could not load templates."}
            </p>
          )}
          {!isLoading && !error && templates.length === 0 && (
            <p className="p-5 font-ui text-sm text-slate">
              No templates yet — the required patient templates appear here once your
              WhatsApp account is connected.
            </p>
          )}
          {templates.map((t) => (
            <TemplateRow key={t.name} branchId={branchId} t={t} />
          ))}
        </div>

        {/* Right — create + live preview (the whole point: legible placeholders) */}
        <div className="card p-5">
          {creating ? (
            <TemplateEditor branch={branch} submitting={create.isPending}
              onSubmit={(payload) => create.mutate(payload)} />
          ) : (
            <p className="font-ui text-sm text-slate">
              Press <strong className="text-ink">+ New template</strong> to write your own —
              you'll see exactly what the patient receives as you type, with your
              own clinic's details standing in for {"{{1}}"}, {"{{2}}"}…
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
