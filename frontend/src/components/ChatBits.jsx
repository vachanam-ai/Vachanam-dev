import { useEffect, useState } from "react";

/** Three jiggling dots — "assistant is typing". */
export function TypingDots() {
  return (
    <div className="text-left">
      <span className="inline-flex items-center gap-1 rounded-2xl bg-teal-mint px-3 py-3">
        {[0, 150, 300].map((d) => (
          <span
            key={d}
            className="h-1.5 w-1.5 animate-bounce rounded-full bg-ink/50 motion-reduce:animate-none"
            style={{ animationDelay: `${d}ms` }}
          />
        ))}
      </span>
    </div>
  );
}

/** Streams the answer in character-by-character (client-side; the API returns
 *  one JSON blob — ticket status needs the full answer, so real SSE buys
 *  nothing on 1-4 sentence replies). */
export function TypedText({ text, done, onTick, onDone }) {
  const [n, setN] = useState(done ? text.length : 0);
  useEffect(() => {
    if (done) return undefined;
    if (n >= text.length) { onDone(); return undefined; }
    const t = setTimeout(() => { setN((v) => v + 2); onTick(); }, 18);
    return () => clearTimeout(t);
  }, [n, done, text, onTick, onDone]);
  return done ? text : text.slice(0, n);
}

/** Human-readable error for a failed /support/chat call. */
export function chatErrorMessage(err) {
  const code = err?.response?.status;
  if (code === 403) return "Please complete the verification check below, then send again.";
  if (code === 429) return "You're sending messages very quickly — please wait a minute and try again.";
  if (code >= 500) return "We're updating the service right now — please try again in a minute.";
  // No HTTP status at all: network drop, or the request timed out client-side.
  if (!code) return "Couldn't reach us — check your connection and try once more.";
  return "Something went wrong — email hello@vachanam.in and we'll help.";
}
