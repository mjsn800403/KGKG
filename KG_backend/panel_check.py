"""Does the admin panel actually SEE it now? Query with the panel's own defaults."""
import os, django, datetime as dt
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'KG_backend.settings')
django.setup()
from django.utils import timezone
from api.models import ActivityLog

MARK = 'بازسازی‌شده'
now = timezone.now()
print("now:", now)
print()
print("window   total   reconstructed   genuine")
for d in (7, 14, 30, 90):
    since = now - dt.timedelta(days=d)
    q = ActivityLog.objects.filter(created_at__gte=since)
    tot = q.count()
    rec = q.filter(detail__contains=MARK).count()
    print("  %-3dd   %-6d  %-14d  %d" % (d, tot, rec, tot - rec))

print()
print("=== feature-usage counts, 7-day window (what admin_traffic_view shows) ===")
from django.db.models import Count
since = now - dt.timedelta(days=7)
for r in (ActivityLog.objects.filter(created_at__gte=since)
          .values('action').annotate(n=Count('id')).order_by('-n')):
    print("   %-16s %d" % (r['action'], r['n']))

print()
print("=== portal usage view, 30-day default: top users ===")
since = now - dt.timedelta(days=30)
for r in (ActivityLog.objects.filter(created_at__gte=since)
          .values('user__username').annotate(n=Count('id')).order_by('-n')[:8]):
    print("   %-20s %d" % (r['user__username'], r['n']))

print()
print("=== monthly totals (reconstructed + genuine) ===")
from collections import Counter
rec = Counter(); gen = Counter()
for l in ActivityLog.objects.only('created_at', 'detail'):
    k = l.created_at.strftime('%Y-%m')
    (rec if MARK in l.detail else gen)[k] += 1
for k in sorted(set(rec) | set(gen)):
    t = rec[k] + gen[k]
    print("   %s  rec=%-5d gen=%-5d total=%-5d %s" % (k, rec[k], gen[k], t, '#' * (t // 20)))
