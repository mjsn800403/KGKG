'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import Icon from './Icon';
import { adminApi } from '../utils/api';
import useEventStream from '../utils/useEventStream';

const EASE = [0.22, 1, 0.36, 1];

function fmtNum(n) {
  return (n ?? 0).toLocaleString('fa-IR');
}
function fmtTime(iso) {
  try { return new Date(iso).toLocaleTimeString('fa-IR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }); }
  catch { return ''; }
}
function relTime(iso) {
  try {
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 60) return 'همین حالا';
    if (s < 3600) return `${Math.floor(s / 60)} دقیقه پیش`;
    if (s < 86400) return `${Math.floor(s / 3600)} ساعت پیش`;
    return `${Math.floor(s / 86400)} روز پیش`;
  } catch { return ''; }
}

const ACTION_FA = {
  login: 'ورود', view_node: 'مشاهده سند', view_section: 'مرور بخش',
  search: 'جستجو', assist: 'دستیار', open_assistant: 'دستیار هوشمند',
  view_fleet: 'مشاهده ناوگان', team_add: 'افزودن کارمند',
};
function actionLabel(a) { return ACTION_FA[a] || a; }

const EVENT_FA = {
  'data.detected': 'داده جدید شناسایی شد',
  'processing.pending': 'صف پردازش به‌روزرسانی شد',
  'pipeline.started': 'پردازش آغاز شد',
  'pipeline.progress': 'پیشرفت پردازش',
  'pipeline.completed': 'پردازش کامل شد',
  'pipeline.failed': 'پردازش با خطا متوقف شد',
  'pipeline.paused': 'پردازش موقتاً متوقف شد',
  'request.created': 'درخواست جدید شرکت',
  'request.updated': 'به‌روزرسانی درخواست',
  'alert.opened': 'هشدار جدید',
  'alert.resolved': 'هشدار برطرف شد',
};

export default function AdminDashboard({ go }) {
  const [d, setD] = useState(null);
  const [feed, setFeed] = useState([]);       // live event ticker
  const [flash, setFlash] = useState({});     // {panelKey: timestamp} for pulse
  const seq = useRef(0);

  const load = useCallback(async () => {
    try { setD(await adminApi.dashboard()); } catch { /* keep last */ }
  }, []);
  useEffect(() => { load(); }, [load]);
  // Safety re-sync every 60s in case a delta was ever missed.
  useEffect(() => {
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [load]);

  const pulse = useCallback((key) => {
    setFlash((f) => ({ ...f, [key]: Date.now() }));
  }, []);

  const pushFeed = useCallback((evt, label) => {
    seq.current += 1;
    const id = `${evt.id || 't'}-${seq.current}`;
    setFeed((f) => [{ id, type: evt.type, ts: evt.ts, label }, ...f].slice(0, 40));
  }, []);

  const onEvent = useCallback((evt) => {
    const p = evt.payload || {};
    switch (evt.type) {
      case 'data.detected':
      case 'processing.pending':
        setD((cur) => cur ? { ...cur, processing: { ...cur.processing, pending: p.pending || cur.processing.pending, active_job: p.active_job ?? cur.processing.active_job } } : cur);
        pulse('processing');
        pushFeed(evt, EVENT_FA[evt.type]);
        break;
      case 'pipeline.started':
      case 'pipeline.progress':
      case 'pipeline.completed':
      case 'pipeline.failed':
      case 'pipeline.paused':
        setD((cur) => cur ? { ...cur, processing: { ...cur.processing, active_job: p.job ?? cur.processing.active_job } } : cur);
        pulse('processing');
        if (evt.type !== 'pipeline.progress') pushFeed(evt, EVENT_FA[evt.type]);
        break;
      case 'request.created':
        setD((cur) => {
          if (!cur) return cur;
          const req = p.request;
          const exists = cur.open_requests.some((r) => r.id === req.id);
          return {
            ...cur,
            kpis: { ...cur.kpis, open_company_requests: (cur.kpis.open_company_requests || 0) + (exists ? 0 : 1) },
            open_requests: exists ? cur.open_requests : [req, ...cur.open_requests].slice(0, 20),
          };
        });
        pulse('requests');
        pushFeed(evt, `${EVENT_FA[evt.type]} — ${p.request?.subject || ''}`);
        break;
      case 'request.updated':
        setD((cur) => {
          if (!cur) return cur;
          const req = p.request;
          const isOpen = req.status === 'pending' || req.status === 'in_progress';
          let list = cur.open_requests.filter((r) => r.id !== req.id);
          if (isOpen) list = [req, ...list];
          return {
            ...cur,
            kpis: { ...cur.kpis, open_company_requests: list.length },
            open_requests: list.slice(0, 20),
          };
        });
        pulse('requests');
        pushFeed(evt, `${EVENT_FA[evt.type]} — ${p.request?.subject || ''} (${p.request?.status_label || ''})`);
        break;
      case 'alert.opened':
        setD((cur) => cur ? {
          ...cur,
          kpis: { ...cur.kpis, open_alerts: (cur.kpis.open_alerts || 0) + 1 },
          alerts: [{ id: Date.now(), key: p.key, severity: p.severity, message: p.message, last_seen: evt.ts }, ...cur.alerts].slice(0, 20),
        } : cur);
        pulse('alerts');
        pushFeed(evt, `${EVENT_FA[evt.type]} — ${p.message || p.key}`);
        break;
      case 'alert.resolved':
        load();
        pushFeed(evt, EVENT_FA[evt.type]);
        break;
      case 'activity':
        setD((cur) => cur ? {
          ...cur,
          recent_activity: [{
            id: p.activity_id || Date.now(), user: p.user_name, company: '—',
            action: p.action, detail: p.detail, category: p.category,
            car: p.car?.label || null, created_at: evt.ts,
          }, ...cur.recent_activity].slice(0, 20),
        } : cur);
        break;
      default:
        break;
    }
  }, [load, pulse, pushFeed]);

  const { status } = useEventStream({ admin: true, onEvent });

  if (!d) {
    return (
      <div className="rt-dash">
        <div className="rt-kpis">
          {[0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="glass shimmer" style={{ height: 92, borderRadius: 14 }} />)}
        </div>
      </div>
    );
  }

  const k = d.kpis;
  const proc = d.processing?.pending || {};
  const job = d.processing?.active_job;
  const counts = proc.counts || { catalog: 0, rag_ingest: 0, diag: 0 };

  const kpiTiles = [
    { label: 'شرکت‌ها', value: k.companies, icon: 'building', to: 'companies' },
    { label: 'کاربران فعال', value: k.users, icon: 'users', to: 'users' },
    { label: 'خودروها', value: k.vehicles, icon: 'car', to: 'catalog' },
    { label: 'فعالیت امروز', value: k.activities_today, icon: 'clock', to: 'activity' },
    { label: 'درخواست‌های باز', value: k.open_company_requests, icon: 'cart', to: 'company-requests', hot: k.open_company_requests > 0 },
    { label: 'هشدارها', value: k.open_alerts, icon: 'shield', to: 'system', hot: k.open_alerts > 0 },
  ];

  return (
    <div className="rt-dash">
      <div className="rt-head">
        <div>
          <h1 className="rt-title">داشبورد بلادرنگ</h1>
          <p className="rt-sub">وضعیت زندهٔ پلتفرم — به‌روزرسانی لحظه‌ای</p>
        </div>
        <LiveBadge status={status} />
      </div>

      <div className="rt-kpis">
        {kpiTiles.map((t) => (
          <button key={t.label} className={`rt-kpi glass${t.hot ? ' hot' : ''}`} onClick={() => go?.(t.to)}>
            <span className="rk-ico"><Icon name={t.icon} size={18} /></span>
            <span className="rk-val">{fmtNum(t.value)}</span>
            <span className="rk-label">{t.label}</span>
          </button>
        ))}
      </div>

      <div className="rt-grid">
        <ProcessingPanel proc={proc} counts={counts} job={job} flash={flash.processing} go={go} />
        <RequestsPanel requests={d.open_requests} flash={flash.requests} go={go} />
        <AlertsPanel alerts={d.alerts} flash={flash.alerts} go={go} />
        <ActivityPanel activity={d.recent_activity} />
        <TrafficPanel spark={d.traffic_spark} />
        <TickerPanel feed={feed} />
      </div>
    </div>
  );
}

function LiveBadge({ status }) {
  const map = {
    open: { t: 'زنده', c: 'ok' }, connecting: { t: 'در حال اتصال…', c: 'warn' },
    reconnecting: { t: 'اتصال مجدد…', c: 'warn' }, unauthorized: { t: 'قطع', c: 'bad' },
    idle: { t: '…', c: 'warn' },
  };
  const s = map[status] || map.idle;
  return (
    <div className={`rt-live rt-live-${s.c}`}>
      <span className="rt-dot" />
      {s.t}
    </div>
  );
}

function Panel({ title, tag, hot, children, flash, action }) {
  return (
    <motion.section
      className="rt-panel glass"
      animate={flash ? { boxShadow: ['0 0 0 rgba(227,78,99,0)', '0 0 0 2px var(--accent-glow)', '0 0 0 rgba(227,78,99,0)'] } : {}}
      transition={{ duration: 1.1 }}
    >
      <header className="rt-panel-head">
        <h3>{title}{hot ? <span className="rt-hot-dot" /> : null}</h3>
        <div className="rt-panel-head-r">
          {tag && <span className="rt-tag">{tag}</span>}
          {action}
        </div>
      </header>
      {children}
    </motion.section>
  );
}

function ProcessingPanel({ proc, counts, job, flash, go }) {
  const hasWork = proc.has_work;
  const pct = job?.progress?.overall_pct ?? 0;
  const running = job && (job.status === 'running' || job.status === 'pending');
  const embed = proc.pages_to_embed || 0;

  const badges = [
    { label: 'کاتالوگ', n: counts.catalog, hint: 'خودروهای ثبت‌نشده' },
    { label: 'RAG', n: counts.rag_ingest + (embed > 0 ? 1 : 0), hint: 'نیازمند ایندکس معنایی' },
    { label: 'DIAG', n: counts.diag, hint: 'نیازمند موتور عیب‌یابی' },
  ];

  return (
    <Panel title="پردازش داده‌ها" tag="// LIVE" hot={hasWork} flash={flash}
      action={<button className="rt-mini-btn" onClick={() => go?.('pipeline')}>باز کردن</button>}>
      <div className="rt-badges">
        {badges.map((b) => (
          <div key={b.label} className={`rt-badge${b.n > 0 ? ' active' : ''}`} title={b.hint}>
            <span className="rb-n">{fmtNum(b.n)}</span>
            <span className="rb-l">{b.label}</span>
          </div>
        ))}
      </div>
      {embed > 0 && (
        <div className="rt-embed-note">{fmtNum(embed)} صفحه در انتظار ایندکس معنایی</div>
      )}
      {running ? (
        <div className="rt-progress-wrap">
          <div className="rt-progress-label">
            <span>{job.progress?.stage ? `مرحله: ${job.progress.stage}` : 'در حال پردازش'}</span>
            <span>{pct.toLocaleString('fa-IR')}٪</span>
          </div>
          <div className="rt-progress"><motion.div className="rt-progress-bar" animate={{ width: `${pct}%` }} transition={{ ease: EASE, duration: 0.6 }} /></div>
        </div>
      ) : (
        <div className="rt-idle">{hasWork ? 'کار پردازشی در صف — به‌صورت خودکار در زمان کم‌باری اجرا می‌شود.' : 'همه‌چیز پردازش شده و به‌روز است ✓'}</div>
      )}
    </Panel>
  );
}

function statusClass(s) {
  return { pending: 'warn', in_progress: 'info', completed: 'ok', rejected: 'bad' }[s] || 'warn';
}

function RequestsPanel({ requests, flash, go }) {
  return (
    <Panel title="درخواست‌های شرکت‌ها" tag="// INBOX" hot={requests.length > 0} flash={flash}
      action={<button className="rt-mini-btn" onClick={() => go?.('company-requests')}>همه</button>}>
      {requests.length === 0 ? (
        <div className="rt-idle">درخواست بازی وجود ندارد.</div>
      ) : (
        <ul className="rt-list">
          <AnimatePresence initial={false}>
            {requests.slice(0, 6).map((r) => (
              <motion.li key={r.id} layout
                initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }}>
                <span className={`rt-pill rt-pill-${statusClass(r.status)}`}>{r.status_label}</span>
                <div className="rt-list-main">
                  <b>{r.subject}</b>
                  <small>{r.company?.name} — {r.kind_label}</small>
                </div>
                <span className="rt-when">{relTime(r.created_at)}</span>
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      )}
    </Panel>
  );
}

function AlertsPanel({ alerts, flash, go }) {
  return (
    <Panel title="هشدارهای عملیاتی" tag="// OPS" hot={alerts.length > 0} flash={flash}
      action={<button className="rt-mini-btn" onClick={() => go?.('system')}>پایش</button>}>
      {alerts.length === 0 ? (
        <div className="rt-idle">هیچ هشدار بازی نیست ✓</div>
      ) : (
        <ul className="rt-list">
          {alerts.slice(0, 6).map((a) => (
            <li key={a.id}>
              <span className={`rt-pill rt-pill-${a.severity === 'critical' ? 'bad' : 'warn'}`}>{a.severity}</span>
              <div className="rt-list-main"><b>{a.message}</b><small>{a.key}</small></div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function ActivityPanel({ activity }) {
  return (
    <Panel title="فعالیت زنده کاربران" tag="// STREAM">
      {(!activity || activity.length === 0) ? (
        <div className="rt-idle">فعالیتی ثبت نشده.</div>
      ) : (
        <ul className="rt-list rt-list-dense">
          <AnimatePresence initial={false}>
            {activity.slice(0, 8).map((a) => (
              <motion.li key={a.id} layout
                initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
                <span className="rt-av">{(a.user || '?').slice(0, 1)}</span>
                <div className="rt-list-main">
                  <b>{a.user}</b>
                  <small>{actionLabel(a.action)}{a.car ? ` — ${a.car}` : ''}</small>
                </div>
                <span className="rt-when">{relTime(a.created_at)}</span>
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      )}
    </Panel>
  );
}

function TrafficPanel({ spark }) {
  const data = spark || [];
  const max = Math.max(1, ...data.map((x) => x.requests || 0));
  return (
    <Panel title="ترافیک ۱۴ روز اخیر" tag="// TRAFFIC">
      {data.length === 0 ? (
        <div className="rt-idle">داده‌ای برای نمایش نیست.</div>
      ) : (
        <div className="rt-spark">
          {data.map((x) => (
            <div key={x.date} className="rt-spark-col" title={`${x.date}: ${fmtNum(x.requests)}`}>
              <div className="rt-spark-bar" style={{ height: `${Math.max(4, (x.requests / max) * 100)}%` }} />
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

function TickerPanel({ feed }) {
  return (
    <Panel title="جریان رویدادها" tag="// EVENTS">
      {feed.length === 0 ? (
        <div className="rt-idle">در انتظار رویداد…</div>
      ) : (
        <ul className="rt-ticker">
          <AnimatePresence initial={false}>
            {feed.slice(0, 12).map((e) => (
              <motion.li key={e.id}
                initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }}>
                <span className="rt-tk-time">{fmtTime(e.ts)}</span>
                <span className="rt-tk-label">{e.label}</span>
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      )}
    </Panel>
  );
}
