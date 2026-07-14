'use client';

// «نقش‌ها و سطوح دسترسی» — the configurable hierarchy editor.
//
// The company manager designs their OWN pyramid here: create positions,
// rename them, drag to re-rank (Reorder from `motion` gives the fluid list),
// choose each position's reach (everyone below / own subtree / none), its
// capability defaults, an accent color, and a default car/package access
// template that can be pushed to existing members in one tap.

import { useEffect, useMemo, useState } from 'react';
import { AnimatePresence, motion, Reorder, useDragControls } from 'motion/react';
import Icon from './Icon';
import Switch from './Switch';
import { teamApi } from '../utils/api';

const SPRING = { type: 'spring', stiffness: 420, damping: 34, mass: 0.8 };
const SCOPES = [
  { id: 'org', label: 'همه رده‌های پایین‌تر', hint: 'به کل افراد پایین‌تر از این جایگاه دسترسی دارد — مستقل از خطوط گزارش‌دهی.' },
  { id: 'subtree', label: 'فقط زیرمجموعه خودش', hint: 'فقط افرادی که مستقیم یا غیرمستقیم به او گزارش می‌دهند.' },
  { id: 'none', label: 'بدون دسترسی مدیریتی', hint: 'عضو عادی؛ کسی را در بخش کاربران نمی‌بیند.' },
];
const SWATCHES = ['#e8b04b', '#7c6cf0', '#4bb3e8', '#5ecf8a', '#e86c6c', '#d16cd6', '#6cd6c3', '#a0a8b8'];

export default function RolesPanel({ meta, members = [], onChanged, onAddWithRole, notify }) {
  const [roles, setRoles] = useState(meta?.roles || []);
  const [expanded, setExpanded] = useState(null);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);

  // The panel's list stays in step with every other tab (SSE refresh, member
  // moves, ...) — server responses win over local optimistic state.
  useEffect(() => { setRoles(meta?.roles || []); }, [meta]);

  const myRank = meta?.my_rank ?? 1;
  const locked = useMemo(() => roles.filter((r) => !r.editable), [roles]);
  const editable = useMemo(() => roles.filter((r) => r.editable), [roles]);

  const assignMember = async (memberId, role) => {
    if (!memberId || busy) return;
    setBusy(true);
    try {
      const res = await teamApi.updateMember(Number(memberId), { org_role_id: role.id });
      const adj = res?.adjustments || {};
      let msg = `عضو به جایگاه «${role.name}» منتقل شد.`;
      if (adj.caps_reseeded) msg += ' دسترسی‌ها مطابق جایگاه جدید تنظیم شد.';
      if (adj.reparented > 0) msg += ` ${adj.reparented} خط گزارش‌دهی اصلاح شد.`;
      notify?.(msg);
      onChanged?.();
    } catch (e) {
      notify?.(e?.message || 'انتساب عضو ناموفق بود.', 'error');
    } finally {
      setBusy(false);
    }
  };

  const refresh = (nextRoles) => {
    setRoles(nextRoles);
    onChanged?.(nextRoles);
  };

  const commitOrder = async (list) => {
    try {
      const res = await teamApi.reorderRoles(list.map((r) => r.id));
      refresh(res.roles);
    } catch (e) {
      notify?.(e?.message || 'ذخیره ترتیب ناموفق بود.', 'error');
    }
  };

  // Optimistic order while dragging; commit on release.
  const onReorder = (list) => setRoles([...locked, ...list]);

  const patchRole = async (id, payload, msg) => {
    setBusy(true);
    try {
      const res = await teamApi.updateRole(id, payload);
      refresh(res.roles);
      if (msg) notify?.(msg);
      return res;
    } catch (e) {
      notify?.(e?.message || 'ذخیره ناموفق بود.', 'error');
      return null;
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="roles-panel">
      <motion.div
        className="roles-intro glass"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
      >
        <Icon name="layers" size={20} />
        <div>
          <b>سلسله‌مراتب سازمان شما، با قوانین خودتان.</b>
          <p>
            جایگاه‌ها را بکشید و مرتب کنید؛ هر جایگاه بالاتر، به رده‌های پایین‌ترِ خود دسترسی دارد.
            برای هر جایگاه می‌توانید محدوده دید، قابلیت‌ها و الگوی دسترسی به خودروها را جداگانه تنظیم کنید.
          </p>
        </div>
      </motion.div>

      <div className="roles-list">
        {locked.map((r) => (
          <div key={r.id} className="role-row glass locked">
            <span className="role-grip muted"><Icon name="shield" size={15} /></span>
            <span className="role-color" style={{ background: r.color || 'var(--accent)' }} />
            <span className="role-name">
              {r.name}
              {r.rank === myRank && meta?.me && (
                <span className="role-selftag">{meta.me.name} — جایگاه شما</span>
              )}
            </span>
            <span className="role-rank">رتبه {r.rank}</span>
            <span className="role-members">{r.members_count} عضو</span>
            <span className="role-locktag">
              {r.rank === myRank ? 'جایگاه شما' : 'بالاتر از جایگاه شما'}
            </span>
          </div>
        ))}

        <Reorder.Group axis="y" values={editable} onReorder={onReorder} as="div">
          {editable.map((role) => (
            <RoleRow
              key={role.id}
              role={role}
              allRoles={roles}
              meta={meta}
              members={members}
              expanded={expanded === role.id}
              onExpand={() => setExpanded(expanded === role.id ? null : role.id)}
              onCommitOrder={() => commitOrder(roles.filter((r) => r.editable))}
              onPatch={patchRole}
              onDeleted={(res) => { refresh(res.roles); setExpanded(null); }}
              onAddWithRole={onAddWithRole}
              onAssignMember={assignMember}
              busy={busy}
              notify={notify}
            />
          ))}
        </Reorder.Group>
      </div>

      <AnimatePresence mode="wait">
        {adding ? (
          <AddRoleForm
            key="form"
            onCancel={() => setAdding(false)}
            onCreated={(res) => { refresh(res.roles); setAdding(false); setExpanded(res.role.id); }}
            notify={notify}
          />
        ) : (
          <motion.button
            key="btn"
            className="btn role-add-btn"
            onClick={() => setAdding(true)}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.97 }}
          >
            <Icon name="plus" size={16} /> افزودن جایگاه جدید
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  );
}

function RoleRow({ role, allRoles, meta, members, expanded, onExpand, onCommitOrder,
                   onPatch, onDeleted, onAddWithRole, onAssignMember, busy, notify }) {
  const controls = useDragControls();
  const [name, setName] = useState(role.name);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [reassignTo, setReassignTo] = useState('');
  const [assignPick, setAssignPick] = useState('');

  const otherRoles = allRoles.filter((r) => r.editable && r.id !== role.id);
  const holders = (members || []).filter((m) => m.org_role?.id === role.id);
  const assignables = (members || []).filter((m) => m.org_role?.id !== role.id);
  const accesses = useMemo(() => {
    const map = {};
    (role.default_accesses || []).forEach((a) => { map[a.car_id] = a.documents || []; });
    return map;
  }, [role]);

  const toggleCar = (carId, docs) => {
    const next = { ...accesses };
    if (next[carId]) delete next[carId]; else next[carId] = docs;
    onPatch(role.id, {
      default_accesses: Object.entries(next).map(([car_id, documents]) => ({
        car_id: Number(car_id), documents,
      })),
    });
  };

  const doDelete = async () => {
    try {
      const res = await teamApi.deleteRole(role.id, reassignTo ? Number(reassignTo) : undefined);
      notify?.(`جایگاه «${role.name}» حذف شد.`);
      onDeleted(res);
    } catch (e) {
      notify?.(e?.message || 'حذف ناموفق بود.', 'error');
    }
  };

  return (
    <Reorder.Item
      value={role}
      as="div"
      dragListener={false}
      dragControls={controls}
      onDragEnd={onCommitOrder}
      layout
      transition={SPRING}
      whileDrag={{ scale: 1.03, boxShadow: '0 18px 40px rgba(0,0,0,0.35)', zIndex: 30 }}
      className={`role-row glass${expanded ? ' open' : ''}`}
    >
      <div className="role-row-head" onClick={onExpand}>
        <span
          className="role-grip"
          onPointerDown={(e) => { e.stopPropagation(); controls.start(e); }}
          title="بکشید تا جابجا شود"
        >
          <Icon name="grip" size={16} />
        </span>
        <span className="role-color" style={{ background: role.color || 'var(--accent)' }} />
        <span className="role-name">{role.name}</span>
        <span className="role-rank">رتبه {role.rank}</span>
        <span className="role-members">{role.members_count} عضو</span>
        <motion.span className="role-chev" animate={{ rotate: expanded ? 180 : 0 }} transition={SPRING}>
          <Icon name="chevron" size={15} />
        </motion.span>
      </div>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            className="role-body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
          >
            <div className="role-body-in">
              <div className="pform-grid">
                <div className="field">
                  <label>نام جایگاه</label>
                  <div className="role-name-edit">
                    <input value={name} onChange={(e) => setName(e.target.value)} />
                    {name.trim() && name.trim() !== role.name && (
                      <button className="btn btn-accent" disabled={busy}
                        onClick={() => onPatch(role.id, { name: name.trim() }, 'نام جایگاه ذخیره شد.')}>
                        ذخیره
                      </button>
                    )}
                  </div>
                </div>
                <div className="field">
                  <label>رنگ نشانه</label>
                  <div className="role-swatches">
                    {SWATCHES.map((c) => (
                      <motion.button
                        key={c}
                        className={`swatch${(role.color || '') === c ? ' on' : ''}`}
                        style={{ background: c }}
                        whileHover={{ scale: 1.2 }}
                        whileTap={{ scale: 0.9 }}
                        onClick={() => onPatch(role.id, { color: c })}
                        aria-label={`رنگ ${c}`}
                      />
                    ))}
                  </div>
                </div>
              </div>

              <div className="drawer-section-title">محدوده دسترسی در بخش کاربران</div>
              <div className="scope-picker">
                {SCOPES.map((s) => (
                  <motion.button
                    key={s.id}
                    className={`scope-opt${role.manage_scope === s.id ? ' on' : ''}`}
                    onClick={() => onPatch(role.id, { manage_scope: s.id })}
                    whileTap={{ scale: 0.97 }}
                  >
                    <b>{s.label}</b>
                    <span>{s.hint}</span>
                    {role.manage_scope === s.id && (
                      <motion.span layoutId={`scope-check-${role.id}`} className="scope-check">
                        <Icon name="check" size={13} />
                      </motion.span>
                    )}
                  </motion.button>
                ))}
              </div>

              <div className="drawer-section-title">قابلیت‌های پیش‌فرض اعضای این جایگاه</div>
              <div className="cap-row"><div><b>مدیریت تیم</b><span>افزودن و مدیریت اعضای پایین‌تر</span></div>
                <Switch checked={role.can_manage_team} onChange={(v) => onPatch(role.id, { can_manage_team: v })} /></div>
              <div className="cap-row"><div><b>مشاهده تحلیل‌ها</b><span>گزارش‌های استفاده تیم</span></div>
                <Switch checked={role.can_view_analytics} onChange={(v) => onPatch(role.id, { can_view_analytics: v })} /></div>
              <div className="cap-row"><div><b>دستیار هوشمند</b><span>چت‌بات فنی خودرو</span></div>
                <Switch checked={role.ai_assistant_enabled} onChange={(v) => onPatch(role.id, { ai_assistant_enabled: v })} /></div>

              <div className="drawer-section-title">اعضای این جایگاه</div>
              {holders.length > 0 ? (
                <div className="role-holder-chips">
                  {holders.map((m) => (
                    <span key={m.id} className="holder-chip">
                      <span className="dot" style={{ background: role.color || 'var(--accent)' }} />
                      {m.display_name || m.username}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="muted role-hint">این جایگاه هنوز عضوی ندارد.</p>
              )}
              <div className="role-assign-row">
                <button type="button" className="btn btn-accent" disabled={busy}
                  onClick={() => onAddWithRole?.(role.id)}>
                  <Icon name="plus" size={14} /> افزودن عضو جدید با این جایگاه
                </button>
                {assignables.length > 0 && (
                  <div className="role-assign-existing">
                    <select value={assignPick} onChange={(e) => setAssignPick(e.target.value)}>
                      <option value="">— انتقال عضو موجود به این جایگاه —</option>
                      {assignables.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.display_name || m.username} ({m.role_label})
                        </option>
                      ))}
                    </select>
                    <button type="button" className="btn" disabled={busy || !assignPick}
                      onClick={async () => { await onAssignMember?.(assignPick, role); setAssignPick(''); }}>
                      انتقال
                    </button>
                  </div>
                )}
              </div>

              <div className="drawer-section-title">الگوی دسترسی به خودروها</div>
              <p className="muted role-hint">
                خودروهایی که عضو جدیدِ این جایگاه به‌صورت خودکار دریافت می‌کند.
              </p>
              <div className="access-list">
                {(meta?.cars || []).map((c) => {
                  const on = !!accesses[c.id];
                  return (
                    <button type="button" key={c.id}
                      className={`access-chip${on ? ' on' : ''}`}
                      onClick={() => toggleCar(c.id, c.documents)}>
                      <Icon name={on ? 'check' : 'plus'} size={14} />
                      {c.brand} {c.model} {c.year}
                    </button>
                  );
                })}
                {(meta?.cars || []).length === 0 && (
                  <div className="muted">خودرویی برای واگذاری در دسترس نیست.</div>
                )}
              </div>

              <div className="role-actions">
                <motion.button
                  className="btn"
                  whileTap={{ scale: 0.96 }}
                  disabled={busy || !role.members_count}
                  onClick={async () => {
                    const res = await onPatch(role.id, { apply_defaults: true });
                    if (res) notify?.(`تنظیمات این جایگاه به ${res.applied} عضو اعمال شد.`);
                  }}
                >
                  <Icon name="refresh" size={15} /> اعمال به اعضای فعلی ({role.members_count})
                </motion.button>

                {!confirmDelete ? (
                  <button className="btn btn-danger" onClick={() => setConfirmDelete(true)} disabled={busy}>
                    <Icon name="trash" size={15} /> حذف جایگاه
                  </button>
                ) : (
                  <motion.div className="role-delete-confirm" initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }}>
                    {role.members_count > 0 && (
                      <select value={reassignTo} onChange={(e) => setReassignTo(e.target.value)}>
                        <option value="">— جایگاه جدید اعضا —</option>
                        {otherRoles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                      </select>
                    )}
                    <button className="btn btn-danger" disabled={busy || (role.members_count > 0 && !reassignTo)} onClick={doDelete}>
                      تأیید حذف
                    </button>
                    <button className="btn" onClick={() => setConfirmDelete(false)}>انصراف</button>
                  </motion.div>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </Reorder.Item>
  );
}

function AddRoleForm({ onCancel, onCreated, notify }) {
  const [name, setName] = useState('');
  const [scope, setScope] = useState('none');
  const [color, setColor] = useState(SWATCHES[3]);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    try {
      const res = await teamApi.createRole({
        name: name.trim(), manage_scope: scope, color,
        can_manage_team: scope !== 'none', can_view_analytics: scope !== 'none',
      });
      notify?.(`جایگاه «${name.trim()}» ساخته شد.`);
      onCreated(res);
    } catch (e) {
      notify?.(e?.message || 'ایجاد جایگاه ناموفق بود.', 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <motion.div
      className="role-add-form glass"
      initial={{ opacity: 0, y: 14, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 8, scale: 0.98 }}
      transition={SPRING}
    >
      <div className="field">
        <label>نام جایگاه جدید</label>
        <input autoFocus value={name} onChange={(e) => setName(e.target.value)}
          placeholder="مثلاً: کارشناس ارشد گارانتی"
          onKeyDown={(e) => e.key === 'Enter' && submit()} />
      </div>
      <div className="pform-grid">
        <div className="field">
          <label>محدوده دسترسی</label>
          <select value={scope} onChange={(e) => setScope(e.target.value)}>
            {SCOPES.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
        </div>
        <div className="field">
          <label>رنگ</label>
          <div className="role-swatches">
            {SWATCHES.map((c) => (
              <button key={c} className={`swatch${color === c ? ' on' : ''}`}
                style={{ background: c }} onClick={() => setColor(c)} aria-label={c} />
            ))}
          </div>
        </div>
      </div>
      <div className="role-actions">
        <button className="btn btn-accent" onClick={submit} disabled={busy || !name.trim()}>
          {busy ? 'در حال ایجاد…' : 'ایجاد جایگاه'}
        </button>
        <button className="btn" onClick={onCancel}>انصراف</button>
      </div>
      <p className="muted role-hint">جایگاه جدید در پایین فهرست ساخته می‌شود؛ با کشیدن، رتبه‌اش را تغییر دهید.</p>
    </motion.div>
  );
}
