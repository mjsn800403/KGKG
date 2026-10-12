// /frm/<slug> — flat-rate manual hub: LTS (hours table) and Preparation.
import CardGrid from '@/components/CardGrid';
import FrmShell from '@/components/FrmShell';
import { FRM_TITLE } from '@/utils/frmSets';
import { loadFrm } from '@/utils/frmServer';

export default async function FrmHub({ params }) {
  const { slug } = await params;
  // Small sheet only: proves login + access before showing the hub.
  const { set, error } = await loadFrm(slug, 'op_types');
  const base = `/frm/${slug}`;
  return (
    <FrmShell set={set} error={error} title={`${set.family} · ${FRM_TITLE}`}
      sub={`${set.brand.toUpperCase()} / ${set.years.join('، ')}`}>
      <CardGrid items={[
        { href: `${base}/lts`, icon: 'clock', title: 'LTS', sub: 'Labor Time Standards', go: 'مشاهده جدول ←' },
        { href: `${base}/preparation`, icon: 'wrench', title: 'Preparation', sub: 'Type of operation · Car model', go: 'ورود ←' },
      ]} />
    </FrmShell>
  );
}
