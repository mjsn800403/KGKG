// A manual section's children as a compact list.
//
// These indexes used to render as a 4-column wall of identical cards (one huge
// card per row on a phone) holding only an English title. The manual's own
// vocabulary is English, so each row keeps the original as its heading and puts
// our Persian equivalent underneath when the terminology store knows it —
// nothing is invented, and the row is still scannable by someone who searches
// in Persian.
import Link from 'next/link';
import Icon from './Icon';

// Icon by what the section is about — the same reading the assistant applies.
const ICON_RULES = [
  [/brake/i, 'wrench'],
  [/wiring|electric|circuit|diagram/i, 'wiring'],
  [/engine|powertrain|hybrid|fuel|ignition/i, 'gear'],
  [/labor|labour|time|flat rate/i, 'clock'],
  [/part|catalog/i, 'parts'],
  [/bulletin|tsb|campaign|recall/i, 'bulletin'],
  [/spec|service data|torque|capacit/i, 'catalog'],
  [/diagnos|dtc|trouble|fault/i, 'search'],
  [/body|frame|interior|exterior|seat|door|glass/i, 'layers'],
  [/maintenance|lubric|inspect/i, 'refresh'],
  [/tool|sst|equipment/i, 'wrench'],
];

export function iconForTitle(title) {
  const hit = ICON_RULES.find(([re]) => re.test(String(title || '')));
  return hit ? hit[1] : 'manual';
}

/**
 * items: [{ href, title, titleFa?, isPage? }]
 * `titleFa` is only shown when it differs from the English title.
 */
export default function SectionList({ items = [], empty = 'موردی در این بخش یافت نشد.' }) {
  if (!items.length) return <div className="empty-state">{empty}</div>;
  return (
    <ul className="sec-list">
      {items.map((it) => (
        <li key={it.href}>
          <Link href={it.href} className="sec-row">
            <span className="sec-ico" aria-hidden="true"><Icon name={iconForTitle(it.title)} /></span>
            <span className="sec-text">
              <bdi dir="ltr" className="sec-title">{it.title}</bdi>
              {it.titleFa && it.titleFa !== it.title && <span className="sec-fa">{it.titleFa}</span>}
            </span>
            <span className="sec-kind">{it.isPage ? 'صفحهٔ مستند' : 'زیربخش'}</span>
            <span className="sec-go" aria-hidden="true"><Icon name="back" /></span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
