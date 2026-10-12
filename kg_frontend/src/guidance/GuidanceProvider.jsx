'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import Icon from '../components/Icon';
import { getPortalUser, getAdminToken } from '../utils/api';
import { resolveAudience, autoTourFor, tourById, TOURS, audienceMatches } from './content';
import { tourSeen, markTourSeen, markHelpOpened } from './storage';
import TourEngine from './TourEngine';
import HelpCenter from './HelpCenter';
import HintLayer from './HintLayer';

// The single client root for the whole guidance layer. Mounted once in the app
// layout, it works across public, portal and admin surfaces. It:
//   * resolves the viewer's audience (role + capabilities) live;
//   * tracks the current surface (route + admin section) for context-sensitive help;
//   * owns the help panel, the guided tours, and the contextual hint layer;
//   * auto-starts each role's tour once, and lets it be replayed on demand;
//   * exposes a keyboard shortcut (?) and an always-present help button.
// Guidance is suppressed on auth screens so they stay clean.
const SUPPRESS = [/^\/login/, /^\/admin\/login/, /^\/invite\//];

export default function GuidanceProvider() {
  const pathname = usePathname() || '/';
  const router = useRouter();

  const [mounted, setMounted] = useState(false);
  const [portalUser, setPortalUser] = useState(null);
  const [hasAdmin, setHasAdmin] = useState(false);
  const [section, setSection] = useState(null);       // admin section id
  const [helpOpen, setHelpOpen] = useState(false);
  const [helpArticle, setHelpArticle] = useState(null);
  const [tour, setTour] = useState(null);             // active tour object
  const [pendingTour, setPendingTour] = useState(null);
  const [signals, setSignals] = useState({});

  // Refs so the auto-start effect can read live "is something already open"
  // state without listing it as a dependency (which would re-trigger it).
  const busyRef = useRef(false);
  useEffect(() => { busyRef.current = !!(tour || pendingTour || helpOpen); }, [tour, pendingTour, helpOpen]);

  // Mount + read the session; refresh on login/logout (kg:me) and cross-tab.
  useEffect(() => {
    setMounted(true);
    const readSession = () => {
      setPortalUser(getPortalUser());
      setHasAdmin(!!getAdminToken());
    };
    readSession();
    window.addEventListener('kg:me', readSession);
    window.addEventListener('storage', readSession);
    return () => {
      window.removeEventListener('kg:me', readSession);
      window.removeEventListener('storage', readSession);
    };
  }, []);

  // Admin section context: read the hash and listen for the explicit context
  // event the admin panel dispatches on section change (replaceState doesn't
  // fire hashchange).
  useEffect(() => {
    const read = () => {
      if (pathname.startsWith('/admin')) {
        const h = (typeof window !== 'undefined' ? window.location.hash : '').replace('#', '');
        setSection(h || null);
      } else {
        setSection(null);
      }
    };
    read();
    const onCtx = (e) => { if (e?.detail && 'section' in e.detail) setSection(e.detail.section || null); };
    window.addEventListener('hashchange', read);
    window.addEventListener('kg:guide-context', onCtx);
    return () => {
      window.removeEventListener('hashchange', read);
      window.removeEventListener('kg:guide-context', onCtx);
    };
  }, [pathname]);

  // Contextual-hint signals from around the app.
  useEffect(() => {
    const onSig = (e) => {
      const d = e?.detail;
      if (!d || !d.name) return;
      setSignals((s) => (s[d.name] === d.value ? s : { ...s, [d.name]: d.value }));
    };
    window.addEventListener('kg:guide-signal', onSig);
    return () => window.removeEventListener('kg:guide-signal', onSig);
  }, []);

  const audience = useMemo(
    () => resolveAudience({ pathname, portalUser, isAdmin: hasAdmin }),
    [pathname, portalUser, hasAdmin],
  );
  const suppressed = SUPPRESS.some((re) => re.test(pathname));

  const openHelp = useCallback((articleId = null) => {
    setHelpArticle(articleId);
    setHelpOpen(true);
    setTour(null); // opening help ends any running tour cleanly (no re-nag: unseen)
    try { markHelpOpened(); } catch { /* ignore */ }
  }, []);

  const toggleHelp = useCallback(() => {
    setHelpOpen((o) => {
      if (!o) { setHelpArticle(null); try { markHelpOpened(); } catch { /* ignore */ } }
      return !o;
    });
  }, []);

  const startTour = useCallback((tourId) => {
    const t = tourById(tourId);
    if (!t) return;
    setHelpOpen(false);
    if (t.autoRoute(pathname)) {
      setTour(t);
    } else {
      setPendingTour(tourId);
      if (t.route) router.push(t.route);
    }
  }, [pathname, router]);

  // Cancel a running tour the moment we leave its surface (client navigation,
  // login redirect, …). Cleared silently — NOT marked seen — so the tour stays
  // eligible to auto-start later on its proper surface. Without this a leftover
  // tour would render on the wrong page, gracefully self-close, and wrongly mark
  // the *current* role's onboarding as already seen.
  useEffect(() => {
    if (tour && !tour.autoRoute(pathname)) setTour(null);
  }, [tour, pathname]);

  // Start a pending (navigation-deferred) tour once we reach its route.
  useEffect(() => {
    if (!pendingTour) return undefined;
    const t = tourById(pendingTour);
    if (t && t.autoRoute(pathname)) {
      const id = setTimeout(() => { setTour(t); setPendingTour(null); }, 500);
      return () => clearTimeout(id);
    }
    return undefined;
  }, [pendingTour, pathname]);

  // Auto-start each role's tour once, on its matching surface.
  useEffect(() => {
    if (!mounted || suppressed || busyRef.current) return undefined;
    const t = autoTourFor(audience, pathname);
    if (t && !tourSeen(audience.role)) {
      const id = setTimeout(() => { if (!busyRef.current) setTour(t); }, 1300);
      return () => clearTimeout(id);
    }
    return undefined;
  }, [mounted, suppressed, audience, pathname]);

  // Keyboard: "?" toggles help; Esc closes it.
  useEffect(() => {
    const onKey = (e) => {
      const t = e.target;
      const typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable);
      if (e.key === '?' && !typing && !suppressed) { e.preventDefault(); toggleHelp(); }
      else if (e.key === 'Escape' && helpOpen) { setHelpOpen(false); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [helpOpen, suppressed, toggleHelp]);

  // Legacy/explicit restart hook (Settings "restart tour" dispatches kg:tour).
  useEffect(() => {
    const onTour = (e) => {
      const id = e?.detail?.tourId;
      if (id) { startTour(id); return; }
      const t = TOURS.find((x) => audienceMatches(x, audience));
      if (t) startTour(t.id);
    };
    window.addEventListener('kg:tour', onTour);
    return () => window.removeEventListener('kg:tour', onTour);
  }, [audience, startTour]);

  const closeTour = useCallback(() => {
    setTour(null);
    // Skipping or finishing both mark the role's tour seen — never re-nag.
    try { markTourSeen(audience.role); } catch { /* ignore */ }
  }, [audience.role]);

  if (!mounted || suppressed) return null;

  return (
    <>
      {/* FAB stays mounted during a tour (only hidden while help is open) so the
          admin tour's final step can spotlight it; the tour dim covers it on
          every other step. */}
      {!helpOpen && (
        <button
          type="button"
          className="guide-fab"
          aria-label="راهنما"
          title="راهنما (کلید ؟)"
          onClick={() => openHelp(null)}
        >
          <Icon name="question" />
        </button>
      )}
      <HelpCenter
        open={helpOpen}
        audience={audience}
        context={{ pathname, section }}
        initialArticleId={helpArticle}
        onClose={() => setHelpOpen(false)}
        onStartTour={startTour}
      />
      {/* key by tour id: a fresh TourEngine (idx=0) per tour — never renders a
          new tour at the previous tour's step index. */}
      {tour && <TourEngine key={tour.id} tour={tour} onClose={closeTour} />}
      <HintLayer
        audience={audience}
        pathname={pathname}
        section={section}
        signals={signals}
        onOpenHelp={openHelp}
        onStartTour={startTour}
      />
    </>
  );
}
