// Vehicle "cover page": what this car is (facts from its schema.org VehicleSpec),
// what you can do with it (assistant, parts catalog, SST list) and the service
// capacities table. Everything shown is read from stored data; a field the spec
// does not carry is simply left out, never guessed.
import Link from 'next/link';
import Icon from './Icon';

const BODY = {
  'Crossover SUV': 'کراس‌اوور شاسی‌بلند', SUV: 'شاسی‌بلند', 'Pickup Truck': 'وانت',
  Sedan: 'سدان', Hatchback: 'هاچ‌بک', Minivan: 'مینی‌ون', Coupe: 'کوپه',
};
const FUEL = {
  Gasoline: 'بنزینی', 'Gasoline/Electric Hybrid': 'هیبرید (بنزین/برق)',
  Electric: 'تمام‌برقی', 'Hydrogen (fuel cell)': 'هیدروژنی (پیل سوختی)',
};
const GEARBOX = { Automatic: 'اتوماتیک', Manual: 'دستی' };
const DRIVE = {
  FourWheelDriveConfiguration: ['چهارچرخ محرک', '4WD'],
  AllWheelDriveConfiguration: ['تمام‌چرخ محرک', 'AWD'],
  FrontWheelDriveConfiguration: ['دیفرانسیل جلو', 'FWD'],
  RearWheelDriveConfiguration: ['دیفرانسیل عقب', 'RWD'],
};
// Service-capacity rows, in the order a technician reads them.
const FLUIDS = [
  ['Engine Oil', 'روغن موتور'],
  ['Engine Coolant', 'مایع خنک‌کننده'],
  ['Automatic Transmission Fluid', 'روغن گیربکس اتوماتیک'],
  ['Manual Transmission Fluid', 'روغن گیربکس دستی'],
  ['Differential Gear Oil', 'روغن دیفرانسیل'],
  ['Transfer Case Fluid', 'روغن جعبه‌انتقال'],
  ['Brake Fluid', 'روغن ترمز'],
  ['Air Cond Refrigerant', 'گاز کولر'],
];

const AMOUNT_RE = /^[\d.]+\s*(L|KG)$/i;
const IMPERIAL_RE = /^(N\/A|[\d.]+\s*(QTS?\.?|LBS?\.?|GALS?\.?))$/i;

// "Drain and Refill,w/Filter ; 4.50 QTS. ; 4.25 L ; <fluid> ; <note> ; S"
// -> { qualifier, amount: '4.25 L', type, note }
export function parseCapacity(value) {
  const seg = String(value || '').split(' ; ').map((s) => s.trim()).filter(Boolean);
  if (seg[seg.length - 1] === 'S') seg.pop();
  const first = seg.findIndex((s) => IMPERIAL_RE.test(s) || AMOUNT_RE.test(s));
  if (first < 0) return null;
  // Some source rows carry a truncated condition ("Except For", "For Models")
  // that names nothing; drop those rather than show a dangling phrase.
  const qualifier = seg.slice(0, first).filter((q) => !/^(except\s+)?for(\s+models)?$/i.test(q)).join(', ');
  let i = first;
  let amount = '';
  while (i < seg.length && (IMPERIAL_RE.test(seg[i]) || AMOUNT_RE.test(seg[i]))) {
    if (AMOUNT_RE.test(seg[i])) amount = seg[i].replace(/\s+/, ' ');
    i += 1;
  }
  return { qualifier, amount, type: seg[i] || '', note: seg[i + 1] || '' };
}

function facts(spec) {
  if (!spec) return [];
  const out = [];
  const add = (label, fa, latin) => { if (fa || latin) out.push({ label, fa, latin }); };
  add('نوع بدنه', BODY[spec.bodyType] || '', BODY[spec.bodyType] ? '' : spec.bodyType);
  add('سوخت', FUEL[spec.fuelType] || '', FUEL[spec.fuelType] ? '' : spec.fuelType);
  if (spec.vehicleTransmission) {
    add('گیربکس', GEARBOX[spec.vehicleTransmission] || '', GEARBOX[spec.vehicleTransmission] ? '' : spec.vehicleTransmission);
  }
  const dw = spec.driveWheelConfiguration;
  const dwName = dw && typeof dw === 'object' ? dw.name : dw;
  if (DRIVE[dwName]) add('محور محرک', DRIVE[dwName][0], DRIVE[dwName][1]);
  const eng = spec.vehicleEngine;
  const disp = eng && typeof eng === 'object' ? eng.engineDisplacement : null;
  if (disp && disp.value != null) add('حجم موتور', '', `${disp.value} ${disp.unitText || 'L'}`);
  else if (eng?.engineType === 'Electric motor') add('پیشرانه', 'موتور الکتریکی', '');
  const fc = spec.fuelCapacity;
  if (fc && fc.value != null) add('حجم باک', '', `${fc.value} ${fc.unitText || 'L'}`);
  if (spec.numberOfDoors) add('تعداد در', String(spec.numberOfDoors).replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[d]), '');
  const tire = (spec.additionalProperty || []).find((p) => p.name === 'tireSize');
  if (tire?.value) add('سایز لاستیک', '', tire.value);
  return out;
}

function capacities(spec) {
  const props = spec?.additionalProperty || [];
  const rows = [];
  FLUIDS.forEach(([key, label]) => {
    props.filter((p) => p.name === key).forEach((p) => {
      const c = parseCapacity(p.value);
      if (c && (c.amount || c.type)) rows.push({ label, ...c });
    });
  });
  return rows;
}

export default function VehicleCover({ brand, year, model, spec, tools = [] }) {
  const list = facts(spec);
  const caps = capacities(spec);
  // The trim is only worth a line when the page title doesn't already say it.
  const config = spec?.vehicleConfiguration && !String(model).toLowerCase().includes(String(spec.vehicleConfiguration).toLowerCase())
    ? spec.vehicleConfiguration : '';

  return (
    <div className="vcover" role="region" aria-label="معرفی خودرو">
      <header className="vcover-head">
        <div className="vcover-id">
          <span className="vcover-kicker"><bdi dir="ltr">{String(brand).toUpperCase()} · {year}</bdi></span>
          <h1 className="page-title"><bdi dir="ltr">{model}</bdi></h1>
          {config && <span className="vcover-config">نسخه <bdi dir="ltr">{config}</bdi></span>}
        </div>
        {tools.length > 0 && (
          <nav className="vcover-tools" aria-label="ابزارهای این خودرو">
            {tools.map((t) => {
              const inner = (
                <>
                  <Icon name={t.icon} />
                  <span><b>{t.title}</b><small>{t.sub}</small></span>
                </>
              );
              const cls = `vtool${t.primary ? ' vtool-primary' : ''}`;
              return t.download ? (
                <a key={t.href} href={t.href} download className={cls}>{inner}</a>
              ) : (
                <Link key={t.href} href={t.href} className={cls}>{inner}</Link>
              );
            })}
          </nav>
        )}
      </header>

      {list.length > 0 && (
        <dl className="vcover-facts">
          {list.map((f) => (
            <div key={f.label}>
              <dt>{f.label}</dt>
              <dd>
                {f.fa}
                {f.fa && f.latin ? ' ' : ''}
                {f.latin && <bdi dir="ltr" className="vcover-latin">{f.latin}</bdi>}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {caps.length > 0 && (
        <details className="vcover-caps">
          <summary>
            <span>ظرفیت روغن‌ها و مایعات</span>
            <small>{caps.length.toLocaleString('fa-IR')} مورد · از جدول ظرفیت‌های مستندات همین خودرو</small>
          </summary>
          <div className="vcover-caps-scroll">
            <table>
              <thead>
                <tr><th>مورد</th><th>مقدار</th><th>مشخصه</th></tr>
              </thead>
              <tbody>
                {caps.map((c, i) => (
                  <tr key={`${c.label}${i}`}>
                    <td>
                      {c.label}
                      {c.qualifier && <small><bdi dir="ltr">{c.qualifier}</bdi></small>}
                    </td>
                    <td className="vcover-amt">{c.amount ? <bdi dir="ltr">{c.amount}</bdi> : '—'}</td>
                    <td className="vcover-type" title={c.note || undefined}>
                      <bdi dir="ltr">{c.type || '—'}</bdi>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="vcover-note">مقادیر، مرجع کارخانه‌اند. پیش از سرویس با دستورالعمل همان سیستم در مستندات تطبیق دهید.</p>
        </details>
      )}
    </div>
  );
}
