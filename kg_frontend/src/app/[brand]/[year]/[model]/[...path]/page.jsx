// app/[brand]/[year]/[model]/[[...path]]/page.js
import { redirect } from 'next/navigation';
import {
  fetchNodes, fetchSubtree, buildNodeHref, urlToSeg, laborTimesCsvUrl, FLATTEN_MAX,
} from '@/utils/api';
import { portalTokenCookie, browseModeCookie } from '@/utils/serverAuth';
import UserChip from '@/components/UserChip';
import DashboardShell from '@/components/DashboardShell';
import Breadcrumb from '@/components/Breadcrumb';
import CardGrid from '@/components/CardGrid';
import StackedContent from '@/components/StackedContent';
import ContentRenderer from '@/components/ContentRenderer';
import CarBrowser from '@/components/CarBrowser';
import SearchBox from '@/components/SearchBox';
import ActivityBeacon from '@/components/ActivityBeacon';

const ICONS = ['▣', '⌖', '◷', '⚙', '◧', '◩', '⬡', '⊞'];

export default async function NodePage({ params }) {
  const raw = await params;
  const brand = decodeURIComponent(raw.brand);
  const year = raw.year;
  const model = decodeURIComponent(raw.model);
  const pathArray = (raw.path || []).map((s) => urlToSeg(decodeURIComponent(s)));

  // Paid content: must be signed in (token in the SSR cookie). No token -> login.
  const token = await portalTokenCookie();
  if (!token) redirect('/login');

  // Classic mode = the original card-by-card drill-down, no sidebar and no
  // subtree flattening. Modern mode = sidebar tree + adaptive flatten.
  const classic = (await browseModeCookie()) === 'classic';

  const inLaborTimes = pathArray[0] === 'Labor Times';
  const laborCsvHref = laborTimesCsvUrl(brand, year, model);

  // Adaptive flatten: try to stack this node's whole subtree onto one page. The
  // backend returns mode 'stack' when the subtree is small enough, or mode
  // 'cards' (no bodies) when it's too big to render at once — in which case we
  // fetch this node's immediate children and show a drill-down index instead.
  let subtree = null;
  let nodes = [];
  let error = null;
  let denied = false;

  try {
    if (classic) {
      nodes = await fetchNodes(brand, year, model, pathArray, token);
    } else {
      subtree = await fetchSubtree(brand, year, model, pathArray, token, FLATTEN_MAX);
      if (subtree?.mode !== 'stack') {
        nodes = await fetchNodes(brand, year, model, pathArray, token);
      }
    }
  } catch (err) {
    if (err?.status === 401) redirect('/login');
    else if (err?.forbidden) denied = true;
    else { console.error('Error fetching content:', err); error = err.message; }
  }

  const currentTitle = pathArray.length ? pathArray[pathArray.length - 1] : model;

  if (denied) {
    return (
      <DashboardShell>
        <div className="topbar">
          <Breadcrumb brand={brand} year={year} model={model} path={pathArray} />
          <UserChip />
        </div>
        <h1 className="page-title">دسترسی محدود</h1>
        <div className="error-box">
          <p>دسترسی به مستندات این خودرو در اشتراک شما نیست. برای افزودن این خودرو با مدیر یا پشتیبانی تماس بگیرید.</p>
          <a href="/browse" className="back-link">← بازگشت به خودروهای فعال</a>
        </div>
      </DashboardShell>
    );
  }

  if (error) {
    return (
      <DashboardShell>
        <div className="topbar">
          <Breadcrumb brand={brand} year={year} model={model} path={pathArray} />
          <SearchBox brand={brand} year={year} model={model} />
          <UserChip />
        </div>
        <h1 className="page-title">خطا</h1>
        <div className="error-box">
          <p>بارگذاری محتوا ناموفق بود: {error}</p>
          <a href={`/${encodeURIComponent(brand)}/${year}/${encodeURIComponent(model)}`} className="back-link">← بازگشت</a>
        </div>
      </DashboardShell>
    );
  }

  const stacked = subtree?.mode === 'stack';

  let body;
  let mode;
  if (stacked) {
    mode = 'STACKED_VIEW';
    body = <StackedContent payload={subtree} brand={brand} year={year} model={model} />;
  } else if ((nodes || []).length === 1 && nodes[0].content != null) {
    // A resolved leaf: car_view returns the content node itself as a
    // single-element list (any node with content short-circuits the children
    // query). It is NOT a child to link into — carding it would build a
    // self-referential .../X/X URL that 404s. Render its content directly.
    mode = 'LEAF_VIEW';
    body = (
      <ContentRenderer content={nodes[0].content} brand={brand} year={year} model={model} />
    );
  } else {
    mode = 'SECTION_INDEX';
    const items = (nodes || []).map((node, i) => ({
      href: buildNodeHref(brand, year, model, [...pathArray, node.title]),
      icon: ICONS[i % ICONS.length],
      title: node.title,
      go: 'ورود به مستند ←',
    }));
    body = <CardGrid items={items} />;
  }

  return (
    <DashboardShell>
      <div className="topbar">
        <Breadcrumb brand={brand} year={year} model={model} path={pathArray} />
        <SearchBox brand={brand} year={year} model={model} />
        <UserChip />
      </div>
      <h1 className="page-title">{currentTitle}</h1>
      <div className="page-sub">// {mode}</div>
      {inLaborTimes && (
        <a
          href={laborCsvHref}
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
          دانلود گزارش CSV زمان‌های کارکرد
        </a>
      )}
      <ActivityBeacon
        action={stacked ? 'view_node' : 'view_section'}
        detail={`${model} — ${currentTitle}`}
        segments={pathArray}
        nodeTitle={currentTitle}
        appUrl={buildNodeHref(brand, year, model, pathArray)}
        brand={brand}
        year={String(year)}
        model={model}
      />
      {classic ? body : (
        <CarBrowser brand={brand} year={year} model={model} currentPath={pathArray}>
          {body}
        </CarBrowser>
      )}
    </DashboardShell>
  );
}
