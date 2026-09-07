// app/[brand]/[year]/[model]/parts/[...ppath]/page.jsx — parts tree levels.
// Folders render the same CardGrid as the manuals ("same until the last
// node"); a LEAF renders the parts-catalog layout (PartsViewer): exploded
// diagram(s) + structured parts tables. The active configuration rides in
// ?cfg=; tree titles ride the URL path (encoded — %2F-bearing titles arrive
// as one segment) but are sent to the backend as ?seg= params.
import { redirect } from 'next/navigation';
import { fetchPartsNodes } from '@/utils/api';
import { portalTokenCookie } from '@/utils/serverAuth';
import UserChip from '@/components/UserChip';
import DashboardShell from '@/components/DashboardShell';
import CardGrid from '@/components/CardGrid';
import ActivityBeacon from '@/components/ActivityBeacon';
import PartsViewer from '@/components/PartsViewer';
import {
  PARTS_LABEL, PARTS_CATEGORY_ANALYTICS, PartsBreadcrumb, partsHref,
} from '@/components/PartsNav';

const GROUP_ICONS = ['parts', 'gear', 'wrench', 'catalog', 'wiring', 'manual', 'car', 'clock'];

export default async function PartsNodePage({ params, searchParams }) {
  const raw = await params;
  const sp = await searchParams;
  const brand = decodeURIComponent(raw.brand);
  const year = raw.year;
  const model = decodeURIComponent(raw.model);
  const pathArray = (raw.ppath || []).map(decodeURIComponent);
  const cfg = typeof sp?.cfg === 'string' ? sp.cfg : '';

  const token = await portalTokenCookie();
  if (!token) redirect('/login');
  // No configuration in the URL (hand-edited link) -> restart at the root,
  // which resolves the default configuration.
  if (!cfg) redirect(partsHref(brand, year, model));

  let data = null;
  let denied = false;
  let error = '';
  try {
    data = await fetchPartsNodes(brand, year, model, cfg, pathArray, token);
  } catch (e) {
    if (e?.status === 401) redirect('/login');
    else if (e?.status === 403) denied = true;
    else error = e?.message || 'بارگذاری این بخش ناموفق بود.';
  }

  const currentTitle = pathArray.length ? pathArray[pathArray.length - 1] : PARTS_LABEL;

  if (denied || error) {
    return (
      <DashboardShell>
        <div className="topbar">
          <PartsBreadcrumb brand={brand} year={year} model={model}
            path={pathArray} cfg={cfg} />
          <UserChip />
        </div>
        <h1 className="page-title">{denied ? 'دسترسی محدود' : 'خطا'}</h1>
        <div className="error-box">
          <p>{denied
            ? 'دسترسی به کاتالوگ قطعات این خودرو در اشتراک شما نیست.'
            : `بارگذاری محتوا ناموفق بود: ${error}`}</p>
          <a href={partsHref(brand, year, model, [], cfg)} className="back-link">← بازگشت به کاتالوگ</a>
        </div>
      </DashboardShell>
    );
  }

  const isLeaf = !!(data && !Array.isArray(data) && data.leaf);
  const category = isLeaf ? (data.group?.category || '') : '';

  const items = !isLeaf ? (data || []).map((node, i) => ({
    href: partsHref(brand, year, model, [...pathArray, node.title], cfg),
    icon: GROUP_ICONS[i % GROUP_ICONS.length],
    title: node.title,
    go: node.is_leaf ? 'مشاهده قطعات ←' : 'ورود به دسته ←',
  })) : [];

  return (
    <DashboardShell>
      <div className="topbar">
        <PartsBreadcrumb brand={brand} year={year} model={model}
          path={pathArray} cfg={cfg} />
        <UserChip />
      </div>
      <h1 className="page-title">{currentTitle}</h1>
      <div className="page-sub" dir="ltr">
        // {isLeaf ? 'PARTS_VIEW' : 'PARTS_INDEX'} — {cfg}
      </div>
      <ActivityBeacon
        action="parts_view"
        detail={`${model} — قطعات — ${currentTitle}`}
        segments={pathArray}
        nodeTitle={currentTitle}
        appUrl={partsHref(brand, year, model, pathArray, cfg)}
        brand={brand}
        year={String(year)}
        model={model}
        category={PARTS_CATEGORY_ANALYTICS[category] || ''}
      />
      {isLeaf ? (
        <PartsViewer group={data.group} sections={data.sections || []} />
      ) : (
        <CardGrid items={items} />
      )}
    </DashboardShell>
  );
}
