// components/NodeItem.js
import Link from 'next/link';

export default function NodeItem({ node, brand, year, model, currentPath }) {
  const segments = [...currentPath, node.title].map(encodeURIComponent);
  const href = `/${encodeURIComponent(brand)}/${year}/${encodeURIComponent(model)}/${segments.join('/')}`;

  return (
    <Link href={href} className="node-item">
      <span className="node-title">{node.title}</span>
      <span className="node-arrow">→</span>
    </Link>
  );
}
