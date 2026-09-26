// Backend errors reach the UI as-is, and most of them are already Persian
// sentences written for the reader. The exceptions are transport failures
// ("fetch failed", "socket hang up") and other English developer strings,
// which say nothing to a technician in a workshop — those become one plain
// Persian sentence, and the original stays in the console/server log.
const TRANSPORT = /fetch failed|failed to fetch|networkerror|econnrefused|econnreset|etimedout|socket hang up|network request failed|timeout/i;

export function friendlyError(err, fallback = 'بارگذاری اطلاعات ناموفق بود.') {
  const msg = String(err?.message || err || '').trim();
  if (!msg) return fallback;
  if (TRANSPORT.test(msg)) {
    return 'ارتباط با سامانه برقرار نشد. اتصال اینترنت را بررسی کنید و دوباره تلاش کنید.';
  }
  // A message with no Persian letters is a developer string, not copy.
  if (!/[؀-ۿ]/.test(msg)) return fallback;
  return msg;
}
