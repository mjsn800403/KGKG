// app/[brand]/[year]/page.js
import { fetchYearData } from '@/utils/api';
import Link from 'next/link';

export default async function YearPage({ params }) {
  const raw = await params;
  const brand = decodeURIComponent(raw.brand);
  const year = raw.year;
  const cars = await fetchYearData(brand, parseInt(year));

  return (
    <div className="container">
      <h1>{brand} {year}</h1>
      <div className="car-grid">
        {cars.map((car) => (
          <Link
            key={car.car_name}
            href={`/${encodeURIComponent(brand)}/${year}/${encodeURIComponent(car.car_name)}`}
            className="car-card"
          >
            <h3>{car.car_name}</h3>
            <p>Repair manuals · parts catalog · special tools</p>
            <span>View Manual →</span>
          </Link>
        ))}
      </div>
    </div>
  );
}