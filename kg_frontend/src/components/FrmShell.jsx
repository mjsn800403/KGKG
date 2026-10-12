// Page frame for the flat-rate manual (/frm/<slug>/...): dashboard shell, a
// breadcrumb rooted at the brand/year the label was clicked from, and the title.
import Link from 'next/link';
import DashboardShell from './DashboardShell';
import UserChip from './UserChip';
import { FRM_TITLE } from '@/utils/frmSets';

export default function FrmShell({ set, trail = [], title, sub, error, children }) {
  const year = set.years[0];
  const root = `/frm/${set.slug}`;
  const items = [
    { label: 'خودروهای فعال', href: '/browse' },
    { label: set.brand, href: `/${encodeURIComponent(set.brand)}` },
    { label: String(year), href: `/${encodeURIComponent(set.brand)}/${year}` },
    { label: `${set.family} · ${FRM_TITLE}`, href: root },
    ...trail.map((t) => ({ label: t.label, href: `${root}${t.href}` })),
  ];
  return (
    <DashboardShell>
      <div className="topbar">
        <nav className="breadcrumb" aria-label="مسیر">
          {items.map((it, i) => (
            <span key={it.href} className="bc-item">
              {i > 0 && <span className="sep" aria-hidden="true">/</span>}
              {i === items.length - 1 ? <b aria-current="page">{it.label}</b> : <Link href={it.href}>{it.label}</Link>}
            </span>
          ))}
        </nav>
        <UserChip />
      </div>
      <h1 className="page-title">{title}</h1>
      {sub && <div className="page-sub">{sub}</div>}
      {error ? <div className="empty-state" style={{ marginTop: 24 }}>{error}</div> : children}
    </DashboardShell>
  );
}
