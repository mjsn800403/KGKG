// app/assistant — car picker for the smart assistant. The assistant now lives
// INSIDE each car (the customer picks the vehicle first, then diagnoses faults /
// asks repair questions scoped to that car). This page just routes there.
import { redirect } from 'next/navigation';
import { portalTokenCookie } from '@/utils/serverAuth';
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

const BACKEND_URL = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

export default async function AssistantPickerPage() {
  const token = await portalTokenCookie();
  if (!token) redirect('/login');
  const meRes = await fetch(`${BACKEND_URL}/api/auth/me/`, {
    headers: { Authorization: `Bearer ${token}` }, cache: 'no-store',
  }).catch(() => null);
  if (!meRes || !meRes.ok) redirect('/login');
  const me = await meRes.json().catch(() => ({}));
  if (!me?.user?.ai_eligible) {
    return (
      <DashboardShell>
        <div className="topbar">
          <div className="breadcrumb"><b>دستیار هوشمند</b></div>
          <UserChip />
        </div>
        <h1 className="page-title">دستیار هوشمند سرویس</h1>
        <div className="empty-state">
          دستیار هوش مصنوعی برای حساب شما فعال نیست. برای فعال‌سازی با مدیر شرکت یا پشتیبانی تماس بگیرید.
        </div>
      </DashboardShell>
    );
  }
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
      <div className="page-sub">ابتدا خودرو را انتخاب کنید، سپس علامت یا کد خطا را بنویسید.</div>
      <ActivityBeacon action="open_assistant" detail="ورود به دستیار هوشمند" />
      <VehicleCardGrid vehicles={cars} hrefSuffix="/assistant" go="دستیار این خودرو ←" />
    </DashboardShell>
  );
}
