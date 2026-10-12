// Server-side loader shared by the /frm pages: login redirect on 401, a
// readable Persian message for 403/404 instead of a crash.
import { notFound } from 'next/navigation';
import { fetchFrm } from '@/utils/api';
import { portalTokenCookie, redirectToLogin } from '@/utils/serverAuth';
import { frmSetBySlug } from '@/utils/frmSets';

export async function loadFrm(slug, part) {
  const set = frmSetBySlug(slug);
  if (!set) notFound();
  const token = await portalTokenCookie();
  if (!token) await redirectToLogin();
  let data = null;
  let status = 0;
  try {
    data = await fetchFrm(slug, part, token);
  } catch (e) {
    status = e?.status || 500;
  }
  // redirect() throws, so it must stay outside the try.
  if (status === 401) await redirectToLogin();
  const error = !status ? '' : status === 403
    ? 'دسترسی به مستندات این خودرو در اشتراک شما نیست. برای افزودن این خودرو با مدیر یا پشتیبانی تماس بگیرید.'
    : 'بارگذاری زمان استاندارد تعمیراتی ناموفق بود.';
  return { set, data, error };
}
