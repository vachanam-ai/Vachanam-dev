import { Fragment, useEffect, useRef } from "react";

/* Peak-hours heatmap (2026-07-11): weekday × hour grid of answered calls in
   branch-local time. Teal intensity = volume; cells stagger-fade in. */

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const HOURS = Array.from({ length: 14 }, (_, i) => i + 8); // 8:00–21:00

export default function Heatmap({ cells }) {
  const gridRef = useRef(null);
  const byKey = new Map((cells ?? []).map((c) => [`${c.weekday}-${c.hour}`, c.calls]));
  const max = Math.max(1, ...(cells ?? []).map((c) => c.calls));
  const peak = (cells ?? []).reduce((a, b) => (b.calls > (a?.calls ?? 0) ? b : a), null);

  useEffect(() => {
    if (!gridRef.current) return;
    let mm;
    import("gsap").then(({ gsap }) => {
      mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        gsap.fromTo(
          gridRef.current.querySelectorAll("[data-cell]"),
          { autoAlpha: 0, scale: 0.6 },
          { autoAlpha: 1, scale: 1, duration: 0.3, ease: "power2.out",
            stagger: { each: 0.006, from: "start" } }
        );
      });
    });
    return () => mm?.revert();
  }, [cells]);

  if (!(cells ?? []).some((c) => c.calls > 0)) {
    return <p className="font-ui text-sm text-slate">No calls in this period yet — the heatmap lights up as your phone rings.</p>;
  }

  return (
    <div>
      <div ref={gridRef} className="overflow-x-auto">
        <div className="grid min-w-[520px] gap-[3px]"
          style={{ gridTemplateColumns: `2.4rem repeat(${HOURS.length}, minmax(0,1fr))` }}>
          <span />
          {HOURS.map((h) => (
            <span key={h} className="text-center font-ui text-[9px] text-slate">
              {h > 12 ? h - 12 : h}{h >= 12 ? "p" : "a"}
            </span>
          ))}
          {DAYS.map((d, di) => (
            <Fragment key={d}>
              <span className="self-center font-ui text-[10px] text-slate">{d}</span>
              {HOURS.map((h) => {
                const v = byKey.get(`${di}-${h}`) ?? 0;
                const isPeak = peak && peak.weekday === di && peak.hour === h && v > 0;
                return (
                  <div key={`${di}-${h}`} data-cell
                    className={`aspect-square rounded-[4px] ${isPeak ? "ring-2 ring-gold" : ""}`}
                    style={{ background: v ? `rgba(15, 118, 110, ${0.15 + 0.85 * (v / max)})` : "var(--cell-empty)" }}
                    title={`${d} ${h}:00–${h + 1}:00 · ${v} call${v === 1 ? "" : "s"}`} />
                );
              })}
            </Fragment>
          ))}
        </div>
      </div>
      {peak && peak.calls > 0 && (
        <p className="mt-3 font-ui text-xs text-slate">
          Your phone is busiest <b className="text-teal-deep">{DAYS[peak.weekday]} {peak.hour}:00–{peak.hour + 1}:00</b> ({peak.calls} calls)
        </p>
      )}
    </div>
  );
}
