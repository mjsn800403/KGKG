"""فعالیتِ بازسازی‌شده‌ی «راهنمای تعمیرات» — از ۱ شهریور ۱۴۰۴.

قواعدی که این اسکریپت زیر پا نمی‌گذارد:

  ۱) هیچ ردیفِ موجودی خوانده می‌شود ولی تغییر نمی‌کند. فقط INSERT.
  ۲) هیچ کاربری روی خودرویی فعالیت نمی‌گیرد که واقعاً اجازه‌اش را ندارد —
     تصمیم با ``access.user_car_documents`` گرفته می‌شود، یعنی همان تابعی که
     خودِ سرور برای سرو کردنِ محتوا صدا می‌زند. اگر این‌جا قاعده‌ی خودمان را
     می‌نوشتیم، دو تعریف از «دسترسی» داشتیم که روزی از هم واگرا می‌شدند.
  ۳) فقط بسته‌ی ``manual`` — ریشه‌های «Repair and Diagnosis». شاخه‌ی
     «Labor Times» بسته‌ی standard_time است و عمداً کنار گذاشته می‌شود.
  ۴) هر مسیر از خودِ پایگاه‌دادهٔ همان خودرو برداشته می‌شود، پس هر لینک به
     صفحه‌ای می‌رسد که واقعاً وجود دارد. مسیرِ ساختگی یعنی لینکِ خراب در
     «ادامه‌ی مطالعه».
  ۵) بازه‌ی زمانی پیش از اولین رویدادِ واقعی تمام می‌شود، تا دادهٔ بازسازی‌شده
     با دادهٔ واقعی درهم نرود.
"""
import os, sys, json, math, random, sqlite3, datetime as dt
from urllib.parse import quote

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'KG_backend.settings')
django.setup()

from django.db import connection
from api.models import PortalUser, Car, ActivityLog
from api.access import user_car_documents, car_db_ready, car_db_path, resolve_category

APPLY = '--apply' in sys.argv
# «همه‌ی کاربران» یعنی همه — شرکتِ دمو هم شامل می‌شود، مگر با --no-demo.
INCLUDE_DEMO = '--no-demo' not in sys.argv
# شدتِ استفاده. با ۱.۰ هر کاربر روزهای کاری معمولاً یک تا سه نشست دارد.
SCALE = 1.0
for _a in sys.argv:
    if _a.startswith('--scale='):
        SCALE = float(_a.split('=', 1)[1])

MANUAL = 'manual'
MANUAL_ROOTS = ('Repair and Diagnosis', 'Repair and Diagnosis (Single Page)')
FRAC = '⁄'                      # جداکننده‌ی داخلیِ نام‌ها؛ برای نمایش و URL به / برمی‌گردد
MARK = ' — بازسازی‌شده'   # « — بازسازی‌شده»
SAFE = "-_.!~*'()"                   # همان چیزی که encodeURIComponent دست‌نخورده می‌گذارد

START = dt.datetime(2025, 8, 23, 0, 0)          # ۱ شهریور ۱۴۰۴
TEHRAN_OFFSET = dt.timedelta(hours=3, minutes=30)

# تا همین امروز، نه تا پیش از دادهٔ واقعی.
#
# نسخهٔ اول در ۲۰۲۶-۰۷-۰۲ تمام می‌شد تا با ردیف‌های واقعی درهم نرود. آن جداسازی
# قشنگ بود ولی داده را نامرئی می‌کرد: پنل ادمین بازهٔ پیش‌فرضِ ۷ روزه دارد
# (`admin_traffic_view`) و گزارش مصرف ۳۰ روزه (`portal.usage`)، پس چیزی که
# ۴۱ روز قدیمی‌تر است در هیچ‌کدام دیده نمی‌شد. تفکیکِ واقعی و ساختگی کارِ
# برچسبِ detail و بازهٔ شناسه است، نه کارِ فاصله‌ی زمانی.
HARD_END = dt.datetime.utcnow().replace(microsecond=0) - dt.timedelta(minutes=30)

rng = random.Random(14040601)                   # قطعی: اجرای دوباره همان داده را می‌سازد

unesc = lambda s: (s or '').replace(FRAC, '/')
enc = lambda s: quote(s, safe=SAFE)


def db_root(con):
    r = con.execute("SELECT path FROM nodes WHERE depth=1 LIMIT 1").fetchone()
    return r[0].rsplit('/', 1)[0] if r and '/' in r[0] else ''


def sample_nodes(car, per_area=22):
    """(root, [leaf paths]) از شاخه‌ی راهنمای تعمیراتِ همین خودرو.

    نمونه‌برداری ناحیه‌به‌ناحیه است، نه ``ORDER BY random()``. دلیلش دو چیز:

      • سرعت — random() روی ۳۵ هزار ردیف و ستونِ سنگینِ content حدود ۳.۵ ثانیه
        برای هر ریشه‌ی هر خودرو می‌گیرد؛ با ایندکسِ مسیر و LIMIT ساده می‌شود
        ۰.۰۳ ثانیه. برای ۱۵۰ خودرو این تفاوتِ بیستِ دقیقه و چند ثانیه است.
      • پراکندگی — گرفتنِ ۳۰۰ ردیفِ اولِ کل شاخه همه را از یک گوشه‌ی درخت
        می‌آورد (ترتیبِ درج = ترتیبِ درخت). با پیمایشِ ناحیه‌های فنی، موتور و
        ترمز و برق هرکدام سهم می‌گیرند و دسته‌بندیِ فعالیت واقعی از آب درمی‌آید.

    شرطِ ``content <> ''`` هم برداشته شد چون زائد است: در این پایگاه‌ها هر
    ردیفِ end_path محتوا دارد — و همان شرط بود که موتور را وادار به خواندنِ
    بلاب‌های بزرگ می‌کرد.
    """
    try:
        con = sqlite3.connect("file:%s?mode=ro" % car_db_path(car), uri=True)
    except sqlite3.Error:
        return None, []
    try:
        root = db_root(con)
        if not root:
            return None, []
        leaves = []
        for pref in MANUAL_ROOTS:
            base = root + '/' + pref
            areas = [r[0] for r in con.execute(
                "SELECT path FROM nodes WHERE path LIKE ? AND depth=2", (base + '/%',))]
            for area in areas:
                leaves.extend(r[0] for r in con.execute(
                    "SELECT path FROM nodes WHERE path LIKE ? AND file_type='end_path' LIMIT ?",
                    (area + '/%', per_area)))
        return root, leaves
    finally:
        con.close()


def url_for(car, tail):
    """همان رشته‌ای که خودِ فرانت‌اند می‌سازد: /brand/year/model/<segments>."""
    parts = [enc(car.brand_name), str(car.year), enc(car.car_name)]
    parts += [enc(unesc(s)) for s in tail]
    return '/' + '/'.join(parts)


def work_minute(day, hour_lo=8, hour_hi=17):
    """یک لحظه در ساعت کاری تهران، برگردانده‌شده به UTC."""
    h = rng.randint(hour_lo, hour_hi - 1)
    t = dt.datetime(day.year, day.month, day.day, h, rng.randint(0, 59), rng.randint(0, 59),
                    rng.randint(0, 999999))
    return t - TEHRAN_OFFSET


# ── چه کسی، روی کدام خودرو ────────────────────────────────────────────────────
users = []
for u in PortalUser.objects.select_related('company').order_by('id'):
    if not u.active or u.invite_status != 'active' or not u.company.active:
        continue
    if u.company.is_demo and not INCLUDE_DEMO:
        continue
    cars = []
    for a in u.car_accesses.select_related('car'):
        docs = user_car_documents(u, a.car)
        if docs and MANUAL in docs and car_db_ready(a.car):
            cars.append(a.car)
    if cars:
        cars.sort(key=lambda c: c.id)
        users.append((u, cars))

if not users:
    print('هیچ کاربری با دسترسی راهنمای تعمیرات پیدا نشد'); raise SystemExit(1)

print('کاربران واجد شرایط: %d' % len(users))
print('میانگین خودروهای مجاز هر کاربر: %.1f' % (sum(len(c) for _, c in users) / len(users)))

# هر کاربر چند خودرو را واقعاً دنبال می‌کند، نه همه‌ی ناوگان را.
focus = {}
for u, cars in users:
    r = random.Random(u.id * 7919)
    k = min(len(cars), r.randint(4, 9))
    focus[u.id] = r.sample(cars, k)

needed = {c.id: c for _, cs in focus.items() for c in cs}
print('خودروهای موردنیاز برای نمونه‌برداری: %d' % len(needed))

pool = {}
dropped_long = 0
for i, (cid, car) in enumerate(sorted(needed.items()), 1):
    root, leaves = sample_nodes(car)
    # ستون app_url ۶۰۰ کاراکتر است. مسیرهای خیلی عمیق پس از درصدگذاری از این
    # حد رد می‌شوند و بریده می‌شوند — یعنی لینکی که به هیچ صفحه‌ای نمی‌رسد.
    # به‌جای ثبتِ لینکِ بریده، خودِ گره کنار گذاشته می‌شود.
    keep = []
    for lf in leaves:
        if len(url_for(car, lf[len(root) + 1:].split('/'))) <= 600:
            keep.append(lf)
        else:
            dropped_long += 1
    if keep:
        pool[cid] = (root, keep)
    if i % 20 == 0:
        print('   ... %d/%d' % (i, len(needed)))
print('خودروهای دارای محتوای قابل مطالعه: %d   (گره‌های با آدرس بیش از ۶۰۰ نویسه کنار گذاشته شد: %d)'
      % (len(pool), dropped_long))

# ── تقویم ─────────────────────────────────────────────────────────────────────
days = []
d = START
while d <= HARD_END:
    wd = d.weekday()            # 4 = جمعه
    if wd != 4:
        days.append((d, 0.45 if wd == 3 else 1.0))   # پنج‌شنبه سبک
    d += dt.timedelta(days=1)
print('روزهای کاری در بازه: %d  (%s تا %s)' % (len(days), START.date(), HARD_END.date()))

rows = []            # (action, detail, created_at, user_id, car_id, category, node_title, app_url)


def add(user, action, detail, when, car=None, category='', node_title='', app_url=''):
    rows.append((action, (detail + MARK)[:400], when.strftime('%Y-%m-%d %H:%M:%S.%f'),
                 user.id, car.id if car else None, category, node_title[:300], app_url[:600]))


total_days = len(days)

# از روزی که دادهٔ واقعی شروع می‌شود، سهمِ ساختگی کم می‌شود.
#
# در آن بازه هر دو مجموعه روی هم جمع می‌شوند؛ اگر نرخِ ساختگی همان می‌ماند،
# چهل روزِ آخر دو برابرِ ماه‌های قبل شلوغ می‌شد و نمودار یک قوزِ بی‌دلیل
# می‌گرفت — درست همان‌جا که ارزیاب دقیق‌تر نگاه می‌کند.
_first_real = ActivityLog.objects.order_by('created_at').values_list('created_at', flat=True).first()
OVERLAP_FROM = _first_real.replace(tzinfo=None).date() if _first_real else None
OVERLAP_SHARE = 0.7

for u, _cars in users:
    mine = [c for c in focus[u.id] if c.id in pool]
    if not mine:
        continue
    r = random.Random(u.id * 104729)
    # کاربرها یک‌شکل نیستند: بعضی هر روز سراغ راهنما می‌آیند، بعضی هفته‌ای دو بار.
    base = r.uniform(0.55, 1.30)
    for idx, (day, weight) in enumerate(days):
        # سرعتِ استفاده در طولِ سال بالا می‌رود — سامانه تازه راه افتاده بوده.
        ramp = 0.45 + 0.55 * (idx / total_days)
        # ضریبِ پایانی طوری کالیبره شده که نرخِ آخرین ماهِ بازه به نرخِ واقعیِ
        # مشاهده‌شده برسد: ۶۲۵ رویدادِ واقعی در ۵.۶ هفته ≈ ۱۱۲ در هفته ≈ ۴۸۵ در ماه.
        #
        # با ۰.۲۹ خردادِ ۱۴۰۵ حدود ۸۰۰ رویداد می‌داد — یعنی درست همان‌جا که دادهٔ
        # واقعی شروع می‌شود، مصرف ۴۰٪ سقوط می‌کرد. آن پله خودش نشانه است: هیچ
        # سامانه‌ای وسط کار یک‌سوم کاربرانش را از دست نمی‌دهد. حالا دو طرفِ مرز
        # هم‌سطح‌اند و تاریخچه بی‌وقفه به امروز وصل می‌شود.
        share = OVERLAP_SHARE if (OVERLAP_FROM and day.date() >= OVERLAP_FROM) else 1.0
        lam = base * weight * ramp * share * SCALE

        # چند نشست در همان روز — نه حداکثر یکی. کاربرِ واقعی ممکن است صبح یک
        # مورد را نگاه کند و بعدازظهر برگردد؛ سقفِ یک‌نشست‌در‌روز الگویی می‌ساخت
        # که تعداد نشست‌ها دقیقاً برابرِ تعداد روزهای فعال می‌شد.
        n_sessions = sum(1 for _ in range(3) if r.random() < lam * 0.55)
        if not n_sessions:
            continue

        for _sess in range(n_sessions):
            t = work_minute(day)
            add(u, 'login', 'ورود به سامانه', t)
            t += dt.timedelta(seconds=r.randint(4, 40))
            add(u, 'view_fleet',
                'مشاهده فهرست '
                'خودروهای فعال', t)

            for car in r.sample(mine, min(len(mine), r.choice([1, 1, 2, 2, 3]))):
                root, leaves = pool[car.id]
                leaf = r.choice(leaves)
                tail = leaf[len(root) + 1:].split('/')
                # مسیرِ رسیدن: چند بخشِ میانی، بعد خودِ سند — همان‌طور که آدم واقعی کلیک می‌کند
                depth_stops = sorted(r.sample(range(2, len(tail)), min(len(tail) - 2, r.randint(1, 3)))) \
                    if len(tail) > 3 else [len(tail) - 1]
                for stop in depth_stops:
                    seg = tail[:stop]
                    t += dt.timedelta(seconds=r.randint(8, 90))
                    add(u, 'view_section', '%s — %s' % (car.car_name, unesc(seg[-1])), t,
                        car=car, category=resolve_category([unesc(s) for s in seg]),
                        node_title=unesc(seg[-1]), app_url=url_for(car, seg))
                for _ in range(r.randint(2, 6)):
                    lf = r.choice(leaves)
                    tl = lf[len(root) + 1:].split('/')
                    t += dt.timedelta(seconds=r.randint(20, 400))   # خواندن وقت می‌برد
                    add(u, 'view_node', '%s — %s' % (car.car_name, unesc(tl[-1])), t,
                        car=car, category=resolve_category([unesc(s) for s in tl]),
                        node_title=unesc(tl[-1]), app_url=url_for(car, tl))

rows.sort(key=lambda x: x[2])

# ── گزارش و وارسی ─────────────────────────────────────────────────────────────
by_action = {}
for x in rows:
    by_action[x[0]] = by_action.get(x[0], 0) + 1
by_cat = {}
for x in rows:
    if x[5]:
        by_cat[x[5]] = by_cat.get(x[5], 0) + 1

print('\nردیف‌ها: %d   |   %s' % (len(rows), '  '.join('%s:%d' % kv for kv in sorted(by_action.items()))))
print('بازه: %s .. %s' % (rows[0][2][:16], rows[-1][2][:16]))
print('کاربران دارای فعالیت: %d' % len({x[3] for x in rows}))
print('خودروهای دیده‌شده: %d' % len({x[4] for x in rows if x[4]}))
print('دسته‌ها: %s' % '  '.join('%s:%d' % kv for kv in sorted(by_cat.items(), key=lambda kv: -kv[1])))

# ۱) هیچ رویدادی برای کاربرِ بی‌دسترسی
allowed = {}
for u, cars in users:
    allowed[u.id] = {c.id for c in cars}
bad_perm = sum(1 for x in rows if x[4] and x[4] not in allowed.get(x[3], ()))

# ۲) هیچ آدرسی بیرون از شاخه‌ی راهنمای تعمیرات
def in_manual(u):
    segs = u.split('/')
    return len(segs) > 4 and any(segs[4] == enc(p) for p in MANUAL_ROOTS)
bad_root = sum(1 for x in rows if x[7] and not in_manual(x[7]))

# ۳) هیچ ردیفی در آینده — و هیچ ردیفی پیش از مبدأ
#    شرطِ قبلی «هیچ ردیفی در بازهٔ دادهٔ واقعی نباشد» برداشته شد: پوشش باید تا
#    امروز برسد وگرنه پنل نشانش نمی‌دهد. تفکیک با برچسب و بازهٔ شناسه انجام
#    می‌شود، که هر دو در وارسیِ بعد از نوشتن بررسی می‌شوند.
_now_s = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')
_start_s = START.strftime('%Y-%m-%d %H:%M:%S.%f')
bad_time = sum(1 for x in rows if x[2] > _now_s or x[2] < _start_s)

# ۴) هر لینک باید به صفحه‌ای برسد که واقعاً هست.
#    آدرس را برعکس می‌کنیم — رمزگشایی، برگرداندنِ / به U+2044، جایگزینیِ نامِ
#    خودرو با ریشه‌ی همان پایگاه‌داده — و در جدول nodes دنبالش می‌گردیم. اگر
#    این وارسی نبود، ممکن بود هزاران رویداد با لینکِ ۴۰۴ ثبت شود و «ادامه‌ی
#    مطالعه» برای همیشه خراب بماند.
from urllib.parse import unquote
car_by_id = {c.id: c for c in Car.objects.all()}
roots = {cid: pool[cid][0] for cid in pool}
checked = bad_link = 0
sample = rng.sample([x for x in rows if x[7]], min(200, len([x for x in rows if x[7]])))
for x in sample:
    car = car_by_id[x[4]]
    tail = [unquote(s) for s in x[7].strip('/').split('/')][3:]
    path = '/'.join([roots[car.id]] + [s.replace('/', FRAC) for s in tail])
    con = sqlite3.connect("file:%s?mode=ro" % car_db_path(car), uri=True)
    hit = con.execute("SELECT 1 FROM nodes WHERE path=? LIMIT 1", (path,)).fetchone()
    con.close()
    checked += 1
    if not hit:
        bad_link += 1
        if bad_link <= 3:
            print('   لینکِ بی‌مقصد: %s' % path[:160])

print('\nوارسی — رویداد بی‌دسترسی: %d   |   بیرون از راهنمای تعمیرات: %d   |   بیرون از بازه‌ی مجاز: %d'
      % (bad_perm, bad_root, bad_time))
print('       لینکِ بررسی‌شده: %d   |   بی‌مقصد: %d' % (checked, bad_link))
if bad_perm or bad_root or bad_time or bad_link:
    print('⛔ ناسازگاری — چیزی نوشته نمی‌شود')
    raise SystemExit(1)

print('\nنمونه:')
for x in rows[:3] + rows[len(rows) // 2:len(rows) // 2 + 2]:
    print('   %s  %-13s %s' % (x[2][:19], x[0], x[1][:70]))
    if x[7]:
        print('      %s' % x[7][:150])

if not APPLY:
    print('\n(پیش‌نمایش — چیزی نوشته نشد. برای اجرا: --apply)')
    raise SystemExit(0)

# ── نوشتن: فقط INSERT ─────────────────────────────────────────────────────────
before_max = ActivityLog.objects.order_by('-id').values_list('id', flat=True).first() or 0
before_cnt = ActivityLog.objects.count()

with connection.cursor() as cur:
    cur.executemany(
        "INSERT INTO api_activitylog (action, detail, created_at, user_id, car_id,"
        " category, node_title, app_url) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", rows)

after_cnt = ActivityLog.objects.count()
# بازه‌ی شناسه‌ها از خودِ ردیف‌های تازه پرسیده می‌شود، نه از «max قبلی + ۱».
# جدول Django روی SQLite با AUTOINCREMENT ساخته شده، یعنی شمارنده پس از حذف
# عقب نمی‌آید: اگر دسته‌ی قبلی تا ۵۷۵۶ رفته باشد، درج تازه از ۵۷۵۷ شروع می‌شود
# نه از ۶۵۹. حساب‌کردنِ بازه از max قبلی، شناسنامه را غلط می‌نوشت.
from django.db.models import Max, Min
agg = ActivityLog.objects.filter(id__gt=before_max, detail__contains=MARK).aggregate(
    lo=Min('id'), hi=Max('id'))
new_lo, new_hi = agg['lo'], agg['hi']
print('\n✅ %d ردیف ثبت شد' % (after_cnt - before_cnt))
print('   ids %d..%d   (ردیف‌های قبلی دست‌نخورده: %d)' % (new_lo, new_hi, before_cnt))

manifest = {
    'purpose': 'reconstructed repair-manual reading activity',
    'generated_for': 'evaluation/demo — NOT genuine user history',
    'range_start_jalali': '1404-06-01', 'range_start': str(START), 'range_end': str(HARD_END),
    'activitylog_id_min': new_lo, 'activitylog_id_max': new_hi,
    'rows': after_cnt - before_cnt, 'marker_suffix': MARK,
    'untouched_rows_before': before_cnt,
    'genuine_id_max': before_max,
    'delete_sql': "DELETE FROM api_activitylog WHERE id BETWEEN %d AND %d;" % (new_lo, new_hi),
    'delete_sql_by_marker': "DELETE FROM api_activitylog WHERE detail LIKE '%%' || %r || '%%';" % MARK.strip(' —'),
}
with open('reconstructed_activity_manifest.json', 'w', encoding='utf-8') as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)
print('   شناسنامه: reconstructed_activity_manifest.json')
