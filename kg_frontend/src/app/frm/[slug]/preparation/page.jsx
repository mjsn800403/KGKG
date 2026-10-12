// /frm/<slug>/preparation — the two reference sheets behind the LTS codes.
import CardGrid from '@/components/CardGrid';
import FrmShell from '@/components/FrmShell';
import { loadFrm } from '@/utils/frmServer';

export default async function FrmPreparation({ params }) {
  const { slug } = await params;
  const { set, error } = await loadFrm(slug, 'op_types');
  const base = `/frm/${slug}/preparation`;
  return (
    <FrmShell set={set} error={error} trail={[{ label: 'Preparation', href: '/preparation' }]} title="Preparation">
      <CardGrid items={[
        { href: `${base}/operations`, icon: 'gear', title: 'Type of operation', sub: 'R&R, ADJ, OTH, …', go: 'مشاهده ←' },
        { href: `${base}/models`, icon: 'car', title: 'Car model', sub: 'AAAAG, BAAAG, …', go: 'مشاهده ←' },
      ]} />
    </FrmShell>
  );
}
