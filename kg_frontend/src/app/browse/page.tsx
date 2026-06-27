// app/browse/page.js — dashboard fleet view (real cars)
import DashboardShell from '@/components/DashboardShell';
import FleetView from '@/components/FleetView';
import { fetchAllBrands, fetchBrands } from '@/utils/api';

// Data comes from the backend at request time — never prerender at build
// (the backend is not reachable during `next build` / Docker image build).
export const dynamic = 'force-dynamic';

export default async function Browse() {
  const brands = await fetchAllBrands();
  const nested = await Promise.all(brands.map((b: string) => fetchBrands(b)));
  const cars = nested.flat();

  return (
    <DashboardShell>
      <div className="topbar">
        <div className="breadcrumb"><b>خودروهای فعال</b></div>
        <div className="userchip"><div className="avatar">۰۱</div> شرکت خدمات گستر سپهر گیتی</div>
      </div>
      <h1 className="page-title">پنل دسترسی به مستندات فنی</h1>
      <div className="page-sub">// ACTIVE_VEHICLE_ACCESS.LIST</div>
      <FleetView cars={cars} />
    </DashboardShell>
  );
}
