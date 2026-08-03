import { useMemo, useState } from "react";

// WA MVP1 Task 10 — a clinic-authored WhatsApp template, built by referring
// AiSensy/Wati/Interakt (they converge on the same shape): a name, a
// category, a body with {{n}} placeholders, an example value per
// placeholder, and up to a few quick-reply buttons. The right-hand preview
// is the whole point — a clinic writing raw {{1}} markers gets rejected by
// Meta and blames us, so the body always renders with realistic sample data
// substituted in, live, as they type.
const PLACEHOLDER_RE = /\{\{(\d+)\}\}/g;
const NAME_RE = /^[a-z0-9_]+$/;
const CATEGORIES = ["UTILITY", "MARKETING"];
const MAX_BUTTONS = 3;

// Generic sample data for the preview — index 0 → {{1}}, etc. Index 3
// (clinic name) prefers the clinic's own name when known.
function samplesFor(branch) {
  return ["Ravi", "tomorrow 10:30 AM", "Dr Srinivas", branch?.name || "Venkateshwara Clinic", "12 August", "the clinic"];
}

function placeholderNumbers(body) {
  const seen = new Set();
  let m;
  const re = new RegExp(PLACEHOLDER_RE);
  // eslint-disable-next-line no-cond-assign
  while ((m = re.exec(body || ""))) seen.add(Number(m[1]));
  return [...seen].sort((a, b) => a - b);
}

function isSequential(numbers) {
  return numbers.length === 0 || numbers.every((n, i) => n === i + 1);
}

function renderPreview(body, examples, samples) {
  return (body || "").replace(/\{\{(\d+)\}\}/g, (_match, n) => {
    const i = Number(n) - 1;
    const typed = (examples[i] || "").trim();
    return typed || samples[i] || `value ${n}`;
  });
}

export default function TemplateEditor({ branch, onSubmit, submitting }) {
  const [name, setName] = useState("");
  const [category, setCategory] = useState("UTILITY");
  const [body, setBody] = useState("");
  const [examples, setExamples] = useState([]);
  const [buttons, setButtons] = useState([]);

  const numbers = useMemo(() => placeholderNumbers(body), [body]);
  const sequential = isSequential(numbers);
  const samples = samplesFor(branch);
  const preview = renderPreview(body, examples, samples);

  const setExample = (idx, value) =>
    setExamples((prev) => {
      const next = [...prev];
      next[idx] = value;
      return next;
    });

  const nameOk = name.trim().length > 0 && NAME_RE.test(name.trim());
  const hasAllExamples = numbers.every((n) => (examples[n - 1] || "").trim().length > 0);
  const canSubmit = nameOk && body.trim().length > 0 && sequential && hasAllExamples;

  const submit = () => {
    if (!canSubmit) return;
    onSubmit?.({
      name: name.trim(),
      category,
      body: body.trim(),
      examples: numbers.map((n) => (examples[n - 1] || "").trim()),
      buttons: buttons.filter((b) => b && b.trim()),
    });
  };

  return (
    <div className="space-y-4">
      <div>
        <label htmlFor="tpl-name" className="label">Template name</label>
        <input id="tpl-name" className="field" value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="diwali_offer" />
        <p className="mt-1 font-ui text-xs text-slate">
          Lowercase letters, numbers and underscores only — Meta rejects anything else.
        </p>
        {name.trim() && !nameOk && (
          <p className="mt-1 font-ui text-xs text-danger">
            Use lowercase letters, numbers and underscores only.
          </p>
        )}
      </div>

      <div>
        <label htmlFor="tpl-category" className="label">Category</label>
        <select id="tpl-category" className="field" value={category}
          onChange={(e) => setCategory(e.target.value)}>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c === "UTILITY" ? "Utility (recommended — cheaper, reviewed faster)" : "Marketing"}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor="tpl-body" className="label">Message body</label>
        <textarea id="tpl-body" className="field min-h-[100px]" value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder="Namaste! Your appointment at {{1}} is confirmed for {{2}}." />
        <p className="mt-1 font-ui text-xs text-slate">
          Use {"{{1}}"}, {"{{2}}"}… for the details Vachanam fills in per patient —
          must start at {"{{1}}"} with no gaps.
        </p>
        {!sequential && (
          <p className="mt-1 font-ui text-xs text-danger">
            Placeholders must run in order from {"{{1}}"} — e.g. {"{{1}}"}, {"{{2}}"},
            not {"{{1}}"}, {"{{3}}"}.
          </p>
        )}
      </div>

      {numbers.length > 0 && (
        <div className="space-y-2">
          <p className="label">Example values (shown to Meta's reviewer)</p>
          {numbers.map((n) => (
            <div key={n} className="flex items-center gap-2">
              <span className="numeral w-9 shrink-0 font-ui text-xs text-slate">{`{{${n}}}`}</span>
              <input className="field" value={examples[n - 1] || ""}
                onChange={(e) => setExample(n - 1, e.target.value)}
                placeholder={samples[n - 1] || `Example for {{${n}}}`} />
            </div>
          ))}
        </div>
      )}

      <div>
        <p className="label">Buttons (optional quick replies)</p>
        <div className="space-y-2">
          {buttons.map((b, i) => (
            <div key={i} className="flex items-center gap-2">
              <input className="field" value={b}
                onChange={(e) =>
                  setButtons((prev) => prev.map((x, j) => (j === i ? e.target.value : x)))}
                placeholder="Reschedule" />
              <button type="button" className="btn-ghost shrink-0 px-2 py-1 text-xs"
                onClick={() => setButtons((prev) => prev.filter((_, j) => j !== i))}>
                Remove
              </button>
            </div>
          ))}
          {buttons.length < MAX_BUTTONS && (
            <button type="button" className="btn-ghost text-xs"
              onClick={() => setButtons((prev) => [...prev, ""])}>
              + Add a button
            </button>
          )}
        </div>
      </div>

      {/* Live phone-shaped preview — makes {{n}} legible before Meta ever sees it. */}
      <div>
        <p className="label">Preview</p>
        <div className="mx-auto max-w-[300px] rounded-[28px] border border-line2 bg-pill p-3">
          <div data-testid="preview"
            className="whitespace-pre-wrap rounded-2xl bg-surface p-3 font-ui text-sm text-ink shadow-soft">
            {preview || <span className="text-slate">Type a message body to see the preview…</span>}
            {buttons.filter((b) => b.trim()).length > 0 && (
              <div className="mt-2 space-y-1 border-t border-hairline pt-2">
                {buttons.filter((b) => b.trim()).map((b, i) => (
                  <div key={i} className="rounded-lg border border-line2 py-1 text-center text-teal">
                    {b}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <button type="button" className="btn-primary w-full min-h-[56px]"
        disabled={!canSubmit || submitting}
        onClick={submit}>
        {submitting ? "Submitting…" : "Submit for review"}
      </button>
    </div>
  );
}
