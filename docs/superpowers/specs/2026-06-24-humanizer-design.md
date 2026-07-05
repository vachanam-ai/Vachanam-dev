# Humanizer — Design Spec

**Goal:** make the Vachanam voice agent's phone conversations indistinguishable
from a warm, competent human clinic receptionist (Telugu first), via a closed
research → author → score → fix → call loop that learns from Vinay's feedback
and from real conversations.

**Status of inputs (already done + approved):**
- Research + rules: [docs/research/receptionist-rules-te.md](../../research/receptionist-rules-te.md) (R1–R9, cited).
- Telugu method: **Gemini spoken-generation** — situation in, spoken line out,
  never translated, never authored by the assistant; reviewed by Vinay. Natural
  urban Tenglish (English loanwords in Telugu script, RULE 6).
- Training approach: **Level 1 only** — an in-context example/correction bank
  (few-shot + judge gold set). No Vertex fine-tuning now.

## Hard constraints (override everything)
- RULE 6 — all TTS text in Telugu script; English loanwords transliterated, never romanized.
- RULE 7 — agent books + relays; never advises/diagnoses/triages. Angry/anxious
  handling is empathy + a concrete next step, never medical reassurance.
- RULE 9 / RULE 1 (DPDP) — the example bank stores NO personal data. De-identified
  patterns + placeholders only. A de-id gate is a hard precondition to any write.

## Components

### C1 — Gemini spoken-line generator (`agent/i18n/te_gen.py`)
- `generate_lines(situations: dict[str,str], examples: list[dict]) -> dict[str,str]`
- Calls Gemini 2.5 Flash. Prompt = the spoken-generation instruction (generate,
  don't translate; Tenglish in Telugu script; placeholders; polite register; no
  medical advice) + few-shot `examples` from the bank (C3).
- Returns Telugu-script lines. Best-effort retry on 503 (Gemini high-demand).
- **Consumes** the bank's approved examples so generation conditions on Vinay's taste.

### C2 — Naturalness judge (`agent/eval/naturalness.py`)
- `score_naturalness(transcript: list[turn]) -> {scores, flags, suggestions}`.
- LLM-as-judge (reuse the existing call-scoring judge infra) scoring against
  R1–R9: warmth, greeting, honorifics/register (R2), active-listening restate
  (R3), turn-taking/backchannels/fillers (R4), prosody/short-lines (R5),
  appointment flow (R6), de-escalation correctness (R7), anti-patterns (R9),
  + **pronunciation flags** (any Latin/romanized token that TTS will spell), and
  an overall human-likeness 1–5 with concrete fixes.
- Output is structured (drives the auto-diff). NOT a substitute for Vinay's final
  judgement on real calls.

### C3 — Example/correction bank (`agent/eval/example_bank.py` + JSON store)
- Entry = `{situation_key, line (placeholders), score, source}`. NO PII, NO raw
  health text. Source ∈ {seed, vinay_correction, real_call}.
- `add_example(entry)` runs the **de-id gate** (C4) and REJECTS on any failure.
- Seeded from the approved rules-doc lines (Vinay-reviewed).
- `examples_for(situation_key) -> list` feeds C1 (few-shot) and C2 (gold).

### C4 — De-identification gate (`backend/services/deidentify.py`, reuse retention logic)
- `assert_deidentified(text)` raises if `text` contains a phone pattern, a likely
  personal name, an age, or other quasi-identifier; strips/placeholdersany that
  slip through. Hard precondition for every bank write. Tested with PII samples
  that MUST be rejected.

### C5 — humanizer subagent (`.claude/agents/humanizer.md`)
- Persona + mission: own the rules doc, drive C1→C2→diff, propose prompt/line
  edits, analyse transcripts. Read-mostly; proposes diffs; the main thread applies.

### C6 — Phase-A text-sim loop (`scripts/humanizer_sim.py`)
- Patient personas (one per R7/R8 situation) "talk" to the candidate prompt via
  Gemini (no telephony); C2 scores each; the humanizer emits a diff; repeat until
  scores plateau. Cheap, fast. All synthetic data (no real PII).

### Wiring + Phase B
- Apply the winning lines/prompt to [agent/i18n/lines.py](../../../agent/i18n/lines.py)
  + [agent/prompts/system_prompt.py](../../../agent/prompts/system_prompt.py).
- **Phase B (real call):** dispatch outbound to Vinay's number with the winning
  prompt (reuse outbound dispatch + testing-only recording override, consented).
  Vinay judges "could a human tell?"; transcript auto-scored; a de-identified
  pattern from a good turn → C3 (via C4). This is the Level-1 learning-from-real-
  conversations step.

## Data flow
rules-doc seed → C3 bank → C1 generates lines (few-shot from bank) → applied to
prompt → C6 sim → C2 judge → diff → repeat → Phase-B call → Vinay + C2 → de-id
good turns → C3. The bank is the loop's memory and the "training" (Level 1).

## DPDP compliance (RULE 1 / RULE 9)
- Bank = de-identified patterns only; C4 gate enforced + tested; stored locally;
  no new external PII exposure (Gemini only ever sees synthetic sim data or
  de-identified examples). Flag for privacy-legal review before Phase B goes live.

## Testing
- C1: returns Telugu-script lines; retries 503; injects bank examples (mock Gemini).
- C2: scores structure present; flags a romanized token; penalises an R7 medical-advice line.
- C3: add_example rejects a PII-bearing entry (via C4); accepts a clean one.
- C4: rejects phone/name/age samples; passes placeholder lines.
- C6: runs one persona end-to-end against a stub prompt, produces a score.

## Out of scope (now)
Vertex SFT / preference tuning (Level 2); non-Telugu languages; recording in
production (testing-only override stays env-gated).
