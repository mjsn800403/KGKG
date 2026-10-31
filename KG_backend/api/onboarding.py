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

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from . import access
from .models import ActivityLog, CompanyRequest, PortalUser, SearchLog
from .portal_auth import require_portal_user


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
    # href is None for anything that lives INSIDE a vehicle: the strip is
    # rendered on /browse, and an item linking back to the page it is shown on
    # is a pointer at itself. The copy says where to go instead.
    Item('use_search', 'در محتوا جستجو کنید',
         'پس از باز کردن یک خودرو، کادر جستجوی بالای صفحه؛ فارسی را هم در متن انگلیسی منوال پیدا می‌کند.',
         None),
    Item('ask_assistant', 'از دستیار هوشمند بپرسید',
         'به‌جای گشتن در فصل‌ها، سؤالتان را بپرسید؛ پاسخ با ارجاع به منبع می‌آید.',
         '/assistant'),
    Item('open_parts', 'کاتالوگ قطعات را ببینید',
         'داخل هر خودرویی که کاتالوگ دارد، دکمهٔ «قطعات»: شمارهٔ فنی و نقشهٔ انفجاری.',
         None),
    Item('export_times', 'زمان استاندارد یا ابزار مخصوص را خروجی بگیرید',
         'داخل هر خودرو، خروجی CSV برای برآورد زمان کار و فهرست ابزار.', None),
    Item('ask_support', 'یک درخواست پشتیبانی ثبت کنید',
         'هر مشکل یا پرسشی را از همین‌جا پیگیری کنید؛ مهلت پاسخ مشخص است.',
         '/requests'),
    Item('invite_colleague', 'یک همکار را دعوت کنید',
         'برای هر کارشناس یک حساب جدا بسازید.', '/team'),
    # Title says DOWNLOAD because the signal is the PDF download (team.py
    # writes `report_pdf` there and nowhere else). A title promising "read"
    # beside a completion that needs a download is an item that never ticks
    # for someone who opens the page every week.
    Item('read_team_report', 'گزارش PDF تیم را دریافت کنید',
         'میزان استفادهٔ تیم به تفکیک حوزهٔ فنی، به صورت فایل.', '/team/analytics'),
)

#: Packages that make the CSV exports meaningful.
_EXPORT_PACKAGES = {'standard_time', 'special_tools'}

#: Every ActivityLog action completion depends on. A signal nothing writes is
#: an item that can never tick — it nags forever and reports a permanent zero
#: to management. `test_an_item_is_never_offered_against_an_action_nothing_writes`
#: checks each of these against the code that actually logs.
ACTIONS_USED = ('view_node', 'view_section', 'ask_assistant', 'parts_view',
                'download_csv', 'report_pdf')


def _entitlements(user):
    """Everything entitlement depends on, read once per seat."""
    from . import orggraph
    packages = access.user_package_set(user)
    return {
        'has_car': user.car_accesses.exists(),
        'packages': packages,
        'ai': access.user_ai_eligible(user),
        'manages': bool(user.can_manage_team),
        # The gate that actually serves /api/team/analytics/ is an org-graph
        # position test, not the can_manage_team flag. Offering the item on the
        # flag sent a leaf-node manager to a 403.
        'sees_team': orggraph.user_can_view_team(user),
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
        # Every seat MAY file one, but a seat with nothing assigned has nothing
        # to ask about yet, and "file a support ticket" is a poor first
        # instruction to someone who has just been given an account. Their
        # screen already says to contact their administrator.
        return ent['has_car']
    if item_id == 'invite_colleague':
        return ent['manages']
    if item_id == 'read_team_report':
        return ent['sees_team']
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
        # Derived from STATE, not from an action. Nothing in the product logs
        # "a manager invited someone" — the seat-creation log is written
        # against the new user — so an action-based rule could never tick, and
        # would have nagged every manager who had already built their team.
        # A company with colleagues in it is a manager who plainly knows the
        # feature exists, which is what a discovery item is asking.
        return PortalUser.objects.filter(company_id=user.company_id).exclude(
            id=user.id).exists()
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


# ---------------------------------------------------------------------------
# The seat's own endpoint
# ---------------------------------------------------------------------------

@csrf_exempt
@require_portal_user
def onboarding_view(request):
    """GET  /api/auth/onboarding/  -> {items, done, total, dismissed}
    POST /api/auth/onboarding/ {"dismissed": true}

    `dismissed` hides the strip; it does not change the items, which keep
    describing what the seat has and has not found. The two are separate on
    purpose: someone who dismissed the prompt has not thereby discovered
    anything, and the metric must not pretend otherwise.
    """
    user = request.portal_user

    if request.method == 'POST':
        from .portal import _body
        b = _body(request)
        if not b.get('dismissed'):
            return JsonResponse(
                {'error': 'تنها عملیات مجاز، بستن راهنمای شروع است.'}, status=400)
        # Idempotent: a second dismissal must not restart the clock, because
        # the timestamp is a record of when they said no.
        if user.onboarding_dismissed_at is None:
            user.onboarding_dismissed_at = timezone.now()
            user.save(update_fields=['onboarding_dismissed_at'])
    elif request.method != 'GET':
        return JsonResponse({'error': 'GET or POST'}, status=405)

    items = progress_for(user)
    return JsonResponse({
        'items': items,
        'done': sum(1 for i in items if i['done']),
        'total': len(items),
        'dismissed': user.onboarding_dismissed_at is not None,
    })


def measurable_seats():
    """The seats a discovery rate may be computed over.

    `active=True` alone includes invited seats that have never set a password
    and cannot sign in (see team.py: employees are provisioned with an unusable
    password). Counting them as discovery failures is the same error the module
    rejects for unentitled seats — it reports a feature as undiscovered by
    people who were never able to open the product at all.
    """
    return (PortalUser.objects.filter(active=True, password_set=True)
            .select_related('company')
            .prefetch_related('car_accesses', 'company__car_accesses'))
