import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CaretDown, ChatCenteredText, PhoneCall, Trash, UserCircle } from "@phosphor-icons/react";
import { answerQuestion, dismissQuestion, fetchQuestions } from "../api/client.js";
import { revealNow } from "../lib/motion.js";

function QuestionRow({ branchId, question }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [answer, setAnswer] = useState("");
  const [toFaq, setToFaq] = useState(true);
  const [confirmDrop, setConfirmDrop] = useState(false);
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["questions", branchId] });
    queryClient.invalidateQueries({ queryKey: ["branch-faq", branchId] });
  };
  const save = useMutation({ mutationFn: () => answerQuestion(branchId, question.id, answer, toFaq), onSuccess: () => { setOpen(false); refresh(); } });
  const drop = useMutation({ mutationFn: () => dismissQuestion(branchId, question.id), onSuccess: refresh });
  const caller = question.patient_name || "Unknown caller";
  const phone = question.caller_phone || (question.caller_last4 ? `•••• ${question.caller_last4}` : "Number unavailable");

  return (
    <li className={`doctor-question ${open ? "is-open" : ""}`}>
      <button type="button" className="doctor-question-summary" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        <span className="doctor-question-avatar"><UserCircle size={22} weight="duotone" /></span>
        <span className="doctor-question-copy"><strong>{question.question}</strong><small>{caller} · {phone}{question.created_at ? ` · ${new Date(question.created_at).toLocaleString()}` : ""}</small></span>
        <CaretDown size={17} weight="bold" aria-hidden />
      </button>
      {open && (
        <div className="doctor-question-answer">
          <label><span>Doctor or receptionist answer</span><textarea className="field" rows={3} maxLength={1000} placeholder="This answer will be read to the patient during the callback." value={answer} onChange={(event) => setAnswer(event.target.value)} /></label>
          <label className="doctor-question-faq"><input type="checkbox" checked={toFaq} onChange={(event) => setToFaq(event.target.checked)} /><span><strong>Add to clinic FAQ</strong><small>The agent can use this approved answer next time.</small></span></label>
          <div className="doctor-question-actions">
            <button type="button" className="btn-primary" disabled={!answer.trim() || save.isPending} onClick={() => save.mutate()}><PhoneCall size={17} weight="duotone" />{save.isPending ? "Saving…" : "Save and call back"}</button>
            {confirmDrop ? <><button type="button" className="btn-danger" disabled={drop.isPending} onClick={() => drop.mutate()}><Trash size={16} />{drop.isPending ? "Ignoring…" : "Confirm ignore"}</button><button type="button" className="btn-ghost" onClick={() => setConfirmDrop(false)}>Keep question</button></> : <button type="button" className="btn-ghost" onClick={() => setConfirmDrop(true)}><Trash size={16} />Ignore</button>}
          </div>
          {(save.isError || drop.isError) && <p className="doctor-question-error">{save.error?.response?.data?.detail || drop.error?.response?.data?.detail || "This action could not be completed."}</p>}
        </div>
      )}
    </li>
  );
}

export default function QuestionsCard({ branchId }) {
  const { data } = useQuery({ queryKey: ["questions", branchId], queryFn: () => fetchQuestions(branchId), enabled: Boolean(branchId), refetchInterval: 60_000 });
  const questions = data?.questions ?? [];
  const ref = useRef(null);
  useEffect(() => { if (questions.length) revealNow(ref.current); });
  if (!questions.length) return null;
  return (
    <section ref={ref} data-reveal className="doctor-questions-card">
      <header><span className="doctor-questions-icon"><ChatCenteredText size={24} weight="duotone" /></span><div><h2>Questions for the doctor</h2><p>Review what the receptionist could not safely answer.</p></div>{data.pending > 0 && <span className="doctor-questions-count">{data.pending} awaiting answer</span>}</header>
      <ul>{questions.map((question) => <QuestionRow key={question.id} branchId={branchId} question={question} />)}</ul>
    </section>
  );
}
