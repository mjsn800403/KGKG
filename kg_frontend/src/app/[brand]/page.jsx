// app/[brand]/page.js — years for a brand, in the dashboard shell
import { fetchBrands } from '@/utils/api';
import DashboardShell from '@/components/DashboardShell';
import Breadcrumb from '@/components/Breadcrumb';
import CardGrid from '@/components/CardGrid';

export default async function BrandPage({ params }) {
  const raw = await params;
  const brand = decodeURIComponent(raw.brand);
  const cars = await fetchBrands(brand);
  const years = [...new Set(cars.map((car) => car.year))].sort((a, b) => b - a);

  const items = years.map((year) => ({
    href: `/${encodeURIComponent(brand)}/${year}`,
    icon: '◷',
    title: String(year),
    sub: 'MODEL YEAR',
    go: 'مشاهده ←',
  }));

  return (
    <DashboardShell>
      <div className="topbar">
        <Breadcrumb brand={brand} />
        <div className="userchip"><div className="avatar">۰۱</div> شرکت خدمات گستر سپهر گیتی</div>
      </div>
      <h1 className="page-title">{brand}</h1>
      <div className="page-sub">// SELECT_MODEL_YEAR</div>
      <CardGrid items={items} />
    </DashboardShell>
  );
}
