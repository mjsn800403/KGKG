// app/team/analytics/page.jsx — company usage analytics (manager / analytics cap).
import DashboardShell from '@/components/DashboardShell';
import UserChip from '@/components/UserChip';
import AnalyticsView from '@/components/AnalyticsView';

export default function TeamAnalyticsPage() {
  return (
    <DashboardShell>
      <div className="topbar">
        <div className="breadcrumb"><b>تحلیل و گزارش‌ها</b></div>
        <UserChip />
      </div>
      <h1 className="page-title">تحلیل استفاده کارکنان</h1>
      <div className="page-sub">// USAGE_ANALYTICS</div>
      <AnalyticsView />
    </DashboardShell>
  );
}
