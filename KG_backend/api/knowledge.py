"""The knowledge base: durable answers, owned by a named person, reachable by
the people who need them.

Why it exists (audit-evidence/16-improvement-programme/ROOT_CAUSE_ANALYSIS.md,
Finding 3): the project's documentation is strong but it is all engineer-shaped
Markdown in docs/. A customer in the portal, and whoever answers their ticket,
could reach none of it; so a recurring question was answered from scratch every
time and the answer was buried in one ticket's admin_note. Nothing turned a
solved problem into reusable knowledge.

Three mechanisms, each aimed at a stated root cause:

  * **named ownership and a review interval** — `KnowledgeArticle.owner` and
    `is_stale`, so "which knowledge is rotting" is a query instead of an
    impression;
  * **revisions** — every edit appends a `KnowledgeRevision`, so knowledge has
    a history the way code does;
  * **promotion from a ticket** — `promote_request_view` turns a resolved
    ticket into a draft article seeded with the subject, the customer's words
    and the resolution, so writing the article is an edit, not a blank page.

Search misses are logged (`KbSearchLog`): a question with no answer is the
most actionable signal the base produces, because it names an article that
ought to exist.

    GET  /api/kb/?q=&category=            any seat: published, customer-facing
    GET  /api/kb/<slug>/                  article (counts a view)
    POST /api/kb/<slug>/vote/             {helpful: bool}
    GET  /api/admin/kb/                   admin: everything, any status
    POST /api/admin/kb/                   admin: create
    GET  /api/admin/kb/<id>/              admin: article + revision history
    POST /api/admin/kb/<id>/              admin: edit / review / reassign
    POST /api/admin/company-requests/<id>/promote-to-article/
"""
from datetime import timedelta

from django.db.models import Count, F, Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .admin_auth import acting_admin, require_admin_token
from .models import (CompanyRequest, KbSearchLog, KnowledgeArticle,
                     KnowledgeRevision, PlatformAdmin)
from .portal import _body
from .portal_auth import require_portal_user
from .ratelimit import rate_limited

VALID_STATUSES = {s for s, _ in KnowledgeArticle.STATUS_CHOICES}
VALID_AUDIENCES = {a for a, _ in KnowledgeArticle.AUDIENCE_CHOICES}
MAX_BODY = 60000


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _summary(a):
    return {
        'id': a.id, 'slug': a.slug, 'title': a.title, 'category': a.category,
        'audience': a.audience, 'status': a.status, 'version': a.version,
        'excerpt': a.body[:200],
        'views': a.views, 'helpful': a.helpful, 'unhelpful': a.unhelpful,
        'updated_at': a.updated_at.isoformat(),
    }


def _full(a, *, admin=False):
    d = _summary(a)
    d['body'] = a.body
    if admin:
        d.update({
            'owner': ({'id': a.owner_id, 'name': a.owner.username}
                      if a.owner_id and a.owner else None),
            'review_interval_days': a.review_interval_days,
            'reviewed_at': a.reviewed_at.isoformat() if a.reviewed_at else None,
            'is_stale': a.is_stale,
            'source_request_id': a.source_request_id,
            'created_at': a.created_at.isoformat(),
        })
    return d


# ---------------------------------------------------------------------------
# Seat side
# ---------------------------------------------------------------------------

def _published_qs():
    return KnowledgeArticle.objects.filter(status='published', audience='customer')


@require_portal_user
@rate_limited('kb', 300, 60)
def kb_list_view(request):
    """GET /api/kb/?q=&category= — published, customer-facing articles."""
    user = request.portal_user
    qs = _published_qs()
    category = (request.GET.get('category') or '').strip()
    if category:
        qs = qs.filter(category=category)
    q = (request.GET.get('q') or '').strip()[:200]
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(body__icontains=q))
    items = [_summary(a) for a in qs[:100]]

    # Only a real question is a search. Opening the index is browsing, and
    # counting it would dilute the zero-result rate that makes the log useful.
    if q:
        try:
            KbSearchLog.objects.create(user=user, company_id=user.company_id, query=q,
                                       query_norm=q.lower(), results=len(items))
        except Exception:
            pass        # a logging failure must never cost the reader an answer

    categories = sorted(c for c in _published_qs().values_list('category', flat=True)
                        .distinct() if c)
    return JsonResponse({'articles': items, 'categories': categories, 'query': q})


@require_portal_user
def kb_detail_view(request, slug):
    a = _published_qs().filter(slug=slug).first()
    if not a:
        return JsonResponse({'error': 'not found'}, status=404)
    KnowledgeArticle.objects.filter(id=a.id).update(views=F('views') + 1)
    a.views += 1
    return JsonResponse({'article': _full(a)})


@csrf_exempt
@require_portal_user
def kb_vote_view(request, slug):
    """POST /api/kb/<slug>/vote/ {helpful: true|false} — was this any use?"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    a = _published_qs().filter(slug=slug).first()
    if not a:
        return JsonResponse({'error': 'not found'}, status=404)
    b = _body(request)
    if 'helpful' not in b or not isinstance(b.get('helpful'), bool):
        return JsonResponse({'error': 'helpful باید true یا false باشد.'}, status=400)
    field = 'helpful' if b['helpful'] else 'unhelpful'
    KnowledgeArticle.objects.filter(id=a.id).update(**{field: F(field) + 1})
    return JsonResponse({'ok': True})


# ---------------------------------------------------------------------------
# Admin side
# ---------------------------------------------------------------------------

def _revise(a, admin, note=''):
    KnowledgeRevision.objects.create(article=a, version=a.version, title=a.title,
                                     body=a.body, editor=admin, note=note[:300])


@csrf_exempt
@require_admin_token
def admin_kb_view(request):
    """GET  /api/admin/kb/?status=&audience=&stale=1
    POST /api/admin/kb/ {title, slug, body, category?, audience?, status?,
                         review_interval_days?}"""
    if request.method == 'POST':
        return _create(request)
    if request.method != 'GET':
        return JsonResponse({'error': 'GET or POST'}, status=405)

    qs = KnowledgeArticle.objects.select_related('owner')
    status = (request.GET.get('status') or '').strip()
    if status in VALID_STATUSES:
        qs = qs.filter(status=status)
    audience = (request.GET.get('audience') or '').strip()
    if audience in VALID_AUDIENCES:
        qs = qs.filter(audience=audience)
    items = [_full(a, admin=True) for a in qs[:300]]
    if request.GET.get('stale') == '1':
        items = [d for d in items if d['is_stale']]
    return JsonResponse({
        'articles': items,
        'owners': [{'id': p.id, 'name': p.username}
                   for p in PlatformAdmin.objects.filter(active=True).order_by('username')],
        'counts': {'total': KnowledgeArticle.objects.count(),
                   'published': KnowledgeArticle.objects.filter(status='published').count()},
    })


def _create(request):
    b = _body(request)
    title = (str(b.get('title') or '')).strip()[:200]
    slug = (str(b.get('slug') or '')).strip()[:120]
    body = (str(b.get('body') or '')).strip()[:MAX_BODY]
    if not title or not slug or not body:
        return JsonResponse({'error': 'عنوان، شناسه و متن الزامی است.'}, status=400)
    if KnowledgeArticle.objects.filter(slug=slug).exists():
        return JsonResponse({'error': 'این شناسه قبلاً استفاده شده است.'}, status=400)
    status = (str(b.get('status') or 'draft')).strip()
    if status not in VALID_STATUSES:
        return JsonResponse({'error': 'وضعیت نامعتبر است.'}, status=400)
    audience = (str(b.get('audience') or 'customer')).strip()
    if audience not in VALID_AUDIENCES:
        return JsonResponse({'error': 'مخاطب نامعتبر است.'}, status=400)
    try:
        interval = int(b.get('review_interval_days')
                       or KnowledgeArticle.DEFAULT_REVIEW_DAYS)
    except (TypeError, ValueError):
        interval = KnowledgeArticle.DEFAULT_REVIEW_DAYS
    admin = acting_admin(request)

    a = KnowledgeArticle.objects.create(
        slug=slug, title=title, body=body, status=status, audience=audience,
        category=(str(b.get('category') or '')).strip()[:60],
        owner=admin, review_interval_days=max(1, min(interval, 3650)),
        reviewed_at=timezone.now())
    _revise(a, admin, note=str(b.get('note') or 'created'))
    return JsonResponse({'ok': True, 'article': _full(a, admin=True)})


@csrf_exempt
@require_admin_token
def admin_kb_detail_view(request, article_id):
    """GET  /api/admin/kb/<id>/   -> article + revision history
    POST /api/admin/kb/<id>/   {title?, body?, category?, status?, audience?,
                                owner_id?, review_interval_days?, reviewed?,
                                note?}

    A change to the TEXT appends a revision and bumps the version. Everything
    else — status, owner, category, a plain review — is metadata and does not,
    because a reviewer confirming that an article is still correct has not
    written a new version of it.
    """
    a = KnowledgeArticle.objects.select_related('owner').filter(id=article_id).first()
    if not a:
        return JsonResponse({'error': 'not found'}, status=404)
    if request.method == 'GET':
        return JsonResponse({
            'article': _full(a, admin=True),
            'revisions': [{'version': r.version, 'title': r.title, 'note': r.note,
                           'editor': r.editor.username if r.editor_id and r.editor else None,
                           'created_at': r.created_at.isoformat()}
                          for r in a.revisions.select_related('editor')],
        })
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)

    b = _body(request)
    admin = acting_admin(request)
    # The text as it stands, so an edit can preserve it even for a row that
    # was created outside this API (a data migration, a shell fix) and
    # therefore has no revision for its current version.
    base_version, base_title, base_body = a.version, a.title, a.body
    text_changed = False

    if 'title' in b:
        title = (str(b.get('title') or '')).strip()[:200]
        if not title:
            return JsonResponse({'error': 'عنوان الزامی است.'}, status=400)
        if title != a.title:
            a.title, text_changed = title, True
    if 'body' in b:
        body = (str(b.get('body') or '')).strip()[:MAX_BODY]
        if not body:
            return JsonResponse({'error': 'متن الزامی است.'}, status=400)
        if body != a.body:
            a.body, text_changed = body, True
    if 'category' in b:
        a.category = (str(b.get('category') or '')).strip()[:60]
    if 'status' in b:
        status = (str(b.get('status') or '')).strip()
        if status not in VALID_STATUSES:
            return JsonResponse({'error': 'وضعیت نامعتبر است.'}, status=400)
        a.status = status
    if 'audience' in b:
        audience = (str(b.get('audience') or '')).strip()
        if audience not in VALID_AUDIENCES:
            return JsonResponse({'error': 'مخاطب نامعتبر است.'}, status=400)
        a.audience = audience
    if 'owner_id' in b:
        raw = b.get('owner_id')
        if raw is None:
            a.owner = None
        else:
            owner = (PlatformAdmin.objects.filter(id=raw, active=True).first()
                     if isinstance(raw, int) and not isinstance(raw, bool) else None)
            if not owner:
                return JsonResponse({'error': 'مالک انتخاب‌شده معتبر نیست.'}, status=400)
            a.owner = owner
    if 'review_interval_days' in b:
        try:
            a.review_interval_days = max(1, min(int(b['review_interval_days']), 3650))
        except (TypeError, ValueError):
            return JsonResponse({'error': 'دورهٔ بازبینی نامعتبر است.'}, status=400)

    if text_changed:
        a.version += 1
        a.reviewed_at = timezone.now()
    elif b.get('reviewed'):
        a.reviewed_at = timezone.now()

    a.save()
    if text_changed:
        if not a.revisions.filter(version=base_version).exists():
            KnowledgeRevision.objects.create(article=a, version=base_version,
                                             title=base_title, body=base_body,
                                             note='pre-edit snapshot')
        _revise(a, admin, note=str(b.get('note') or ''))
    return JsonResponse({'ok': True, 'article': _full(a, admin=True)})


@csrf_exempt
@require_admin_token
def promote_request_view(request, req_id):
    """POST /api/admin/company-requests/<id>/promote-to-article/
            {slug, category?, audience?, title?}

    The loop that makes knowledge transfer actually happen: a resolved ticket
    becomes a DRAFT article seeded with the customer's words and the
    resolution. A draft, not a publication — someone still has to edit it into
    an answer that reads well, and that is a deliberate human step.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    r = CompanyRequest.objects.filter(id=req_id).select_related('company').first()
    if not r:
        return JsonResponse({'error': 'not found'}, status=404)
    if r.status not in CompanyRequest.CLOSED_STATUSES:
        return JsonResponse(
            {'error': 'تا بسته شدن درخواست نمی‌توان از آن مقاله ساخت.'}, status=400)
    if KnowledgeArticle.objects.filter(source_request_id=r.id).exists():
        return JsonResponse({'error': 'از این درخواست قبلاً مقاله ساخته شده است.'},
                            status=400)
    b = _body(request)
    slug = (str(b.get('slug') or '')).strip()[:120]
    if not slug:
        return JsonResponse({'error': 'شناسهٔ مقاله الزامی است.'}, status=400)
    if KnowledgeArticle.objects.filter(slug=slug).exists():
        return JsonResponse({'error': 'این شناسه قبلاً استفاده شده است.'}, status=400)
    audience = (str(b.get('audience') or 'customer')).strip()
    if audience not in VALID_AUDIENCES:
        return JsonResponse({'error': 'مخاطب نامعتبر است.'}, status=400)

    admin = acting_admin(request)
    parts = []
    if r.body:
        parts.append(f'## پرسش\n\n{r.body}')
    public = [m.body for m in r.messages.filter(internal=False).order_by('created_at', 'id')]
    if public:
        parts.append('## گفت‌وگو\n\n' + '\n\n'.join(public))
    if r.admin_note:
        parts.append(f'## پاسخ\n\n{r.admin_note}')
    body = '\n\n'.join(parts) or r.subject

    a = KnowledgeArticle.objects.create(
        slug=slug, title=(str(b.get('title') or '')).strip()[:200] or r.subject,
        body=body[:MAX_BODY], status='draft', audience=audience,
        category=(str(b.get('category') or '')).strip()[:60],
        owner=admin, reviewed_at=timezone.now(), source_request=r)
    _revise(a, admin, note=f'promoted from request #{r.id}')
    return JsonResponse({'ok': True, 'article': _full(a, admin=True)})


# ---------------------------------------------------------------------------
# Metrics (reported inside /api/admin/support/metrics/)
# ---------------------------------------------------------------------------

def metrics(since):
    """Knowledge figures for the window. Definitions in
    audit-evidence/16-improvement-programme/METRIC_DEFINITIONS.md."""
    all_articles = KnowledgeArticle.objects.all()
    stale = sum(1 for a in all_articles if a.is_stale)
    searches = KbSearchLog.objects.filter(created_at__gte=since)
    total = searches.count()
    zero = searches.filter(results=0)
    zero_n = zero.count()
    return {
        'articles': all_articles.count(),
        'published': all_articles.filter(status='published').count(),
        'drafts': all_articles.filter(status='draft').count(),
        'internal': all_articles.filter(audience='internal').count(),
        'stale': stale,
        'unowned': all_articles.filter(owner__isnull=True).count(),
        'from_tickets': all_articles.filter(source_request__isnull=False).count(),
        'views': sum(a.views for a in all_articles),
        'helpful': sum(a.helpful for a in all_articles),
        'unhelpful': sum(a.unhelpful for a in all_articles),
        'searches': total,
        'zero_result_searches': zero_n,
        # None, not 0.0: with no searches there is no rate to report.
        'zero_result_rate': (round(zero_n / total, 4) if total else None),
        'top_misses': [{'query': r['query_norm'], 'count': r['n']}
                       for r in (zero.values('query_norm').annotate(n=Count('id'))
                                 .order_by('-n', 'query_norm')[:20])],
    }
