// /frm/<slug>/preparation/operations — operation-type codes (type of op sheet).
import FrmShell from '@/components/FrmShell';
import FrmTable from '@/components/FrmTable';
import { loadFrm } from '@/utils/frmServer';

export default async function FrmOperations({ params }) {
  const { slug } = await params;
  const { set, data, error } = await loadFrm(slug, 'op_types');
  return (
    <FrmShell set={set} error={error} title="Type of operation"
      trail={[{ label: 'Preparation', href: '/preparation' }, { label: 'Type of operation', href: '/preparation/operations' }]}>
      {data && <FrmTable columns={data.op_types.columns} rows={data.op_types.rows} />}
    </FrmShell>
  );
}
