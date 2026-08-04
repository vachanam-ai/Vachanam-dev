import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { answerQuestion, dismissQuestion, fetchQuestions } from "../api/client.js";
import { revealNow } from "../lib/motion.js";

/* Questions the AI could not answer (2026-08-02). The doctor opens one, types
   the answer and decides whether it joins the FAQ; either way Vachanam calls
   the patient back and reads the answer out. Hidden when there are none.

   Vinay 2026-08-03: the list is unanswered-only — once saved, the question
   leaves this card (into the FAQ if ticked, otherwise simply handled). */
function QuestionRow({ branchId, q }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [toFaq, setToFaq] = useState(true);
  const [confirmDrop, setConfirmDrop] = useState(false);
  const save = useMutation({
    mutationFn: () => answerQuestion(branchId, q.id, text, toFaq),
    onSuccess: () => {
      setOpen(false);
      qc.invalidateQueries({ queryKey: ["questions", branchId] });
      qc.invalidateQueries({ queryKey: ["branch-faq", branchId] });
    },
  });
  // Vinay 2026-08-04: sarcastic and duplicate questions land here too, and
  // answering was the only way off the desk — which then PHONES the caller.
  const drop = useMutation({
    mutationFn: () => dismissQuestion(branchId, q.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["questions", branchId] });
      qc.invalidateQueries({ queryKey: ["branch-faq", branchId] });
    },
  });
  return (
    <li className="px-5 py-3">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="font-ui text-sm text-ink">{q.question}</p>
          <p className="mt-1 font-ui text-xs text-slate">
            {q.patient_name || "Unknown caller"}
            {q.caller_phone
              ? ` · ${q.caller_phone}`
              : q.caller_last4
                ? ` · …${q.caller_last4}`
                : ""}
            {q.created_at ? ` · ${new Date(q.created_at).toLocaleString()}` : ""}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {confirmDrop ? (
            <>
              <button
                className="btn-ghost text-xs text-danger"
                disabled={drop.isPending}
                onClick={() => drop.mutate()}
              >
                {drop.isPending ? "Ignoring…" : "Yes, ignore"}
              </button>
              <button className="btn-ghost text-xs" onClick={() => setConfirmDrop(false)}>
                Keep
              </button>
            </>
          ) : (
            <button
              className="btn-ghost text-xs text-slate"
              title="Drop this question — the patient is not contacted"
              onClick={() => setConfirmDrop(true)}
            >
              Ignore
            </button>
          )}
          <button className="btn-ghost text-xs" onClick={() => setOpen((o) => !o)}>
            {open ? "Close" : "Answer"}
          </button>
        </div>
      </div>
      {drop.isError && (
        <p className="mt-1 font-ui text-xs text-danger">
          {drop.error?.response?.data?.detail || "Could not ignore this one"}
        </p>
      )}
      {open && (
        <div className="mt-3 space-y-2">
          <textarea
            className="field w-full py-2 text-sm"
            rows={3}
            maxLength={1000}
            placeholder="The doctor's answer — this is read out to the patient on a callback."
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <label className="flex cursor-pointer items-center gap-2 font-ui text-xs text-ink-soft">
            <input
              type="checkbox"
              className="h-4 w-4 accent-teal"
              checked={toFaq}
              onChange={(e) => setToFaq(e.target.checked)}
            />
            Also add this question and answer to the clinic FAQ
          </label>
          <div className="flex items-center gap-2">
            <button
              className="btn-primary px-3 py-1.5 text-xs"
              disabled={!text.trim() || save.isPending}
              onClick={() => save.mutate()}
            >
              {save.isPending ? "Saving…" : "Save & call back"}
            </button>
            {save.isError && (
              <span className="font-ui text-xs text-danger">
                {save.error?.response?.data?.detail || "Could not save"}
              </span>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

export default function QuestionsCard({ branchId }) {
  const { data } = useQuery({
    queryKey: ["questions", branchId],
    queryFn: () => fetchQuestions(branchId),
    enabled: Boolean(branchId),
    refetchInterval: 60_000,
  });
  const questions = data?.questions ?? [];
  const ref = useRef(null);
  useEffect(() => {
    if (questions.length) revealNow(ref.current);
  });
  if (!questions.length) return null;
  return (
    <section ref={ref} data-reveal className="card overflow-hidden">
      <header className="flex items-center gap-3 border-b border-hairline bg-pill px-5 py-3">
        <h2 className="font-display text-lg font-semibold">Questions for the doctor</h2>
        {data.pending > 0 && (
          <span className="chip bg-gold-soft text-gold-ink">{data.pending} unanswered</span>
        )}
      </header>
      <ul className="divide-y divide-hairline">
        {questions.map((q) => (
          <QuestionRow key={q.id} branchId={branchId} q={q} />
        ))}
      </ul>
    </section>
  );
}
