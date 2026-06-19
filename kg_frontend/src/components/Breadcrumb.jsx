// components/Breadcrumb.js
import Link from 'next/link';

export default function Breadcrumb({ brand, year, model, path = [] }) {
  const encodedBrand = encodeURIComponent(brand);
  const encodedModel = encodeURIComponent(model);

  const items = [
    { label: brand, href: `/${encodedBrand}` },
    ...(year ? [{ label: year, href: `/${encodedBrand}/${year}` }] : []),
    ...(model ? [{ label: model, href: `/${encodedBrand}/${year}/${encodedModel}` }] : []),
    ...path.map((p, index) => ({
      label: p,
      href: `/${encodedBrand}/${year}/${encodedModel}/${path.slice(0, index + 1).map(encodeURIComponent).join('/')}`
    }))
  ];

  return (
    <nav className="breadcrumb">
      <Link href="/">Home</Link>
      {items.map((item, index) => (
        <span key={index}>
          <span className="separator"> / </span>
          {index === items.length - 1 ? (
            <span className="current">{item.label}</span>
          ) : (
            <Link href={item.href}>{item.label}</Link>
          )}
        </span>
      ))}
    </nav>
  );
}