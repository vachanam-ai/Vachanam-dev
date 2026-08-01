/** Consistent page header used across every page: small eyebrow, title,
 *  optional sub, and a right-aligned action slot. Keeps the whole app on one
 *  rhythm (the BizLink reference leads every screen with a tight title block). */
export default function PageHeader({ eyebrow, title, sub, children }) {
  return (
    <div data-reveal className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1 className="section-title text-2xl">{title}</h1>
        {sub && <p className="mt-1 font-ui text-sm text-slate">{sub}</p>}
      </div>
      {children && <div className="flex shrink-0 flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

/** Compact stat pill row (the mockup's arrow-KPIs, flattened). */
export function StatRow({ items }) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {items.map((s) => (
        <div key={s.label} data-reveal className="rounded-xl border border-hairline bg-surface px-4 py-3">
          <p className="eyebrow">{s.label}</p>
          <p className={`numeral mt-1 text-2xl ${s.tone === "gold" ? "text-gold-ink" : "text-ink"}`}>{s.value}</p>
        </div>
      ))}
    </div>
  );
}
