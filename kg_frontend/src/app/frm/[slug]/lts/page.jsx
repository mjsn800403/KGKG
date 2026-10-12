// /frm/<slug>/lts — the full labor-time standards sheet, filterable.
import FrmShell from '@/components/FrmShell';
import FrmTable from '@/components/FrmTable';
import { loadFrm } from '@/utils/frmServer';

const FILTERS = [
  { column: 'Year', label: 'سال' },
  { column: 'Category', label: 'دسته' },
  { column: 'Section', label: 'بخش' },
  { column: 'Type', label: 'نوع عملیات' },
];

export default async function FrmLts({ params }) {
  const { slug } = await params;
  const { set, data, error } = await loadFrm(slug);
  // Hover an Hours(<code>) header to see which trim the code is.
  const headTitles = {};
  (data?.car_models?.rows || []).forEach((r) => {
    const [, code, model, engine] = r;
    if (code) headTitles[`Hours(${code})`] = `${model} — ${engine}`;
  });
  return (
    <FrmShell set={set} error={error} title="LTS" sub="ساعت استاندارد هر عملیات به تفکیک کد مدل خودرو"
      trail={[{ label: 'LTS', href: '/lts' }]}>
      {data && <FrmTable columns={data.lts.columns} rows={data.lts.rows} filters={FILTERS} headTitles={headTitles} hideEmpty />}
    </FrmShell>
  );
}
