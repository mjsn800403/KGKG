// app/[brand]/[year]/[model]/[[...path]]/page.js
import { fetchNodes } from '@/utils/api';
import DashboardShell from '@/components/DashboardShell';
import Breadcrumb from '@/components/Breadcrumb';
import CardGrid from '@/components/CardGrid';
import ContentRenderer from '@/components/ContentRenderer';

const ICONS = ['▣', '⌖', '◷', '⚙', '◧', '◩', '⬡', '⊞'];

export default async function NodePage({ params }) {
  const raw = await params;
  const brand = decodeURIComponent(raw.brand);
  const year = raw.year;
  const model = decodeURIComponent(raw.model);
  const pathArray = (raw.path || []).map(decodeURIComponent);

  let nodes = [];
  let error = null;

  try {
    nodes = await fetchNodes(brand, parseInt(year), model, pathArray);
  } catch (err) {
    console.error('Error fetching nodes:', err);
    error = err.message;
  }

  const isLeafWithContent =
    nodes && nodes.length === 1 && nodes[0]?.content &&
    (!nodes[0]?.children || nodes[0].children.length === 0);

  const currentTitle = pathArray.length ? pathArray[pathArray.length - 1] : model;

  if (error) {
    return (
      <DashboardShell>
        <div className="topbar">
          <Breadcrumb brand={brand} year={year} model={model} path={pathArray} />
          <div className="userchip"><div className="avatar">۰۱</div> شرکت خدمات گستر سپهر گیتی</div>
        </div>
        <h1 className="page-title">خطا</h1>
        <div className="error-box">
          <p>بارگذاری محتوا ناموفق بود: {error}</p>
          <p>لطفاً مطمئن شوید سرور بک‌اند روی http://127.0.0.1:8000 در حال اجراست.</p>
          <a href={`/${encodeURIComponent(brand)}/${year}/${encodeURIComponent(model)}`} className="back-link">← بازگشت</a>
        </div>
      </DashboardShell>
    );
  }

  const items = (nodes || []).map((node, i) => ({
    href: `/${encodeURIComponent(brand)}/${year}/${encodeURIComponent(model)}/${[...pathArray, node.title].map(encodeURIComponent).join('/')}`,
    icon: ICONS[i % ICONS.length],
    title: node.title,
    go: 'ورود به مستند ←',
  }));

  return (
    <DashboardShell>
      <div className="topbar">
        <Breadcrumb brand={brand} year={year} model={model} path={pathArray} />
        <div className="userchip"><div className="avatar">۰۱</div> شرکت خدمات گستر سپهر گیتی</div>
      </div>
      <h1 className="page-title">{currentTitle}</h1>
      <div className="page-sub">// {isLeafWithContent ? 'DOCUMENT_VIEW' : 'SECTION_INDEX'}</div>

      {isLeafWithContent ? (
        <ContentRenderer content={nodes[0].content} brand={brand} year={year} model={model} />
      ) : (
        <CardGrid items={items} />
      )}
    </DashboardShell>
  );
}
