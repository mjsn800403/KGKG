// Public purchase page — packages, comparison, FAQ, and order form.
import PurchasePageContent from '@/components/PurchasePageContent';
import { fetchAllBrands, fetchBrands } from '@/utils/api';

export const dynamic = 'force-dynamic';

export default async function Purchase() {
  let cars = [];
  try {
    const brands = await fetchAllBrands();
    const nested = await Promise.all(brands.map((b: string) => fetchBrands(b)));
    cars = nested.flat();
  } catch {
    cars = [];
  }

  return (
    <div className="screen fade" id="purchase-public">
      <main className="main purchase-main purchase-main--compact">
        <PurchasePageContent cars={cars} />
      </main>
    </div>
  );
}
