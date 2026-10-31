// app/requests/page.jsx — the customer's side of the support desk. Open to any
// signed-in seat (it was manager-gated, which left everyone else with the
// telephone); file a ticket, hold the conversation, see the SLA state, and rate
// the resolution once it closes.
import DashboardShell from '@/components/DashboardShell';
import UserChip from '@/components/UserChip';
import RequestsView from '@/components/RequestsView';

export default function RequestsPage() {
  return (
    <DashboardShell>
      <div className="topbar">
        <div className="breadcrumb"><b>پشتیبانی و درخواست‌ها</b></div>
        <UserChip />
      </div>
      <RequestsView />
    </DashboardShell>
  );
}
