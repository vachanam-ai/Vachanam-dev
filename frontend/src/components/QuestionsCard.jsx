import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { answerQuestion, fetchQuestions } from "../api/client.js";
import { revealNow } from "../lib/motion.js";

/* Questions the AI could not answer (2026-08-02). The doctor opens one, types
   the answer and decides whether it joins the FAQ; either way Vachanam calls
   the patient back and reads the answer out. Hidden when there are none. */
const QUESTION_STATE = {
  answered: "Callback queued",
  called: "Answer read out on a callback",
  unreachable: "No number on record — answer them at the clinic",
};

function QuestionRow({ branchId, q }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(q.answer || "");
  const [toFaq, setToFaq] = useState(true);
  const save = useMutation({
    mutationFn: () => answerQuestion(branchId, q.id, text, toFaq),
    onSuccess: () => {
      setOpen(false);
      qc.invalidateQueries({ queryKey: ["questions", branchId] });
      qc.invalidateQueries({ queryKey: ["branch-faq", branchId] });
    },
  });
  const answered = Boolean(q.answer);
  return (
    <li className={`px-5 py-3 ${answered ? "opacity-70" : ""}`}>
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
          {answered && (
            <p className="mt-1 font-ui text-xs text-slate">
              <span className="text-ink">Answer:</span> {q.answer}
              {q.added_to_faq && <span className="chip ml-2">in FAQ</span>}
              <span className="ml-2">{QUESTION_STATE[q.status] || ""}</span>
            </p>
          )}
        </div>
        <button className="btn-ghost shrink-0 text-xs" onClick={() => setOpen((o) => !o)}>
          {open ? "Close" : answered ? "Edit" : "Answer"}
        </button>
      </div>
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
