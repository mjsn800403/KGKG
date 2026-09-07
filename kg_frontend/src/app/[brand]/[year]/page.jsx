// app/[brand]/[year]/page.js — cars for a brand+year, in the dashboard shell
import { notFound } from 'next/navigation';
import { fetchYearData } from '@/utils/api';
import UserChip from '@/components/UserChip';
import DashboardShell from '@/components/DashboardShell';
import Breadcrumb from '@/components/Breadcrumb';
import VehicleCardGrid from '@/components/VehicleCardGrid';

export default async function YearPage({ params }) {
  const raw = await params;
  const brand = decodeURIComponent(raw.brand);
  const year = raw.year;

  // Guard: year must be a 4-digit integer (e.g. /admin/config would otherwise
  // fall through here as brand="admin", year="config" and throw a JSON parse
  // error when the backend returns 404 HTML instead of JSON).
  if (!/^\d{4}$/.test(year)) {
    notFound();
  }

  const cars = await fetchYearData(brand, parseInt(year));

  // schema.org markup for the public catalog: an ItemList of Car objects
  // built from each vehicle's structured identity spec (backend-provided;
  // identity fields only — never manual content).
  const specs = cars.filter((c) => c.spec);
  const jsonld = specs.length
    ? {
        '@context': 'https://schema.org',
        '@type': 'ItemList',
        name: `${brand} ${year} vehicle documentation`,
        numberOfItems: specs.length,
        itemListElement: specs.map((c, i) => {
          const { ['@context']: _ctx, ...item } = c.spec;
          return { '@type': 'ListItem', position: i + 1, item };
        }),
      }
    : null;

  return (
    <DashboardShell>
      {jsonld && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonld) }}
        />
      )}
      <div className="topbar">
        <Breadcrumb brand={brand} year={year} />
        <UserChip />
      </div>
      <h1 className="page-title">{brand} {year}</h1>
      <div className="page-sub">// SELECT_VEHICLE</div>
      <VehicleCardGrid vehicles={cars} brand={brand} year={year} />
    </DashboardShell>
  );
}
