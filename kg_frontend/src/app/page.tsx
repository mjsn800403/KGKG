// app/page.js
import { fetchAllBrands } from '@/utils/api';

export default async function Home() {
  const brands = await fetchAllBrands();

  return (
    <div className="container">
      <div className="eyebrow">Vehicle Documentation Platform</div>
      <h1>Factory precision, <em>in the shop&apos;s hands</em>.</h1>
      <p className="subtitle">SELECT A BRAND TO GET STARTED</p>
      <div className="brand-list">
        {brands.map((brand) => (
          <a key={brand} href={`/${encodeURIComponent(brand)}`} className="brand-card">
            <h2>{brand}</h2>
            <p>Repair manuals · parts catalog · special tools</p>
            <span>Browse {brand} →</span>
          </a>
        ))}
      </div>
    </div>
  );
}
