'use client';
// Content guard for signed-in document pages: discourages copying and makes
// leaks traceable. It cannot make copying impossible (screenshots, devtools);
// the real limits are server-side (api/contentguard.py: per-user page caps,
// scraping alerts, one session per account).
//
//  * blocks text selection, copy/cut, the context menu, image dragging and
//    Ctrl/Cmd+S/P/U on content pages (form fields keep working);
//  * hides the page when printing;
//  * draws a faint watermark with the viewer's username and the date across
//    the page, so a screenshot shows whose account it came from.
// Not active on the landing, login/recovery, purchase or admin pages.
import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';
import { getPortalUser } from '@/utils/api';

const OFF = [/^\/$/, /^\/login/, /^\/recover/, /^\/purchase/, /^\/invite/, /^\/admin/, /^\/admin-review/];
const EDITABLE = 'input, textarea, select, [contenteditable="true"]';

function watermarkUrl(text) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="360" height="200">`
    + `<text x="20" y="120" transform="rotate(-24 180 100)" font-family="sans-serif" font-size="15" `
    + `fill="rgba(128,128,128,0.20)">${text.replace(/[<>&"']/g, '')}</text></svg>`;
  return `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`;
}

export default function ContentGuard() {
  const path = usePathname() || '/';
  const [user, setUser] = useState(null);
  const active = !!user && !OFF.some((rx) => rx.test(path));

  useEffect(() => {
    const read = () => setUser(getPortalUser());
    const id = setTimeout(read, 0);   // after hydration: SSR never knows the user
    window.addEventListener('storage', read);
    return () => { clearTimeout(id); window.removeEventListener('storage', read); };
  }, [path]);

  useEffect(() => {
    if (!active) return undefined;
    const inField = (e) => e.target instanceof Element && e.target.closest(EDITABLE);
    const block = (e) => { if (!inField(e)) e.preventDefault(); };
    const keys = (e) => {
      const k = (e.key || '').toLowerCase();
      if ((e.ctrlKey || e.metaKey) && ['s', 'p', 'u'].includes(k)) e.preventDefault();
      if ((e.ctrlKey || e.metaKey) && ['c', 'x', 'a'].includes(k) && !inField(e)) e.preventDefault();
    };
    const evts = ['copy', 'cut', 'contextmenu', 'dragstart', 'selectstart'];
    evts.forEach((t) => document.addEventListener(t, block));
    document.addEventListener('keydown', keys);
    document.documentElement.classList.add('kg-guard');
    return () => {
      evts.forEach((t) => document.removeEventListener(t, block));
      document.removeEventListener('keydown', keys);
      document.documentElement.classList.remove('kg-guard');
    };
  }, [active]);

  if (!active) return null;
  const day = new Date().toLocaleDateString('fa-IR');
  const label = `${user.username || ''} · ${day} · KGTechVault`;
  return <div className="kg-watermark" aria-hidden="true" style={{ backgroundImage: watermarkUrl(label) }} />;
}
