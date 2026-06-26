// app/[brand]/[year]/[model]/assistant — the per-car smart assistant.
// The customer selects a car first, then lands here; the chat is scoped to this
// vehicle (its DTC / symptom diagnostic index + manual), so answers and links
// are about THIS car.
import DashboardShell from '@/components/DashboardShell';
import Breadcrumb from '@/components/Breadcrumb';
import SearchBox from '@/components/SearchBox';
import AssistantChat from '@/components/AssistantChat';

export default async function CarAssistantPage({ params }) {
  const raw = await params;
  const brand = decodeURIComponent(raw.brand);
  const year = raw.year;
  const model = decodeURIComponent(raw.model);

  return (
    <DashboardShell>
      <div className="topbar">
        <Breadcrumb brand={brand} year={year} model={model} path={['دستیار هوشمند']} />
        <SearchBox brand={brand} year={year} model={model} />
        <div className="userchip"><div className="avatar">۰۱</div> شرکت خدمات گستر سپهر گیتی</div>
      </div>
      <h1 className="page-title">دستیار هوشمند — {model} {year}</h1>
      <div className="page-sub">// AI_DIAGNOSTIC_ASSISTANT</div>
      <AssistantChat brand={brand} year={year} model={model} car={model} />
    </DashboardShell>
  );
}
