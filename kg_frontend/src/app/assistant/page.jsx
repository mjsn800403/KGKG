// app/assistant — car picker for the smart assistant. The assistant now lives
// INSIDE each car (the customer picks the vehicle first, then diagnoses faults /
// asks repair questions scoped to that car). This page just routes there.
import DashboardShell from '@/components/DashboardShell';
import UserChip from '@/components/UserChip';
import VehicleCardGrid from '@/components/VehicleCardGrid';
import ActivityBeacon from '@/components/ActivityBeacon';
import { fetchAllBrands, fetchBrands } from '@/utils/api';

export const metadata = {
  title: 'دستیار هوشمند | KGtechvault',
};

// Depends on live backend data (the car list) — render on request, never
// statically prerender at build time (when the backend isn't running).
export const dynamic = 'force-dynamic';

export default async function AssistantPickerPage() {
  const brands = await fetchAllBrands();
  const nested = await Promise.all(brands.map((b) => fetchBrands(b)));
  const cars = nested.flat();

  return (
    <DashboardShell>
      <div className="topbar">
        <div className="breadcrumb"><b>دستیار هوشمند</b></div>
        <UserChip />
      </div>
      <h1 className="page-title">دستیار هوشمند سرویس</h1>
      <div className="page-sub">{'// اول خودرو را انتخاب کن، بعد عیب را بگو یا کد خطا را وارد کن'}</div>
      <ActivityBeacon action="open_assistant" detail="ورود به دستیار هوشمند" />
      <VehicleCardGrid vehicles={cars} hrefSuffix="/assistant" go="دستیار این خودرو ←" />
    </DashboardShell>
  );
}
