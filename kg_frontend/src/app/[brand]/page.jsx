// app/[brand]/page.js — model years for a brand, in the dashboard shell.
// An unknown first segment lands here too (the route is a catch-all for one
// path segment), so a brand with no vehicles renders the real 404 page
// instead of an empty year list titled with whatever was typed.
import { notFound } from 'next/navigation';
import { fetchBrands } from '@/utils/api';
import UserChip from '@/components/UserChip';
import DashboardShell from '@/components/DashboardShell';
import Breadcrumb from '@/components/Breadcrumb';
import CardGrid from '@/components/CardGrid';

export default async function BrandPage({ params }) {
  const raw = await params;
  const brand = decodeURIComponent(raw.brand);
  const cars = await fetchBrands(brand).catch(() => []);
  if (!cars.length) notFound();

  const years = [...new Set(cars.map((car) => car.year))].sort((a, b) => b - a);
  const countFor = (year) => cars.filter((c) => c.year === year).length;

  const items = years.map((year) => ({
    href: `/${encodeURIComponent(brand)}/${year}`,
    icon: 'clock',
    title: String(year),
    sub: `${countFor(year).toLocaleString('fa-IR')} خودرو`,
    go: 'مشاهده خودروها ←',
  }));

  return (
    <DashboardShell>
      <div className="topbar">
        <Breadcrumb brand={brand} />
        <UserChip />
      </div>
      <h1 className="page-title">{brand}</h1>
      <div className="page-sub">
        {`${cars.length.toLocaleString('fa-IR')} خودرو در ${years.length.toLocaleString('fa-IR')} سال مدل — سال موردنظر را انتخاب کنید.`}
      </div>
      <CardGrid items={items} />
    </DashboardShell>
  );
}
