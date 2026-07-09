// app/[brand]/[year]/[model]/page.js — vehicle view (real root documents)
import { fetchModels } from '@/utils/api';
import UserChip from '@/components/UserChip';
import DashboardShell from '@/components/DashboardShell';
import Breadcrumb from '@/components/Breadcrumb';
import CardGrid from '@/components/CardGrid';
import SearchBox from '@/components/SearchBox';

// Pick a meaningful icon from the section title; fall back to a rotation so
// neighbouring cards still look distinct.
const FALLBACK_ICONS = ['manual', 'parts', 'clock', 'wrench', 'catalog', 'bulletin', 'wiring', 'gear'];
function iconFor(title, i) {
  const t = String(title || '').toLowerCase();
  if (/part|catalog/.test(t)) return 'parts';
  if (/wiring|electric|diagram/.test(t)) return 'wiring';
  if (/labor|labour|time|flat rate/.test(t)) return 'clock';
  if (/tool|equipment/.test(t)) return 'wrench';
  if (/bulletin|tsb|campaign/.test(t)) return 'bulletin';
  if (/repair|manual|service|procedure/.test(t)) return 'manual';
  if (/feature|new car|spec/.test(t)) return 'car';
  return FALLBACK_ICONS[i % FALLBACK_ICONS.length];
}

export default async function ModelPage({ params }) {
  const raw = await params;
  const brand = decodeURIComponent(raw.brand);
  const year = raw.year;
  const model = decodeURIComponent(raw.model);

  let nodes = [];
  let loadError = '';
  try {
    nodes = await fetchModels(brand, parseInt(year), model);
  } catch (e) {
    loadError = e?.message || 'بارگذاری مستندات این خودرو ناموفق بود.';
  }

  if (loadError) {
    return (
      <DashboardShell>
        <div className="topbar">
          <Breadcrumb brand={brand} year={year} model={model} />
          <UserChip />
        </div>
        <div className="empty-state" style={{ marginTop: 24 }}>{loadError}</div>
      </DashboardShell>
    );
  }

  const base = `/${encodeURIComponent(brand)}/${year}/${encodeURIComponent(model)}`;
  // The smart assistant lives inside each car: the customer picks the vehicle
  // first, then diagnoses a fault (Persian symptom or DTC) or asks repair Qs.
  const items = [
    {
      href: `${base}/assistant`,
      icon: 'bot',
      title: 'دستیار هوشمند',
      sub: 'تشخیص عیب از روی علائم یا کد خطا (DTC) + راهنمای تعمیر',
      go: 'گفتگو با دستیار ←',
    },
    ...nodes.map((node, i) => ({
      href: `${base}/${encodeURIComponent(node.title)}`,
      icon: iconFor(node.title, i),
      title: node.title,
      go: 'ورود به مستند ←',
    })),
  ];

  return (
    <DashboardShell>
      <div className="topbar">
        <Breadcrumb brand={brand} year={year} model={model} />
        <SearchBox brand={brand} year={year} model={model} />
        <UserChip />
      </div>
      <h1 className="page-title">{model} {year}</h1>
      <div className="page-sub">// VEHICLE_DOCUMENTS</div>
      <CardGrid items={items} />
    </DashboardShell>
  );
}
