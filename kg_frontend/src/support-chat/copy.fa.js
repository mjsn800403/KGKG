// All visitor-facing Persian copy for the support chat, in one place so it can
// be reviewed and changed without touching components. Every string here is a
// PROPOSAL until the owner approves the wording.
//
// Honesty rules (enforced by __tests__/copy.test.js): no staff names, no
// "typing" indicator, no promised reply time, and the staff label is the
// generic «پشتیبانی»; system lines are «سامانه».

export const LABELS = {
  staff: 'پشتیبانی',
  system: 'سامانه',
};

export const COPY = {
  launcher: 'گفتگو با ما',
  title: 'گفتگو با پشتیبانی',
  greeting: 'سلام، چه کمکی از ما برمی‌آید؟',
  close: 'بستن',
  menu: 'منوی گفتگو',
  newChat: 'گفتگوی جدید',
  privacy: 'حریم خصوصی',
  forget: 'حذف این گفتگو از این مرورگر',

  live: 'پشتیبانی آنلاین است',
  async: 'الان کسی پشت میز نیست',
  asyncHint: 'پیام شما ذخیره می‌شود و در اولین فرصت پاسخ می‌دهیم',
  unknown: 'وضعیت پشتیبانی نامشخص است',
  fellBack: 'هنوز کسی پاسخ نداده؛ پیام شما ذخیره شد',
  replyWithin: (n) => `معمولاً ظرف ${n} دقیقه`,

  starters: [
    { intent: 'sales', label: 'قیمت و خرید اشتراک', placeholder: 'دربارهٔ کدام اشتراک یا قیمت می‌پرسید؟' },
    { intent: 'demo', label: 'درخواست دمو', placeholder: 'چه کاری از دمو انتظار دارید؟' },
    { intent: 'technical', label: 'پرسش یا مشکل فنی', placeholder: 'مشکل را کوتاه شرح دهید' },
    { intent: 'other', label: 'سایر', placeholder: 'پیام خود را بنویسید' },
  ],

  placeholder: 'پیام خود را بنویسید',
  send: 'ارسال',
  counter: (n, max) => `${n} / ${max}`,

  sending: 'در حال ارسال',
  sent: 'ارسال شد',
  read: 'خوانده شد',
  failed: 'ارسال نشد',
  retry: 'تلاش دوباره',

  offline: 'اتصال برقرار نیست. پیام‌ها پس از اتصال ارسال می‌شوند',
  rateLimited: (s) => `کمی صبر کنید (${s} ثانیه)`,
  closedBar: 'این گفتگو بسته شده است',
  continueChat: 'ادامهٔ گفتگو',
  reopenExpired: 'مهلت ادامهٔ این گفتگو به پایان رسیده است',
  gone: 'این گفتگو دیگر در دسترس نیست. می‌توانید گفتگوی تازه‌ای شروع کنید.',
  securityFailed: 'تأیید امنیتی بارگذاری نشد',
  securityRetry: 'تلاش دوباره',
  generalError: 'مشکلی پیش آمد. دوباره تلاش کنید.',
  newMessage: 'پیام جدید',

  contactTitle: 'برای پیگیری، راه ارتباطی بگذارید (اختیاری)',
  contactName: 'نام',
  contactPhone: 'شمارهٔ موبایل',
  contactEmail: 'ایمیل',
  contactAdd: 'افزودن راه ارتباطی',
  contactSave: 'ثبت',
  contactSkip: 'فعلاً نه',
  contactSaved: 'اطلاعات تماس ثبت شد',
  privacyNotice:
    'پیام‌ها و اطلاعات تماسی که وارد می‌کنید برای پاسخ‌گویی، امنیت و بهبود پشتیبانی استفاده می‌شود و فقط در دسترس کارکنان مجاز است.',

  rateTitle: 'گفتگو چطور بود؟',
  rateThanks: 'ممنون از امتیاز شما',
  rateFaces: ['خیلی بد', 'بد', 'معمولی', 'خوب', 'عالی'],

  fallbackContacts: 'اگر گفتگو در دسترس نیست، با ما تماس بگیرید یا ایمیل بزنید.',
};
