"""Security / AI / SMS alert rules and off-dashboard delivery.

Plugs into monitoring.evaluate_alerts(): ``evaluate()`` returns the same
``{key: (severity, message, context)}`` shape, and every key starts with one of
``OWNED_PREFIXES`` so the evaluator auto-resolves them when they clear.

``deliver()`` is called when an alert is newly opened. It SMSes the numbers in
KG_ALERT_PHONES (comma separated) for critical alerts and for any ``sec:``
alert, with a per-key cooldown so a flapping condition cannot spam. SMS bodies
follow the Melipayamak rules: Persian needs the لغو11 footer, no links.
"""
import logging
import os
import re
from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone

log = logging.getLogger('kgkg.alerts')

OWNED_PREFIXES = ('sec:', 'ai:', 'sms:')


def _env_num(name, default, cast=int):
    try:
        return cast(os.environ.get(name, default))
    except (TypeError, ValueError):
        return cast(default)


# Thresholds (all overridable from .env.prod).
LOGIN_FAIL_PER_IP = _env_num('KG_ALERT_LOGIN_FAIL_IP', 20)          # / 15 min
LOGIN_FAIL_PER_ACCOUNT = _env_num('KG_ALERT_LOGIN_FAIL_ACCOUNT', 10)  # / 15 min
ADMIN_LOGIN_FAILS = _env_num('KG_ALERT_ADMIN_FAILS', 5)              # / 15 min
SMS_FAILS = _env_num('KG_ALERT_SMS_FAILS', 3)                        # / 1 h
AI_DEGRADED_RATE = _env_num('KG_ALERT_AI_DEGRADED', 0.3, float)      # / 1 h
AI_MIN_ANSWERS = _env_num('KG_ALERT_AI_MIN_N', 5)
AI_COST_SPIKE_X = _env_num('KG_ALERT_AI_COST_X', 3.0, float)          # 24h vs 7-day daily avg
AI_COST_FLOOR = _env_num('KG_ALERT_AI_COST_FLOOR', 0.5, float)        # ignore tiny absolute spend
SMS_COOLDOWN_H = _env_num('KG_ALERT_SMS_COOLDOWN_H', 6)

_AUTH_LOGIN = ('auth.login', 'auth.verify_otp', 'auth.recover_reset')


def evaluate():
    firing = {}
    for rule in (_login_bruteforce, _admin_logins, _sms_failures, _ai_health):
        try:
            firing.update(rule())
        except Exception:
            log.exception('alert rule %s failed', rule.__name__)
    return firing


def _login_bruteforce():
    from .models import AuditLog
    out = {}
    since = timezone.now() - timedelta(minutes=15)
    fails = AuditLog.objects.filter(created_at__gte=since, action__in=_AUTH_LOGIN,
                                    status_code=401)
    for row in (fails.values('ip').annotate(n=Count('id'))
                .filter(n__gte=LOGIN_FAIL_PER_IP).order_by('-n')[:5]):
        out[f"sec:login_ip:{row['ip']}"] = (
            'critical',
            f"{row['n']} تلاش ناموفق ورود از IP {row['ip']} در ۱۵ دقیقهٔ اخیر (احتمال حملهٔ حدس رمز).",
            {'ip': row['ip'], 'fails': row['n']})
    for row in (fails.exclude(target_id='').values('target_id').annotate(n=Count('id'))
                .filter(n__gte=LOGIN_FAIL_PER_ACCOUNT).order_by('-n')[:5]):
        out[f"sec:login_account:{row['target_id']}"] = (
            'warning',
            f"{row['n']} تلاش ناموفق ورود به حساب «{row['target_id']}» در ۱۵ دقیقهٔ اخیر.",
            {'account': row['target_id'], 'fails': row['n']})
    return out


def _admin_logins():
    from .models import AuditLog
    out = {}
    since = timezone.now() - timedelta(minutes=15)
    qs = AuditLog.objects.filter(created_at__gte=since,
                                 action__in=('admin.login', 'admin.verify_otp'))
    n_fail = qs.filter(status_code=401).count()
    if n_fail >= ADMIN_LOGIN_FAILS:
        out['sec:admin_login_fails'] = (
            'critical', f'{n_fail} تلاش ناموفق ورود به پنل ادمین در ۱۵ دقیقهٔ اخیر.',
            {'fails': n_fail})
    no2fa = list(qs.filter(action='admin.login', status_code=200,
                           detail__no_2fa=True).values_list('actor_label', 'ip')[:5])
    if no2fa:
        out['sec:admin_no_2fa'] = (
            'critical',
            'ورود ادمین بدون رمز دوم پیامکی: ' + '، '.join(f'{u} از {ip}' for u, ip in no2fa),
            {'logins': [{'admin': u, 'ip': ip} for u, ip in no2fa]})
    return out


def _sms_failures():
    from .models import AuditLog, NotificationLog
    since = timezone.now() - timedelta(hours=1)
    notify_fail = NotificationLog.objects.filter(created_at__gte=since, sent=False).count()
    # OTP sends that failed surface as 502/503 on the login/recover endpoints.
    otp_fail = AuditLog.objects.filter(created_at__gte=since, action__startswith='auth.',
                                       status_code__in=(502, 503)).count()
    otp_fail += AuditLog.objects.filter(created_at__gte=since, action='admin.login',
                                        status_code=502).count()
    total = notify_fail + otp_fail
    if total >= SMS_FAILS:
        sev = 'critical' if otp_fail >= SMS_FAILS else 'warning'
        return {'sms:send_failures': (
            sev,
            f'{total} پیامک در یک ساعت اخیر ارسال نشد ({otp_fail} کد ورود، {notify_fail} اعلان). '
            'اعتبار یا خط ملی‌پیامک را بررسی کنید.',
            {'otp_failures': otp_fail, 'notify_failures': notify_fail})}
    return {}


def _ai_health():
    from .models import ChatLog
    out = {}
    now = timezone.now()
    hour = ChatLog.objects.filter(created_at__gte=now - timedelta(hours=1))
    n = hour.count()
    if n >= AI_MIN_ANSWERS:
        deg = hour.filter(degraded=True).count()
        if deg / n >= AI_DEGRADED_RATE:
            out['ai:degraded'] = (
                'critical',
                f'دستیار هوشمند در {deg} از {n} پاسخ ساعت اخیر بدون مدل زبانی (حالت پشتیبان) پاسخ داده — Metis را بررسی کنید.',
                {'answers': n, 'degraded': deg})
    day = (ChatLog.objects.filter(created_at__gte=now - timedelta(days=1))
           .aggregate(c=Sum('llm_cost'))['c'] or 0)
    week = (ChatLog.objects.filter(created_at__gte=now - timedelta(days=8),
                                   created_at__lt=now - timedelta(days=1))
            .aggregate(c=Sum('llm_cost'))['c'] or 0)
    baseline = week / 7
    if day >= AI_COST_FLOOR and baseline > 0 and day >= AI_COST_SPIKE_X * baseline:
        out['ai:cost_spike'] = (
            'warning',
            f'هزینهٔ دستیار در ۲۴ ساعت اخیر {day:.2f} است؛ {day / baseline:.1f} برابر میانگین روزانهٔ هفتهٔ قبل.',
            {'cost_24h': round(day, 4), 'daily_avg_7d': round(baseline, 4)})
    return out


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

def _phones():
    return [p.strip() for p in os.environ.get('KG_ALERT_PHONES', '').split(',') if p.strip()]


def deliver(key, severity, message):
    """SMS a newly-opened alert to the on-call numbers. Best-effort."""
    if not (severity == 'critical' or key.startswith('sec:')):
        return
    phones = _phones()
    if not phones:
        return
    from .models import SystemState
    state = SystemState.get('alert_sms_sent', {})
    now = timezone.now()
    last = state.get(key)
    if last:
        try:
            from datetime import datetime
            if now - datetime.fromisoformat(last) < timedelta(hours=SMS_COOLDOWN_H):
                return
        except ValueError:
            pass
    from .portal import _post_sms
    # The operator rejects anything that looks like a link or an @domain, so
    # defuse dotted numbers (IPs) and @ in usernames before sending.
    body = re.sub(r'(\d)\.(?=\d)', '\\1٫', message[:250]).replace('@', ' at ')
    text = f'خدمات گستر\nهشدار سامانه ({severity}):\n{body}\nلغو11'
    sent_any = False
    for phone in phones:
        try:
            ok, value = _post_sms(phone, text)
            sent_any = sent_any or ok
            if not ok:
                log.warning('alert SMS %s to %s failed (Value=%s)', key, phone[-4:], value)
        except Exception:
            log.exception('alert SMS %s crashed', key)
    if sent_any:
        state[key] = now.isoformat()
        SystemState.put('alert_sms_sent', state)
