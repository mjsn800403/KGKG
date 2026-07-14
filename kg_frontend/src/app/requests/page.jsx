// app/requests/page.jsx — company requests (manager-gated): file a request and
// watch its status update in real time as the platform admin actions it.
import DashboardShell from '@/components/DashboardShell';
import UserChip from '@/components/UserChip';
import RequestsView from '@/components/RequestsView';

export default function RequestsPage() {
  return (
    <DashboardShell>
      <div className="topbar">
        <div className="breadcrumb"><b>درخواست‌های شرکت</b></div>
        <UserChip />
      </div>
      <RequestsView />
    </DashboardShell>
  );
}
