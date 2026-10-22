// /frm/<slug>/preparation/models — car-model codes used as LTS hour columns.
import FrmShell from '@/components/FrmShell';
import FrmTable from '@/components/FrmTable';
import { loadFrm } from '@/utils/frmServer';
import { sealProp } from '@/utils/shieldServer';

export default async function FrmModels({ params }) {
  const { slug } = await params;
  const { set, data, error, token } = await loadFrm(slug, 'car_models');
  return (
    <FrmShell set={set} error={error} title="Car model"
      trail={[{ label: 'Preparation', href: '/preparation' }, { label: 'Car model', href: '/preparation/models' }]}>
      {data && <FrmTable columns={data.car_models.columns} {...sealProp(token, 'rows', data.car_models.rows)} />}
    </FrmShell>
  );
}
