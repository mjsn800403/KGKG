// app/browse/page.js — dashboard fleet view (live grants from backend)
import DashboardShell from '@/components/DashboardShell';
import UserChip from '@/components/UserChip';
import FleetView from '@/components/FleetView';

export default function Browse() {
  return (
    <DashboardShell>
      <div className="topbar">
        <div className="breadcrumb"><b>خودروهای فعال</b></div>
        <UserChip />
      </div>
      <h1 className="page-title">پنل دسترسی به مستندات فنی</h1>
      <div className="page-sub">// ACTIVE_VEHICLE_ACCESS.LIST</div>
      <FleetView />
    </DashboardShell>
  );
}
