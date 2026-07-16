// Small localStorage layer for guidance state. Every read/write is guarded so a
// disabled/quota-full storage never breaks the UI (guidance is enhancement, not
// a hard dependency). Keys are namespaced under `kg-guide:`.

const PREFIX = 'kg-guide:';
const LEGACY_TOUR_DONE = 'kg-tour-done'; // set by the old SiteTour

function read(key, fallback = null) {
  try {
    const raw = localStorage.getItem(PREFIX + key);
    return raw == null ? fallback : JSON.parse(raw);
  } catch {
    return fallback;
  }
}
function write(key, value) {
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    /* ignore */
  }
}

// --- Tours: "seen once" per role -------------------------------------------
export function tourSeen(role) {
  if (read(`tour-done:${role}`, false)) return true;
  // Honour the legacy flag once so upgraders don't get the tour re-forced.
  try {
    if (localStorage.getItem(LEGACY_TOUR_DONE) && (role === 'user' || role === 'visitor')) return true;
  } catch { /* ignore */ }
  return false;
}
export function markTourSeen(role) {
  write(`tour-done:${role}`, true);
}

// --- Hints: dismissals with optional cooldown ------------------------------
// A permanently-dismissed hint stores `true`; a snoozed one stores an expiry
// timestamp (ms). `hintDismissed` treats a passed expiry as "show again".
export function hintDismissed(id) {
  const v = read(`hint:${id}`, false);
  if (v === true) return true;
  if (typeof v === 'number') return Date.now() < v;
  return false;
}
export function dismissHint(id, cooldownMs = 0) {
  write(`hint:${id}`, cooldownMs > 0 ? Date.now() + cooldownMs : true);
}
// How many times a hint has been shown (to cap noisy ones).
export function hintShownCount(id) {
  return read(`hint-shown:${id}`, 0);
}
export function bumpHintShown(id) {
  write(`hint-shown:${id}`, hintShownCount(id) + 1);
}

// --- Help center: has the user ever opened help? (used for a one-time nudge) -
export function helpEverOpened() {
  return read('help-opened', false);
}
export function markHelpOpened() {
  write('help-opened', true);
}
