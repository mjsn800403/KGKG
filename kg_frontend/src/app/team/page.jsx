// app/team/page.jsx — company self-service team management (manager-gated).
import DashboardShell from '@/components/DashboardShell';
import UserChip from '@/components/UserChip';
import TeamView from '@/components/TeamView';

export default function TeamPage() {
  return (
    <DashboardShell>
      <div className="topbar">
        <div className="breadcrumb"><b>تیم و کارکنان</b></div>
        <UserChip />
      </div>
      <h1 className="page-title">مدیریت کارکنان شرکت</h1>
      <div className="page-sub">// TEAM_MANAGEMENT</div>
      <TeamView />
    </DashboardShell>
  );
}
