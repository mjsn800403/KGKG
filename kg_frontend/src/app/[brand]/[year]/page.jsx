// app/[brand]/[year]/page.js — cars for a brand+year, in the dashboard shell
import { fetchYearData } from '@/utils/api';
import UserChip from '@/components/UserChip';
import DashboardShell from '@/components/DashboardShell';
import Breadcrumb from '@/components/Breadcrumb';
import CardGrid from '@/components/CardGrid';

export default async function YearPage({ params }) {
  const raw = await params;
  const brand = decodeURIComponent(raw.brand);
  const year = raw.year;
  const cars = await fetchYearData(brand, parseInt(year));

  const items = cars.map((car) => ({
    href: `/${encodeURIComponent(brand)}/${year}/${encodeURIComponent(car.car_name)}`,
    icon: '▣',
    title: car.display_name || car.car_name,
    sub: String(brand).toUpperCase() + ' / ' + year,
    go: 'مشاهده مستندات ←',
  }));

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
      <CardGrid items={items} />
    </DashboardShell>
  );
}
