'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { AnimatePresence, motion, MotionConfig, useInView, useReducedMotion } from 'motion/react';
import Icon from '@/components/Icon';
import { ENGINE, MANUAL_CONFIGS_FLOOR, SPECIMEN, fa } from './landing-data';
import { BRAND_LINE, PLANS_HREF, L, Wordmark, HelpButton, ThemeButton, LoginButton, Footer } from './lp-shared';
import './landing.css';

// "Service Manual, Engineered" — see landing.css for the token system.
// Positioning: repair manuals → technical knowledge → diagnostics → repair
// procedures → intelligent documentation. Parts stay one layer, not the lead.
// Every value shown comes from landing-data.ts (read from production).

const REQUEST_HREF = PLANS_HREF;

const EASE = [0.22, 1, 0.36, 1] as const;
const VIEW = { once: true, amount: 0.25 } as const;
const reveal = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.42, ease: EASE } },
};
const stagger = { hidden: {}, show: { transition: { staggerChildren: 0.07 } } };

const CHAPTERS = [
  { id: 'docs', label: 'مستندات' },
  { id: 'assistant', label: 'دستیار هوشمند' },
  { id: 'coverage', label: 'پوشش' },
  { id: 'access', label: 'روند دسترسی' },
  { id: 'team', label: 'مدیریت تیم' },
  { id: 'request', label: 'خرید اشتراک' },
] as const;

/* ------------------------------------------------------------------------ */
/* Hero: repair-manual viewer on an inline-four engine. Tabs walk the real   */
/* ignition coil / spark plug pages of one engine.                           */
/* ------------------------------------------------------------------------ */
type TabKey = 'identify' | 'procedure' | 'torque' | 'diagnose' | 'caution';
const COILS = [180, 270, 360, 450]; // x centres, cylinder 4 → 1 (timing end on the right)

const TABS: { key: TabKey; label: string; icon: string }[] = [
  { key: 'identify', label: 'شناسایی', icon: 'search' },
  { key: 'procedure', label: 'باز و بست', icon: 'manual' },
  { key: 'torque', label: 'گشتاور', icon: 'wrench' },
  { key: 'diagnose', label: 'عیب‌یابی', icon: 'chart' },
  { key: 'caution', label: 'احتیاط', icon: 'shield' },
];

function EnginePanel({ tab }: { tab: TabKey }) {
  switch (tab) {
    case 'identify':
      return (
        <>
          <h3>مجموعهٔ کویل و شمع</h3>
          <p>چهار کویل روی درِ سرسیلندر نصب شده‌اند و هر کویل مستقیماً روی شمعِ همان سیلندر می‌نشیند.</p>
          <dl className="lp-kv">
            <div><dt><L>SPARK PLUG</L></dt><dd><L mono>{ENGINE.partCodes.plug}</L></dd></div>
            <div><dt><L>IGNITION COIL ASSEMBLY</L></dt><dd><L mono>{ENGINE.partCodes.coil}</L></dd></div>
          </dl>
        </>
      );
    case 'procedure':
      return (
        <>
          <h3>رویهٔ نصب</h3>
          <ol className="lp-steps-mini">
            <li>نصب چهار شمع روی سرسیلندر</li>
            <li>نصب کویل‌ها با آچار بکس <L mono>{ENGINE.coilSocket}</L> و اتصال کانکتورها</li>
            <li>اجرای مرحلهٔ <L>Initialization</L> و «بازرسی پس از تعمیر»</li>
          </ol>
          <p className="lp-panel-meta">زمان استاندارد تعویض شمع‌ها: <strong>{fa(ENGINE.laborHours)} ساعت</strong></p>
        </>
      );
    case 'torque':
      return (
        <>
          <h3>گشتاورهای مشخص‌شده</h3>
          <dl className="lp-kv">
            <div><dt>شمع × سرسیلندر</dt><dd><L mono>{ENGINE.plugTorque.nm}</L> <L mono className="lp-kv-alt">({ENGINE.plugTorque.alt})</L></dd></div>
            <div><dt>پیچ کویل</dt><dd><L mono>{ENGINE.coilTorque.nm}</L> <L mono className="lp-kv-alt">({ENGINE.coilTorque.alt})</L></dd></div>
          </dl>
        </>
      );
    case 'diagnose':
      return (
        <>
          <h3>کد خطا <L mono>{ENGINE.dtc.code}</L></h3>
          <p className="lp-panel-en"><L>{ENGINE.dtc.title}</L></p>
          <p>بدسوزی، غلظت هیدروکربن گاز خروجی را بالا می‌برد و می‌تواند به کاتالیست سه‌راهه آسیب بزند؛ به همین دلیل <L>ECM</L> تعداد بدسوزی‌ها را پایش می‌کند.</p>
        </>
      );
    case 'caution':
    default:
      return (
        <>
          <h3>نکات احتیاطی</h3>
          <ul className="lp-bullets">
            <li>شمع یا کویلی که ضربه خورده یا افتاده باشد، باید تعویض شود.</li>
            <li>این رویه شامل پیچ‌های سرکوچک است؛ پیش از نصب آن‌ها را شناسایی کنید.</li>
          </ul>
        </>
      );
  }
}

function EngineDrawing({ tab }: { tab: TabKey }) {
  const reduce = useReducedMotion();
  const draw = (i: number) =>
    reduce ? {} : {
      initial: { pathLength: 0, opacity: 0 },
      animate: { pathLength: 1, opacity: 1 },
      transition: { duration: 0.8, ease: EASE, delay: 0.1 + i * 0.06 },
    };
  const hot = (keys: TabKey[]) => (keys.includes(tab) ? ' is-hot' : '');
  const cyl1 = COILS[3];

  return (
    <svg viewBox="28 0 572 396" className="lp-drawing lp-engine" aria-hidden="true">
      <g className="lp-d-center">
        <line x1={96} y1={286} x2={600} y2={286} />
      </g>
      {/* block, head, cover, pan */}
      <motion.path className="lp-d-strong" d="M130 176 H510 V286 H130 Z" {...draw(0)} />
      <motion.path className="lp-d-strong" d="M118 126 H522 V176 H118 Z" {...draw(1)} />
      <motion.path className="lp-d-strong" d="M140 96 Q140 84 152 84 H488 Q500 84 500 96 V126 H140 Z" {...draw(2)} />
      <motion.path className="lp-d-strong" d="M146 286 H494 L478 334 Q474 344 462 344 H178 Q166 344 162 334 Z" {...draw(3)} />
      <motion.circle className="lp-d-thin" cx={446} cy={344} r={5} {...draw(3.5)} />
      {/* timing cover + pulleys (front of engine) */}
      <motion.path className="lp-d-strong" d="M522 110 H556 Q572 110 572 126 V304 Q572 322 556 322 H510 V286" {...draw(4)} />
      <motion.circle className="lp-d-thin" cx={548} cy={150} r={17} {...draw(5)} />
      <motion.circle className="lp-d-thin" cx={548} cy={290} r={23} {...draw(5.5)} />
      <motion.circle className="lp-d-thin" cx={548} cy={290} r={7} {...draw(6)} />
      <motion.path className="lp-d-hidden" d="M531 150 L525 290 M565 150 L571 290" {...draw(6.5)} />

      {/* cylinders + pistons (hidden lines) */}
      {COILS.map((x, i) => (
        <g key={`cyl${x}`} className={`lp-e-cyl${x === cyl1 ? hot(['diagnose']) : ''}`}>
          <motion.rect x={x - 34} y={184} width={68} height={94} rx={2} className="lp-d-hidden" {...draw(7 + i * 0.2)} />
          <rect x={x - 30} y={226} width={60} height={26} rx={2} className="lp-e-piston" />
        </g>
      ))}

      {/* spark plugs (hidden, in the head) */}
      {COILS.map((x) => (
        <g key={`plug${x}`} className={`lp-e-plug${hot(['identify', 'torque', 'procedure'])}`}>
          <rect x={x - 6} y={120} width={12} height={46} rx={2} />
          <line x1={x} y1={166} x2={x} y2={178} />
        </g>
      ))}

      {/* ignition coils on the cover */}
      {COILS.map((x, i) => (
        <motion.g
          key={`coil${x}`}
          className={`lp-e-coil${hot(['identify', 'procedure', 'torque', 'caution'])}${x === cyl1 && tab === 'diagnose' ? ' is-hot' : ''}`}
          animate={!reduce && tab === 'procedure' ? { y: [0, -10, 0] } : { y: 0 }}
          transition={{ duration: 1.1, ease: EASE, delay: i * 0.08 }}
        >
          <rect x={x - 17} y={30} width={34} height={62} rx={5} />
          <rect x={x - 11} y={18} width={22} height={14} rx={3} className="lp-e-conn" />
          <circle cx={x + 22} cy={84} r={5} className={`lp-e-bolt${hot(['torque'])}`} />
        </motion.g>
      ))}

      {/* tab-specific annotations */}
      <AnimatePresence mode="wait">
        {tab === 'torque' && (
          <motion.g key="t" className="lp-e-note" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <line x1={COILS[0] + 22} y1={84} x2={96} y2={54} />
            <text x={92} y={50} textAnchor="end" direction="ltr">{ENGINE.coilTorque.nm}</text>
            <line x1={COILS[0]} y1={150} x2={96} y2={206} />
            <text x={92} y={212} textAnchor="end" direction="ltr">{ENGINE.plugTorque.nm}</text>
          </motion.g>
        )}
        {tab === 'diagnose' && (
          <motion.g key="d" className="lp-e-note" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <line x1={cyl1} y1={236} x2={cyl1 - 70} y2={372} />
            <rect x={cyl1 - 140} y={358} width={120} height={28} rx={6} className="lp-e-tag" />
            <text x={cyl1 - 80} y={377} textAnchor="middle" direction="ltr">{ENGINE.dtc.code}</text>
          </motion.g>
        )}
        {tab === 'caution' && (
          <motion.g key="c" className="lp-e-note" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <path d="M320 4 L338 34 H302 Z" className="lp-e-warn" />
            <line x1={320} y1={15} x2={320} y2={24} className="lp-e-warn-mark" />
            <circle cx={320} cy={29} r={1.4} className="lp-e-warn-dot" />
          </motion.g>
        )}
      </AnimatePresence>
    </svg>
  );
}

function EngineManual() {
  const [tab, setTab] = useState<TabKey>('identify');
  const [auto, setAuto] = useState(true);
  const reduce = useReducedMotion();
  const ref = useRef<HTMLElement>(null);
  const inView = useInView(ref, { amount: 0.4 });

  // Walk the tabs while the viewer is on screen, until the reader takes over.
  useEffect(() => {
    if (!auto || reduce || !inView) return undefined;
    const t = window.setTimeout(() => {
      setTab((cur) => TABS[(TABS.findIndex((x) => x.key === cur) + 1) % TABS.length].key);
    }, 5200);
    return () => window.clearTimeout(t);
  }, [tab, auto, reduce, inView]);

  const pick = useCallback((k: TabKey) => { setAuto(false); setTab(k); }, []);
  const onKeys = (e: React.KeyboardEvent) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const i = TABS.findIndex((x) => x.key === tab);
    // RTL: ArrowLeft moves forward
    const next = (i + (e.key === 'ArrowLeft' ? 1 : -1) + TABS.length) % TABS.length;
    pick(TABS[next].key);
    document.getElementById(`lp-etab-${TABS[next].key}`)?.focus();
  };

  return (
    <figure className="lp-figure lp-manual" ref={ref} aria-label="نمونهٔ منوال تعمیر: کویل و شمع موتور">
      <div className="lp-figure-head">
        <span className="lp-manual-title"><Icon name="manual" />منوال تعمیر<span className="lp-manual-sys"> · <L>{ENGINE.system}</L></span></span>
        <L className="lp-manual-engine">{ENGINE.engine}</L>
      </div>
      <div className="lp-figure-canvas">
        <EngineDrawing tab={tab} />
      </div>
      <div className="lp-etabs" role="tablist" aria-label="بخش‌های منوال" onKeyDown={onKeys}>
        {TABS.map((t) => (
          <button
            key={t.key}
            id={`lp-etab-${t.key}`}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            aria-controls="lp-epanel"
            tabIndex={tab === t.key ? 0 : -1}
            className={tab === t.key ? 'is-on' : ''}
            onClick={() => pick(t.key)}
          >
            <Icon name={t.icon} />
            <span>{t.label}</span>
            {tab === t.key && auto && !reduce && inView && <i className="lp-etab-timer" aria-hidden="true" />}
          </button>
        ))}
      </div>
      <div className="lp-epanel" id="lp-epanel" role="tabpanel" aria-labelledby={`lp-etab-${tab}`} aria-live="polite">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div key={tab} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.2, ease: EASE }}>
            <EnginePanel tab={tab} />
          </motion.div>
        </AnimatePresence>
      </div>
      <figcaption>
        داده‌های واقعی منوال در پورتال · <L>{ENGINE.vehicle}</L>
      </figcaption>
    </figure>
  );
}

/* ------------------------------------------------------------------------ */
/* Docs section figure: one brake job traced through the four layers.        */
/* ------------------------------------------------------------------------ */
const C = { x: 280, y: 262 };
function pt(r: number, deg: number): [number, number] {
  const a = (deg * Math.PI) / 180;
  return [+(C.x + r * Math.cos(a)).toFixed(1), +(C.y + r * Math.sin(a)).toFixed(1)];
}
function annulus(r1: number, r2: number, a1: number, a2: number) {
  const [x1, y1] = pt(r2, a1);
  const [x2, y2] = pt(r2, a2);
  const [x3, y3] = pt(r1, a2);
  const [x4, y4] = pt(r1, a1);
  const large = a2 - a1 > 180 ? 1 : 0;
  return `M${x1} ${y1} A${r2} ${r2} 0 ${large} 1 ${x2} ${y2} L${x3} ${y3} A${r1} ${r1} 0 ${large} 0 ${x4} ${y4} Z`;
}

function BrakeDrawing() {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLElement>(null);
  const seen = useInView(ref, { once: true, amount: 0.35 });
  const go = seen || !!reduce;
  const draw = (i: number) => ({
    initial: { pathLength: 0, opacity: 0 },
    animate: go ? { pathLength: 1, opacity: 1 } : undefined,
    transition: { duration: reduce ? 0 : 0.75, ease: EASE, delay: reduce ? 0 : 0.1 + i * 0.05 },
  });
  const later = (i: number) => ({
    initial: { opacity: 0 },
    animate: go ? { opacity: 1 } : undefined,
    transition: { duration: reduce ? 0 : 0.3, delay: reduce ? 0 : 0.75 + i * 0.08 },
  });

  const lugs = [0, 72, 144, 216, 288].map((d) => pt(44, d - 90));
  const bolts = [pt(186, -88), pt(186, -12)];
  const piston = pt(160, -50);
  // Numbered in the order a technician reads the job: procedure first, part last.
  const callouts = [
    { n: 1, a: bolts[1], m: [522, 176] as [number, number] },
    { n: 2, a: pt(172, 140), m: [64, 446] as [number, number] },
    { n: 3, a: piston, m: [506, 62] as [number, number] },
    { n: 4, a: pt(151, -64), m: [318, 30] as [number, number] },
  ];
  const legend = [
    { k: 'گشتاور پیچ کالیپر', v: <L mono>{SPECIMEN.torque.value}</L> },
    { k: 'زمان استاندارد', v: <span>{fa(SPECIMEN.labor.hours)} ساعت</span> },
    { k: 'ابزار مخصوص', v: <L mono>{SPECIMEN.sst.number}</L> },
    { k: 'قطعه', v: <L mono>{SPECIMEN.part.number}</L> },
  ];

  return (
    <figure className="lp-figure" aria-labelledby="lp-brake-cap" ref={ref}>
      <div className="lp-figure-head">
        <span>برگهٔ کار · {SPECIMEN.job}</span>
        <L>{SPECIMEN.car}</L>
      </div>
      <div className="lp-figure-canvas">
        <svg viewBox="0 0 560 500" className="lp-drawing" aria-hidden="true">
          <g className="lp-d-center">
            <line x1={C.x - 205} y1={C.y} x2={C.x + 205} y2={C.y} />
            <line x1={C.x} y1={C.y - 222} x2={C.x} y2={C.y + 205} />
          </g>
          <motion.circle cx={C.x} cy={C.y} r={172} className="lp-d-strong" {...draw(0)} />
          <motion.circle cx={C.x} cy={C.y} r={164} className="lp-d-thin" {...draw(1)} />
          <motion.circle cx={C.x} cy={C.y} r={104} className="lp-d-strong" {...draw(2)} />
          <motion.circle cx={C.x} cy={C.y} r={68} className="lp-d-thin" {...draw(3)} />
          <motion.circle cx={C.x} cy={C.y} r={24} className="lp-d-strong" {...draw(4)} />
          {lugs.map(([x, y], i) => (
            <motion.circle key={i} cx={x} cy={y} r={8} className="lp-d-thin" {...draw(4.5 + i * 0.2)} />
          ))}
          <motion.path d={annulus(122, 204, -96, -4)} className="lp-d-body" {...draw(6)} />
          <motion.path d={annulus(132, 170, -80, -22)} className="lp-d-hidden" {...later(0)} />
          <motion.circle cx={piston[0]} cy={piston[1]} r={18} className="lp-d-hidden" {...later(1)} />
          {bolts.map(([x, y], i) => (
            <motion.g key={i} className="lp-d-bolt" {...later(1.5)}>
              <circle cx={x} cy={y} r={9} />
              <line x1={x - 5} y1={y} x2={x + 5} y2={y} />
              <line x1={x} y1={y - 5} x2={x} y2={y + 5} />
            </motion.g>
          ))}
          {callouts.map((c, i) => (
            <motion.g key={c.n} className="lp-d-callout" {...later(2 + i)}>
              <line x1={c.a[0]} y1={c.a[1]} x2={c.m[0]} y2={c.m[1]} />
              <circle cx={c.a[0]} cy={c.a[1]} r={3} className="dot" />
              <circle cx={c.m[0]} cy={c.m[1]} r={15} className="ring" />
              <text x={c.m[0]} y={c.m[1]} textAnchor="middle" dominantBaseline="central">{fa(c.n)}</text>
            </motion.g>
          ))}
        </svg>
      </div>
      <ol className="lp-legend">
        {legend.map((l, i) => (
          <li key={l.k}>
            <span className="lp-legend-n" aria-hidden="true">{fa(i + 1)}</span>
            <span className="lp-legend-k">{l.k}</span>
            <span className="lp-legend-v">{l.v}</span>
          </li>
        ))}
      </ol>
      <figcaption id="lp-brake-cap">
        نمای روبه‌روی دیسک و کالیپر ترمز عقب؛ خط‌چین: لنت و پیستون پشت کالیپر.
      </figcaption>
    </figure>
  );
}

/* ------------------------------------------------------------------------ */

function SectionHead({ n, title, lead, id }: { n: string; title: string; lead?: React.ReactNode; id: string }) {
  return (
    <header className="lp-sechead">
      <span className="lp-chapter" aria-hidden="true">بخش {n}</span>
      <h2 id={`${id}-title`}>{title}</h2>
      {lead && <p className="lp-lead">{lead}</p>}
    </header>
  );
}

function Layers() {
  const cards = [
    {
      icon: 'manual',
      title: 'منوال تعمیر و عیب‌یابی',
      body: 'رویه‌های گام‌به‌گام باز و بست، بازرسی و تعمیر با گشتاورها و هشدارهای ایمنی، به‌همراه نقشه‌های سیم‌کشی و راهنمای کدهای خطا.',
      tag: 'هستهٔ اصلی پلتفرم',
      primary: true,
      specimen: (
        <>
          <div className="lp-spec-row">
            <L mono className="lp-spec-strong">Torque: {SPECIMEN.torque.value}</L>
            <L mono className="lp-spec-dim">({SPECIMEN.torque.alt})</L>
          </div>
          <div className="lp-spec-src"><L>{SPECIMEN.torque.page}</L></div>
        </>
      ),
    },
    {
      icon: 'clock',
      title: 'زمان استاندارد تعمیر',
      body: 'زمان مرجع هر عملیات برای برآورد هزینه و زمان‌بندی تعمیرگاه؛ جدول کامل هر خودرو به‌صورت CSV قابل دریافت است.',
      tag: 'خروجی CSV',
      specimen: (
        <>
          <div className="lp-spec-row">
            <L className="lp-spec-dim">{SPECIMEN.labor.appliesTo}</L>
            <L mono className="lp-spec-strong">{SPECIMEN.labor.hours} h</L>
          </div>
          <div className="lp-spec-src"><L>{SPECIMEN.labor.operation}</L></div>
        </>
      ),
    },
    {
      icon: 'wrench',
      title: 'ابزار مخصوص (SST)',
      body: 'ابزارهای ویژهٔ پراکنده در صفحات مختلف منوال، در یک فهرست یکپارچه برای هر خودرو با شمارهٔ ابزار.',
      tag: 'فهرست یکپارچه · CSV',
      specimen: (
        <>
          <div className="lp-spec-row">
            <L mono className="lp-spec-strong">{SPECIMEN.sst.number}</L>
          </div>
          <div className="lp-spec-src"><L>{SPECIMEN.sst.name}</L></div>
        </>
      ),
    },
    {
      icon: 'parts',
      title: 'کاتالوگ قطعات',
      body: 'شمارهٔ قطعه با دیاگرام انفجاری و شمارهٔ راهنما روی تصویر، مکمل رویه‌های تعمیر.',
      tag: 'برای خودروهای منتخب',
      specimen: (
        <>
          <div className="lp-spec-row">
            <L mono className="lp-spec-strong">{SPECIMEN.part.number}</L>
            <span className="lp-spec-dim">{SPECIMEN.part.nameFa}</span>
          </div>
          <div className="lp-spec-src"><L>{SPECIMEN.part.name} · {SPECIMEN.part.dates}</L></div>
        </>
      ),
    },
  ];

  return (
    <motion.ol className="lp-layers" data-tour="doc-layers" variants={stagger} initial="hidden" whileInView="show" viewport={VIEW}>
      {cards.map((c, i) => (
        <motion.li key={c.title} className={`lp-layer${c.primary ? ' is-primary' : ''}`} variants={reveal}>
          <div className="lp-layer-top">
            <span className="lp-layer-icon"><Icon name={c.icon} /></span>
            <span className="lp-layer-n" aria-hidden="true">{fa(`0${i + 1}`)}</span>
          </div>
          <h3>{c.title}</h3>
          <p>{c.body}</p>
          <div className="lp-spec" aria-label="نمونهٔ داده">
            <span className="lp-spec-label">نمونه از {SPECIMEN.job}</span>
            {c.specimen}
          </div>
          <div className="lp-layer-cov">
            <strong>{c.tag}</strong>
          </div>
        </motion.li>
      ))}
    </motion.ol>
  );
}

function AssistantDemo() {
  return (
    <motion.div className="lp-chat" initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={VIEW} transition={{ duration: 0.45, ease: EASE }}>
      <div className="lp-chat-head">
        <span className="lp-chat-title"><Icon name="bot" />دستیار · <L>{ENGINE.engine}</L></span>
        <span className="lp-chat-tag">نمونهٔ نمایشی</span>
      </div>
      <div className="lp-chat-body">
        <p className="lp-bubble lp-bubble-q">گشتاور بستن شمع موتور چقدر است؟</p>
        <div className="lp-bubble lp-bubble-a">
          <p>
            طبق جدول گشتاورهای مشخص‌شده، شمع با گشتاور{' '}
            <L mono className="lp-em lp-nowrap">{ENGINE.plugTorque.nm} ({ENGINE.plugTorque.alt})</L> روی سرسیلندر بسته می‌شود.
          </p>
          <div className="lp-evidence">
            <span className="lp-evidence-k"><Icon name="manual" />منبع</span>
            <L className="lp-evidence-v">Torque Specifications [11/2023 – ] · {ENGINE.engine} Spark Plug</L>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

/* Coverage: brand-neutral, expanding rings — no vehicle-level detail. */
function CoverageOrbit() {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const seen = useInView(ref, { once: true, amount: 0.35 });
  const go = seen || !!reduce;
  const t = (d: number, dur = 0.6) => ({ duration: reduce ? 0 : dur, delay: reduce ? 0 : d, ease: EASE });
  const cx = 260, cy = 260;
  const inner = Array.from({ length: 6 }, (_, i) => -90 + i * 60);
  const outer = Array.from({ length: 8 }, (_, i) => -67.5 + i * 45);
  const at = (r: number, deg: number) => [cx + r * Math.cos((deg * Math.PI) / 180), cy + r * Math.sin((deg * Math.PI) / 180)];

  return (
    <div className="lp-orbit" ref={ref} data-tour="coverage">
      <svg viewBox="0 0 520 520" aria-hidden="true">
        <motion.circle cx={cx} cy={cy} r={214} className="lp-o-ring lp-o-ring-future" initial={{ pathLength: 0, opacity: 0 }} animate={go ? { pathLength: 1, opacity: 1 } : undefined} transition={t(0.5, 1.2)} />
        <motion.circle cx={cx} cy={cy} r={132} className="lp-o-ring" initial={{ pathLength: 0, opacity: 0 }} animate={go ? { pathLength: 1, opacity: 1 } : undefined} transition={t(0.15, 0.9)} />
        {!reduce && (
          <motion.circle cx={cx} cy={cy} r={132} className="lp-o-pulse" initial={{ scale: 1, opacity: 0 }} animate={go ? { scale: [1, 1.62], opacity: [0.55, 0] } : undefined} transition={{ duration: 1.6, delay: 1.1, ease: 'easeOut' }} style={{ transformOrigin: `${cx}px ${cy}px` }} />
        )}
        {inner.map((deg, i) => {
          const [x, y] = at(132, deg);
          return (
            <motion.g key={`i${deg}`} initial={{ opacity: 0 }} animate={go ? { opacity: 1 } : undefined} transition={t(0.4 + i * 0.07, 0.35)}>
              <line x1={cx} y1={cy} x2={x} y2={y} className="lp-o-spoke" />
              <circle cx={x} cy={y} r={9} className="lp-o-node" />
            </motion.g>
          );
        })}
        {outer.map((deg, i) => {
          const [x, y] = at(214, deg);
          return (
            <motion.g key={`o${deg}`} initial={{ opacity: 0, scale: 0.6 }} animate={go ? { opacity: 1, scale: 1 } : undefined} transition={t(1.3 + i * 0.09, 0.35)} style={{ transformOrigin: `${x}px ${y}px` }}>
              <circle cx={x} cy={y} r={11} className="lp-o-node-future" />
              <path d={`M${x - 4} ${y} H${x + 4} M${x} ${y - 4} V${y + 4}`} className="lp-o-plus" />
            </motion.g>
          );
        })}
        <circle cx={cx} cy={cy} r={70} className="lp-o-core" />
      </svg>
      <div className="lp-orbit-core">
        <bdi dir="ltr" className="lp-brand-name">KG<span>techvault</span></bdi>
        <span>دانش فنی</span>
      </div>
    </div>
  );
}

function Coverage() {
  const current = ['منوال تعمیر', 'عیب‌یابی و کدهای خطا', 'نقشهٔ سیم‌کشی', 'زمان استاندارد', 'ابزار مخصوص', 'کاتالوگ قطعات'];
  const next = ['سازندگان جدید', 'مدل‌های جدید', 'دیتابیس‌های فنی جدید', 'قابلیت‌های هوشمند'];
  return (
    <div className="lp-split lp-cov2">
      <div>
        <SectionHead
          n="۰۳" id="coverage" title="پوششی که پیوسته گسترش می‌یابد"
          lead="پلتفرم امروز مستندات فنی خودروهای منتخب را پوشش می‌دهد و این پوشش به‌طور مستمر گسترده‌تر می‌شود؛ سازندگان، مدل‌ها و مجموعه‌داده‌های فنی تازه در طول زمان به آن افزوده می‌شوند."
        />
        <div className="lp-cov-groups">
          <div>
            <h3><span className="lp-dot" aria-hidden="true" />پوشش فعلی</h3>
            <ul className="lp-chips">{current.map((c) => <li key={c}>{c}</li>)}</ul>
          </div>
          <div>
            <h3><span className="lp-dot lp-dot-future" aria-hidden="true" />قابل افزودن</h3>
            <ul className="lp-chips lp-chips-future">{next.map((c) => <li key={c}>{c}</li>)}</ul>
          </div>
        </div>
        <Link href={REQUEST_HREF} className="lp-textlink lp-cov-link">خودروی موردنظرتان را نمی‌بینید؟ هنگام ثبت درخواست به ما بگویید<span aria-hidden="true"> ←</span></Link>
      </div>
      <CoverageOrbit />
    </div>
  );
}

function AccessFlow() {
  const ref = useRef<HTMLDivElement>(null);
  const barRef = useRef<HTMLSpanElement>(null);
  // Rail fills as the steps cross the reading line (80% → 55% of the viewport).
  useEffect(() => {
    let raf = 0;
    const update = () => {
      raf = 0;
      const el = ref.current, bar = barRef.current;
      if (!el || !bar) return;
      const r = el.getBoundingClientRect(), vh = window.innerHeight;
      const start = vh * 0.8, end = vh * 0.55;
      const p = Math.min(1, Math.max(0, (start - r.top) / (start - end + r.height * 0.5)));
      bar.style.transform = `scaleX(${p.toFixed(3)})`;
    };
    const on = () => { if (!raf) raf = requestAnimationFrame(update); };
    update();
    window.addEventListener('scroll', on, { passive: true });
    window.addEventListener('resize', on);
    return () => { window.removeEventListener('scroll', on); window.removeEventListener('resize', on); if (raf) cancelAnimationFrame(raf); };
  }, []);
  const steps = [
    { t: 'انتخاب پلن و ثبت درخواست', d: 'مدت اشتراک و تعداد کاربران را انتخاب می‌کنید، برآورد قیمت را می‌بینید و درخواست را ثبت می‌کنید.' },
    { t: 'پیش‌فاکتور و پرداخت', d: 'کارشناس ما با شما تماس می‌گیرد، پیش‌فاکتور را ارسال می‌کند و پرداخت از طریق انتقال بانکی (شبا) انجام می‌شود.' },
    { t: 'صدور حساب و ورود دو مرحله‌ای', d: 'پس از تأیید، حساب کاربری صادر می‌شود؛ ورود با رمز عبور و کد پیامکی انجام می‌شود.' },
    { t: 'مرور مستندات', d: 'همهٔ خودروها و مستندات پلتفرم برای کاربران شما در پورتال در دسترس است.' },
  ];
  return (
    <div className="lp-steps-wrap" ref={ref}>
      <div className="lp-steps-rail" aria-hidden="true"><span ref={barRef} /></div>
      <ol className="lp-steps">
        {steps.map((s, i) => (
          <motion.li key={s.t} className="lp-step" initial={{ opacity: 0, y: 12 }} whileInView={{ opacity: 1, y: 0 }} viewport={VIEW} transition={{ duration: 0.4, ease: EASE, delay: i * 0.06 }}>
            <span className="lp-step-n">{fa(`0${i + 1}`)}</span>
            <h3>{s.t}</h3>
            <p>{s.d}</p>
          </motion.li>
        ))}
      </ol>
    </div>
  );
}

function Team() {
  const items = [
    { icon: 'org', t: 'نمودار سازمانی و دسترسی', d: 'ساختار تیم و سطح دسترسی هر نفر روی یک نمودار بصری تعریف می‌شود.' },
    { icon: 'mailplus', t: 'دعوت اعضا', d: 'صدور جایگاه کاربری و ارسال لینک دعوت برای کارکنان شرکت.' },
    { icon: 'chart', t: 'تحلیل و گزارش', d: 'آمار استفادهٔ تیم از مستندات، با گزارش قابل دریافت به‌صورت PDF.' },
    { icon: 'bell', t: 'صندوق درخواست‌ها', d: 'درخواست‌های اعضای شرکت در یک صندوق برای بررسی مدیر.' },
  ];
  return (
    <motion.ul className="lp-team" variants={stagger} initial="hidden" whileInView="show" viewport={VIEW}>
      {items.map((it) => (
        <motion.li key={it.t} variants={reveal}>
          <span className="lp-team-icon"><Icon name={it.icon} /></span>
          <div>
            <h3>{it.t}</h3>
            <p>{it.d}</p>
          </div>
        </motion.li>
      ))}
    </motion.ul>
  );
}

/* ------------------------------------------------------------------------ */
/* Drafting-sheet background: work lamp, two-tier grid that emerges from     */
/* the drawing, ruler + corner marks, and an inspection lamp that follows    */
/* the pointer over empty sheet (never over the copy column).                */
/* ------------------------------------------------------------------------ */
function SheetFx({ bookend = false }: { bookend?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || bookend || !window.matchMedia('(pointer: fine)').matches) return undefined;
    const host = el.parentElement as HTMLElement;
    let raf = 0;
    const onMove = (e: MouseEvent) => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        const r = host.getBoundingClientRect();
        el.style.setProperty('--hx', `${(e.clientX - r.left).toFixed(0)}px`);
        el.style.setProperty('--hy', `${(e.clientY - r.top).toFixed(0)}px`);
      });
    };
    const onEnter = () => el.classList.add('is-lit');
    const onLeave = () => el.classList.remove('is-lit');
    host.addEventListener('mousemove', onMove);
    host.addEventListener('mouseenter', onEnter);
    host.addEventListener('mouseleave', onLeave);
    return () => {
      host.removeEventListener('mousemove', onMove);
      host.removeEventListener('mouseenter', onEnter);
      host.removeEventListener('mouseleave', onLeave);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [bookend]);
  return (
    <div className={`lp-fx${bookend ? ' lp-fx-bookend' : ''}`} ref={ref} aria-hidden="true">
      <div className="lp-fx-lamp" />
      <div className="lp-fx-grid" />
      {!bookend && <div className="lp-fx-hot" />}
      {!bookend && (
        <div className="lp-fx-sheet">
          <div className="lp-fx-ruler">
            {Array.from({ length: 8 }, (_, i) => <span key={i} style={{ right: `${i * 160}px` }}>{fa(i + 1)}</span>)}
          </div>
          <i className="lp-fx-corner tl" /><i className="lp-fx-corner tr" /><i className="lp-fx-corner bl" /><i className="lp-fx-corner br" />
        </div>
      )}
      <div className="lp-fx-grain" />
    </div>
  );
}

export default function Home() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const [active, setActive] = useState<string>('');
  const [pastHero, setPastHero] = useState(false);
  const heroRef = useRef<HTMLDivElement>(null);
  const sheetRef = useRef<HTMLDivElement>(null);
  const burgerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 8);
    on();
    window.addEventListener('scroll', on, { passive: true });
    return () => window.removeEventListener('scroll', on);
  }, []);

  useEffect(() => {
    const spy = new IntersectionObserver(
      (entries) => entries.forEach((e) => e.isIntersecting && setActive(e.target.id)),
      { rootMargin: '-45% 0px -50% 0px' },
    );
    CHAPTERS.forEach((c) => { const el = document.getElementById(c.id); if (el) spy.observe(el); });
    const hero = new IntersectionObserver(([e]) => setPastHero(!e.isIntersecting && e.boundingClientRect.top < 0), { threshold: 0 });
    if (heroRef.current) hero.observe(heroRef.current);
    return () => { spy.disconnect(); hero.disconnect(); };
  }, []);

  useEffect(() => {
    if (!menuOpen) return undefined;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    sheetRef.current?.querySelector<HTMLElement>('a,button')?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenuOpen(false); };
    document.addEventListener('keydown', onKey);
    const trigger = burgerRef.current;
    return () => {
      document.body.style.overflow = prev;
      document.removeEventListener('keydown', onKey);
      trigger?.focus();
    };
  }, [menuOpen]);

  useEffect(() => {
    const onResize = () => { if (window.innerWidth > 1180) setMenuOpen(false); };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const navLinks = (onClick?: () => void) => CHAPTERS.map((c) => (
    <a key={c.id} href={`#${c.id}`} onClick={onClick} className={active === c.id ? 'is-active' : ''} aria-current={active === c.id ? 'location' : undefined}>
      {c.label}
    </a>
  ));

  return (
    <MotionConfig reducedMotion="user">
      <div className="lp" id="landing">
        <a className="lp-skip" href="#main">رفتن به محتوای اصلی</a>

        <header className={`lp-header${scrolled ? ' is-scrolled' : ''}`}>
          <div className="lp-header-in">
            <Wordmark />
            <nav className="lp-nav" aria-label="بخش‌های صفحه">{navLinks()}</nav>
            <div className="lp-header-actions">
              <HelpButton />
              <ThemeButton />
              <LoginButton />
              <button
                ref={burgerRef}
                type="button"
                className="lp-iconbtn lp-burger"
                aria-label="باز کردن منو"
                aria-expanded={menuOpen}
                aria-controls="lp-sheet"
                onClick={() => setMenuOpen(true)}
              >
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h10" /></svg>
              </button>
            </div>
          </div>
        </header>

        <div className={`lp-scrim${menuOpen ? ' is-open' : ''}`} onClick={() => setMenuOpen(false)} aria-hidden="true" />
        <div id="lp-sheet" ref={sheetRef} className={`lp-sheet${menuOpen ? ' is-open' : ''}`} role="dialog" aria-modal="true" aria-label="منو" inert={!menuOpen}>
          <div className="lp-sheet-head">
            <Wordmark />
            <button type="button" className="lp-iconbtn" aria-label="بستن منو" onClick={() => setMenuOpen(false)}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
            </button>
          </div>
          <nav className="lp-sheet-nav" aria-label="بخش‌های صفحه">{navLinks(() => setMenuOpen(false))}</nav>
          <div className="lp-sheet-foot">
            <div className="lp-sheet-theme"><span>حالت نمایش</span><ThemeButton /></div>
            <div className="lp-sheet-theme"><span>راهنمای سامانه</span><HelpButton onOpen={() => setMenuOpen(false)} /></div>
            <Link className="lp-btn lp-btn-primary lp-btn-lg" href="/login" onClick={() => setMenuOpen(false)}>ورود به پورتال</Link>
          </div>
        </div>

        <nav className="lp-thumbs" aria-label="فهرست بخش‌ها">
          {CHAPTERS.map((c, i) => (
            <a key={c.id} href={`#${c.id}`} className={active === c.id ? 'is-active' : ''} aria-current={active === c.id ? 'location' : undefined}>
              <span className="lp-thumb-l">{c.label}</span>
              <span className="lp-thumb-n">{fa(`0${i + 1}`)}</span>
            </a>
          ))}
        </nav>

        <main id="main">
          <section className="lp-hero" aria-labelledby="hero-title">
            <SheetFx />
            <div className="lp-wrap lp-hero-grid">
              <div className="lp-hero-copy">
                <motion.p className="lp-eyebrow" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease: EASE }}>
                  {BRAND_LINE}
                </motion.p>
                <motion.h1 id="hero-title" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, ease: EASE, delay: 0.05 }}>
                  دقتِ کارخانه،<br />در دستِ <em>تعمیرگاه</em>.
                </motion.h1>
                <motion.p className="lp-hero-lead" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, ease: EASE, delay: 0.1 }}>
                  منوال‌های تعمیر، رویه‌های عیب‌یابی و تعمیر، نقشه‌های سیم‌کشی و مشخصات فنی در یک پلتفرم دانش — با دستیار هوشمندی که از روی همین مستندات پاسخ می‌دهد.
                </motion.p>
                <motion.ol className="lp-chain" aria-label="مسیر دانش در پلتفرم" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.5, delay: 0.2 }}>
                  {['منوال تعمیر', 'دانش فنی', 'عیب‌یابی', 'رویهٔ تعمیر', 'مستندسازی هوشمند'].map((s) => <li key={s}>{s}</li>)}
                </motion.ol>
                <motion.div ref={heroRef} className="lp-hero-actions" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, ease: EASE, delay: 0.15 }}>
                  <Link className="lp-btn lp-btn-primary lp-btn-lg" href="/login">ورود به پورتال<span aria-hidden="true" className="lp-arrow">←</span></Link>
                  <Link className="lp-btn lp-btn-outline lp-btn-lg" href={REQUEST_HREF}>پلن‌ها و قیمت</Link>
                </motion.div>
                <motion.dl className="lp-stats lp-stats-3" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.5, delay: 0.3 }}>
                  <div><dt>پیکربندی خودرو تا امروز</dt><dd>{fa(MANUAL_CONFIGS_FLOOR)}<span className="lp-plus">+</span></dd></div>
                  <div><dt>لایهٔ مستند فنی</dt><dd>{fa(4)}</dd></div>
                  <div><dt>پوشش خودروها و مستندات</dt><dd className="lp-dd-text">در حال گسترش</dd></div>
                </motion.dl>
              </div>
              <div className="lp-hero-art">
                <EngineManual />
              </div>
            </div>
          </section>

          <section id="docs" className="lp-sec" aria-labelledby="docs-title">
            <div className="lp-wrap">
              <div className="lp-split lp-docs-head">
                <SectionHead
                  n="۰۱" id="docs" title="از منوال تعمیر تا اجرای کار"
                  lead={<>منوال تعمیر هستهٔ پلتفرم است و زمان استاندارد، ابزار مخصوص و اطلاعات قطعه آن را کامل می‌کنند. نمونه‌های این بخش داده‌های واقعی پورتال برای {SPECIMEN.job} در <L>{SPECIMEN.car}</L> است.</>}
                />
                <BrakeDrawing />
              </div>
              <Layers />
            </div>
          </section>

          <section id="assistant" className="lp-sec lp-sec-alt" aria-labelledby="assistant-title">
            <div className="lp-wrap lp-split">
              <div>
                <SectionHead
                  n="۰۲" id="assistant" title="دستیار هوشمند، متکی به منبع"
                  lead="پرسش خود را به فارسی بنویسید؛ دستیار پاسخ را فقط از مستندات همان خودرو استخراج می‌کند و صفحهٔ منبع را کنار پاسخ نشان می‌دهد."
                />
                <ul className="lp-points">
                  <li><strong>پاسخ همراه با منبع</strong><span>هر پاسخ به صفحه‌های منوالی که از آن‌ها گرفته شده پیوند دارد تا قابل بررسی باشد.</span></li>
                  <li><strong>پرسش فارسی، منوال انگلیسی</strong><span>پرسش فارسی به اصطلاحات فنی منوال انگلیسی کارخانه تطبیق داده می‌شود.</span></li>
                  <li><strong>عیب‌یابی با کد خطا یا علامت</strong><span>با کد خطا (<L mono>DTC</L>) یا شرح علامت، رویه‌های مرتبط همان خودرو پیدا می‌شود.</span></li>
                </ul>
                <p className="lp-note">دستیار هوشمند در همهٔ اشتراک‌ها گنجانده شده است و هر کاربر سهمیهٔ مشخصی پرسش در ماه دارد.</p>
              </div>
              <AssistantDemo />
            </div>
          </section>

          <section id="coverage" className="lp-sec" aria-labelledby="coverage-title">
            <div className="lp-wrap">
              <Coverage />
            </div>
          </section>

          <section id="access" className="lp-sec lp-sec-alt" aria-labelledby="access-title">
            <div className="lp-wrap">
              <SectionHead n="۰۴" id="access" title="روند دسترسی" lead="از ثبت درخواست تا مرور مستندات، در چهار مرحله." />
              <AccessFlow />
            </div>
          </section>

          <section id="team" className="lp-sec" aria-labelledby="team-title">
            <div className="lp-wrap lp-split lp-split-team">
              <SectionHead n="۰۵" id="team" title="برای مدیران شرکت" lead="دسترسی کارکنان را خودتان مدیریت کنید و ببینید تیم از مستندات چگونه استفاده می‌کند." />
              <Team />
            </div>
          </section>

          <section id="request" className="lp-cta" aria-labelledby="request-title">
            <SheetFx bookend />
            <div className="lp-wrap">
              <div className="lp-cta-in">
                <span className="lp-chapter" aria-hidden="true">بخش ۰۶</span>
                <h2 id="request-title">یک اشتراک، همهٔ خودروها.</h2>
                <p className="lp-cta-lead">دسترسی به همهٔ خودروها و لایه‌های مستند پلتفرم، همراه با دستیار هوشمند و مدیریت تیم — به‌صورت ۲ روزه، ماهانه یا سالانه، برای یک نفر تا کل تیم.</p>
                <ol className="lp-cta-steps" aria-label="روند خرید اشتراک">
                  <li>انتخاب پلن و ثبت درخواست</li>
                  <li>تماس کارشناس و پیش‌فاکتور</li>
                  <li>پرداخت و فعال‌سازی دسترسی</li>
                </ol>
                <div className="lp-cta-actions">
                  <Link className="lp-btn lp-btn-primary lp-btn-lg" href={REQUEST_HREF}>مشاهدهٔ پلن‌ها و قیمت<span aria-hidden="true" className="lp-arrow">←</span></Link>
                  <Link className="lp-btn lp-btn-outline lp-btn-lg" href="/login">ورود به پورتال</Link>
                </div>
              </div>
            </div>
          </section>
        </main>

        <Footer coverageHref="#coverage" />

        <div className={`lp-dock${pastHero && !menuOpen ? ' is-on' : ''}`} inert={!pastHero || menuOpen}>
          <Link className="lp-btn lp-btn-outline" href={REQUEST_HREF}>پلن‌ها و قیمت</Link>
          <Link className="lp-btn lp-btn-primary" href="/login">ورود به پورتال</Link>
        </div>
      </div>
    </MotionConfig>
  );
}
