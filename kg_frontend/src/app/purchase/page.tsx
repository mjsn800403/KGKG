// Public plans & ordering page: pick a duration and team size, see the
// estimated price, and file a purchase request for the sales team.
import type { Metadata } from 'next';
import { initialSelection } from '@/lib/pricing';
import PlansPage from './PlansPage';

export const metadata: Metadata = {
  title: 'پلن‌ها و قیمت | KGTechVault',
  description: 'اشتراک ۲ روزه، ماهانه یا سالانهٔ KGTechVault: دسترسی به همهٔ خودروها و مستندات فنی، همراه با دستیار هوشمند و مدیریت تیم.',
};

export default async function Purchase({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { plan, seats } = initialSelection(await searchParams) as { plan: 'pass' | 'monthly' | 'annual'; seats: number };
  return <PlansPage initialPlan={plan} initialSeats={seats} />;
}
