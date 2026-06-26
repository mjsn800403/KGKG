// app/[brand]/[year]/[model]/search/page.js — full search results page.
// The static "search" segment takes precedence over the sibling [...path]
// catch-all in the App Router, so it never collides with node navigation.
import { searchNodes, buildNodeHref } from '@/utils/api';
import DashboardShell from '@/components/DashboardShell';
import Breadcrumb from '@/components/Breadcrumb';
import CardGrid from '@/components/CardGrid';
import SearchBox from '@/components/SearchBox';

const ICONS = ['▣', '⌖', '◷', '⚙', '◧', '◩', '⬡', '⊞'];

export default async function SearchPage({ params, searchParams }) {
  const raw = await params;
  const sp = await searchParams;
  const brand = decodeURIComponent(raw.brand);
  const year = raw.year;
  const model = decodeURIComponent(raw.model);
  const q = (sp?.q || '').trim();

  const results = q ? await searchNodes(brand, parseInt(year), model, q, 30) : [];

  const items = results.map((node, i) => ({
    href: buildNodeHref(brand, year, model, node.segments),
    icon: ICONS[i % ICONS.length],
    title: node.title,
    sub:
      node.segments && node.segments.length > 1
        ? node.segments.slice(0, -1).join(' / ')
        : null,
    go: 'مشاهده ←',
  }));

  return (
    <DashboardShell>
      <div className="topbar">
        <Breadcrumb brand={brand} year={year} model={model} />
        <SearchBox brand={brand} year={year} model={model} initialQuery={q} />
        <div className="userchip"><div className="avatar">۰۱</div> شرکت خدمات گستر سپهر گیتی</div>
      </div>
      <h1 className="page-title">نتایج جستجو{q ? `: ${q}` : ''}</h1>
      <div className="page-sub">{`// SEARCH_RESULTS — ${results.length} نتیجه`}</div>

      {q && results.length === 0 ? (
        <div className="empty-state">نتیجه‌ای برای «{q}» یافت نشد.</div>
      ) : (
        <CardGrid items={items} />
      )}
    </DashboardShell>
  );
}
