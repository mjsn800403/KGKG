'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { AnimatePresence, motion, MotionConfig } from 'motion/react';
import Icon from './Icon';
import Switch from './Switch';
import OrgChart from './OrgChart';
import RolesPanel from './RolesPanel';
import useEventStream from '../utils/useEventStream';
import { teamApi, portalRefreshMe, getPortalToken, downloadTeamReport } from '../utils/api';

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------
const EASE = [0.22, 1, 0.36, 1];
const SPRING = { type: 'spring', stiffness: 380, damping: 32, mass: 0.75 };

function initials(name = '') {
  const parts = String(name).trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return '؟';
  return (parts[0][0] + (parts[1]?.[0] || '')).toUpperCase();
}

function relTime(iso) {
  if (!iso) return 'بدون فعالیت';
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return 'چند لحظه پیش';
  if (diff < 3600) return `${Math.floor(diff / 60)} دقیقه پیش`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} ساعت پیش`;
  if (diff < 2592000) return `${Math.floor(diff / 86400)} روز پیش`;
  return d.toLocaleDateString('fa-IR');
}

const STATUS_META = {
  active: { label: 'فعال', cls: 'ok' },
  invited: { label: 'در انتظار پذیرش دعوت', cls: 'pending' },
  disabled: { label: 'غیرفعال', cls: 'off' },
};

const TABS = [
  { id: 'members', label: 'اعضای تیم', icon: 'users' },
  { id: 'chart', label: 'چارت سازمانی', icon: 'org' },
  { id: 'roles', label: 'نقش‌ها و دسترسی‌ها', icon: 'layers' },
];

function emptyForm() {
  return {
    display_name: '', email: '', phone: '', personnel_code: '',
    org_role_id: '', reports_to_id: '',
    provision: 'invite', username: '', password: '',  // 'invite' | 'credentials'
    can_manage_team: false, can_view_analytics: false, ai_assistant_enabled: true,
    accesses: {},  // { car_id: [docs] }
  };
}

// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------
export default function TeamView() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [members, setMembers] = useState([]);
  const [meta, setMeta] = useState(null);
  const [org, setOrg] = useState(null);
  const [tab, setTab] = useState('members');

  const [drawer, setDrawer] = useState(null);   // null | {mode:'add', roleId?} | {mode:'edit', member}
  const [justAddedId, setJustAddedId] = useState(null);
  const [toasts, setToasts] = useState([]);
  const [query, setQuery] = useState('');
  const [roleFilter, setRoleFilter] = useState(null);
  const reloadTimer = useRef(null);

  const notify = (message, tone = 'ok') => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, message, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3600);
  };

  const load = async () => {
    const [data, orgData] = await Promise.all([teamApi.members(), teamApi.org()]);
    setMembers(data.members || []);
    setMeta(data.meta || null);
    setOrg(orgData);
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!getPortalToken()) { router.replace('/login'); return; }
      try {
        await portalRefreshMe();
        await load();
      } catch (e) {
        if (cancelled) return;
        if (e?.unauthorized) { router.replace('/login'); return; }
        if (e?.forbidden) { router.replace('/browse'); return; }
        setError(e?.message || 'بارگذاری تیم ناموفق بود.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [router]);

  // Any team change made in ANOTHER session (a second manager, the platform
  // admin, ...) arrives as a team.* event — refresh so every open view shows
  // the same hierarchy. Debounced: one reload per burst of changes.
  useEventStream({
    enabled: !loading && !error,
    onEvent: (evt) => {
      if (!String(evt?.type || '').startsWith('team.')) return;
      clearTimeout(reloadTimer.current);
      reloadTimer.current = setTimeout(() => { load().catch(() => {}); }, 600);
    },
  });
  useEffect(() => () => clearTimeout(reloadTimer.current), []);

  const stats = useMemo(() => ({
    total: members.length,
    active: members.filter((m) => m.invite_status === 'active' && m.active).length,
    pending: members.filter((m) => m.invite_status === 'invited').length,
  }), [members]);

  const roleCounts = useMemo(() => {
    const counts = {};
    members.forEach((m) => {
      const rid = m.org_role?.id;
      if (rid) counts[rid] = (counts[rid] || 0) + 1;
    });
    return counts;
  }, [members]);

  const visibleMembers = useMemo(() => {
    const q = query.trim().toLowerCase();
    return members.filter((m) => {
      if (roleFilter && m.org_role?.id !== roleFilter) return false;
      if (!q) return true;
      return [m.display_name, m.username, m.email, m.role_label]
        .some((v) => String(v || '').toLowerCase().includes(q));
    });
  }, [members, query, roleFilter]);

  const onSaved = async (savedId) => {
    await load();
    if (savedId) {
      setJustAddedId(savedId);
      setTimeout(() => setJustAddedId(null), 2200);
    }
  };

  const openEditById = (node) => {
    const m = members.find((x) => x.id === node.id);
    if (m) setDrawer({ mode: 'edit', member: m });
  };

  if (loading) return <TeamSkeleton />;
  if (error) return <div className="pform-error">{error}</div>;

  return (
    <MotionConfig reducedMotion="user">
      <div className="team-wrap">
        <motion.div
          className="team-stats"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: EASE }}
        >
          <StatTile icon="users" label="کل کارکنان" value={stats.total} />
          <StatTile icon="check" label="فعال" value={stats.active} tone="ok" />
          <StatTile icon="mailplus" label="دعوت‌های در انتظار" value={stats.pending} tone="pending" />
          <button className="team-add-fab" onClick={() => setDrawer({ mode: 'add' })} aria-label="افزودن کارمند">
            <motion.span className="fab-plus" whileHover={{ rotate: 90 }} transition={{ type: 'spring', stiffness: 300, damping: 18 }}>
              <Icon name="plus" size={22} />
            </motion.span>
            <span className="fab-text">افزودن کارمند</span>
          </button>
        </motion.div>

        <motion.nav
          className="team-tabs glass"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: EASE, delay: 0.06 }}
        >
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`team-tab${tab === t.id ? ' active' : ''}`}
              onClick={() => setTab(t.id)}
            >
              <Icon name={t.icon} size={16} /> {t.label}
              {tab === t.id && (
                <motion.span className="team-tab-ink" layoutId="team-tab-ink" transition={SPRING} />
              )}
            </button>
          ))}
        </motion.nav>

        <AnimatePresence mode="wait">
          <motion.div
            key={tab}
            initial={{ opacity: 0, y: 16, filter: 'blur(4px)' }}
            animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
            exit={{ opacity: 0, y: -10, filter: 'blur(4px)' }}
            transition={{ duration: 0.32, ease: EASE }}
          >
            {tab === 'members' && (
              members.length === 0 ? (
                <EmptyTeam onAdd={() => setDrawer({ mode: 'add' })} />
              ) : (
                <>
                  <div className="team-toolbar glass">
                    <div className="team-search">
                      <Icon name="search" size={16} />
                      <input
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="جستجوی نام، ایمیل یا نام کاربری…"
                      />
                      {query && (
                        <button className="ts-clear" onClick={() => setQuery('')} aria-label="پاک کردن">
                          <Icon name="x" size={13} />
                        </button>
                      )}
                    </div>
                    <div className="team-filter-chips">
                      <button
                        className={`filter-chip${roleFilter === null ? ' on' : ''}`}
                        onClick={() => setRoleFilter(null)}
                      >
                        همه ({members.length})
                      </button>
                      {(meta?.roles || []).filter((r) => roleCounts[r.id]).map((r) => (
                        <button
                          key={r.id}
                          className={`filter-chip${roleFilter === r.id ? ' on' : ''}`}
                          onClick={() => setRoleFilter(roleFilter === r.id ? null : r.id)}
                        >
                          <span className="dot" style={{ background: r.color || 'var(--accent)' }} />
                          {r.name} ({roleCounts[r.id]})
                        </button>
                      ))}
                    </div>
                  </div>
                  {visibleMembers.length === 0 ? (
                    <div className="team-noresult muted">عضوی مطابق این جستجو یافت نشد.</div>
                  ) : (
                    <motion.div className="team-grid" layout>
                      <AnimatePresence mode="popLayout">
                        {visibleMembers.map((m, i) => (
                          <MemberCard
                            key={m.id}
                            member={m}
                            index={i}
                            highlight={m.id === justAddedId}
                            onEdit={() => setDrawer({ mode: 'edit', member: m })}
                          />
                        ))}
                      </AnimatePresence>
                    </motion.div>
                  )}
                </>
              )
            )}
            {tab === 'chart' && (
              <OrgChart
                data={org}
                onReload={load}
                onEditMember={openEditById}
                onAddWithRole={(roleId) => setDrawer({ mode: 'add', roleId })}
                notify={notify}
              />
            )}
            {tab === 'roles' && meta && (
              <RolesPanel
                meta={meta}
                members={members}
                onChanged={() => load()}
                onAddWithRole={(roleId) => setDrawer({ mode: 'add', roleId })}
                notify={notify}
              />
            )}
          </motion.div>
        </AnimatePresence>

        <AnimatePresence>
          {drawer && meta && (
            <MemberDrawer
              key={drawer.mode + (drawer.member?.id || 'new')}
              mode={drawer.mode}
              member={drawer.member}
              initialRoleId={drawer.roleId}
              meta={meta}
              onClose={() => setDrawer(null)}
              onSaved={onSaved}
              notify={notify}
            />
          )}
        </AnimatePresence>

        <div className="toast-stack">
          <AnimatePresence>
            {toasts.map((t) => (
              <motion.div
                key={t.id}
                className={`toast glass ${t.tone}`}
                initial={{ opacity: 0, y: 24, scale: 0.95 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 12, scale: 0.95 }}
                transition={SPRING}
              >
                <Icon name={t.tone === 'error' ? 'x' : 'check'} size={15} /> {t.message}
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      </div>
    </MotionConfig>
  );
}

// ---------------------------------------------------------------------------
// Pieces
// ---------------------------------------------------------------------------
function StatTile({ icon, label, value, tone }) {
  return (
    <div className={`team-stat glass${tone ? ` tone-${tone}` : ''}`}>
      <div className="ts-ico"><Icon name={icon} /></div>
      <div className="ts-body">
        <div className="ts-value">{value}</div>
        <div className="ts-label">{label}</div>
      </div>
    </div>
  );
}

function MemberCard({ member, index, highlight, onEdit }) {
  const s = STATUS_META[member.invite_status] || STATUS_META.active;
  const accent = member.org_role?.color || 'var(--accent)';
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 18, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: 0.9 }}
      transition={{ duration: 0.4, delay: Math.min(index * 0.04, 0.3), ease: EASE }}
      className={`member-card glass${highlight ? ' just-added' : ''}`}
      whileHover={{ y: -4 }}
      style={{ '--node-accent': accent }}
    >
      <div className="mc-head">
        <div className="mc-avatar" style={{ background: `color-mix(in srgb, ${accent} 22%, transparent)` }}>
          {initials(member.display_name || member.username)}
        </div>
        <div className="mc-id">
          <div className="mc-name">{member.display_name || member.username}</div>
          <div className="mc-role" style={{ color: accent }}>{member.role_label}</div>
        </div>
        <span className={`mc-status ${s.cls}`}>{s.label}</span>
      </div>

      <div className="mc-meta">
        {member.reports_to && <span className="mc-line"><Icon name="org" size={14} /> سرپرست: {member.reports_to.name}</span>}
        {member.email && <span className="mc-line ltr"><Icon name="mail" size={14} /> {member.email}</span>}
        <span className="mc-line"><Icon name="clock" size={14} /> {relTime(member.last_login_at)}</span>
      </div>

      <div className="mc-badges">
        {member.ai_eligible && <span className="mc-badge"><Icon name="bot" size={13} /> دستیار</span>}
        {member.can_manage_team && <span className="mc-badge"><Icon name="users" size={13} /> مدیریت تیم</span>}
        {member.can_view_analytics && <span className="mc-badge"><Icon name="chart" size={13} /> تحلیل</span>}
        {(member.accesses?.length || 0) > 0 && <span className="mc-badge"><Icon name="car" size={13} /> {member.accesses.length} خودرو</span>}
      </div>

      <div className="mc-actions">
        <button className="btn mc-edit" onClick={onEdit}><Icon name="edit" size={15} /> مدیریت</button>
      </div>
    </motion.div>
  );
}

function EmptyTeam({ onAdd }) {
  return (
    <motion.div className="team-empty glass" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45 }}>
      <motion.div className="te-ico" animate={{ y: [0, -6, 0] }} transition={{ repeat: Infinity, duration: 3, ease: 'easeInOut' }}>
        <Icon name="users" size={44} />
      </motion.div>
      <h3>هنوز کارمندی اضافه نکرده‌اید</h3>
      <p>کارکنان زیرمجموعه خود را دعوت کنید تا با حساب کاربری اختصاصی خودشان از سامانه استفاده کنند.</p>
      <button className="btn btn-accent" onClick={onAdd}><Icon name="plus" size={16} /> افزودن اولین کارمند</button>
    </motion.div>
  );
}

function TeamSkeleton() {
  return (
    <div className="team-wrap">
      <div className="team-stats">
        {[0, 1, 2].map((i) => <div key={i} className="team-stat glass shimmer" style={{ height: 76 }} />)}
      </div>
      <div className="team-grid">
        {[0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="member-card glass shimmer" style={{ height: 190 }} />)}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Add / edit slide-over drawer
// ---------------------------------------------------------------------------
function MemberDrawer({ mode, member, initialRoleId, meta, onClose, onSaved, notify }) {
  const isEdit = mode === 'edit';
  const [form, setForm] = useState(() => initForm(member, meta));
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState('');
  const [success, setSuccess] = useState(null); // { invite_url, emailed, name }
  const firstFieldRef = useRef(null);

  useEffect(() => { firstFieldRef.current?.focus(); }, []);

  const set = (patch) => setForm((f) => ({ ...f, ...patch }));
  const assignableRoles = (meta.roles || []).filter((r) => r.editable);
  const me = meta.me || null;

  const selRole = assignableRoles.find((r) => r.id === Number(form.org_role_id)) || null;
  // The org chart only points upward: a supervisor must hold a strictly
  // higher position than the member's chosen one. The acting viewer (the
  // default) always qualifies — they can only assign positions below their own.
  const supervisorOptions = (meta.managers || []).filter(
    (m) => m.id !== me?.id && (!selRole || m.rank < selRole.rank),
  );

  // Seed capability defaults from the chosen position (still editable per-user).
  const onRole = (roleIdRaw) => {
    const roleId = Number(roleIdRaw) || '';
    const role = assignableRoles.find((r) => r.id === roleId);
    const patch = { org_role_id: roleId };
    if (role) {
      patch.can_manage_team = !!role.can_manage_team;
      patch.can_view_analytics = !!role.can_view_analytics;
      patch.ai_assistant_enabled = !!role.ai_assistant_enabled;
      // If the currently chosen supervisor no longer outranks the new
      // position, fall back to the default (the acting viewer).
      if (form.reports_to_id) {
        const sup = (meta.managers || []).find((m) => m.id === Number(form.reports_to_id));
        if (!sup || sup.rank >= role.rank) patch.reports_to_id = '';
      }
      // Pre-fill the position's access template so the manager SEES what the
      // new member will get (and can still adjust before saving).
      if (!isEdit && Array.isArray(role.default_accesses) && role.default_accesses.length) {
        const acc = {};
        role.default_accesses.forEach((a) => { acc[a.car_id] = a.documents || []; });
        patch.accesses = acc;
      }
    }
    set(patch);
  };

  // Opened from "add a member to this position" (org chart / roles panel):
  // pre-apply that position and its defaults.
  useEffect(() => {
    if (!isEdit && initialRoleId) onRole(String(initialRoleId));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggleCar = (carId, docs) => {
    setForm((f) => {
      const next = { ...f.accesses };
      if (next[carId]) delete next[carId];
      else next[carId] = docs;
      return { ...f, accesses: next };
    });
  };

  const accessesPayload = () =>
    Object.entries(form.accesses).map(([car_id, documents]) => ({ car_id: Number(car_id), documents }));

  const submit = async (e) => {
    e.preventDefault();
    setErr('');
    if (!form.display_name.trim()) return setErr('نام و نام خانوادگی الزامی است.');
    if (!isEdit && form.provision === 'invite' && !form.email.trim())
      return setErr('برای دعوت با ایمیل، ایمیل الزامی است (یا حالت «نام کاربری و رمز» را انتخاب کنید).');
    if (!isEdit && form.provision === 'credentials' && form.password && form.password.length < 8)
      return setErr('رمز عبور باید حداقل ۸ نویسه باشد (یا خالی بگذارید تا خودکار ساخته شود).');
    if (!form.org_role_id) return setErr('جایگاه سازمانی را انتخاب کنید.');
    setSubmitting(true);
    try {
      if (isEdit) {
        const res = await teamApi.updateMember(member.id, {
          display_name: form.display_name, phone: form.phone, personnel_code: form.personnel_code,
          org_role_id: Number(form.org_role_id) || null,
          reports_to_id: form.reports_to_id ? Number(form.reports_to_id) : null,
          can_manage_team: form.can_manage_team, can_view_analytics: form.can_view_analytics,
          ai_assistant_enabled: form.ai_assistant_enabled,
        });
        await teamApi.setMemberAccess(member.id, accessesPayload());
        await onSaved(member.id);
        if (res?.adjustments?.reparented > 0) {
          notify?.(`ذخیره شد؛ ${res.adjustments.reparented} خط گزارش‌دهی برای حفظ سازگاری چارت اصلاح شد.`);
        }
        onClose();
      } else {
        const payload = {
          display_name: form.display_name, email: form.email || undefined, phone: form.phone,
          personnel_code: form.personnel_code, org_role_id: Number(form.org_role_id),
          reports_to_id: form.reports_to_id ? Number(form.reports_to_id) : undefined,
          can_manage_team: form.can_manage_team, can_view_analytics: form.can_view_analytics,
          ai_assistant_enabled: form.ai_assistant_enabled,
          accesses: accessesPayload(),
          provision: form.provision,
        };
        if (form.provision === 'credentials') {
          payload.username = form.username || undefined;
          payload.password = form.password || undefined;
        }
        const res = await teamApi.createMember(payload);
        await onSaved(res.user.id);
        if (res.credentials) {
          setSuccess({ mode: 'credentials', credentials: res.credentials, name: form.display_name });
        } else {
          setSuccess({ mode: 'invite', invite_url: res.invite_url, emailed: res.emailed, name: form.display_name });
        }
      }
    } catch (e2) {
      setErr(e2?.message || 'ثبت ناموفق بود.');
    } finally {
      setSubmitting(false);
    }
  };

  const deactivate = async () => {
    setSubmitting(true);
    try {
      await teamApi.updateMember(member.id, { active: !member.active });
      await onSaved(member.id);
      onClose();
    } catch (e2) { setErr(e2?.message || 'خطا'); } finally { setSubmitting(false); }
  };

  const resend = async () => {
    setSubmitting(true);
    try {
      const res = await teamApi.resendInvite(member.id);
      setSuccess({ invite_url: res.invite_url, emailed: res.emailed, name: member.display_name });
    } catch (e2) { setErr(e2?.message || 'خطا'); } finally { setSubmitting(false); }
  };

  return (
    <>
      <motion.div className="drawer-scrim" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
      <motion.aside
        className="drawer glass"
        initial={{ x: '-100%' }}
        animate={{ x: 0 }}
        exit={{ x: '-100%' }}
        transition={{ type: 'spring', stiffness: 320, damping: 34 }}
        role="dialog" aria-modal="true"
      >
        <div className="drawer-head">
          <h3><Icon name={isEdit ? 'edit' : 'sparkles'} /> {isEdit ? 'مدیریت کارمند' : 'افزودن کارمند جدید'}</h3>
          <button className="drawer-close" onClick={onClose} aria-label="بستن"><Icon name="x" /></button>
        </div>

        <AnimatePresence mode="wait">
          {success ? (
            <SuccessPanel key="success" data={success} onDone={onClose} />
          ) : (
            <motion.form key="form" className="drawer-body" onSubmit={submit}
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <div className="field">
                <label>نام و نام خانوادگی <span className="req-star">*</span></label>
                <input ref={firstFieldRef} value={form.display_name} onChange={(e) => set({ display_name: e.target.value })} placeholder="مثلاً علی رضایی" />
              </div>
              {!isEdit && (
                <>
                  <div className="field">
                    <label>روش ایجاد حساب</label>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <button type="button" style={{ flex: 1 }}
                        className={`btn${form.provision === 'invite' ? ' btn-accent' : ''}`}
                        onClick={() => set({ provision: 'invite' })}>
                        <Icon name="mail" size={15} /> دعوت با ایمیل
                      </button>
                      <button type="button" style={{ flex: 1 }}
                        className={`btn${form.provision === 'credentials' ? ' btn-accent' : ''}`}
                        onClick={() => set({ provision: 'credentials' })}>
                        <Icon name="shield" size={15} /> نام کاربری و رمز
                      </button>
                    </div>
                  </div>
                  {form.provision === 'invite' ? (
                    <div className="field">
                      <label>ایمیل (برای ارسال دعوت‌نامه) <span className="req-star">*</span></label>
                      <input type="email" dir="ltr" value={form.email} onChange={(e) => set({ email: e.target.value })} placeholder="ali@company.com" />
                    </div>
                  ) : (
                    <>
                      <p className="muted" style={{ margin: '2px 0 6px' }}>
                        برای کارمندی که ایمیل ندارد؛ نام کاربری و رمز را همین‌جا می‌سازید و به او می‌دهید. خالی گذاشتن هرکدام = ساخت خودکار.
                      </p>
                      <div className="pform-grid">
                        <div className="field">
                          <label>نام کاربری</label>
                          <input dir="ltr" value={form.username} onChange={(e) => set({ username: e.target.value })} placeholder="خالی = خودکار" />
                        </div>
                        <div className="field">
                          <label>رمز عبور</label>
                          <input dir="ltr" value={form.password} onChange={(e) => set({ password: e.target.value })} placeholder="خالی = خودکار (حداقل ۸ نویسه)" />
                        </div>
                      </div>
                      <div className="field">
                        <label>ایمیل (اختیاری)</label>
                        <input type="email" dir="ltr" value={form.email} onChange={(e) => set({ email: e.target.value })} placeholder="اختیاری" />
                      </div>
                    </>
                  )}
                </>
              )}
              <div className="pform-grid">
                <div className="field">
                  <label>تلفن همراه</label>
                  <input dir="ltr" value={form.phone} onChange={(e) => set({ phone: e.target.value })} placeholder="0912…" />
                </div>
                <div className="field">
                  <label>کد پرسنلی</label>
                  <input dir="ltr" value={form.personnel_code} onChange={(e) => set({ personnel_code: e.target.value })} />
                </div>
              </div>
              <div className="drawer-section-title">جایگاه در چارت سازمانی</div>
              <div className="pform-grid">
                <div className="field">
                  <label>جایگاه سازمانی <span className="req-star">*</span></label>
                  <select value={form.org_role_id} onChange={(e) => onRole(e.target.value)}>
                    <option value="">— انتخاب کنید —</option>
                    {assignableRoles.map((r) => <option key={r.id} value={r.id}>{r.name} (رتبه {r.rank})</option>)}
                  </select>
                </div>
                <div className="field">
                  <label>سرپرست مستقیم</label>
                  <select value={form.reports_to_id} onChange={(e) => set({ reports_to_id: e.target.value })}>
                    <option value="">
                      {me ? `${me.name} — ${me.role_label}` : '— مدیر تیم —'}
                    </option>
                    {supervisorOptions.map((m) => (
                      <option key={m.id} value={m.id}>{m.name} — {m.role_label}</option>
                    ))}
                  </select>
                  {selRole && (
                    <p className="field-hint muted">
                      فقط جایگاه‌های بالاتر از «{selRole.name}» می‌توانند سرپرست این عضو باشند.
                    </p>
                  )}
                </div>
              </div>

              <div className="drawer-section-title">دسترسی‌ها و قابلیت‌ها</div>
              <div className="cap-row"><div><b>دستیار هوشمند</b><span>دسترسی به چت‌بات فنی</span></div><Switch checked={form.ai_assistant_enabled} onChange={(v) => set({ ai_assistant_enabled: v })} /></div>
              <div className="cap-row"><div><b>مدیریت تیم</b><span>افزودن و مدیریت زیرمجموعه‌ها</span></div><Switch checked={form.can_manage_team} onChange={(v) => set({ can_manage_team: v })} /></div>
              <div className="cap-row"><div><b>مشاهده تحلیل‌ها</b><span>دسترسی به گزارش‌های استفاده</span></div><Switch checked={form.can_view_analytics} onChange={(v) => set({ can_view_analytics: v })} /></div>

              <div className="drawer-section-title">دسترسی به خودروها</div>
              <div className="access-list">
                {meta.cars.length === 0 && <div className="muted">شرکت هنوز خودرویی خریداری نکرده است.</div>}
                {meta.cars.map((c) => {
                  const on = !!form.accesses[c.id];
                  return (
                    <button type="button" key={c.id} className={`access-chip${on ? ' on' : ''}`} onClick={() => toggleCar(c.id, c.documents)}>
                      <Icon name={on ? 'check' : 'plus'} size={14} />
                      {c.brand} {c.model} {c.year}
                    </button>
                  );
                })}
              </div>

              {err && <div className="pform-error">{err}</div>}

              <div className="drawer-actions">
                {isEdit && (
                  <>
                    {!member.password_set && (
                      <button type="button" className="btn" onClick={resend} disabled={submitting}><Icon name="refresh" size={15} /> ارسال مجدد دعوت</button>
                    )}
                    <button type="button" className={`btn ${member.active ? 'btn-danger' : ''}`} onClick={deactivate} disabled={submitting}>
                      {member.active ? 'غیرفعال‌سازی' : 'فعال‌سازی'}
                    </button>
                  </>
                )}
                <button type="submit" className="btn btn-accent" disabled={submitting}>
                  {submitting ? 'در حال ذخیره…'
                    : (isEdit ? 'ذخیره تغییرات'
                      : (form.provision === 'credentials' ? 'ایجاد حساب کاربری' : 'ایجاد و ارسال دعوت'))}
                </button>
              </div>
            </motion.form>
          )}
        </AnimatePresence>
      </motion.aside>
    </>
  );
}

function SuccessPanel({ data, onDone }) {
  const [copied, setCopied] = useState('');
  const copy = async (text, which) => {
    try { await navigator.clipboard.writeText(text); setCopied(which); setTimeout(() => setCopied(''), 1800); } catch { /* */ }
  };
  const isCred = data.mode === 'credentials';
  return (
    <motion.div key="success" className="drawer-body success-panel" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
      <motion.div className="success-check" initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ type: 'spring', stiffness: 260, damping: 16 }}>
        <motion.svg viewBox="0 0 52 52" width="72" height="72">
          <motion.circle cx="26" cy="26" r="24" fill="none" stroke="var(--accent)" strokeWidth="2"
            initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.5 }} />
          <motion.path d="M16 27l7 7 14-15" fill="none" stroke="var(--accent)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"
            initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.4, delay: 0.35 }} />
        </motion.svg>
      </motion.div>
      <h3 style={{ textAlign: 'center' }}>«{data.name}» اضافه شد!</h3>

      {isCred ? (
        <>
          <p className="success-sub">این اطلاعات ورود را به کارمند بدهید. رمز عبور فقط همین یک‌بار نمایش داده می‌شود.</p>
          <div className="acct-card" style={{ marginTop: 4 }}>
            <div className="acct-row">
              <span className="k">نام کاربری</span>
              <span className="v ltr" style={{ flex: 1 }}>{data.credentials.username}</span>
              <button type="button" className="btn" onClick={() => copy(data.credentials.username, 'u')}>
                <Icon name={copied === 'u' ? 'check' : 'copy'} size={14} />
              </button>
            </div>
            <div className="acct-row" style={{ borderBottom: 'none' }}>
              <span className="k">رمز عبور</span>
              <span className="v ltr" style={{ flex: 1 }}>{data.credentials.password}</span>
              <button type="button" className="btn" onClick={() => copy(data.credentials.password, 'p')}>
                <Icon name={copied === 'p' ? 'check' : 'copy'} size={14} />
              </button>
            </div>
          </div>
          <button className="btn btn-accent" style={{ marginTop: 10 }}
            onClick={() => copy(`${data.credentials.username} / ${data.credentials.password}`, 'both')}>
            <Icon name={copied === 'both' ? 'check' : 'copy'} size={15} /> {copied === 'both' ? 'کپی شد' : 'کپی نام کاربری و رمز'}
          </button>
        </>
      ) : (
        <>
          <p className="success-sub">
            {data.emailed
              ? 'دعوت‌نامه به ایمیل کارمند ارسال شد. لینک زیر را هم می‌توانید مستقیم برایش بفرستید.'
              : 'لینک دعوت زیر را برای کارمند بفرستید تا رمز عبور خود را تعیین و حساب را فعال کند.'}
          </p>
          <div className="invite-link-box">
            <input dir="ltr" readOnly value={data.invite_url} onFocus={(e) => e.target.select()} />
            <button className="btn btn-accent" onClick={() => copy(data.invite_url, 'link')}>
              <Icon name={copied === 'link' ? 'check' : 'copy'} size={15} /> {copied === 'link' ? 'کپی شد' : 'کپی لینک'}
            </button>
          </div>
        </>
      )}

      <button className="btn" style={{ marginTop: 16 }} onClick={onDone}>بستن</button>
    </motion.div>
  );
}

function initForm(member, meta) {
  if (!member) return emptyForm();
  const accesses = {};
  (member.accesses || []).forEach((a) => { accesses[a.car.id] = a.documents || []; });
  // Legacy members may miss org_role — map their legacy rank onto a position.
  let roleId = member.org_role?.id || '';
  if (!roleId && meta?.roles?.length) {
    const match = meta.roles.find((r) => r.rank === member.role_level);
    roleId = match?.id || '';
  }
  // Reporting to the acting viewer is the default ('' -> server assigns them);
  // normalizing avoids a duplicate "me" entry in the supervisor list.
  const supId = member.reports_to?.id || '';
  return {
    display_name: member.display_name || '', email: member.email || '',
    phone: member.phone || '', personnel_code: member.personnel_code || '',
    org_role_id: roleId,
    reports_to_id: supId === meta?.me?.id ? '' : supId,
    provision: 'invite', username: '', password: '',
    can_manage_team: !!member.can_manage_team, can_view_analytics: !!member.can_view_analytics,
    ai_assistant_enabled: !!member.ai_assistant_enabled, accesses,
  };
}
