"""Designed PDF reports (fa/RTL) for company managers.

Renders an HTML template with inline SVG charts through WeasyPrint. Heavy
native deps (Pango/Cairo) load only when a report is requested — this module
must never be imported at startup (team.py imports it lazily inside the view).

Fonts: Vazirmatn TTFs live in api/reporting_assets/fonts/ (decompressed from
the frontend's self-hosted WOFF2 files at deploy time). If they are missing,
WeasyPrint falls back to any system sans font — the report still renders.
"""
from __future__ import annotations

import datetime
from pathlib import Path

from django.utils import timezone

ASSETS = Path(__file__).resolve().parent / 'reporting_assets'

# ---------------------------------------------------------------------------
# Persian formatting helpers
# ---------------------------------------------------------------------------

_FA_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')


def fa_num(value):
    """Format a number with Persian digits and thousands separators."""
    if value is None:
        return '—'
    if isinstance(value, float):
        value = round(value, 1)
        text = f'{value:,}'.rstrip('0').rstrip('.')
    else:
        text = f'{value:,}'
    return text.replace(',', '،').translate(_FA_DIGITS)


def fa_int(value):
    """Persian digits with NO grouping (years, ranks, small counters)."""
    if value is None:
        return '—'
    return str(int(value)).translate(_FA_DIGITS)


_JALALI_MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
                  'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند']


def _gregorian_to_jalali(gy, gm, gd):
    """Standard arithmetic Gregorian→Jalali conversion."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = (355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100)
            + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1])
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def fa_date(dt):
    """'۲۱ تیر ۱۴۰۵'-style Jalali date for a datetime/date."""
    if dt is None:
        return '—'
    if isinstance(dt, datetime.datetime):
        dt = timezone.localtime(dt) if timezone.is_aware(dt) else dt
        dt = dt.date()
    jy, jm, jd = _gregorian_to_jalali(dt.year, dt.month, dt.day)
    return f'{fa_int(jd)} {_JALALI_MONTHS[jm - 1]} {fa_int(jy)}'


def _rel_activity(iso):
    if not iso:
        return 'بدون فعالیت'
    try:
        d = datetime.datetime.fromisoformat(iso)
    except ValueError:
        return '—'
    return fa_date(d)


# ---------------------------------------------------------------------------
# SVG chart builders (self-contained, no JS — WeasyPrint renders them natively)
# ---------------------------------------------------------------------------

PALETTE = ['#6c5cd6', '#3f9fd8', '#3fbf8f', '#d8a13f', '#d86c3f',
           '#c34f7c', '#5a6acf', '#4fa3a5', '#8f6cd8', '#96a53f', '#777']


def _esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def donut_svg(categories, size=180):
    """Donut of category shares. Falls back to an empty ring when no data."""
    total = sum(c['count'] for c in categories) or 0
    cx = cy = size / 2
    r = size / 2 - 14
    stroke = 24
    circ = 2 * 3.14159265 * r
    parts = []
    if total <= 0:
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
                     f'stroke="#e8e6f2" stroke-width="{stroke}"/>')
    else:
        offset = circ * 0.25  # start at 12 o'clock
        for i, c in enumerate(categories):
            if not c['count']:
                continue
            frac = c['count'] / total
            dash = frac * circ
            color = PALETTE[i % len(PALETTE)]
            parts.append(
                f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" '
                f'stroke-width="{stroke}" stroke-dasharray="{dash:.2f} {circ - dash:.2f}" '
                f'stroke-dashoffset="{offset:.2f}" stroke-linecap="butt"/>')
            offset -= dash
    # Center label as positioned HTML, NOT svg <text> — WeasyPrint does not
    # bidi-shape text inside SVG, which mirrors Persian words.
    svg = (f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" '
           f'xmlns="http://www.w3.org/2000/svg">{"".join(parts)}</svg>')
    return (f'<div style="position:relative;width:{size}px;height:{size}px;'
            f'display:inline-block">{svg}'
            f'<div style="position:absolute;top:0;left:0;right:0;height:{size}px;'
            f'text-align:center;padding-top:{size / 2 - 26}px">'
            f'<div style="font-size:20pt;font-weight:700;color:#241f3d">{_esc(fa_num(total))}</div>'
            f'<div style="font-size:8.5pt;color:#7a7590">رویداد ثبت‌شده</div>'
            f'</div></div>')


def trend_svg(series, width=640, height=150):
    """Filled area chart of daily events."""
    pad = 8
    if not series:
        return (f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}">'
                f'<text x="{width / 2}" y="{height / 2}" text-anchor="middle" '
                f'font-size="12" fill="#9a95b0">داده‌ای در این بازه ثبت نشده است</text></svg>')
    max_v = max(p['count'] for p in series) or 1
    n = len(series)
    step = (width - 2 * pad) / max(n - 1, 1)
    pts = []
    for i, p in enumerate(series):
        x = pad + i * step
        y = height - pad - (p['count'] / max_v) * (height - 2 * pad - 14)
        pts.append((x, y))
    line = ' '.join(f'{x:.1f},{y:.1f}' for x, y in pts)
    area = f'{pad},{height - pad} ' + line + f' {pts[-1][0]:.1f},{height - pad}'
    grid = ''.join(
        f'<line x1="{pad}" y1="{height - pad - k * (height - 2 * pad - 14) / 3:.1f}" '
        f'x2="{width - pad}" y2="{height - pad - k * (height - 2 * pad - 14) / 3:.1f}" '
        f'stroke="#eceaf4" stroke-width="1"/>' for k in range(4))
    dots = ''.join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="#6c5cd6"/>'
                   for x, y in pts) if n <= 45 else ''
    return (
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<defs><linearGradient id="tg" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="#6c5cd6" stop-opacity="0.35"/>'
        f'<stop offset="100%" stop-color="#6c5cd6" stop-opacity="0.02"/>'
        f'</linearGradient></defs>'
        f'{grid}'
        f'<polygon points="{area}" fill="url(#tg)"/>'
        f'<polyline points="{line}" fill="none" stroke="#6c5cd6" stroke-width="2.2" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
        f'{dots}</svg>')


# ---------------------------------------------------------------------------
# Report template
# ---------------------------------------------------------------------------

def _font_css():
    """@font-face rules for the local Vazirmatn TTFs (if present).

    Uses the FULL official Vazirmatn Regular/Bold files (fetched at deploy
    time) — they cover Persian AND Latin in one face, which avoids the
    garbled-glyph fallback that mixing per-script subset fonts under one
    family produced."""
    fonts_dir = ASSETS / 'fonts'
    if not fonts_dir.is_dir():
        return ''
    faces = []
    for f in sorted(fonts_dir.glob('*.ttf')):
        name = f.name.lower()
        if 'bold' in name:
            weight = '700'
        elif 'medium' in name:
            weight = '500'
        else:
            weight = '400'
        faces.append(
            "@font-face { font-family: 'Vazirmatn'; "
            f"src: url('file://{f.as_posix()}') format('truetype'); "
            f"font-weight: {weight}; font-style: normal; }}")
    return '\n'.join(faces)


_CSS = '''
%(fonts)s
* { box-sizing: border-box; }
@page {
  size: A4; margin: 16mm 14mm 20mm 14mm;
  @bottom-center {
    content: "KGtechvault — گزارش عملکرد تیم · صفحه " counter(page) " از " counter(pages);
    font-family: 'Vazirmatn', sans-serif; font-size: 8.5pt; color: #9a95b0;
  }
}
@page cover { margin: 0; @bottom-center { content: none; } }
html { direction: rtl; }
body { font-family: 'Vazirmatn', sans-serif; color: #241f3d; font-size: 10.5pt; margin: 0; }

/* ---- cover ---- */
.cover { page: cover; width: 210mm; height: 297mm; position: relative; overflow: hidden;
         background: linear-gradient(150deg, #191430 0%%, #241d4a 45%%, #3a2a72 100%%); color: #fff; }
.cover .band { position: absolute; inset-inline-start: 0; top: 0; width: 210mm; height: 6mm;
               background: linear-gradient(90deg, #e8b04b, #7c6cf0, #4bb3e8); }
.cover .inner { position: absolute; inset-inline-start: 18mm; inset-inline-end: 18mm; top: 60mm; }
.cover .brand { font-size: 13pt; letter-spacing: 1px; color: #b9b0e8; margin-bottom: 6mm; }
.cover h1 { font-size: 30pt; margin: 0 0 4mm; font-weight: 700; }
.cover .company { font-size: 16pt; color: #e8e4ff; margin-bottom: 14mm; }
.cover .meta { border-top: 0.4pt solid rgba(255,255,255,0.25); padding-top: 6mm; font-size: 10.5pt;
               color: #cfc9ee; line-height: 2.1; }
.cover .meta b { color: #fff; font-weight: 700; }
.cover .foot { position: absolute; bottom: 14mm; inset-inline-start: 18mm; font-size: 8.5pt; color: #8f87c0; }
.cover .rings { position: absolute; bottom: -30mm; inset-inline-end: -30mm; opacity: 0.35; }

/* ---- sections ---- */
h2.sec { font-size: 14pt; margin: 0 0 4mm; padding-bottom: 2.4mm; font-weight: 700;
         border-bottom: 1.6pt solid #6c5cd6; }
h2.sec span { color: #9a95b0; font-size: 9pt; font-weight: 400; }
.section { margin-bottom: 9mm; }
.page-break { page-break-before: always; }

/* KPI tiles */
.kpis { width: 100%%; border-collapse: separate; border-spacing: 3mm 0; margin: 0 -3mm; }
.kpis td { width: 25%%; background: #f4f2fb; border: 0.4pt solid #e3dff2; border-radius: 3mm;
           padding: 4.5mm 4mm; vertical-align: top; }
.kpis .v { font-size: 19pt; font-weight: 700; color: #3a2a72; }
.kpis .l { font-size: 9pt; color: #7a7590; margin-top: 1mm; }

/* two-col layout */
.cols { width: 100%%; border-collapse: collapse; }
.cols td { vertical-align: top; }

/* category legend bars */
.catbar { margin-bottom: 2.6mm; }
.catbar .row { font-size: 9.5pt; margin-bottom: 1mm; }
.catbar .row .n { float: left; color: #7a7590; }
.catbar .track { height: 3mm; background: #efedf7; border-radius: 2mm; overflow: hidden; }
.catbar .fill { height: 3mm; border-radius: 2mm; }

/* tables */
table.data { width: 100%%; border-collapse: collapse; font-size: 9.5pt; }
table.data th { background: #3a2a72; color: #fff; font-weight: 700; padding: 2.6mm 3mm;
                text-align: right; font-size: 9pt; }
table.data th:first-child { border-radius: 0 2mm 2mm 0; }
table.data th:last-child { border-radius: 2mm 0 0 2mm; }
table.data td { padding: 2.4mm 3mm; border-bottom: 0.4pt solid #e9e6f3; }
table.data tr:nth-child(even) td { background: #f8f7fc; }
.badge { display: inline-block; padding: 0.8mm 2.6mm; border-radius: 2mm; font-size: 8pt;
         background: #efedf7; color: #4a4370; }
.rankchip { display: inline-block; min-width: 6mm; text-align: center; padding: 0.6mm 1.8mm;
            border-radius: 2mm; background: #6c5cd6; color: #fff; font-size: 8pt; }
.minibar { display: inline-block; height: 2.4mm; border-radius: 1.2mm;
           background: linear-gradient(90deg, #6c5cd6, #4bb3e8); vertical-align: middle; }
.muted { color: #9a95b0; }
.status-active { color: #2c9d6b; } .status-invited { color: #c9931f; } .status-off { color: #c34f4f; }
'''


def render_team_report_pdf(viewer, data):
    """Build the full report HTML for ``viewer`` and return PDF bytes."""
    from weasyprint import HTML  # heavy import, on purpose inside the function

    company = viewer.company
    now = timezone.now()
    days = data['range_days']
    since = now - timezone.timedelta(days=days)
    cats = data['categories']
    cat_total = sum(c['count'] for c in cats)
    members = data['members']
    top_member = members[0] if members and members[0]['events'] else None
    top_cat = max(cats, key=lambda c: c['count']) if cat_total else None

    cat_rows = []
    for i, c in enumerate(cats):
        pct = (c['count'] / cat_total * 100) if cat_total else 0
        color = PALETTE[i % len(PALETTE)]
        cat_rows.append(
            f'<div class="catbar"><div class="row">'
            f'<span class="n">{_esc(fa_num(c["count"]))} ({_esc(fa_num(round(pct)))}٪)</span>'
            f'{_esc(c["label"])}</div>'
            f'<div class="track"><div class="fill" '
            f'style="width:{max(pct, 1.5):.1f}%; background:{color}"></div></div></div>')

    max_events = max((m['events'] for m in members), default=0) or 1
    member_rows = []
    status_cls = {'active': ('فعال', 'status-active'),
                  'invited': ('در انتظار دعوت', 'status-invited'),
                  'disabled': ('غیرفعال', 'status-off')}
    for i, m in enumerate(members, start=1):
        bar_w = max(2, int(m['events'] / max_events * 28))
        st_label, st_cls = status_cls.get(
            m['invite_status'] if m['active'] else 'disabled', ('فعال', 'status-active'))
        member_rows.append(
            f'<tr><td>{_esc(fa_num(i))}</td>'
            f'<td><b>{_esc(m["name"])}</b></td>'
            f'<td><span class="badge">{_esc(m["role_label"])}</span></td>'
            f'<td><span class="rankchip">{_esc(fa_num(m["rank"]))}</span></td>'
            f'<td>{_esc(fa_num(m["events"]))} '
            f'<span class="minibar" style="width:{bar_w}mm"></span></td>'
            f'<td class="muted">{_esc(_rel_activity(m["last_active"]))}</td>'
            f'<td class="{st_cls}">{st_label}</td></tr>')

    car_rows = []
    max_car = max((c['count'] for c in data['top_cars']), default=0) or 1
    for i, c in enumerate(data['top_cars'], start=1):
        bar_w = max(2, int(c['count'] / max_car * 30))
        car_rows.append(
            f'<tr><td>{_esc(fa_num(i))}</td><td><b>{_esc(c["label"])}</b></td>'
            f'<td>{_esc(fa_num(c["count"]))} '
            f'<span class="minibar" style="width:{bar_w}mm"></span></td></tr>')

    viewer_name = viewer.display_name or viewer.username
    rings = ('<svg class="rings" width="360" height="360" viewBox="0 0 360 360" '
             'xmlns="http://www.w3.org/2000/svg">'
             + ''.join(f'<circle cx="180" cy="180" r="{r}" fill="none" '
                       f'stroke="#7c6cf0" stroke-width="0.8" opacity="{0.9 - r/200:.2f}"/>'
                       for r in range(30, 181, 30)) + '</svg>')

    html = f'''<!DOCTYPE html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8"><style>{_CSS % {"fonts": _font_css()}}</style></head>
<body>

<div class="cover">
  <div class="band"></div>
  {rings}
  <div class="inner">
    <div class="brand">KGTECHVAULT · سامانه مستندات فنی خودرو</div>
    <h1>گزارش عملکرد تیم</h1>
    <div class="company">{_esc(company.name)}</div>
    <div class="meta">
      <div>بازه گزارش: <b>{_esc(fa_date(since))}</b> تا <b>{_esc(fa_date(now))}</b> ({_esc(fa_num(days))} روز)</div>
      <div>واحد سازمانی: <b>{_esc(company.department_label)}</b></div>
      <div>تهیه‌کننده: <b>{_esc(viewer_name)}</b></div>
      <div>تعداد اعضای تحت پوشش: <b>{_esc(fa_num(len(members)))} نفر</b></div>
    </div>
  </div>
  <div class="foot">این گزارش به‌صورت خودکار توسط سامانه KGtechvault تولید شده است · {_esc(fa_date(now))}</div>
</div>

<div class="section">
  <h2 class="sec">نمای کلی <span>// OVERVIEW</span></h2>
  <table class="kpis"><tr>
    <td><div class="v">{_esc(fa_num(data["total_events"]))}</div><div class="l">کل رویدادهای ثبت‌شده</div></td>
    <td><div class="v">{_esc(fa_num(data["active_members"]))}</div><div class="l">عضو فعال در این بازه</div></td>
    <td><div class="v">{_esc(fa_num(len(members)))}</div><div class="l">کل اعضای تحت پوشش</div></td>
    <td><div class="v" style="font-size:12.5pt; padding-top:2mm">{_esc(top_cat["label"] if top_cat else "—")}</div>
        <div class="l">پرمراجعه‌ترین حوزه فنی</div></td>
  </tr></table>
</div>

<div class="section">
  <h2 class="sec">استفاده به تفکیک حوزه فنی <span>// CATEGORIES</span></h2>
  <table class="cols"><tr>
    <td style="width: 62%; padding-inline-end: 8mm;">{''.join(cat_rows)}</td>
    <td style="width: 38%; text-align: center;">{donut_svg(cats)}</td>
  </tr></table>
</div>

<div class="section">
  <h2 class="sec">روند فعالیت روزانه <span>// DAILY TREND</span></h2>
  {trend_svg(data["series"])}
</div>

<div class="section page-break">
  <h2 class="sec">عملکرد اعضای تیم <span>// MEMBERS</span></h2>
  <table class="data">
    <tr><th>#</th><th>نام و نام خانوادگی</th><th>جایگاه سازمانی</th><th>رتبه</th>
        <th>فعالیت</th><th>آخرین فعالیت</th><th>وضعیت</th></tr>
    {''.join(member_rows) or '<tr><td colspan="7" class="muted">عضوی یافت نشد.</td></tr>'}
  </table>
  {f'<p class="muted" style="font-size:9pt">فعال‌ترین عضو تیم در این بازه: <b>{_esc(top_member["name"])}</b> با {_esc(fa_num(top_member["events"]))} رویداد.</p>' if top_member else ''}
</div>

<div class="section">
  <h2 class="sec">پرمراجعه‌ترین خودروها <span>// TOP VEHICLES</span></h2>
  <table class="data">
    <tr><th>#</th><th>خودرو</th><th>دفعات مراجعه</th></tr>
    {''.join(car_rows) or '<tr><td colspan="3" class="muted">در این بازه مراجعه‌ای به خودروها ثبت نشده است.</td></tr>'}
  </table>
</div>

</body></html>'''

    return HTML(string=html).write_pdf()
