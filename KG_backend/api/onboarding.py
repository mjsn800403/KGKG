"""Feature discovery: what this seat is entitled to, and what it has found.

Spec: docs/superpowers/specs/2026-10-30-feature-discovery-onboarding-design.md

Measured on production on 2026-10-30, across four months and 34 active seats:
71,886 manual views, the parts catalogue opened by 6 people, the assistant
asked by 9, the search box used by nobody at all. People found the manuals and
very little else, and nobody knew because every piece of onboarding state lived
in the browser.

Two rules give this module its shape:

**Completion is earned, never claimed.** An item is done when the activity log
already says the person did the thing. There is no "mark as done" — an item a
user can tick without using the feature turns the metric into decoration, and
this one exists to be acted on. It also means the checklist is truthful for
seats that have been using the product for months, from the day it ships.

**Entitlement is computed, never copied.** `access.user_ai_eligible` and
`access.user_package_set` already decide what a seat may use; re-expressing
those rules here would create a second answer to "may this person use the
assistant", and the two would drift. An unentitled item is absent from the
seat's checklist AND from the metric's denominator: telling someone to try
something their company has not bought manufactures support tickets, and
counting them as a discovery failure slanders the feature.
"""
from typing import NamedTuple

from . import access
from .models import ActivityLog, CompanyRequest, SearchLog


class Item(NamedTuple):
    id: str
    title: str          # Persian: shown to the seat
    why: str            # Persian: one line on what it is for
    href: str


#: Order is the order the seat sees. Reading a manual comes first because it is
#: the thing everyone already does — a checklist whose first line is already
#: ticked reads as a description of you, not a demand.
ITEMS = (
    Item('read_manual', 'یک فصل از منوال را باز کنید',
         'مستندات تعمیراتی خودروهایی که برایتان فعال شده است.', '/browse'),
    Item('use_search', 'در محتوا جستجو کنید',
         'جستجوی هوشمند، فارسی را هم در متن انگلیسی منوال پیدا می‌کند.', '/browse'),
    Item('ask_assistant', 'از دستیار هوشمند بپرسید',
         'به‌جای گشتن در فصل‌ها، سؤالتان را بپرسید؛ پاسخ با ارجاع به منبع می‌آید.',
         '/assistant'),
    Item('open_parts', 'کاتالوگ قطعات را ببینید',
         'شمارهٔ فنی و نقشهٔ انفجاری قطعات همان خودرو.', '/browse'),
    Item('export_times', 'زمان استاندارد یا ابزار مخصوص را خروجی بگیرید',
         'خروجی CSV برای برآورد زمان کار و فهرست ابزار.', '/browse'),
    Item('ask_support', 'یک درخواست پشتیبانی ثبت کنید',
         'هر مشکل یا پرسشی را از همین‌جا پیگیری کنید؛ مهلت پاسخ مشخص است.',
         '/requests'),
    Item('invite_colleague', 'یک همکار را دعوت کنید',
         'برای هر کارشناس یک حساب جدا بسازید.', '/team'),
    Item('read_team_report', 'گزارش تیم را بخوانید',
         'میزان استفادهٔ تیم، به تفکیک حوزهٔ فنی.', '/team/analytics'),
)

#: Packages that make the CSV exports meaningful.
_EXPORT_PACKAGES = {'standard_time', 'special_tools'}


def _entitlements(user):
    """Everything entitlement depends on, read once per seat."""
    packages = access.user_package_set(user)
    return {
        'has_car': user.car_accesses.exists(),
        'packages': packages,
        'ai': access.user_ai_eligible(user),
        'manages': bool(user.can_manage_team),
    }


def _is_entitled(item_id, ent):
    if item_id in ('read_manual', 'use_search'):
        return ent['has_car']
    if item_id == 'ask_assistant':
        return ent['ai']
    if item_id == 'open_parts':
        return 'parts' in ent['packages']
    if item_id == 'export_times':
        return bool(_EXPORT_PACKAGES & ent['packages'])
    if item_id == 'ask_support':
        return True          # every seat may file one
    if item_id in ('invite_colleague', 'read_team_report'):
        return ent['manages']
    return False


def _is_done(item_id, user):
    """One `exists()` per item. Never `count()`, never a fetch: the heaviest
    production seat has ~47,000 activity rows and the checklist renders on the
    page they land on."""
    def acted(*actions):
        return ActivityLog.objects.filter(user_id=user.id, action__in=actions).exists()

    if item_id == 'read_manual':
        return acted('view_node', 'view_section')
    if item_id == 'use_search':
        return SearchLog.objects.filter(user_id=user.id).exists()
    if item_id == 'ask_assistant':
        # Asked, not opened: 62 opens produced 43 questions from 9 people, and
        # opening a panel then leaving is not discovery.
        return acted('ask_assistant')
    if item_id == 'open_parts':
        return acted('parts_view')
    if item_id == 'export_times':
        return acted('download_csv')
    if item_id == 'ask_support':
        return CompanyRequest.objects.filter(created_by_id=user.id).exists()
    if item_id == 'invite_colleague':
        return acted('team_add')
    if item_id == 'read_team_report':
        return acted('report_pdf')
    return False


def progress_for(user):
    """The seat's own checklist: entitled items only, in ITEMS order."""
    ent = _entitlements(user)
    out = []
    for item in ITEMS:
        if not _is_entitled(item.id, ent):
            continue
        out.append({'id': item.id, 'title': item.title, 'why': item.why,
                    'href': item.href, 'done': _is_done(item.id, user)})
    return out


def discovery_counts(users):
    """{item_id: {entitled, discovered, rate}} over the given seats.

    The same questions the checklist asks, aggregated — one implementation, so
    the figure management reads and the item the seat sees cannot disagree.
    `rate` is None when nobody is entitled: a rate with an empty denominator is
    not zero, it is unknown.
    """
    counts = {i.id: {'entitled': 0, 'discovered': 0, 'rate': None} for i in ITEMS}
    for user in users:
        ent = _entitlements(user)
        for item in ITEMS:
            if not _is_entitled(item.id, ent):
                continue
            counts[item.id]['entitled'] += 1
            if _is_done(item.id, user):
                counts[item.id]['discovered'] += 1
    for row in counts.values():
        if row['entitled']:
            row['rate'] = round(row['discovered'] / row['entitled'], 4)
    return counts
