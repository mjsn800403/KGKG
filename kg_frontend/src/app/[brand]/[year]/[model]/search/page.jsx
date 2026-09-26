// app/[brand]/[year]/[model]/search/page.js — full search results page.
// The static "search" segment takes precedence over the sibling [...path]
// catch-all in the App Router, so it never collides with node navigation.
import Link from 'next/link';
import { redirect } from 'next/navigation';
import { searchNodes, buildNodeHref } from '@/utils/api';
import { portalTokenCookie } from '@/utils/serverAuth';
import UserChip from '@/components/UserChip';
import DashboardShell from '@/components/DashboardShell';
import Breadcrumb from '@/components/Breadcrumb';
import SearchBox from '@/components/SearchBox';
import Icon from '@/components/Icon';

const FA = (n) => Number(n).toLocaleString('fa-IR');

// The manual's top-level sections, named in Persian where we know them; any
// other root is shown as-is.
const ROOTS = {
  'Repair and Diagnosis': 'تعمیر و عیب‌یابی',
  'Labor Times': 'زمان استاندارد کار',
  'Wiring Diagrams': 'نقشه‌های سیم‌کشی',
  'Technical Service Bulletins': 'بولتن‌های فنی',
};
const ROOT_ICON = { 'Labor Times': 'clock', 'Wiring Diagrams': 'wiring', 'Technical Service Bulletins': 'bulletin' };

// What kind of page a result is, read from its own title. Only a label the
// title actually supports is shown; most results get none.
const KINDS = [
  [/\b[PBCU][0-9A-F]{4}\b|\bDTC\b/, 'کد خطا'],
  [/torque/i, 'گشتاور'],
  [/wiring|diagram/i, 'نقشه سیم‌کشی'],
  [/removal|installation|remove|replace|install/i, 'باز و بست'],
  [/specification/i, 'مشخصات فنی'],
  [/inspection|\bcheck\b|\btest\b/i, 'بازرسی'],
  [/location/i, 'محل قرارگیری'],
];
function kindOf(title) {
  const hit = KINDS.find(([re]) => re.test(title));
  return hit ? hit[1] : '';
}

// Wrap the query's Latin words in <mark>. A Persian query matches the English
// manual semantically, so it has nothing literal to highlight — by design.
function highlight(text, words) {
  if (!words.length) return text;
  const re = new RegExp(`(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'gi');
  return String(text).split(re).map((part, i) => (i % 2 ? <mark key={i}>{part}</mark> : part));
}

export default async function SearchPage({ params, searchParams }) {
  const raw = await params;
  const sp = await searchParams;
  const brand = decodeURIComponent(raw.brand);
  const year = raw.year;
  const model = decodeURIComponent(raw.model);
  const q = (sp?.q || '').trim();
  const only = (sp?.in || '').trim();

  const token = await portalTokenCookie();
  if (!token) redirect('/login');

  const results = q ? await searchNodes(brand, parseInt(year), model, q, 30, token) : [];
  const words = (q.match(/[A-Za-z0-9][A-Za-z0-9-]+/g) || []).filter((w) => w.length >= 2);

  const rows = results.map((node) => {
    const segs = node.segments || [];
    const root = segs.length > 1 ? segs[0] : '';
    return {
      href: buildNodeHref(brand, year, model, segs),
      title: node.title,
      root,
      // The most specific levels say where a result sits; the full trail is
      // in the tooltip.
      trail: segs.slice(root ? 1 : 0, -1),
      kind: root === 'Labor Times' ? '' : kindOf(node.title),
    };
  });

  const counts = new Map();
  rows.forEach((r) => { if (r.root) counts.set(r.root, (counts.get(r.root) || 0) + 1); });
  const shown = only ? rows.filter((r) => r.root === only) : rows;
  const base = `/${encodeURIComponent(brand)}/${year}/${encodeURIComponent(model)}/search?q=${encodeURIComponent(q)}`;

  return (
    <DashboardShell>
      <div className="topbar">
        <Breadcrumb brand={brand} year={year} model={model} />
        <SearchBox brand={brand} year={year} model={model} initialQuery={q} />
        <UserChip />
      </div>
      <h1 className="page-title">نتایج جستجو{q ? <>: «<bdi>{q}</bdi>»</> : ''}</h1>
      <div className="page-sub">
        {q ? `${FA(results.length)} نتیجه در مستندات این خودرو` : 'عبارتی را در کادر جستجو بنویسید.'}
      </div>

      {q && results.length === 0 && (
        <div className="empty-state">
          نتیجه‌ای برای «<bdi>{q}</bdi>» یافت نشد. عبارت کوتاه‌تر یا نام انگلیسی قطعه را امتحان کنید.
        </div>
      )}

      {counts.size > 1 && (
        <nav className="sr-filter" aria-label="محدود کردن به بخش">
          <Link href={base} className={`model-chip${only ? '' : ' active'}`} aria-current={only ? undefined : 'true'}>
            همه <span className="cnt">{FA(rows.length)}</span>
          </Link>
          {[...counts].map(([root, n]) => (
            <Link key={root} href={`${base}&in=${encodeURIComponent(root)}`}
              className={`model-chip${only === root ? ' active' : ''}`}
              aria-current={only === root ? 'true' : undefined}>
              {ROOTS[root] || <bdi dir="ltr">{root}</bdi>} <span className="cnt">{FA(n)}</span>
            </Link>
          ))}
        </nav>
      )}

      {shown.length > 0 && (
        <ol className="sr-list">
          {shown.map((r, i) => (
            <li key={`${i}:${r.href}`}>
              <Link href={r.href} className="sr-item">
                <span className="sr-icon" aria-hidden="true"><Icon name={ROOT_ICON[r.root] || 'manual'} /></span>
                <span className="sr-body">
                  <span className="sr-title" dir="ltr">{highlight(r.title, words)}</span>
                  {r.trail.length > 0 && (
                    <span className="sr-trail" dir="ltr" title={r.trail.join(' › ')}>
                      {r.trail.length > 3 ? '… › ' : ''}{r.trail.slice(-3).join(' › ')}
                    </span>
                  )}
                </span>
                <span className="sr-tags">
                  {r.root && <span className="sr-tag">{ROOTS[r.root] || <bdi dir="ltr">{r.root}</bdi>}</span>}
                  {r.kind && <span className="sr-tag sr-kind">{r.kind}</span>}
                </span>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </DashboardShell>
  );
}
