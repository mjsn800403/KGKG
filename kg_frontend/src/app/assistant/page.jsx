// app/assistant — car picker for the smart assistant. The assistant now lives
// INSIDE each car (the customer picks the vehicle first, then diagnoses faults /
// asks repair questions scoped to that car). This page just routes there.
import DashboardShell from '@/components/DashboardShell';
import CardGrid from '@/components/CardGrid';
import { fetchAllBrands, fetchBrands } from '@/utils/api';

export const metadata = {
  title: 'دستیار هوشمند | KGtechvault',
};

// Depends on live backend data (the car list) — render on request, never
// statically prerender at build time (when the backend isn't running).
export const dynamic = 'force-dynamic';

const ICONS = ['▣', '⌖', '◷', '⚙', '◧', '◩', '⬡', '⊞'];

export default async function AssistantPickerPage() {
  const brands = await fetchAllBrands();
  const nested = await Promise.all(brands.map((b) => fetchBrands(b)));
  const cars = nested.flat();

  const items = cars.map((c, i) => ({
    href: `/${encodeURIComponent(c.brand_name)}/${c.year}/${encodeURIComponent(c.car_name)}/assistant`,
    icon: ICONS[i % ICONS.length],
    title: `${c.car_name}`,
    sub: `${c.brand_name} • ${c.year}`,
    go: 'دستیار این خودرو ←',
  }));

  return (
    <DashboardShell>
      <div className="topbar">
        <div className="breadcrumb"><b>دستیار هوشمند</b></div>
        <div className="userchip"><div className="avatar">۰۱</div> شرکت خدمات گستر سپهر گیتی</div>
      </div>
      <h1 className="page-title">دستیار هوشمند سرویس</h1>
      <div className="page-sub">{'// اول خودرو را انتخاب کن، بعد عیب را بگو یا کد خطا را وارد کن'}</div>
      <CardGrid items={items} />
    </DashboardShell>
  );
}
