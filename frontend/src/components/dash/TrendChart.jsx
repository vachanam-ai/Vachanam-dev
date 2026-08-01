import { useEffect, useMemo, useRef, useState } from "react";

/* Bookings chart v6 (2026-07-29 — Vinay picked "C · minimal pills" + the
   222831/393E46/948979/DFD0B8 taupe palette). Fully-rounded pill columns
   lifted off the baseline, generous spacing, two faint gridlines, muted
   totals. Colours come from theme tokens (--book-*) so dark stays readable.
   GSAP grows the pills up; reduced motion = instant. */

const C = {
  seen: "var(--book-seen)",
  upcoming: "var(--book-up)",
  noShow: "var(--book-no)",
  cancelled: "var(--book-can)",
  grid: "var(--chart-grid)",
  rate: "var(--book-up)",
};

const W = 760, H = 250, PL = 30, PR = 14, PT = 22, PB = 30;
const IW = W - PL - PR, IH = H - PT - PB;
const LIFT = 6, SEG_GAP = 3;

/* Rounded-rect path with per-corner radius (tl,tr,br,bl). */
function rr(x, y, w, h, tl, tr, br, bl) {
  const m = Math.min(w, h) / 2;
  tl = Math.min(tl, m); tr = Math.min(tr, m); br = Math.min(br, m); bl = Math.min(bl, m);
  return `M${x + tl},${y} H${x + w - tr} Q${x + w},${y} ${x + w},${y + tr} `
    + `V${y + h - br} Q${x + w},${y + h} ${x + w - br},${y + h} H${x + bl} `
    + `Q${x},${y + h} ${x},${y + h - bl} V${y + tl} Q${x},${y} ${x + tl},${y} Z`;
}

export default function TrendChart({ daily, calls }) {
  const svgRef = useRef(null);
  const [hover, setHover] = useState(null);

  const n = daily.length;
  const slot = IW / Math.max(n, 1);
  const bw = Math.max(9, Math.min(slot * 0.42, 40));
  const cx = (i) => PL + i * slot + slot / 2;
  const R = bw / 2; // pill radius

  const model = useMemo(() => {
    const rawMax = Math.max(1, ...daily.map((d) => d.booked + d.cancelled));
    const step = Math.max(1, Math.ceil(rawMax / 4));
    const axisMax = step * 4;
    const ticks = [0, step * 2, step * 4]; // just three: 0, mid, top
    const yh = (v) => (v / axisMax) * IH;

    const bars = daily.map((d, i) => {
      const upcoming = Math.max(d.booked - d.attended - d.no_show, 0);
      const stack = [
        ["seen", d.attended, C.seen],
        ["upcoming", upcoming, C.upcoming],
        ["noShow", d.no_show, C.noShow],
        ["cancelled", d.cancelled, C.cancelled],
      ].filter(([, v]) => v > 0);
      const segs = [];
      let y = H - PB - LIFT;
      stack.forEach(([key, v, fill], si) => {
        const isTop = si === stack.length - 1, isBottom = si === 0;
        const h = yh(v);
        y -= h;
        segs.push({ key, y, h, fill, isTop, isBottom });
      });
      return { segs, total: d.booked + d.cancelled, top: y, x: cx(i) - bw / 2 };
    });

    return { bars, ticks, axisMax };
  }, [daily, bw]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    let mm;
    import("gsap").then(({ gsap }) => {
      mm = gsap.matchMedia();
      const grids = svg.querySelectorAll("[data-grid]");
      const bars = svg.querySelectorAll("[data-bar]");
      const labels = svg.querySelectorAll("[data-blabel]");

      mm.add("(prefers-reduced-motion: no-preference)", () => {
        const tl = gsap.timeline({ defaults: { ease: "power3.out" } });
        tl.fromTo(grids, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.25, stagger: 0.04 });
        tl.fromTo(bars, { scaleY: 0, transformOrigin: "center bottom" },
          { scaleY: 1, duration: 0.6, ease: "power3.out", stagger: 0.07 }, 0.1);
        tl.fromTo(labels, { y: 6, autoAlpha: 0 },
          { y: 0, autoAlpha: 1, duration: 0.3, stagger: 0.07 }, 0.45);
      });
      mm.add("(prefers-reduced-motion: reduce)", () => {
        gsap.set([grids, bars, labels], { clearProps: "all", autoAlpha: 1 });
      });
    });
    return () => mm?.revert();
  }, [model]);

  const onMove = (e) => {
    const rect = svgRef.current.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * W;
    const i = Math.round((px - PL - slot / 2) / slot);
    setHover(i >= 0 && i < n ? i : null);
  };

  const hd = hover != null ? daily[hover] : null;
  const hc = hover != null ? (calls ?? [])[hover] : null;

  return (
    <div className="relative">
      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} className="w-full"
        role="img" aria-label="Daily bookings by outcome"
        onMouseMove={onMove} onMouseLeave={() => setHover(null)}>

        {/* two faint gridlines + baseline */}
        {model.ticks.map((t, k) => {
          const y = H - PB - (t / model.axisMax) * IH;
          const base = t === 0;
          return (
            <g key={k} data-grid>
              <line x1={PL} x2={W - PR} y1={y} y2={y} stroke={C.grid}
                strokeWidth={base ? 1.4 : 1} strokeDasharray={base ? "0" : "2 6"}
                opacity={base ? 1 : 0.6} />
              <text x={PL - 8} y={y + 3} textAnchor="end" fontSize="10"
                fontFamily="General Sans, ui-sans-serif" fill="rgb(var(--slate))"
                opacity="0.8" style={{ fontVariantNumeric: "tabular-nums" }}>{t}</text>
            </g>
          );
        })}

        {/* soft hover column highlight */}
        {hover != null && (
          <rect x={cx(hover) - bw / 2 - 12} y={PT - 6} width={bw + 24} height={IH + 12}
            rx="14" fill="rgb(var(--pill))" opacity="0.6" />
        )}

        {/* pill columns + totals */}
        {model.bars.map((b, i) => (
          <g key={daily[i].date} opacity={hover == null || hover === i ? 1 : 0.35}
            style={{ transition: "opacity 0.15s" }}>
            {b.segs.map((s) => {
              const h = Math.max(s.h - (s.isTop ? 0 : SEG_GAP), 1.5);
              const tl = s.isTop ? R : 0, tr = s.isTop ? R : 0;
              const br = s.isBottom ? R : 0, bl = s.isBottom ? R : 0;
              return (
                <path key={s.key} data-bar d={rr(b.x, s.y, bw, h, tl, tr, br, bl)}
                  style={{ fill: s.fill }} />
              );
            })}
            {b.total > 0 && (
              <text data-blabel x={b.x + bw / 2} y={b.top - 9} textAnchor="middle"
                fontSize="11" fontWeight="600" fontFamily="General Sans, ui-sans-serif"
                fill="rgb(var(--slate))" style={{ fontVariantNumeric: "tabular-nums" }}>
                {b.total}
              </text>
            )}
          </g>
        ))}

        {/* x labels */}
        {daily.map((d, i) =>
          i % Math.ceil(n / 7) === 0 ? (
            <text key={d.date} x={cx(i)} y={H - 8} textAnchor="middle" fontSize="10.5"
              fontFamily="General Sans, ui-sans-serif"
              fill={hover === i ? "rgb(var(--ink))" : "rgb(var(--slate))"}
              fontWeight={hover === i ? 600 : 400}>{d.date.slice(5)}</text>
          ) : null
        )}
      </svg>

      {/* tooltip */}
      {hd && (
        <div className="pointer-events-none absolute z-10 w-44 rounded-xl border border-hairline bg-surface/95 px-3 py-2 shadow-lift backdrop-blur transition-all duration-150"
          style={{ left: `${Math.min(Math.max((cx(hover) / W) * 100, 12), 82)}%`, top: 0, transform: "translate(-50%, -6px)" }}>
          <p className="font-ui text-[11px] font-semibold text-ink">
            {new Date(hd.date + "T00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" })}
          </p>
          <div className="mt-1 space-y-0.5 font-ui text-[11px] text-slate">
            <p><span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: C.seen }} /> Seen <b className="numeral float-right">{hd.attended}</b></p>
            <p><span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: C.upcoming }} /> Upcoming <b className="numeral float-right">{Math.max(hd.booked - hd.attended - hd.no_show, 0)}</b></p>
            <p><span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: C.noShow }} /> No-show <b className="numeral float-right">{hd.no_show}</b></p>
            <p><span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: C.cancelled }} /> Cancelled <b className="numeral float-right">{hd.cancelled}</b></p>
            {hc != null && <p><span className="mr-1 inline-block h-2 w-2 rounded-full bg-slate" /> Calls <b className="numeral float-right">{hc.calls}</b></p>}
            {hd.show_rate !== null && (
              <p><span className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: C.rate }} /> Show rate <b className="numeral float-right">{Math.round(hd.show_rate * 100)}%</b></p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function ChartLegend() {
  const items = [
    [C.seen, "Seen"],
    [C.upcoming, "Upcoming"],
    [C.noShow, "No-show"],
    [C.cancelled, "Cancelled"],
  ];
  return (
    <div className="flex flex-wrap gap-4">
      {items.map(([c, l]) => (
        <span key={l} className="flex items-center gap-1.5 font-ui text-xs text-slate">
          <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: c }} /> {l}
        </span>
      ))}
    </div>
  );
}
