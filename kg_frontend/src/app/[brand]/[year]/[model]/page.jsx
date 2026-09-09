// app/[brand]/[year]/[model]/page.js — vehicle view (real root documents)
import { redirect } from 'next/navigation';
import {
  fetchModels, fetchPartsRoot, buildNodeHref, sstCsvUrl, fetchSstAvailable,
} from '@/utils/api';
import { portalTokenCookie, browseModeCookie } from '@/utils/serverAuth';
import UserChip from '@/components/UserChip';
import DashboardShell from '@/components/DashboardShell';
import Breadcrumb from '@/components/Breadcrumb';
import CardGrid from '@/components/CardGrid';
import CarBrowser from '@/components/CarBrowser';
import SearchBox from '@/components/SearchBox';

// Pick a meaningful icon from the section title; fall back to a rotation so
// neighbouring cards still look distinct.
const FALLBACK_ICONS = ['manual', 'parts', 'clock', 'wrench', 'catalog', 'bulletin', 'wiring', 'gear'];
function iconFor(title, i) {
  const t = String(title || '').toLowerCase();
  if (/part|catalog/.test(t)) return 'parts';
  if (/wiring|electric|diagram/.test(t)) return 'wiring';
  if (/labor|labour|time|flat rate/.test(t)) return 'clock';
  if (/tool|equipment/.test(t)) return 'wrench';
  if (/bulletin|tsb|campaign/.test(t)) return 'bulletin';
  if (/repair|manual|service|procedure/.test(t)) return 'manual';
  if (/feature|new car|spec/.test(t)) return 'car';
  return FALLBACK_ICONS[i % FALLBACK_ICONS.length];
}

export default async function ModelPage({ params }) {
  const raw = await params;
  const brand = decodeURIComponent(raw.brand);
  const year = raw.year;
  const model = decodeURIComponent(raw.model);

  const token = await portalTokenCookie();
  if (!token) redirect('/login');
  // Classic mode drops the sidebar; modern wraps content in the tree browser.
  const classic = (await browseModeCookie()) === 'classic';

  // A vehicle can carry a manual tree, a parts catalog, or both (parts-only
  // vehicles exist — their manual fetch 403/404s by design). Load both in
  // parallel and fail the page only when NEITHER surface is available.
  let nodes = [];
  let partsRoot = null;
  let loadError = '';
  // The SST probe rides along in the same round trip; it resolves to a plain
  // boolean and never throws, so it cannot affect whether the page renders.
  const [manualRes, partsRes, sstRes] = await Promise.allSettled([
    // Raw year segment on purpose: parseInt turns a legacy 'unknown' year into
    // NaN; the backend resolves the car by brand+name when the year mismatches.
    fetchModels(brand, year, model, token),
    fetchPartsRoot(brand, year, model, token),
    fetchSstAvailable(brand, year, model, token),
  ]);
  if (manualRes.status === 'fulfilled') {
    nodes = manualRes.value || [];
  } else if (manualRes.reason?.status === 401) {
    redirect('/login');
  }
  if (partsRes.status === 'fulfilled') {
    partsRoot = partsRes.value;
  } else if (partsRes.reason?.status === 401) {
    redirect('/login');
  }
  const hasManual = manualRes.status === 'fulfilled';
  const hasSst = sstRes.status === 'fulfilled' && sstRes.value === true;
  const hasParts = !!partsRoot;
  if (!hasManual && !hasParts) {
    // Prefer a 403 from EITHER surface: "not in your subscription" is the
    // actionable message, and a raw backend 404 string would be shown instead
    // whenever the manual happens to fail differently from the parts side.
    const reasons = [manualRes.reason, partsRes.reason].filter(Boolean);
    const denied = reasons.find((e) => e?.forbidden);
    if (denied) {
      loadError = 'دسترسی به مستندات این خودرو در اشتراک شما نیست. برای افزودن این خودرو با مدیر یا پشتیبانی تماس بگیرید.';
    } else {
      loadError = reasons[0]?.message || 'بارگذاری مستندات این خودرو ناموفق بود.';
    }
  }

  if (loadError) {
    return (
      <DashboardShell>
        <div className="topbar">
          <Breadcrumb brand={brand} year={year} model={model} />
          <UserChip />
        </div>
        <div className="empty-state" style={{ marginTop: 24 }}>{loadError}</div>
      </DashboardShell>
    );
  }

  const base = `/${encodeURIComponent(brand)}/${year}/${encodeURIComponent(model)}`;
  // The smart assistant lives inside each car: the customer picks the vehicle
  // first, then diagnoses a fault (Persian symptom or DTC) or asks repair Qs.
  // It grounds in the manual tree, so it only appears when a manual exists.
  const items = [
    ...(hasManual ? [{
      href: `${base}/assistant`,
      icon: 'bot',
      title: 'دستیار هوشمند',
      sub: 'تشخیص عیب از روی علائم یا کد خطا (DTC) + راهنمای تعمیر',
      go: 'گفتگو با دستیار ←',
    }] : []),
    ...(hasParts ? [{
      href: `${base}/parts`,
      icon: 'parts',
      title: 'کاتالوگ قطعات یدکی',
      sub: `OEM EPC / ${partsRoot?.frames?.length || 1} CONFIG`,
      go: 'ورود به کاتالوگ ←',
    }] : []),
    ...nodes.map((node, i) => ({
      href: buildNodeHref(brand, year, model, [node.title]),
      icon: iconFor(node.title, i),
      title: node.title,
      go: 'ورود به مستند ←',
    })),
  ];

  return (
    <DashboardShell>
      <div className="topbar">
        <Breadcrumb brand={brand} year={year} model={model} />
        {hasManual && <SearchBox brand={brand} year={year} model={model} />}
        <UserChip />
      </div>
      <h1 className="page-title">{model} {year}</h1>
      <div className="page-sub">// VEHICLE_DOCUMENTS</div>
      {/* Every system in the manual has its own SST page; this merges all of
          them into one deduplicated tool list for the whole vehicle, which no
          single page in the tree can show. Same download mechanics as the
          Labor Times CSV: the kg_portal_token cookie rides the top-level
          navigation, so no client-side token handling is needed. */}
      {hasSst && (
        <a
          href={sstCsvUrl(brand, year, model)}
          download
          className="back-link"
          style={{
            display: 'inline-flex', alignItems: 'center', gap: '0.5rem',
            margin: '0.25rem 0 1rem', padding: '0.5rem 0.9rem',
            border: '1px solid var(--border, #3a3a3a)', borderRadius: '8px',
            fontSize: '0.9rem', textDecoration: 'none', width: 'fit-content',
          }}
        >
          <span aria-hidden="true">⭳</span>
          دانلود فهرست ابزار مخصوص (SST)
        </a>
      )}
      {classic ? (
        <CardGrid items={items} />
      ) : (
        <CarBrowser brand={brand} year={year} model={model} currentPath={[]}>
          <CardGrid items={items} />
        </CarBrowser>
      )}
    </DashboardShell>
  );
}
