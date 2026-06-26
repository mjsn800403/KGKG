// app/[brand]/[year]/[model]/page.js — vehicle view (real root documents)
import { fetchModels } from '@/utils/api';
import DashboardShell from '@/components/DashboardShell';
import Breadcrumb from '@/components/Breadcrumb';
import CardGrid from '@/components/CardGrid';
import SearchBox from '@/components/SearchBox';

const ICONS = ['▣', '⌖', '◷', '⚙', '◧', '◩', '⬡', '⊞'];

export default async function ModelPage({ params }) {
  const raw = await params;
  const brand = decodeURIComponent(raw.brand);
  const year = raw.year;
  const model = decodeURIComponent(raw.model);

  const nodes = await fetchModels(brand, parseInt(year), model);

  const base = `/${encodeURIComponent(brand)}/${year}/${encodeURIComponent(model)}`;
  // The smart assistant lives inside each car: the customer picks the vehicle
  // first, then diagnoses a fault (Persian symptom or DTC) or asks repair Qs.
  const items = [
    {
      href: `${base}/assistant`,
      icon: '🤖',
      title: 'دستیار هوشمند',
      sub: 'تشخیص عیب از روی علائم یا کد خطا (DTC) + راهنمای تعمیر',
      go: 'گفتگو با دستیار ←',
    },
    ...nodes.map((node, i) => ({
      href: `${base}/${encodeURIComponent(node.title)}`,
      icon: ICONS[i % ICONS.length],
      title: node.title,
      go: 'ورود به مستند ←',
    })),
  ];

  return (
    <DashboardShell>
      <div className="topbar">
        <Breadcrumb brand={brand} year={year} model={model} />
        <SearchBox brand={brand} year={year} model={model} />
        <div className="userchip"><div className="avatar">۰۱</div> شرکت خدمات گستر سپهر گیتی</div>
      </div>
      <h1 className="page-title">{model} {year}</h1>
      <div className="page-sub">// VEHICLE_DOCUMENTS</div>
      <CardGrid items={items} />
    </DashboardShell>
  );
}
