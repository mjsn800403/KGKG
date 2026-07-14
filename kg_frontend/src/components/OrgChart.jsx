'use client';

// Interactive company org chart (RTL). Builds the tree from the flat
// /api/team/org/ payload (explicit reports_to edges). A manager can:
//   * collapse/expand branches,
//   * pick a member and MOVE them under a new supervisor (click-to-place:
//     tap "جابجایی", then tap the new parent — every valid target glows),
//   * change a member's position (role) inline,
//   * jump into the full edit drawer.
// All motion runs through `motion` springs; reduced-motion users get the
// static layout via the page-level <MotionConfig>.

import { useMemo, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import Icon from './Icon';
import { teamApi } from '../utils/api';

const SPRING = { type: 'spring', stiffness: 380, damping: 32, mass: 0.7 };

function initials(name = '') {
  const parts = String(name).trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return '؟';
  return (parts[0][0] + (parts[1]?.[0] || '')).toUpperCase();
}

function buildTree(members) {
  const byId = new Map(members.map((m) => [m.id, { ...m, children: [] }]));
  const roots = [];
  for (const node of byId.values()) {
    const parent = node.reports_to_id ? byId.get(node.reports_to_id) : null;
    if (parent && parent.id !== node.id) parent.children.push(node);
    else roots.push(node);
  }
  const byRank = (a, b) => (a.rank - b.rank) || a.name.localeCompare(b.name, 'fa');
  const sortRec = (n) => { n.children.sort(byRank); n.children.forEach(sortRec); };
  roots.sort(byRank);
  roots.forEach(sortRec);
  return roots;
}

function subtreeIds(node, acc = new Set()) {
  acc.add(node.id);
  node.children.forEach((c) => subtreeIds(c, acc));
  return acc;
}

export default function OrgChart({ data, onReload, onEditMember, onAddWithRole, notify }) {
  const [collapsed, setCollapsed] = useState(() => new Set());
  const [moving, setMoving] = useState(null);      // member being re-parented
  const [menuFor, setMenuFor] = useState(null);    // node id with the open menu
  const [busy, setBusy] = useState(false);

  const roots = useMemo(() => buildTree(data?.members || []), [data]);
  const movingSubtree = useMemo(() => {
    if (!moving) return new Set();
    const node = roots.length ? findNode(roots, moving.id) : null;
    return node ? subtreeIds(node) : new Set([moving.id]);
  }, [moving, roots]);

  function findNode(nodes, id) {
    for (const n of nodes) {
      if (n.id === id) return n;
      const hit = findNode(n.children, id);
      if (hit) return hit;
    }
    return null;
  }

  const toggle = (id) => setCollapsed((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  // A supervisor must hold a STRICTLY higher position — the chart only ever
  // points upward (matches the server-side rule).
  const canReceive = (node) =>
    moving && !movingSubtree.has(node.id) && node.rank < (moving.rank ?? 99);

  const placeUnder = async (target) => {
    if (!moving || busy) return;
    setBusy(true);
    try {
      await teamApi.updateMember(moving.id, {
        reports_to_id: target.is_self ? null : target.id,
      });
      notify?.(`«${moving.name}» زیرمجموعه «${target.name}» شد.`);
      setMoving(null);
      await onReload?.();
    } catch (e) {
      notify?.(e?.message || 'جابجایی ناموفق بود.', 'error');
    } finally {
      setBusy(false);
    }
  };

  const changeRole = async (member, roleId) => {
    if (busy) return;
    setBusy(true);
    try {
      const res = await teamApi.updateMember(member.id, { org_role_id: roleId });
      setMenuFor(null);
      await onReload?.();
      const adj = res?.adjustments || {};
      let msg = `جایگاه «${member.name}» تغییر کرد.`;
      if (adj.caps_reseeded) msg += ' دسترسی‌ها مطابق جایگاه جدید تنظیم شد.';
      if (adj.reparented > 0) msg += ` ${adj.reparented} خط گزارش‌دهی اصلاح شد.`;
      notify?.(msg);
    } catch (e) {
      notify?.(e?.message || 'تغییر نقش ناموفق بود.', 'error');
    } finally {
      setBusy(false);
    }
  };

  if (!data) return null;
  const assignableRoles = (data.roles || []).filter((r) => r.editable);
  const emptyRoles = assignableRoles.filter((r) => !r.members_count);

  return (
    <div className="orgchart-wrap">
      <AnimatePresence>
        {moving && (
          <motion.div
            className="org-move-banner glass"
            initial={{ opacity: 0, y: -14, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -14, scale: 0.97 }}
            transition={SPRING}
          >
            <span className="omb-pulse" />
            سرپرست جدیدِ «<b>{moving.name}</b>» را انتخاب کنید — کارت‌های روشن مجاز هستند.
            <button className="btn" onClick={() => setMoving(null)}>انصراف</button>
          </motion.div>
        )}
      </AnimatePresence>

      {(data.roles || []).length > 0 && (
        <div className="org-legend glass">
          {(data.roles || []).map((r) => (
            <span key={r.id} className="org-legend-chip">
              <span className="dot" style={{ background: r.color || 'var(--accent)' }} />
              {r.name}
              <b>{r.members_count}</b>
            </span>
          ))}
        </div>
      )}

      <div className="orgchart-scroll">
        <ul className="org-tree org-root">
          {roots.map((node) => (
            <OrgNode
              key={node.id}
              node={node}
              depth={0}
              collapsed={collapsed}
              onToggle={toggle}
              moving={moving}
              canReceive={canReceive}
              onPlace={placeUnder}
              menuFor={menuFor}
              setMenuFor={setMenuFor}
              onStartMove={(m) => { setMenuFor(null); setMoving(m); }}
              onChangeRole={changeRole}
              onEditMember={onEditMember}
              assignableRoles={assignableRoles}
              busy={busy}
            />
          ))}
        </ul>
      </div>

      {emptyRoles.length > 0 && (
        <div className="org-ghosts">
          <div className="org-ghosts-title">
            <Icon name="layers" size={15} /> جایگاه‌های بدون عضو
          </div>
          <div className="org-ghosts-grid">
            {emptyRoles.map((r) => (
              <motion.div
                key={r.id}
                className="ghost-card glass"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                style={{ '--node-accent': r.color || 'var(--accent)' }}
              >
                <span className="org-accent" />
                <div className="ghost-id">
                  <div className="ghost-name">{r.name}</div>
                  <div className="ghost-rank muted">رتبه {r.rank} — هنوز عضوی ندارد</div>
                </div>
                <button className="btn ghost-add" onClick={() => onAddWithRole?.(r.id)}>
                  <Icon name="plus" size={14} /> افزودن عضو
                </button>
              </motion.div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function OrgNode({
  node, depth, collapsed, onToggle, moving, canReceive, onPlace,
  menuFor, setMenuFor, onStartMove, onChangeRole, onEditMember,
  assignableRoles, busy,
}) {
  const isCollapsed = collapsed.has(node.id);
  const receivable = canReceive(node);
  const dimmed = moving && !receivable && !node.is_self;
  const accent = node.color || 'var(--accent)';

  return (
    <li className="org-li">
      <motion.div
        layout
        transition={SPRING}
        initial={{ opacity: 0, y: 14, scale: 0.96 }}
        animate={{ opacity: dimmed ? 0.35 : 1, y: 0, scale: 1 }}
        whileHover={!moving ? { y: -3 } : undefined}
        className={[
          'org-node glass',
          node.is_self ? 'is-self' : '',
          receivable ? 'receivable' : '',
          moving?.id === node.id ? 'is-moving' : '',
        ].join(' ')}
        style={{ '--node-accent': accent }}
        onClick={() => {
          if (moving) { if (receivable) onPlace(node); return; }
          setMenuFor(menuFor === node.id ? null : node.id);
        }}
      >
        <span className="org-accent" />
        <div className="org-avatar" style={{ background: `color-mix(in srgb, ${accent} 22%, transparent)` }}>
          {initials(node.name)}
        </div>
        <div className="org-id">
          <div className="org-name">
            {node.name}
            {node.is_self && <span className="org-you">شما</span>}
            {node.invite_status === 'invited' && <span className="org-pending">در انتظار</span>}
            {!node.active && <span className="org-off">غیرفعال</span>}
          </div>
          <div className="org-role" style={{ color: accent }}>{node.role_label}</div>
        </div>
        {node.children.length > 0 && (
          <motion.button
            className="org-collapse"
            onClick={(e) => { e.stopPropagation(); onToggle(node.id); }}
            animate={{ rotate: isCollapsed ? 180 : 0 }}
            transition={SPRING}
            aria-label={isCollapsed ? 'باز کردن زیرمجموعه' : 'بستن زیرمجموعه'}
          >
            <Icon name="chevron" size={14} />
            <span className="org-count">{node.children.length}</span>
          </motion.button>
        )}

        <AnimatePresence>
          {menuFor === node.id && !moving && (
            <motion.div
              className="org-menu glass"
              initial={{ opacity: 0, scale: 0.9, y: 6 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.94, y: 6 }}
              transition={{ type: 'spring', stiffness: 480, damping: 30 }}
              onClick={(e) => e.stopPropagation()}
            >
              {!node.is_self && (
                <>
                  <button className="org-menu-item" disabled={busy}
                    onClick={() => onStartMove(node)}>
                    <Icon name="org" size={14} /> جابجایی در چارت
                  </button>
                  {assignableRoles.length > 0 && (
                    <div className="org-menu-roles">
                      <div className="org-menu-label">تغییر جایگاه:</div>
                      {assignableRoles.map((r) => (
                        <button
                          key={r.id}
                          className={`org-menu-role${r.id === node.role_id ? ' current' : ''}`}
                          disabled={busy || r.id === node.role_id}
                          onClick={() => onChangeRole(node, r.id)}
                        >
                          <span className="dot" style={{ background: r.color || 'var(--accent)' }} />
                          {r.name}
                        </button>
                      ))}
                    </div>
                  )}
                  <button className="org-menu-item" disabled={busy}
                    onClick={() => { setMenuFor(null); onEditMember?.(node); }}>
                    <Icon name="edit" size={14} /> ویرایش کامل
                  </button>
                </>
              )}
              {node.is_self && <div className="org-menu-label">این کارت خودِ شماست.</div>}
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>

      <AnimatePresence initial={false}>
        {node.children.length > 0 && !isCollapsed && (
          <motion.ul
            className="org-tree"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.34, ease: [0.22, 1, 0.36, 1] }}
          >
            {node.children.map((child) => (
              <OrgNode
                key={child.id}
                node={child}
                depth={depth + 1}
                collapsed={collapsed}
                onToggle={onToggle}
                moving={moving}
                canReceive={canReceive}
                onPlace={onPlace}
                menuFor={menuFor}
                setMenuFor={setMenuFor}
                onStartMove={onStartMove}
                onChangeRole={onChangeRole}
                onEditMember={onEditMember}
                assignableRoles={assignableRoles}
                busy={busy}
              />
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
    </li>
  );
}
