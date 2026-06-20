// app/[brand]/[year]/[model]/page.js — vehicle view (real root documents)
import { fetchModels } from '@/utils/api';
import DashboardShell from '@/components/DashboardShell';
import Breadcrumb from '@/components/Breadcrumb';
import CardGrid from '@/components/CardGrid';

const ICONS = ['▣', '⌖', '◷', '⚙', '◧', '◩', '⬡', '⊞'];

export default async function ModelPage({ params }) {
  const raw = await params;
  const brand = decodeURIComponent(raw.brand);
  const year = raw.year;
  const model = decodeURIComponent(raw.model);

  const nodes = await fetchModels(brand, parseInt(year), model);

  const items = nodes.map((node, i) => ({
    href: `/${encodeURIComponent(brand)}/${year}/${encodeURIComponent(model)}/${encodeURIComponent(node.title)}`,
    icon: ICONS[i % ICONS.length],
    title: node.title,
    sub: (node.file_type || node.node_type || 'DOCUMENT').toString().toUpperCase().replace(/_/g, ' '),
    go: 'ورود به مستند ←',
  }));

  return (
    <DashboardShell>
      <div className="topbar">
        <Breadcrumb brand={brand} year={year} model={model} />
        <div className="userchip"><div className="avatar">۰۱</div> شرکت خدمات گستر سپهر گیتی</div>
      </div>
      <h1 className="page-title">{model} {year}</h1>
      <div className="page-sub">// VEHICLE_DOCUMENTS</div>
      <CardGrid items={items} />
    </DashboardShell>
  );
}
