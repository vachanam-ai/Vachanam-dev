import { useEffect, useMemo, useRef, useState } from "react";

/* Bookings chart v5 (2026-07-29 — "best of the best" bar design).
   Following modern dashboard practice: wide rounded-TOP columns, generous
   spacing, light dashed gridlines with a solid 0-baseline, bold value labels,
   one semantic accent (green = Seen), and a soft hover-column highlight
   instead of a crosshair. GSAP grows the columns up; reduced motion = instant. */

const COLORS = {
  seen: "#2f9e5f",
  upcoming: "#9aa3a0",
  noShow: "#cf9330",
  cancelled: "var(--chart-cancelled)",
  grid: "var(--chart-grid)",
  rate: "#c98a2e",
};

const W = 760, H = 250, PL = 30, PR = 14, PT = 20, PB = 30;
const IW = W - PL - PR, IH = H - PT - PB;

/* Path for a column with rounded TOP corners and a flat base — the clean,
   modern bar shape (only the topmost stacked segment uses it). */
function topRoundedRect(x, y, w, h, r) {
  r = Math.max(0, Math.min(r, w / 2, h));
  return `M${x},${y + h} L${x},${y + r} Q${x},${y} ${x + r},${y} `
    + `L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + h} Z`;
}

export default function TrendChart({ daily, calls }) {
  const svgRef = useRef(null);
  const [hover, setHover] = useState(null);

  const n = daily.length;
  const slot = IW / Math.max(n, 1);
  const bw = Math.max(10, Math.min(slot * 0.58, 46));
  const cx = (i) => PL + i * slot + slot / 2;

  const model = useMemo(() => {
    const rawMax = Math.max(1, ...daily.map((d) => d.booked + d.cancelled));
    const step = Math.max(1, Math.ceil(rawMax / 4));
    const axisMax = step * 4;
    const ticks = [0, 1, 2, 3, 4].map((k) => k * step);
    const yh = (v) => (v / axisMax) * IH;
    const r = Math.min(bw * 0.42, 9);

    const bars = daily.map((d, i) => {
      const upcoming = Math.max(d.booked - d.attended - d.no_show, 0);
      const stack = [
        ["seen", d.attended, COLORS.seen],
        ["upcoming", upcoming, COLORS.upcoming],
        ["noShow", d.no_show, COLORS.noShow],
        ["cancelled", d.cancelled, COLORS.cancelled],
      ].filter(([, v]) => v > 0);
      const segs = [];
      let y = H - PB;
      stack.forEach(([key, v, fill], si) => {
        const h = yh(v);
        y -= h;
        segs.push({ key, y, h, fill, top: si === stack.length - 1, r });
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
        tl.fromTo(grids, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.25, stagger: 0.03 });
        tl.fromTo(bars, { scaleY: 0, transformOrigin: "center bottom" },
          { scaleY: 1, duration: 0.55, ease: "power3.out", stagger: 0.06 }, 0.1);
        tl.fromTo(labels, { y: 6, autoAlpha: 0 },
          { y: 0, autoAlpha: 1, duration: 0.3, stagger: 0.06 }, 0.4);
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

        {/* gridlines — dashed + light, solid emphasized 0-baseline */}
        {model.ticks.map((t, k) => {
          const y = H - PB - (t / model.axisMax) * IH;
          const base = t === 0;
          return (
            <g key={k} data-grid>
              <line x1={PL} x2={W - PR} y1={y} y2={y} stroke={COLORS.grid}
                strokeWidth={base ? 1.4 : 1} strokeDasharray={base ? "0" : "2 5"}
                opacity={base ? 1 : 0.9} />
              <text x={PL - 8} y={y + 3} textAnchor="end" fontSize="10"
                fontFamily="General Sans, ui-sans-serif" className="fill-slate"
                opacity="0.8">{t}</text>
            </g>
          );
        })}

        {/* soft hover column highlight */}
        {hover != null && (
          <rect x={cx(hover) - bw / 2 - 10} y={PT - 6} width={bw + 20} height={IH + 12}
            rx="12" className="fill-pill" opacity="0.65" />
        )}

        {/* stacked rounded-top columns + totals */}
        {model.bars.map((b, i) => (
          <g key={daily[i].date} opacity={hover == null || hover === i ? 1 : 0.35}
            style={{ transition: "opacity 0.15s" }}>
            {b.segs.map((s) =>
              s.top ? (
                <path key={s.key} data-bar d={topRoundedRect(b.x, s.y, bw, s.h, s.r)} fill={s.fill} />
              ) : (
                <rect key={s.key} data-bar x={b.x} y={s.y} width={bw} height={s.h} fill={s.fill} />
              )
            )}
            {b.total > 0 && (
              <text data-blabel x={b.x + bw / 2} y={b.top - 8} textAnchor="middle"
                fontSize="12" fontWeight="700" fontFamily="General Sans, ui-sans-serif"
                className="fill-ink" style={{ fontVariantNumeric: "tabular-nums" }}>
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
              className={hover === i ? "fill-ink" : "fill-slate"}
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
            <p><span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: COLORS.seen }} /> Seen <b className="numeral float-right">{hd.attended}</b></p>
            <p><span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: COLORS.upcoming }} /> Upcoming <b className="numeral float-right">{Math.max(hd.booked - hd.attended - hd.no_show, 0)}</b></p>
            <p><span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: COLORS.noShow }} /> No-show <b className="numeral float-right">{hd.no_show}</b></p>
            <p><span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: COLORS.cancelled }} /> Cancelled <b className="numeral float-right">{hd.cancelled}</b></p>
            {hc != null && <p><span className="mr-1 inline-block h-2 w-2 rounded-full bg-slate" /> Calls <b className="numeral float-right">{hc.calls}</b></p>}
            {hd.show_rate !== null && (
              <p><span className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: COLORS.rate }} /> Show rate <b className="numeral float-right">{Math.round(hd.show_rate * 100)}%</b></p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function ChartLegend() {
  const items = [
    [COLORS.seen, "Seen"],
    [COLORS.upcoming, "Upcoming"],
    [COLORS.noShow, "No-show"],
    [COLORS.cancelled, "Cancelled"],
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
