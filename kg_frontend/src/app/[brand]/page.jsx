// app/[brand]/page.js
import { fetchBrands } from '@/utils/api';
import Link from 'next/link';

export default async function BrandPage({ params }) {
  const raw = await params;
  const brand = decodeURIComponent(raw.brand);
  const cars = await fetchBrands(brand);
  const years = [...new Set(cars.map((car) => car.year))].sort((a, b) => b - a);

  return (
    <div className="container">
      <h1>{decodeURIComponent(brand)}</h1>
      <p className="subtitle">Select a year</p>
      <div className="year-grid">
        {years.map((year) => (
          <Link key={year} href={`/${encodeURIComponent(brand)}/${year}`} className="year-card">
            <h3>{year}</h3>
          </Link>
        ))}
      </div>
    </div>
  );
}
