// Lightweight, decoupled channel for components to feed the contextual-hint
// engine without importing the provider. A component calls reportSignal when it
// learns something the hint rules care about (e.g. "the team has 0 members");
// the GuidanceProvider listens and re-evaluates. Safe to call from anywhere on
// the client; a no-op on the server.
export function reportSignal(name, value) {
  try {
    window.dispatchEvent(new CustomEvent('kg:guide-signal', { detail: { name, value } }));
  } catch {
    /* SSR / no window */
  }
}
