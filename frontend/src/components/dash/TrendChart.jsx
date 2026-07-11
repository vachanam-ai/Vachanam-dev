import { useEffect, useMemo, useRef, useState } from "react";

/* Bookings & show-rate chart v2 (2026-07-11 dashboard overhaul).

   Design: smooth Catmull-Rom curves (no polyline corners), gradient area
   under the calls curve, rounded stacked bars that grow from the baseline,
   always-visible bar totals, crosshair + tooltip on hover, gold gradient
   show-rate stroke. GSAP timeline draws everything left→right; a leading
   dot rides each curve like a pen tip. Range switches re-run the entrance
   (fade + redraw — deliberate, never a snap). Reduced motion = instant. */

const COLORS = {
  seen: "#0f766e",
  upcoming: "#5eead4",
  noShow: "#f59e0b",
  cancelled: "#e5e9ee",
  calls: "#0e7490",
  grid: "#eef2f6",
};

const W = 760, H = 264, PL = 36, PR = 16, PT = 20, PB = 30;
const IW = W - PL - PR, IH = H - PT - PB;

/* Catmull-Rom → cubic Bézier path through points [{x,y}]. */
function smoothPath(pts) {
  if (pts.length < 2) return "";
  const d = [`M ${pts[0].x} ${pts[0].y}`];
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2] ?? p2;
    const c1x = p1.x + (p2.x - p0.x) / 6, c1y = p1.y + (p2.y - p0.y) / 6;
    const c2x = p2.x - (p3.x - p1.x) / 6, c2y = p2.y - (p3.y - p1.y) / 6;
    d.push(`C ${c1x} ${c1y}, ${c2x} ${c2y}, ${p2.x} ${p2.y}`);
  }
  return d.join(" ");
}

export default function TrendChart({ daily, calls }) {
  const wrapRef = useRef(null);
  const svgRef = useRef(null);
  const [hover, setHover] = useState(null); // day index or null

  const n = daily.length;
  const slot = IW / Math.max(n, 1);
  const bw = Math.max(8, Math.min(slot * 0.55, 40));
  const cx = (i) => PL + i * slot + slot / 2;

  const model = useMemo(() => {
    const maxStack = Math.max(1, ...daily.map((d) => d.booked + d.cancelled));
    const maxCalls = Math.max(1, ...(calls ?? []).map((c) => c.calls));
    const yh = (v) => (v / maxStack) * IH;
    const bars = daily.map((d, i) => {
      const upcoming = Math.max(d.booked - d.attended - d.no_show, 0);
      const segs = [];
      let y = H - PB;
      for (const [key, v, fill] of [
        ["seen", d.attended, COLORS.seen],
        ["upcoming", upcoming, COLORS.upcoming],
        ["noShow", d.no_show, COLORS.noShow],
        ["cancelled", d.cancelled, COLORS.cancelled],
      ]) {
        const h = yh(v);
        if (h > 0) { y -= h; segs.push({ key, y, h, fill }); }
      }
      const total = d.booked + d.cancelled;
      return { segs, total, top: y, x: cx(i) - bw / 2 };
    });
    const callPts = (calls ?? []).slice(0, n).map((c, i) => ({
      x: cx(i), y: H - PB - (c.calls / maxCalls) * IH * 0.86, v: c.calls,
    }));
    const ratePts = daily
      .map((d, i) => (d.show_rate === null ? null : { x: cx(i), y: H - PB - d.show_rate * IH, v: d.show_rate }))
      .filter(Boolean);
    const callPath = smoothPath(callPts);
    const areaPath = callPts.length >= 2
      ? `${callPath} L ${callPts[callPts.length - 1].x} ${H - PB} L ${callPts[0].x} ${H - PB} Z`
      : "";
    return { bars, callPts, ratePts, callPath, ratePath: smoothPath(ratePts), areaPath };
  }, [daily, calls]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    let mm;
    import("gsap").then(({ gsap }) => {
      mm = gsap.matchMedia();
      const grids = svg.querySelectorAll("[data-grid]");
      const rects = svg.querySelectorAll("rect[data-bar]");
      const labels = svg.querySelectorAll("[data-blabel]");
      const dots = svg.querySelectorAll("[data-dot]");
      const rateLabels = svg.querySelectorAll("[data-rlabel]");
      const area = svg.querySelector("[data-area]");
      const paths = [svg.querySelector("[data-callpath]"), svg.querySelector("[data-ratepath]")];
      const pens = [svg.querySelector("[data-pen-call]"), svg.querySelector("[data-pen-rate]")];

      mm.add("(prefers-reduced-motion: no-preference)", () => {
        const tl = gsap.timeline({ defaults: { ease: "power3.out" } });
        tl.fromTo(grids, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.25, stagger: 0.03 });
        tl.fromTo(rects, { scaleY: 0, transformOrigin: "center bottom" },
          { scaleY: 1, duration: 0.55, stagger: 0.04 }, 0.1);
        tl.fromTo(labels, { scale: 0, autoAlpha: 0, transformOrigin: "center bottom" },
          { scale: 1, autoAlpha: 1, duration: 0.35, ease: "back.out(1.7)", stagger: 0.04 }, 0.32);
        paths.forEach((p, pi) => {
          if (!p) return;
          const len = p.getTotalLength();
          if (!len) return;
          tl.fromTo(p, { strokeDasharray: len, strokeDashoffset: len },
            { strokeDashoffset: 0, duration: 0.8, ease: "none" }, 0.5 + pi * 0.25);
          const pen = pens[pi];
          if (pen) {
            const proxy = { t: 0 };
            tl.fromTo(pen, { autoAlpha: 1 }, { autoAlpha: 1, duration: 0.01 }, 0.5 + pi * 0.25);
            tl.to(proxy, {
              t: 1, duration: 0.8, ease: "none",
              onUpdate: () => {
                const pt = p.getPointAtLength(proxy.t * len);
                pen.setAttribute("cx", pt.x); pen.setAttribute("cy", pt.y);
              },
            }, 0.5 + pi * 0.25);
            tl.to(pen, { autoAlpha: 0, duration: 0.2 }, 1.3 + pi * 0.25);
          }
        });
        if (area) tl.fromTo(area, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.4 }, 1.25);
        tl.fromTo(dots, { scale: 0, transformOrigin: "center center" },
          { scale: 1, duration: 0.3, ease: "back.out(2)", stagger: 0.03 }, 0.9);
        tl.fromTo(rateLabels, { autoAlpha: 0, y: 4 }, { autoAlpha: 1, y: 0, duration: 0.3 }, 1.5);
      });
      mm.add("(prefers-reduced-motion: reduce)", () => {
        gsap.set([grids, rects, labels, dots, rateLabels, area, ...paths.filter(Boolean)],
          { clearProps: "all", autoAlpha: 1 });
        pens.forEach((pen) => pen && gsap.set(pen, { autoAlpha: 0 }));
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
    <div ref={wrapRef} className="relative">
      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} className="w-full"
        role="img" aria-label="Daily bookings, calls and show rate"
        onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        <defs>
          <linearGradient id="rateGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#d97706" />
            <stop offset="100%" stopColor="#f0b429" />
          </linearGradient>
          <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={COLORS.calls} stopOpacity="0.14" />
            <stop offset="100%" stopColor={COLORS.calls} stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {[0.25, 0.5, 0.75, 1].map((g) => (
          <g key={g} data-grid>
            <line x1={PL} x2={W - PR} y1={H - PB - g * IH} y2={H - PB - g * IH}
              stroke={COLORS.grid} strokeWidth="1" />
            <text x={PL - 6} y={H - PB - g * IH + 3} textAnchor="end" fontSize="9"
              fontFamily="ui-sans-serif" className="fill-slate" opacity="0.7">
              {Math.round(g * Math.max(1, ...daily.map((d) => d.booked + d.cancelled)))}
            </text>
          </g>
        ))}

        {/* crosshair */}
        {hover != null && (
          <line x1={cx(hover)} x2={cx(hover)} y1={PT} y2={H - PB}
            stroke="#94a3b8" strokeWidth="1" strokeDasharray="3 3" opacity="0.6" />
        )}

        {/* bars + totals */}
        {model.bars.map((b, i) => (
          <g key={daily[i].date} opacity={hover == null || hover === i ? 1 : 0.45}
            style={{ transition: "opacity 0.15s" }}>
            {b.segs.map((s, si) => (
              <rect key={s.key} data-bar x={b.x} y={s.y} width={bw} height={s.h}
                fill={s.fill} rx={si === b.segs.length - 1 ? 3 : 0} />
            ))}
            {b.total > 0 && (
              <text data-blabel x={b.x + bw / 2} y={b.top - 5} textAnchor="middle"
                fontSize="10.5" fontWeight="600" fontFamily="ui-sans-serif"
                className="fill-slate">{b.total}</text>
            )}
          </g>
        ))}

        {/* calls curve: area + stroke + pen + dots */}
        {model.areaPath && <path data-area d={model.areaPath} fill="url(#areaGrad)" />}
        {model.callPath && (
          <path data-callpath d={model.callPath} fill="none" stroke={COLORS.calls}
            strokeWidth="2" strokeLinecap="round" />
        )}
        <circle data-pen-call r="3.5" fill={COLORS.calls} opacity="0" />
        {model.callPts.map((p, i) => (
          <circle key={`c${i}`} data-dot cx={p.x} cy={p.y} r={hover === i ? 4 : 2.5}
            fill="#fff" stroke={COLORS.calls} strokeWidth="1.8" />
        ))}

        {/* show-rate curve */}
        {model.ratePath && (
          <path data-ratepath d={model.ratePath} fill="none" stroke="url(#rateGrad)"
            strokeWidth="2.5" strokeLinecap="round" />
        )}
        <circle data-pen-rate r="3.5" fill="#f0b429" opacity="0" />
        {model.ratePts.map((p, i) => (
          <g key={`r${i}`}>
            <circle data-dot cx={p.x} cy={p.y} r="2.8" fill="#f0b429" stroke="#fff" strokeWidth="1.2" />
            {(i === 0 || i === model.ratePts.length - 1) && (
              <text data-rlabel x={p.x} y={p.y - 8} textAnchor="middle" fontSize="10"
                fontWeight="600" fontFamily="ui-sans-serif" fill="#b45309">
                {Math.round(p.v * 100)}%
              </text>
            )}
          </g>
        ))}

        {/* x labels */}
        {daily.map((d, i) =>
          i % Math.ceil(n / 7) === 0 ? (
            <text key={d.date} x={cx(i)} y={H - 9} textAnchor="middle" fontSize="10"
              fontFamily="ui-sans-serif" className="fill-slate">
              {d.date.slice(5)}
            </text>
          ) : null
        )}
      </svg>

      {/* tooltip */}
      {hd && (
        <div className="pointer-events-none absolute z-10 w-44 rounded-xl border border-hairline bg-white/95 px-3 py-2 shadow-lift backdrop-blur transition-all duration-150"
          style={{
            left: `${Math.min(Math.max((cx(hover) / W) * 100, 12), 82)}%`,
            top: 0, transform: "translate(-50%, -6px)",
          }}>
          <p className="font-ui text-[11px] font-semibold text-teal-deep">
            {new Date(hd.date + "T00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" })}
          </p>
          <div className="mt-1 space-y-0.5 font-ui text-[11px] text-slate">
            <p><span className="inline-block h-2 w-2 rounded-sm" style={{ background: COLORS.seen }} /> Seen <b className="numeral float-right">{hd.attended}</b></p>
            <p><span className="inline-block h-2 w-2 rounded-sm" style={{ background: COLORS.upcoming }} /> Upcoming <b className="numeral float-right">{Math.max(hd.booked - hd.attended - hd.no_show, 0)}</b></p>
            <p><span className="inline-block h-2 w-2 rounded-sm" style={{ background: COLORS.noShow }} /> No-show <b className="numeral float-right">{hd.no_show}</b></p>
            <p><span className="inline-block h-2 w-2 rounded-sm" style={{ background: COLORS.cancelled }} /> Cancelled <b className="numeral float-right">{hd.cancelled}</b></p>
            <p><span className="inline-block h-2 w-2 rounded-full" style={{ background: COLORS.calls }} /> Calls <b className="numeral float-right">{hc?.calls ?? 0}</b></p>
            {hd.show_rate !== null && (
              <p><span className="inline-block h-2 w-2 rounded-full bg-amber-500" /> Show rate <b className="numeral float-right">{Math.round(hd.show_rate * 100)}%</b></p>
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
    ["#f0b429", "Show-rate curve"],
    [COLORS.calls, "Calls answered"],
  ];
  return (
    <div className="flex flex-wrap gap-4">
      {items.map(([c, l]) => (
        <span key={l} className="flex items-center gap-1.5 font-ui text-xs text-slate">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: c }} /> {l}
        </span>
      ))}
    </div>
  );
}
