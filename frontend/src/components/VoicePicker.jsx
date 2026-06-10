import { useEffect, useRef, useState } from "react";

export const VOICES = [
  { id: "rupali", label: "Rupali", note: "warm · default" },
  { id: "simran", label: "Simran", note: "bright" },
  { id: "kavya", label: "Kavya", note: "soft" },
  { id: "ishita", label: "Ishita", note: "crisp" },
  { id: "shreya", label: "Shreya", note: "friendly" },
  { id: "suhani", label: "Suhani", note: "calm" }
];

export const SAMPLE_TRANSCRIPT =
  "నమస్కారం! వచనం క్లినిక్‌కి స్వాగతం. మీ అపాయింట్‌మెంట్ బుక్ చేయడానికి నేను సహాయం చేస్తాను. మీ పేరు చెప్పగలరా?";

/** Audio sample cards. selectable=false → listen-only (landing page). */
export default function VoicePicker({ value, onSelect, selectable = true }) {
  const [playing, setPlaying] = useState(null);
  const audioRef = useRef(null);

  useEffect(() => () => audioRef.current?.pause(), []);

  const play = (id) => {
    audioRef.current?.pause();
    if (playing === id) {
      setPlaying(null);
      return;
    }
    const a = new Audio(`/voices/${id}.wav`);
    audioRef.current = a;
    setPlaying(id);
    a.onended = () => setPlaying(null);
    a.play().catch(() => setPlaying(null));
  };

  return (
    <div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {VOICES.map((v) => {
          const selected = value === v.id;
          return (
            <div
              key={v.id}
              className={`rounded-2xl border p-4 transition ${
                selected
                  ? "border-teal bg-teal-mint shadow-lift"
                  : "border-hairline bg-white/85 shadow-card hover:border-teal-light/60"
              }`}
            >
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-display text-lg font-semibold">{v.label}</p>
                  <p className="font-ui text-xs text-slate">{v.note}</p>
                </div>
                <button
                  type="button"
                  onClick={() => play(v.id)}
                  aria-label={`Play ${v.label} sample`}
                  className={`grid h-11 w-11 place-items-center rounded-full border transition ${
                    playing === v.id
                      ? "border-gold bg-gold-soft text-gold-ink"
                      : "border-hairline bg-white text-teal hover:bg-teal-mint"
                  }`}
                >
                  {playing === v.id ? (
                    <span className="flex items-end gap-0.5" aria-hidden>
                      {[3, 5, 4].map((h, i) => (
                        <span key={i} className="w-1 animate-pulse rounded-sm bg-gold-ink"
                          style={{ height: `${h * 3}px`, animationDelay: `${i * 120}ms` }} />
                      ))}
                    </span>
                  ) : (
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor" aria-hidden>
                      <path d="M3 1.5v11l9-5.5z" />
                    </svg>
                  )}
                </button>
              </div>
              {selectable && (
                <button
                  type="button"
                  onClick={() => onSelect?.(v.id)}
                  className={`mt-3 w-full rounded-lg py-2 font-ui text-sm font-medium transition ${
                    selected
                      ? "bg-teal text-white"
                      : "border border-hairline bg-white text-teal hover:bg-teal-mint"
                  }`}
                >
                  {selected ? "Selected" : "Choose this voice"}
                </button>
              )}
            </div>
          );
        })}
      </div>
      <p className="mt-4 font-ui text-sm italic text-slate">
        Sample: &ldquo;{SAMPLE_TRANSCRIPT}&rdquo;
      </p>
    </div>
  );
}
