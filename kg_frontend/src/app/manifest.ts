import type { MetadataRoute } from 'next';

// Web app manifest: supplies the name and icon set a browser uses when the
// site is bookmarked to a home screen. `display: 'browser'` is deliberate —
// this is a documentation portal, not an installable app, so we take the
// icons without opting into standalone-window install prompts.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'KGTechVault — پلتفرم هوشمند دانش و مستندات فنی خودرو',
    short_name: 'KGTechVault',
    description: 'منوال تعمیر، نقشهٔ سیم‌کشی، زمان استاندارد و کاتالوگ قطعات، همراه با دستیار هوشمند فارسی.',
    lang: 'fa',
    dir: 'rtl',
    start_url: '/',
    display: 'browser',
    background_color: '#0B0C0F',
    theme_color: '#0B0C0F',
    icons: [
      { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
      { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
      { src: '/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
    ],
  };
}
