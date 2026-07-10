// app/[brand]/[year]/[model]/page/[file]/page.js
// Renders a raw manual page that has no node of its own (an orphan
// cross-link target, e.g. "Labor Times: Other Variant"). Served straight
// from the car's source folder by the backend's ?page= endpoint.
import { redirect } from 'next/navigation';
import { fetchRawPage } from '@/utils/api';
import { portalTokenCookie } from '@/utils/serverAuth';
import UserChip from '@/components/UserChip';
import DashboardShell from '@/components/DashboardShell';
import Breadcrumb from '@/components/Breadcrumb';
import ContentRenderer from '@/components/ContentRenderer';

export default async function RawPage({ params }) {
  const raw = await params;
  const brand = decodeURIComponent(raw.brand);
  const year = raw.year;
  const model = decodeURIComponent(raw.model);
  const file = decodeURIComponent(raw.file);

  const token = await portalTokenCookie();
  if (!token) redirect('/login');

  let page = null;
  let error = null;
  try {
    page = await fetchRawPage(brand, year, model, file, token);
  } catch (err) {
    if (err?.status === 401) redirect('/login');
    else if (err?.status === 403) error = 'دسترسی به مستندات این خودرو در اشتراک شما نیست.';
    else error = err.message;
  }

  return (
    <DashboardShell>
      <div className="topbar">
        <Breadcrumb brand={brand} year={year} model={model} path={[page?.title || file]} />
        <UserChip />
      </div>
      <h1 className="page-title">{page?.title || file}</h1>
      <div className="page-sub">// DOCUMENT_VIEW</div>

      {page?.content ? (
        <ContentRenderer content={page.content} brand={brand} year={year} model={model} />
      ) : (
        <div className="error-box">
          <p>این صفحه یافت نشد{error ? `: ${error}` : ''}.</p>
          <a href={`/${encodeURIComponent(brand)}/${year}/${encodeURIComponent(model)}`} className="back-link">← بازگشت</a>
        </div>
      )}
    </DashboardShell>
  );
}
