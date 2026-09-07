// components/Breadcrumb.js — dashboard topbar breadcrumb (prototype style)
import Link from 'next/link';
import { buildNodeHref } from '@/utils/api';

export default function Breadcrumb({ brand, year, model, path = [] }) {
  const encodedBrand = encodeURIComponent(brand);
  const encodedModel = encodeURIComponent(model);

  const items = [
    { label: 'خودروهای فعال', href: '/browse' },
    { label: brand, href: `/${encodedBrand}` },
    ...(year ? [{ label: year, href: `/${encodedBrand}/${year}` }] : []),
    ...(model ? [{ label: model, href: `/${encodedBrand}/${year}/${encodedModel}` }] : []),
    ...path.map((p, index) => ({
      label: p,
      href: buildNodeHref(brand, year, model, path.slice(0, index + 1)),
    })),
  ];

  return (
    <div className="breadcrumb">
      {items.map((item, index) => (
        <span key={index} style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
          {index > 0 && <span className="sep">/</span>}
          {index === items.length - 1 ? (
            <b>{item.label}</b>
          ) : (
            <Link href={item.href}>{item.label}</Link>
          )}
        </span>
      ))}
    </div>
  );
}
