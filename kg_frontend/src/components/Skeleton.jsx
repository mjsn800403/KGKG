// Loading placeholders shaped like the content that is coming, so the page
// doesn't jump when data arrives. Purely visual; screen readers get the label.
export default function Skeleton({ kind = 'cards', count = 8, label = 'در حال بارگذاری…' }) {
  const n = Array.from({ length: count });
  return (
    <div className={`sk sk-${kind}`} role="status" aria-live="polite">
      <span className="sk-sr">{label}</span>
      {kind === 'cards' && n.map((_, i) => (
        <div className="sk-card" key={i} aria-hidden="true">
          <i className="sk-line sk-w30" /><i className="sk-line sk-w70 sk-lg" /><i className="sk-line sk-w40" />
        </div>
      ))}
      {kind === 'tree' && n.map((_, i) => (
        <i className={`sk-line ${i % 3 === 0 ? 'sk-w70' : i % 3 === 1 ? 'sk-w55 sk-in' : 'sk-w40 sk-in'}`} key={i} aria-hidden="true" />
      ))}
      {kind === 'block' && <div className="sk-block" aria-hidden="true" />}
    </div>
  );
}
