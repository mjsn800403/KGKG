// Kept out of lib/shield.js because that file is obfuscated at build time and
// Next.js must still see the literal process.env.NEXT_PUBLIC_API_BASE to inline it.
export const SHIELD_BASE = (process.env.NEXT_PUBLIC_API_BASE || '/kg-api').replace(/\/+$/, '');
