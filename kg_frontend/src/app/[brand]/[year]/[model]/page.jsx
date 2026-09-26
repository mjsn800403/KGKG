// app/[brand]/[year]/[model]/page.js — vehicle view (real root documents)
import { redirect } from 'next/navigation';
import {
  fetchModels, fetchPartsRoot, buildNodeHref, sstCsvUrl, fetchSstAvailable,
  fetchVehicleSpec,
} from '@/utils/api';
import { portalTokenCookie, browseModeCookie } from '@/utils/serverAuth';
import UserChip from '@/components/UserChip';
import DashboardShell from '@/components/DashboardShell';
import Breadcrumb from '@/components/Breadcrumb';
import CardGrid from '@/components/CardGrid';
import CarBrowser from '@/components/CarBrowser';
import SearchBox from '@/components/SearchBox';
import VehicleCover from '@/components/VehicleCover';
import { friendlyError } from '@/lib/friendlyError';

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
  const [manualRes, partsRes, sstRes, specRes] = await Promise.allSettled([
    // Raw year segment on purpose: parseInt turns a legacy 'unknown' year into
    // NaN; the backend resolves the car by brand+name when the year mismatches.
    fetchModels(brand, year, model, token),
    fetchPartsRoot(brand, year, model, token),
    fetchSstAvailable(brand, year, model, token),
    fetchVehicleSpec(brand, year, model, token),
  ]);
  const spec = specRes.status === 'fulfilled' ? specRes.value : null;
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
      loadError = friendlyError(reasons[0], 'بارگذاری مستندات این خودرو ناموفق بود.');
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
  // These tools sit in the cover's tool row; the grid below holds only the
  // manual's own sections.
  const tools = [
    ...(hasManual ? [{
      href: `${base}/assistant`, icon: 'bot', primary: true,
      title: 'دستیار هوشمند', sub: 'عیب‌یابی از علائم یا کد خطا',
    }] : []),
    ...(hasParts ? [{
      href: `${base}/parts`, icon: 'parts',
      title: 'کاتالوگ قطعات',
      sub: `${(partsRoot?.frames?.length || 1).toLocaleString('fa-IR')} پیکربندی`,
    }] : []),
    // Every system in the manual has its own SST page; this merges all of them
    // into one deduplicated tool list for the whole vehicle. The
    // kg_portal_token cookie rides the top-level navigation.
    ...(hasSst ? [{
      href: sstCsvUrl(brand, year, model), icon: 'download', download: true,
      title: 'ابزار مخصوص (SST)', sub: 'دانلود فهرست کامل',
    }] : []),
  ];
  const items = nodes.map((node, i) => ({
    href: buildNodeHref(brand, year, model, [node.title]),
    icon: iconFor(node.title, i),
    title: node.title,
    go: 'ورود به مستند ←',
  }));
  const sections = (
    <>
      {items.length > 0 && <h2 className="section-label">بخش‌های مستندات</h2>}
      {items.length > 0 ? <CardGrid items={items} /> : null}
    </>
  );
  // A parts-only vehicle has no manual tree to browse: its one way in is the
  // catalog, shown as a card instead of an empty contents sidebar.
  const partsOnly = !hasManual && hasParts;

  return (
    <DashboardShell>
      <div className="topbar">
        <Breadcrumb brand={brand} year={year} model={model} />
        {hasManual && <SearchBox brand={brand} year={year} model={model} />}
        <UserChip />
      </div>
      <VehicleCover brand={brand} year={year} model={model} spec={spec} tools={tools} />
      {partsOnly ? (
        <CardGrid items={[{
          href: `${base}/parts`, icon: 'parts', title: 'کاتالوگ قطعات یدکی',
          sub: `${(partsRoot?.frames?.length || 1).toLocaleString('fa-IR')} پیکربندی`, go: 'ورود به کاتالوگ ←',
        }]} />
      ) : classic ? sections : (
        <CarBrowser brand={brand} year={year} model={model} currentPath={[]}>
          {sections}
        </CarBrowser>
      )}
    </DashboardShell>
  );
}
