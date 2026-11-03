// Lazy Cloudflare Turnstile for the first send. The script is loaded only when
// the panel first opens (never on page load); the widget is invisible
// ('interaction-only') and runs on demand; the token is single-use and only
// needed to create a thread. It reuses the login page's sitekey, which still
// has to be confirmed against the new action in staging (see the spec, 3.6).

export const DEFAULT_SITEKEY = '0x4AAAAAAEjnbFG2W2QYf-cE';
export const SCRIPT_SRC = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
const TIMEOUT_MS = 20000;

/**
 * `doc` is a document-like object; `getApi()` returns window.turnstile (injected
 * so tests can fake it). Methods return promises that reject with
 * {kind: 'blocked' | 'timeout' | 'failed'}.
 */
export function createTurnstile({ sitekey = DEFAULT_SITEKEY, doc, getApi, mount, setTimer = setTimeout, clearTimer = clearTimeout }) {
  let widgetId = null;
  let scriptPromise = null;
  let disposed = false;
  let pending = null;

  function load() {
    if (getApi()) return Promise.resolve();
    if (scriptPromise) return scriptPromise;
    scriptPromise = new Promise((resolve, reject) => {
      const existing = doc.querySelector?.('script[data-cf-turnstile]');
      const s = existing || doc.createElement('script');
      if (!existing) {
        s.src = SCRIPT_SRC;
        s.async = true;
        s.setAttribute('data-cf-turnstile', '1');
        doc.head.appendChild(s);
      }
      s.addEventListener('load', () => (getApi() ? resolve() : reject({ kind: 'blocked' })));
      s.addEventListener('error', () => {
        // A failed element never fires again: drop it so a retry loads a fresh one.
        s.remove?.();
        reject({ kind: 'blocked' });
      });
    }).catch((e) => { scriptPromise = null; throw e; });
    return scriptPromise;
  }

  function render() {
    if (widgetId !== null || disposed) return;
    widgetId = getApi().render(mount(), {
      sitekey,
      action: 'support_chat',
      appearance: 'interaction-only',
      execution: 'execute',
      callback: (token) => pending?.resolve(token),
      'error-callback': () => pending?.reject({ kind: 'failed' }),
      'expired-callback': () => pending?.reject({ kind: 'failed' }),
      'timeout-callback': () => pending?.reject({ kind: 'timeout' }),
    });
  }

  return {
    /** Load the script and render the idle widget. Safe to call repeatedly. */
    async prepare() {
      await load();
      render();
    },
    /** Resolve with a fresh single-use token. */
    async execute() {
      await this.prepare();
      if (disposed || widgetId === null) throw { kind: 'failed' };
      const api = getApi();
      return new Promise((resolve, reject) => {
        const timer = setTimer(() => { pending = null; reject({ kind: 'timeout' }); }, TIMEOUT_MS);
        pending = {
          resolve: (t) => { clearTimer(timer); pending = null; resolve(t); },
          reject: (e) => { clearTimer(timer); pending = null; reject(e); },
        };
        try { api.reset(widgetId); api.execute(widgetId); } catch { pending.reject({ kind: 'failed' }); }
      });
    },
    reset() {
      try { if (widgetId !== null) getApi()?.reset(widgetId); } catch { /* ignore */ }
    },
    dispose() {
      disposed = true;
      pending?.reject({ kind: 'failed' });
      try { if (widgetId !== null) getApi()?.remove(widgetId); } catch { /* ignore: already detached */ }
      widgetId = null;
    },
  };
}
