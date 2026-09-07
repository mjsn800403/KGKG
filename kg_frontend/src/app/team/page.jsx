// app/team/page.jsx — org-graph canvas (n8n-style). The graph is the org
// structure; only the root-seat occupant (company super-admin) can edit.
import DashboardShell from '@/components/DashboardShell';
import UserChip from '@/components/UserChip';
import OrgGraphCanvas from '@/components/OrgGraphCanvas';

export default function TeamPage() {
  return (
    <DashboardShell>
      <div className="topbar">
        <div className="breadcrumb"><b>تیم و کارکنان</b></div>
        <UserChip />
      </div>
      <h1 className="page-title">ساختار سازمانی</h1>
      <div className="page-sub">// ORG_GRAPH</div>
      <OrgGraphCanvas />
    </DashboardShell>
  );
}
