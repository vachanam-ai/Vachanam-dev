import { useEffect, useRef, useState } from "react";
import { Pause, Play } from "@phosphor-icons/react";

export const LANGUAGES = [
  { code: "te", native: "తెలుగు", english: "Telugu" },
  { code: "hi", native: "हिन्दी", english: "Hindi" },
  { code: "ta", native: "தமிழ்", english: "Tamil" },
  { code: "kn", native: "ಕನ್ನಡ", english: "Kannada" },
  { code: "ml", native: "മലയാളം", english: "Malayalam" },
  { code: "mr", native: "मराठी", english: "Marathi" },
  { code: "bn", native: "বাংলা", english: "Bengali" },
];

export default function VoicePicker() {
  const [playing, setPlaying] = useState(null);
  const audioRef = useRef(null);
  useEffect(() => () => audioRef.current?.pause(), []);

  const play = (code) => {
    audioRef.current?.pause();
    if (playing === code) { setPlaying(null); return; }
    const audio = new Audio(`/voices/lang/${code}.wav`);
    audioRef.current = audio;
    setPlaying(code);
    audio.onended = () => setPlaying(null);
    audio.play().catch(() => setPlaying(null));
  };

  return (
    <div className="voice-picker">
      <div className="voice-picker-grid">
        {LANGUAGES.map((language) => {
          const active = playing === language.code;
          return (
            <button key={language.code} type="button" onClick={() => play(language.code)} aria-label={`${active ? "Pause" : "Play"} ${language.english} sample`} className={active ? "is-playing" : ""}>
              <span><strong lang={language.code}>{language.native}</strong><small>{language.english}</small></span>
              <span className="voice-play">{active ? <Pause size={16} weight="fill" /> : <Play size={16} weight="fill" />}</span>
              {active && <span className="voice-bars" aria-hidden>{[1,2,3,4,5].map((bar) => <i key={bar} />)}</span>}
            </button>
          );
        })}
      </div>
      <p>One reception workflow, spoken in the language your patient chooses.</p>
    </div>
  );
}
