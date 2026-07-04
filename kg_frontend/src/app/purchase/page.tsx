// app/purchase/page.tsx — PUBLIC purchase/demo request page, reached from the
// landing page (deliberately NOT part of the logged-in dashboard: buying and
// requesting a demo happen before any account exists).
import Link from 'next/link';
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
    <div className="screen fade" id="purchase-public">
      <main className="main" style={{ maxWidth: 920, margin: '0 auto', padding: '32px 20px' }}>
        <div className="topbar">
          <div className="breadcrumb">
            <Link href="/" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              → بازگشت به صفحه اصلی
            </Link>
          </div>
          <div className="userchip"><div className="avatar">KG</div> KGTECHVAULT Company</div>
        </div>
        <h1 className="page-title">درخواست خرید مستندات فنی</h1>
        <div className="page-sub">// PURCHASE_REQUEST — ثبت درخواست خرید یا نسخه دمو</div>
        <PurchaseForm cars={cars} />
      </main>
    </div>
  );
}
