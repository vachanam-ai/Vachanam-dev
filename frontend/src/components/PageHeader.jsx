export default function PageHeader({ eyebrow, title, sub, children }) {
  return (
    <header data-reveal className="page-header">
      <div className="page-header-copy">
        {eyebrow && <span className="page-kicker">{eyebrow}</span>}
        <h1>{title}</h1>
        {sub && <p>{sub}</p>}
      </div>
      {children && <div className="page-header-actions">{children}</div>}
    </header>
  );
}

export function StatRow({ items }) {
  return (
    <div className="stat-row">
      {items.map((item) => (
        <div key={item.label} data-reveal className="stat-tile">
          <p>{item.label}</p>
          <p className={item.tone === "gold" ? "text-gold-ink" : "text-ink"}>{item.value}</p>
        </div>
      ))}
    </div>
  );
}
