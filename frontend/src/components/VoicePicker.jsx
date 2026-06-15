import { useEffect, useRef, useState } from "react";

// Landing-page showcase: the SAME AI agent greeting, spoken in each supported
// language. Samples are real smallest.ai audio (the clinic's default voice per
// language), generated into /public/voices/lang/<code>.wav.
export const LANGUAGES = [
  { code: "te", native: "తెలుగు", english: "Telugu" },
  { code: "hi", native: "हिन्दी", english: "Hindi" },
  { code: "ta", native: "தமிழ்", english: "Tamil" },
  { code: "kn", native: "ಕನ್ನಡ", english: "Kannada" },
  { code: "ml", native: "മലയാളം", english: "Malayalam" },
  { code: "mr", native: "मराठी", english: "Marathi" },
  { code: "bn", native: "বাংলা", english: "Bengali" },
  { code: "or", native: "ଓଡ଼ିଆ", english: "Odia" }
];

/** Language sample cards. Click play to hear the agent greet in that language. */
export default function VoicePicker() {
  const [playing, setPlaying] = useState(null);
  const audioRef = useRef(null);

  useEffect(() => () => audioRef.current?.pause(), []);

  const play = (code) => {
    audioRef.current?.pause();
    if (playing === code) {
      setPlaying(null);
      return;
    }
    const a = new Audio(`/voices/lang/${code}.wav`);
    audioRef.current = a;
    setPlaying(code);
    a.onended = () => setPlaying(null);
    a.play().catch(() => setPlaying(null));
  };

  return (
    <div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {LANGUAGES.map((l) => {
          const isPlaying = playing === l.code;
          return (
            <button
              key={l.code}
              type="button"
              onClick={() => play(l.code)}
              aria-label={`Play ${l.english} sample`}
              className={`flex items-center justify-between rounded-2xl border p-4 text-left transition ${
                isPlaying
                  ? "border-teal bg-teal-mint shadow-lift"
                  : "border-hairline bg-white/85 shadow-card hover:border-teal-light/60"
              }`}
            >
              <div className="min-w-0">
                <p className="truncate font-display text-lg font-semibold">{l.native}</p>
                <p className="font-ui text-xs text-slate">{l.english}</p>
              </div>
              <span
                className={`ml-3 grid h-11 w-11 shrink-0 place-items-center rounded-full border transition ${
                  isPlaying
                    ? "border-gold bg-gold-soft text-gold-ink"
                    : "border-hairline bg-white text-teal"
                }`}
              >
                {isPlaying ? (
                  <span className="flex items-end gap-0.5" aria-hidden>
                    {[3, 5, 4].map((h, i) => (
                      <span
                        key={i}
                        className="w-1 animate-pulse rounded-sm bg-gold-ink"
                        style={{ height: `${h * 3}px`, animationDelay: `${i * 120}ms` }}
                      />
                    ))}
                  </span>
                ) : (
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor" aria-hidden>
                    <path d="M3 1.5v11l9-5.5z" />
                  </svg>
                )}
              </span>
            </button>
          );
        })}
      </div>
      <p className="mt-4 font-ui text-sm italic text-slate">
        One AI agent — the same warm greeting, in your patients’ language.
      </p>
    </div>
  );
}
