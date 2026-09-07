// instrumentation.ts
//
// Server-side error monitoring for the Next.js half of the app, reporting to
// the self-hosted GlitchTip instance over loopback.
//
// Why @sentry/node through Next's `instrumentation` hook rather than the
// @sentry/nextjs SDK: this app runs Next 16.2.9, and @sentry/nextjs does its
// work through a webpack/turbopack build plugin whose Next 16 support is still
// settling. `instrumentation.ts` + `onRequestError` are stable Next APIs, need
// no build-time plugin, and cover what actually matters here — unhandled
// errors in server components, route handlers, and above all /api/chat, which
// spends real money at Metis and previously failed silently.
//
// Deliberately NOT instrumenting the browser: that needs the client bundle and
// a tunnel route (GlitchTip is loopback-only and must stay that way), which is
// a lot of moving parts for errors we can already see server-side. Revisit if
// client-side JS faults become a real support burden.
//
// The whole thing is inert unless SENTRY_DSN is set.

export async function register() {
  if (!process.env.SENTRY_DSN) return;
  // Only the Node.js runtime — the edge runtime has no @sentry/node.
  if (process.env.NEXT_RUNTIME !== 'nodejs') return;

  const Sentry = await import('@sentry/node');

  Sentry.init({
    dsn: process.env.SENTRY_DSN,
    environment: process.env.SENTRY_ENVIRONMENT || 'production',
    release: process.env.KG_RELEASE || undefined,

    // Persian manual content and staff identifiers must not leave the box in
    // an error payload. In SDK v10 `sendDefaultPii: false` is what governs
    // this — the old `maxRequestBodySize` option no longer exists — and it
    // keeps request bodies, headers, cookies and user data off the event.
    sendDefaultPii: false,
    // Truncate anything unusually long rather than shipping a whole manual
    // page that happened to be in scope when something threw.
    maxValueLength: 2048,

    tracesSampleRate: Number(process.env.SENTRY_TRACES_RATE || 0),

    // No compression override needed here. The Python SDK had to be pinned to
    // gzip because it auto-selects Brotli when the `brotli` module is present
    // and GlitchTip 4.1.3 can't decompress it; the JS Node transport sends
    // envelopes uncompressed, so there's nothing to force.

    // Last-line scrub. `sendDefaultPii: false` already drops request bodies and
    // user data; this catches credentials that end up inside an exception
    // message or a logged URL.
    beforeSend(event) {
      const redact = (value?: string) =>
        typeof value === 'string'
          ? value
              .replace(
                /((?:secret|password|token|api[-_]?key|apikey|auth|key)["']?\s*[=:]\s*["']?)([^\s"'&,;}\]]{6,})/gi,
                '$1***redacted***',
              )
              .replace(/\b(Bearer|Token)\s+[A-Za-z0-9._-]{12,}/gi, '$1 ***redacted***')
          : value;

      if (event.message) event.message = redact(event.message)!;
      event.exception?.values?.forEach((v) => {
        if (v.value) v.value = redact(v.value)!;
      });
      if (event.request?.query_string && typeof event.request.query_string === 'string') {
        event.request.query_string = redact(event.request.query_string)!;
      }
      if (event.request?.headers) {
        for (const name of Object.keys(event.request.headers)) {
          if (/authorization|cookie|token|key|secret/i.test(name)) {
            event.request.headers[name] = '***redacted***';
          }
        }
      }
      return event;
    },
  });
}

// Next calls this for every error thrown while handling a request — server
// components, route handlers, middleware. Without it, those are logged to
// stdout and nowhere else.
export async function onRequestError(
  err: unknown,
  request: { path?: string; method?: string; headers?: Record<string, string> },
  context: { routerKind?: string; routePath?: string; routeType?: string },
) {
  if (!process.env.SENTRY_DSN) return;
  if (process.env.NEXT_RUNTIME !== 'nodejs') return;

  const Sentry = await import('@sentry/node');
  Sentry.withScope((scope) => {
    scope.setContext('nextjs', {
      path: request?.path,
      method: request?.method,
      routerKind: context?.routerKind,
      routePath: context?.routePath,
      routeType: context?.routeType,
    });
    Sentry.captureException(err);
  });
}
