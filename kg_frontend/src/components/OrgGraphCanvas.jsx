'use client';

// n8n-style org canvas. The graph IS the org structure: nodes are people/seats,
// each connected to its parent (a purely visual reporting line). Only the
// occupant of the root node (the company super-admin) may edit — create users,
// assign them, and set each node's car-database access + AI eligibility.
// Everyone else sees the same graph read-only, with their own node highlighted.

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ReactFlow, Background, Controls, Handle, Position,
  useNodesState, useEdgesState,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  orgGraph, orgCreateNode, orgUpdateNode, orgDeleteNode,
  orgSetPermission, orgCreateUser,
} from '@/utils/api';
import { useVehicleFilter } from './VehicleFilter';

const GAP_X = 210;
const GAP_Y = 165;
const SNAP = [15, 15];

// ---- custom node -----------------------------------------------------------
function SeatNode({ data }) {
  const occ = data.occupant;
  const horizontal = data.dir === 'h';
  return (
    <div className={`seat-node${data.isRoot ? ' seat-root' : ''}${data.isMine ? ' seat-mine' : ''}${data.selected ? ' seat-selected' : ''}`}>
      <Handle type="target" position={horizontal ? Position.Right : Position.Top} />
      <div className="seat-name">
        {occ ? (occ.display_name || occ.username) : <span className="seat-empty">بدون کاربر</span>}
      </div>
      {data.label && <div className="seat-role">{data.label}</div>}
      {data.isRoot && <div className="seat-badge">مدیر ارشد</div>}
      <Handle type="source" position={horizontal ? Position.Left : Position.Bottom} />
    </div>
  );
}
const nodeTypes = { seat: SeatNode };

// Tidy tree layout: children are centred under (or beside) their parent.
function tidyLayout(list, dir) {
  const children = new Map();
  list.forEach((n) => {
    if (n.parent_id != null) {
      if (!children.has(n.parent_id)) children.set(n.parent_id, []);
      children.get(n.parent_id).push(n.id);
    }
  });
  const pos = {};
  let cursor = 0;
  const walk = (id, depth) => {
    const kids = children.get(id) || [];
    let main;
    if (!kids.length) {
      main = cursor * GAP_X;
      cursor += 1;
    } else {
      const xs = kids.map((k) => walk(k, depth + 1));
      main = (Math.min(...xs) + Math.max(...xs)) / 2;
    }
    // `main` is the cross-axis offset; `depth` is the flow axis.
    pos[id] = dir === 'h'
      ? { x: -depth * (GAP_X + 40), y: main }
      : { x: main, y: depth * GAP_Y };
    return main;
  };
  const root = list.find((n) => n.is_root);
  if (root) walk(root.id, 0);
  list.filter((n) => !n.is_root && n.parent_id == null).forEach((o) => walk(o.id, 1));
  return pos;
}

export default function OrgGraphCanvas() {
  const [graph, setGraph] = useState(null);
  const [err, setErr] = useState('');
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState(null);
  const [dir, setDir] = useState('v');           // 'v' top-down | 'h' right-to-left
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const canEdit = graph?.can_edit;

  const load = useCallback(async () => {
    try {
      const g = await orgGraph();
      setGraph(g);
      setErr('');
    } catch (e) {
      setErr(e.message || 'خطا در بارگذاری');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!graph) return;
    setNodes(graph.nodes.map((n) => ({
      id: String(n.id),
      type: 'seat',
      position: { x: n.x, y: n.y },
      draggable: canEdit && !n.is_root,
      data: {
        label: n.label, occupant: n.occupant, isRoot: n.is_root, dir,
        isMine: n.id === graph.my_node_id, selected: n.id === selectedId,
      },
    })));
    setEdges(graph.nodes.filter((n) => n.parent_id).map((n) => ({
      id: `e${n.parent_id}-${n.id}`,
      source: String(n.parent_id), target: String(n.id),
      type: 'smoothstep',
    })));
  }, [graph, selectedId, canEdit, dir, setNodes, setEdges]);

  const selected = useMemo(
    () => graph?.nodes.find((n) => n.id === selectedId) || null, [graph, selectedId]);

  const guard = useCallback(async (fn) => {
    try { await fn(); await load(); setErr(''); }
    catch (e) { setErr(e.message || 'خطا'); }
  }, [load]);

  const onNodeDragStop = useCallback((_e, node) => {
    if (!canEdit) return;
    guard(() => orgUpdateNode(node.id, { x: node.position.x, y: node.position.y }));
  }, [canEdit, guard]);

  const onConnect = useCallback((params) => {
    if (!canEdit) return;
    guard(() => orgUpdateNode(params.target, { parent_id: Number(params.source) }));
  }, [canEdit, guard]);

  // New node hangs off the SELECTED node (so any depth is reachable), else root.
  const addNode = useCallback((parentId) => {
    if (!canEdit || !graph) return;
    const parent = graph.nodes.find((n) => n.id === parentId)
      || graph.nodes.find((n) => n.is_root);
    const siblings = graph.nodes.filter((n) => n.parent_id === parent?.id).length;
    guard(() => orgCreateNode({
      label: '', parent_id: parent?.id ?? null,
      x: (parent?.x ?? 0) + (dir === 'h' ? -(GAP_X + 40) : (siblings - 1) * GAP_X),
      y: (parent?.y ?? 0) + (dir === 'h' ? (siblings - 1) * 90 : GAP_Y),
    }));
  }, [canEdit, graph, dir, guard]);

  const autoArrange = useCallback(async () => {
    if (!canEdit || !graph) return;
    const pos = tidyLayout(graph.nodes, dir);
    try {
      await Promise.all(graph.nodes
        .filter((n) => pos[n.id])
        .map((n) => orgUpdateNode(n.id, { x: pos[n.id].x, y: pos[n.id].y })));
      await load();
    } catch (e) { setErr(e.message); }
  }, [canEdit, graph, dir, load]);

  const seatCapLabel = graph?.seat_cap != null
    ? `${graph.seats_used}/${graph.seat_cap} کاربر`
    : `${graph?.seats_used ?? 0} کاربر`;
  const capReached = graph?.seat_cap != null && graph.seats_used >= graph.seat_cap;

  if (loading) return <div className="org-loading">در حال بارگذاری ساختار…</div>;
  if (err && !graph) return <div className="org-error">{err}</div>;

  return (
    <div className="org-wrap" dir="rtl">
      <div className="org-toolbar">
        {canEdit ? (
          <>
            <button className="org-btn primary" onClick={() => addNode(selectedId)}
              disabled={capReached}>
              + افزودن کاربر{selected && !selected.is_root ? ' (زیرمجموعه)' : ''}
            </button>
            <button className="org-btn" onClick={autoArrange}>مرتب‌سازی خودکار</button>
            <div className="org-dirs">
              <button className={`org-btn sm${dir === 'v' ? ' on' : ''}`}
                onClick={() => setDir('v')}>عمودی</button>
              <button className={`org-btn sm${dir === 'h' ? ' on' : ''}`}
                onClick={() => setDir('h')}>افقی</button>
            </div>
            <span className={`org-cap${capReached ? ' full' : ''}`}>{seatCapLabel}</span>
            {capReached && <span className="org-cap-warn">به سقف مجاز رسیده‌اید</span>}
          </>
        ) : (
          <span className="org-readonly">نمای فقط‌خواندنی — تنها مدیر ارشد می‌تواند ویرایش کند</span>
        )}
        {err && <span className="org-error inline">{err}</span>}
      </div>

      <div className="org-canvas">
        <ReactFlow
          nodes={nodes} edges={edges} nodeTypes={nodeTypes}
          onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
          onNodeDragStop={onNodeDragStop} onConnect={onConnect}
          onNodeClick={(_e, n) => setSelectedId(Number(n.id))}
          onPaneClick={() => setSelectedId(null)}
          snapToGrid snapGrid={SNAP} fitView
          nodesConnectable={!!canEdit} elementsSelectable
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={30} size={1} />
          <Controls showInteractive={false} position="bottom-left" />
        </ReactFlow>

        {selected && (
          <NodePanel
            key={selected.id}
            node={selected} graph={graph} canEdit={canEdit}
            onClose={() => setSelectedId(null)}
            onAddChild={() => addNode(selected.id)}
            capReached={capReached}
            onChanged={load} setErr={setErr}
          />
        )}
      </div>
    </div>
  );
}

// ---- side panel ------------------------------------------------------------
function NodePanel({ node, graph, canEdit, onClose, onAddChild, capReached, onChanged, setErr }) {
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState('person');      // person | access
  const [label, setLabel] = useState(node.label || '');
  const [ai, setAi] = useState(!!node.permission.ai_eligible);
  const [access, setAccess] = useState(() => {
    const m = {};
    for (const row of node.permission.car_access || []) m[row.car_id] = new Set(row.documents || []);
    return m;
  });
  const [form, setForm] = useState({ display_name: '', phone: '', username: '', password: '' });
  const [creds, setCreds] = useState(null);
  const readonly = !canEdit;

  const guard = async (fn) => {
    setBusy(true);
    try { const r = await fn(); await onChanged(); return r; }
    catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  };

  const saveLabel = () => guard(() => orgUpdateNode(node.id, { label }));
  const assign = (uid) => guard(() => orgUpdateNode(node.id, { occupant_id: uid }));
  const vacate = () => guard(() => orgUpdateNode(node.id, { occupant_id: null }));
  const setParent = (pid) => guard(() => orgUpdateNode(node.id, { parent_id: pid || null }));
  const del = () => {
    if (confirm('این گره حذف شود؟ زیرمجموعه‌ها به گره بالادست منتقل می‌شوند.')) {
      guard(() => orgDeleteNode(node.id)).then(onClose);
    }
  };

  const createUser = () => guard(async () => {
    const r = await orgCreateUser(node.id, form);
    if (r?.credentials) setCreds(r.credentials);
    setForm({ display_name: '', phone: '', username: '', password: '' });
  });

  // Same filtering surface as every other vehicle list on the platform —
  // narrowed by brand/model/year, plus "what has this seat already got?".
  const { filtered: cars, bar: carFilterBar } = useVehicleFilter(graph.company_cars, {
    dense: true,
    searchPlaceholder: 'جستجوی خودرو…',
    facets: [
      {
        id: 'granted',
        label: 'دسترسی',
        options: [
          { id: 'on', label: 'انتخاب‌شده', test: (c) => !!access[c.car_id] },
          { id: 'off', label: 'انتخاب‌نشده', test: (c) => !access[c.car_id] },
        ],
      },
    ],
  });

  const toggleCar = (carId) => setAccess((prev) => {
    const next = { ...prev };
    if (next[carId]) delete next[carId]; else next[carId] = new Set();
    return next;
  });
  const togglePkg = (carId, pkg) => setAccess((prev) => {
    const next = { ...prev };
    const s = new Set(next[carId] || []);
    if (s.has(pkg)) s.delete(pkg); else s.add(pkg);
    next[carId] = s;
    return next;
  });
  // Bulk actions follow the filter: "select all" after narrowing to 2025 RAV4
  // must mean those, not the whole purchase.
  const allCars = () => setAccess((prev) => {
    const next = { ...prev };
    cars.forEach((c) => { if (!next[c.car_id]) next[c.car_id] = new Set(); });
    return next;
  });
  const noCars = () => setAccess((prev) => {
    const next = { ...prev };
    cars.forEach((c) => delete next[c.car_id]);
    return next;
  });

  const savePerm = () => guard(() => orgSetPermission(node.id, {
    ai_eligible: ai,
    car_access: Object.entries(access).map(([cid, set]) => ({
      car_id: Number(cid), documents: [...set],
    })),
  }));

  // Brand bulk-select — same affordance as the admin access editor, so both
  // screens grant access the same way.
  const brands = useMemo(() => {
    const m = new Map();
    graph.company_cars.forEach((c) => m.set(c.brand, (m.get(c.brand) || 0) + 1));
    return [...m.entries()].sort((a, b) => String(a[0]).localeCompare(String(b[0])));
  }, [graph.company_cars]);

  const brandOn = (brand) => {
    const ids = graph.company_cars.filter((c) => c.brand === brand).map((c) => c.car_id);
    return ids.length > 0 && ids.every((id) => access[id]);
  };

  const toggleBrand = (brand) => setAccess((prev) => {
    const ids = graph.company_cars.filter((c) => c.brand === brand).map((c) => c.car_id);
    const next = { ...prev };
    if (ids.every((id) => next[id])) ids.forEach((id) => delete next[id]);
    else ids.forEach((id) => { if (!next[id]) next[id] = new Set(); });
    return next;
  });

  const parents = graph.nodes.filter((n) => n.id !== node.id);

  return (
    <aside className="org-panel" dir="rtl">
      <header className="org-panel-head">
        <div>
          <b>{node.occupant ? (node.occupant.display_name || node.occupant.username) : 'گره خالی'}</b>
          <div className="org-panel-sub">{node.is_root ? 'مدیر ارشد سازمان' : (node.label || 'بدون سمت')}</div>
        </div>
        <button className="org-x" onClick={onClose} aria-label="بستن">×</button>
      </header>

      <nav className="org-tabs">
        <button className={tab === 'person' ? 'on' : ''} onClick={() => setTab('person')}>کاربر و جایگاه</button>
        {!node.is_root &&
          <button className={tab === 'access' ? 'on' : ''} onClick={() => setTab('access')}>دسترسی‌ها</button>}
      </nav>

      <div className="org-panel-body">
        {tab === 'person' && (
          <>
            <label className="org-field">
              <span>سمت</span>
              <input value={label} disabled={readonly || node.is_root}
                onChange={(e) => setLabel(e.target.value)} placeholder="مثلاً سرپرست فنی" />
            </label>
            {!readonly && !node.is_root &&
              <button className="org-btn" onClick={saveLabel} disabled={busy}>ذخیره سمت</button>}

            {!readonly && !node.is_root && (
              <label className="org-field">
                <span>زیرمجموعهٔ</span>
                <select className="org-select" value={node.parent_id || ''} disabled={busy}
                  onChange={(e) => setParent(Number(e.target.value) || null)}>
                  <option value="">— بدون والد —</option>
                  {parents.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.occupant ? (p.occupant.display_name || p.occupant.username) : (p.label || `گره ${p.id}`)}
                    </option>
                  ))}
                </select>
              </label>
            )}

            <section className="org-sec">
              <div className="org-sec-t">کاربر این گره</div>
              {node.occupant ? (
                <div className="org-occ">
                  <div>
                    <b>{node.occupant.display_name || node.occupant.username}</b>
                    <div className="org-panel-sub ltr">{node.occupant.username}</div>
                  </div>
                  {!readonly && !node.is_root &&
                    <button className="org-btn ghost" onClick={vacate} disabled={busy}>برداشتن</button>}
                </div>
              ) : readonly ? <span className="seat-empty">بدون کاربر</span> : (
                <>
                  <div className="org-sec-t sm">انتخاب از کاربران شرکت</div>
                  <select className="org-select" disabled={busy} defaultValue=""
                    onChange={(e) => e.target.value && assign(Number(e.target.value))}>
                    <option value="" disabled>یک کاربر انتخاب کنید…</option>
                    {graph.employees.map((u) => (
                      <option key={u.id} value={u.id}>
                        {(u.display_name || u.username)}
                        {u.seated_node_id ? ' — هم‌اکنون در گره دیگر' : ''}
                      </option>
                    ))}
                  </select>
                  <div className="org-hint">انتخاب کاربری که در گره دیگری نشسته، او را به این گره منتقل می‌کند.</div>

                  <div className="org-sec-t sm" style={{ marginTop: 10 }}>یا ساخت کاربر جدید</div>
                  <input className="org-select" placeholder="نام و نام خانوادگی *" value={form.display_name}
                    onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
                  <input className="org-select ltr" placeholder="شماره موبایل * (09xxxxxxxxx)" value={form.phone}
                    onChange={(e) => setForm({ ...form, phone: e.target.value })} />
                  <input className="org-select ltr" placeholder="نام کاربری (اختیاری)" value={form.username}
                    onChange={(e) => setForm({ ...form, username: e.target.value })} />
                  <input className="org-select ltr" placeholder="رمز عبور (خالی = خودکار)" value={form.password}
                    onChange={(e) => setForm({ ...form, password: e.target.value })} />
                  <button className="org-btn primary" onClick={createUser}
                    disabled={busy || !form.display_name.trim() || !form.phone.trim()}>ساخت کاربر</button>
                  {creds && (
                    <div className="org-creds">
                      <div>کاربر ساخته شد — این اطلاعات را ذخیره کنید:</div>
                      <div className="ltr"><b>{creds.username}</b> / <b>{creds.password}</b></div>
                    </div>
                  )}
                </>
              )}
            </section>

            {!readonly && (
              <section className="org-sec">
                <button className="org-btn" onClick={onAddChild} disabled={busy || capReached}>
                  + افزودن زیرمجموعه به این گره
                </button>
                {!node.is_root &&
                  <button className="org-btn danger" onClick={del} disabled={busy}>حذف این گره</button>}
              </section>
            )}
          </>
        )}

        {tab === 'access' && !node.is_root && (
          <>
            <label className="org-check">
              <input type="checkbox" checked={ai} disabled={readonly}
                onChange={(e) => setAi(e.target.checked)} />
              <span>دستیار هوش مصنوعی</span>
            </label>

            <div className="org-sec-t">دیتابیس خودروها</div>
            {!readonly && (
              <>
                <div className="org-bulk">
                  <button className="org-btn sm" onClick={allCars}>
                    انتخاب {cars.length === graph.company_cars.length ? 'همه' : `${cars.length} نتیجه`}
                  </button>
                  <button className="org-btn sm" onClick={noCars}>
                    حذف {cars.length === graph.company_cars.length ? 'همه' : 'نتایج'}
                  </button>
                </div>
                {brands.length > 1 && (
                  <div className="org-bulk wrap">
                    <span className="org-hint">بر اساس برند:</span>
                    {brands.map(([brand, n]) => (
                      <button key={brand} type="button"
                        className={`org-btn sm${brandOn(brand) ? ' on' : ''}`}
                        onClick={() => toggleBrand(brand)}>{brand} ({n})</button>
                    ))}
                  </div>
                )}
              </>
            )}
            {carFilterBar}
            <div className="org-cars">
              {cars.map((c) => {
                const on = !!access[c.car_id];
                return (
                  <div key={c.car_id} className={`org-car${on ? ' on' : ''}`}>
                    <label className="org-check">
                      <input type="checkbox" checked={on} disabled={readonly}
                        onChange={() => toggleCar(c.car_id)} />
                      <span>{c.label}</span>
                    </label>
                    {on && (
                      <div className="org-pkgs">
                        {graph.packages.map((p) => (
                          <label key={p.id} className="org-pkg">
                            <input type="checkbox" disabled={readonly}
                              checked={access[c.car_id].has(p.id)}
                              onChange={() => togglePkg(c.car_id, p.id)} />
                            <span>{p.label}</span>
                          </label>
                        ))}
                        <div className="org-hint">بدون انتخاب لایه = همه لایه‌ها</div>
                      </div>
                    )}
                  </div>
                );
              })}
              {!graph.company_cars.length &&
                <div className="org-hint">شرکت خودرویی خریداری نکرده است.</div>}
              {!!graph.company_cars.length && !cars.length &&
                <div className="org-hint">خودرویی مطابق فیلتر یافت نشد.</div>}
            </div>
          </>
        )}
      </div>

      {tab === 'access' && !readonly && !node.is_root && (
        <footer className="org-panel-foot">
          <button className="org-btn primary" onClick={savePerm} disabled={busy}>
            {busy ? 'در حال ذخیره…' : 'ذخیره دسترسی‌ها'}
          </button>
        </footer>
      )}
    </aside>
  );
}
