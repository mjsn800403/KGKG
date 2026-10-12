// app/[brand]/[year]/[model]/parts/page.jsx — parts-catalog root.
// Static segment: wins over the manuals [...path] catch-all (same precedence
// trick as /search). Shows the configuration picker + the top level of the
// selected configuration's group tree. Deeper levels: ./[...ppath]/page.jsx.
import { redirect } from 'next/navigation';
import { fetchPartsRoot, fetchPartsNodes, fetchPartsSearch } from '@/utils/api';
import { redirectToLogin, portalTokenCookie } from '@/utils/serverAuth';
import UserChip from '@/components/UserChip';
import DashboardShell from '@/components/DashboardShell';
import CardGrid from '@/components/CardGrid';
import ActivityBeacon from '@/components/ActivityBeacon';
import {
  PARTS_LABEL, PartsBreadcrumb, ConfigPicker, FrameInfo, partsHref, PartsSearchForm,
} from '@/components/PartsNav';
import { friendlyError } from '@/lib/friendlyError';

const GROUP_ICONS = ['parts', 'gear', 'wrench', 'catalog', 'wiring', 'manual', 'car', 'clock'];

export default async function PartsRootPage({ params, searchParams }) {
  const raw = await params;
  const sp = await searchParams;
  const brand = decodeURIComponent(raw.brand);
  const year = raw.year;
  const model = decodeURIComponent(raw.model);

  const token = await portalTokenCookie();
  if (!token) await redirectToLogin();

  let root = null;
  let denied = false;
  let error = '';
  let noCatalog = null;
  try {
    root = await fetchPartsRoot(brand, year, model, token);
  } catch (e) {
    if (e?.status === 401) await redirectToLogin();
    else if (e?.status === 403) denied = true;
    else if (e?.status === 404 && e?.data?.error === 'no_parts_catalog') noCatalog = e.data.related || [];
    else error = friendlyError(e, 'بارگذاری کاتالوگ قطعات ناموفق بود.');
  }

  if (noCatalog) {
    return (
      <DashboardShell>
        <div className="topbar">
          <PartsBreadcrumb brand={brand} year={year} model={model} />
          <UserChip />
        </div>
        <h1 className="page-title">{PARTS_LABEL}</h1>
        <div className="empty-state" style={{ marginTop: 16 }}>
          {noCatalog.length
            ? 'این خودرو کاتالوگ قطعات جداگانه ندارد؛ کاتالوگ قطعات همین تیپ در زیر آمده است.'
            : 'برای این خودرو کاتالوگ قطعات موجود نیست.'}
        </div>
        {noCatalog.length > 0 && (
          <CardGrid items={noCatalog.map((c) => ({
            href: partsHref(c.brand, c.year, c.model), icon: 'parts',
            title: c.model, sub: String(c.year), go: 'ورود به کاتالوگ ←',
          }))} />
        )}
      </DashboardShell>
    );
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
    if (e?.status === 401) await redirectToLogin();
    nodes = [];
  }

  const q = typeof sp?.q === 'string' ? sp.q.trim().slice(0, 80) : '';
  let search = null;
  if (q) {
    try {
      search = await fetchPartsSearch(brand, year, model, cfg, q, token);
    } catch (e) {
      if (e?.status === 401) await redirectToLogin();
      search = { query: q, results: [], failed: true };
    }
  }
  const hits = (search?.results || []).map((h) => ({
    href: partsHref(brand, year, model, h.path_titles || [], cfg),
    icon: 'parts',
    title: `${h.pn_display || h.pn} · ${h.name_en || ''}`,
    sub: [h.name_fa, (h.path_titles || []).join(' / ')].filter(Boolean).join(' — '),
    go: 'مشاهده در نقشه ←',
  }));

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
      <div className="page-sub">کاتالوگ قطعات · <bdi dir="ltr">{model} {year}</bdi></div>
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
      <PartsSearchForm brand={brand} year={year} model={model} cfg={cfg} q={q} />
      {search ? (
        <>
          <h2 className="section-label">
            {search.failed ? 'جستجو ناموفق بود.' : `نتایج «${q}»: ${hits.length.toLocaleString('fa-IR')} مورد`}
          </h2>
          {hits.length > 0
            ? <CardGrid items={hits} />
            : !search.failed && <div className="empty-state">قطعه‌ای یافت نشد. شماره فنی یا بخشی از نام را امتحان کنید.</div>}
          <p><a href={partsHref(brand, year, model, [], cfg)} className="back-link">← همهٔ گروه‌ها</a></p>
        </>
      ) : (
        <CardGrid items={items} />
      )}
    </DashboardShell>
  );
}
