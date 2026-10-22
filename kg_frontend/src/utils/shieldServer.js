// Server-only half of the content shield: seal document props during SSR so
// the HTML/RSC payload carries ciphertext, not the manual. Keys are derived
// exactly like api/shield.py (same KG_SHIELD_SECRET); the browser opens the
// blob with lib/shield.js. Returns null when the shield is off, and callers
// then pass the plain value as before.
import crypto from 'node:crypto';

const EPOCH = 600;

export function seal(token, value) {
  const secret = process.env.KG_SHIELD_SECRET || '';
  if (process.env.KG_SHIELD !== '1' || !secret || !token || value == null) return null;
  const th = crypto.createHash('sha256').update(token).digest('hex');
  const e = Math.floor(Date.now() / 1000 / EPOCH);
  const key = crypto.createHmac('sha256', secret).update(`enc|${th}|${e}`).digest();
  const iv = crypto.randomBytes(12);
  const c = crypto.createCipheriv('aes-256-gcm', key, iv);
  c.setAAD(Buffer.from('kg1'));
  const ct = Buffer.concat([c.update(JSON.stringify(value), 'utf8'), c.final(), c.getAuthTag()]);
  return { _kg: 1, e, iv: iv.toString('base64'), ct: ct.toString('base64') };
}

// Props for a client component: { [name]: value } when the shield is off,
// { sealed } when on.
export function sealProp(token, name, value) {
  const sealed = seal(token, value);
  return sealed ? { sealed } : { [name]: value };
}

// StackedContent: titles/ids stay readable for the contents list; the bodies
// travel as one sealed list in item order.
export function sealStack(token, payload) {
  const items = payload?.items || [];
  const sealed = seal(token, items.map((it) => it.content));
  if (!sealed) return { payload };
  return { payload: { ...payload, items: items.map((it) => ({ ...it, content: '' })) }, sealed };
}
