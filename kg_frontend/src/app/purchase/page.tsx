// app/purchase/page.tsx — legal-entity documentation purchase request form.
import DashboardShell from '@/components/DashboardShell';
import PurchaseForm from '@/components/PurchaseForm';
import { fetchAllBrands, fetchBrands } from '@/utils/api';

// Catalog changes over time; the brand/model typeahead must reflect live data.
export const dynamic = 'force-dynamic';

export default async function Purchase() {
  // Best-effort catalog for typeahead suggestions — the form still works (as
  // free text) even if the backend is unreachable.
  let cars: unknown[] = [];
  try {
    const brands = await fetchAllBrands();
    const nested = await Promise.all(brands.map((b: string) => fetchBrands(b)));
    cars = nested.flat();
  } catch {
    cars = [];
  }

  return (
    <DashboardShell>
      <div className="topbar">
        <div className="breadcrumb"><b>درخواست خرید مستندات</b></div>
        <div className="userchip"><div className="avatar">۰۱</div> شرکت خدمات گستر سپهر گیتی</div>
      </div>
      <h1 className="page-title">درخواست خرید مستندات فنی</h1>
      <div className="page-sub">// PURCHASE_REQUEST</div>
      <PurchaseForm cars={cars} />
    </DashboardShell>
  );
}
