// app/[brand]/[year]/[model]/parts/page.jsx — parts-catalog root.
// Static segment: wins over the manuals [...path] catch-all (same precedence
// trick as /search). Shows the configuration picker + the top level of the
// selected configuration's group tree. Deeper levels: ./[...ppath]/page.jsx.
import { redirect } from 'next/navigation';
import { fetchPartsRoot, fetchPartsNodes } from '@/utils/api';
import { portalTokenCookie } from '@/utils/serverAuth';
import UserChip from '@/components/UserChip';
import DashboardShell from '@/components/DashboardShell';
import CardGrid from '@/components/CardGrid';
import ActivityBeacon from '@/components/ActivityBeacon';
import {
  PARTS_LABEL, PartsBreadcrumb, ConfigPicker, FrameInfo, partsHref,
} from '@/components/PartsNav';

const GROUP_ICONS = ['parts', 'gear', 'wrench', 'catalog', 'wiring', 'manual', 'car', 'clock'];

export default async function PartsRootPage({ params, searchParams }) {
  const raw = await params;
  const sp = await searchParams;
  const brand = decodeURIComponent(raw.brand);
  const year = raw.year;
  const model = decodeURIComponent(raw.model);

  const token = await portalTokenCookie();
  if (!token) redirect('/login');

  let root = null;
  let denied = false;
  let error = '';
  try {
    root = await fetchPartsRoot(brand, year, model, token);
  } catch (e) {
    if (e?.status === 401) redirect('/login');
    else if (e?.status === 403) denied = true;
    else error = e?.message || 'بارگذاری کاتالوگ قطعات ناموفق بود.';
  }

  if (denied || error) {
    return (
      <DashboardShell>
        <div className="topbar">
          <PartsBreadcrumb brand={brand} year={year} model={model} />
          <UserChip />
        </div>
        <h1 className="page-title">{PARTS_LABEL}</h1>
        <div className="error-box">
          <p>{denied
            ? 'دسترسی به کاتالوگ قطعات این خودرو در اشتراک شما نیست. برای افزودن، با مدیر یا پشتیبانی تماس بگیرید.'
            : `بارگذاری کاتالوگ ناموفق بود: ${error}`}</p>
          <a href="/browse" className="back-link">← بازگشت به خودروهای فعال</a>
        </div>
      </DashboardShell>
    );
  }

  const frames = root?.frames || [];
  const requested = typeof sp?.cfg === 'string' ? sp.cfg : '';
  const cfg = frames.some((f) => f.code === requested) ? requested : root.default_frame;
  const activeFrame = frames.find((f) => f.code === cfg) || null;

  let nodes = [];
  try {
    const res = await fetchPartsNodes(brand, year, model, cfg, [], token);
    nodes = Array.isArray(res) ? res : [];
  } catch (e) {
    if (e?.status === 401) redirect('/login');
    nodes = [];
  }

  const items = nodes.map((node, i) => ({
    href: partsHref(brand, year, model, [node.title], cfg),
    icon: GROUP_ICONS[i % GROUP_ICONS.length],
    title: node.title,
    go: node.is_leaf ? 'مشاهده قطعات ←' : 'ورود به دسته ←',
  }));

  return (
    <DashboardShell>
      <div className="topbar">
        <PartsBreadcrumb brand={brand} year={year} model={model} cfg={cfg} />
        <UserChip />
      </div>
      <h1 className="page-title">{PARTS_LABEL}</h1>
      <div className="page-sub" dir="ltr">// PARTS_CATALOG — {model} {year}</div>
      <ActivityBeacon
        action="parts_view"
        detail={`${model} — ${PARTS_LABEL}`}
        nodeTitle={PARTS_LABEL}
        appUrl={partsHref(brand, year, model, [], cfg)}
        brand={brand}
        year={String(year)}
        model={model}
      />
      <ConfigPicker brand={brand} year={year} model={model}
        frames={frames} active={cfg} />
      <FrameInfo frame={activeFrame} />
      <CardGrid items={items} />
    </DashboardShell>
  );
}
