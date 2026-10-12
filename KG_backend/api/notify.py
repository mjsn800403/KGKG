"""SMS notifications for portal users (settings → اعلان‌ها).

Two kinds, each opt-out per user and only for accounts with a phone:
  * manual_update — a car the user can open was re-parsed into the warehouse.
  * new_device    — a login from a browser this account has not used before.

Bodies follow the Melipayamak constraints (see portal._OTP_SMS_TEXT): Persian
needs the ``لغو11`` footer and no links/@domains are allowed.
"""
import hashlib
import logging
import secrets
from datetime import timedelta

from django.utils import timezone

log = logging.getLogger('kgkg.notify')

DEVICE_COOKIE = 'kg_dev'
_MANUAL_TEXT = "خدمات گستر\nمنوال تعمیر {car} به‌روزرسانی شد.\nلغو11"
_CLONE_TEXT = ("خدمات گستر\nهشدار امنیتی: شناسه دستگاه حساب {user} کپی و استفاده شده است ({when}).\n"
               "همه نشست‌ها خارج شدند. رمز عبور را تغییر دهید.\nلغو11")
_DEVICE_TEXT = ("خدمات گستر\nورود به حساب {user} از یک دستگاه جدید در {when}.\n"
                "اگر شما نبودید رمز عبور را تغییر دهید.\nلغو11")


def _send(user, kind, key, text):
    from .models import NotificationLog
    from .portal import _post_sms
    ok = False
    try:
        ok, value = _post_sms(user.phone.strip(), text)
        if not ok:
            log.warning('notify %s to %s failed (Value=%s)', kind, user.username, value)
    except Exception:
        log.exception('notify %s to %s crashed', kind, user.username)
    NotificationLog.objects.create(user=user, kind=kind, key=key[:300], sent=bool(ok))
    return ok


# The trailing لغو11 opt-out line is required by the operator for any Persian
# body (without it the send fails with Value 11).
_WELCOME_TEXT = ("کاربر گرامی، به KGTechVault خوش آمدید.\n"
                 "حساب کاربری شما با موفقیت ایجاد شد.\n\n"
                 "نام کاربری: {username}\n"
                 "رمز عبور: {password}\n\n"
                 "در صورت بروز هرگونه مشکل، با پشتیبانی تماس بگیرید\n"
                 "سپاس از همراهی شما\n"
                 "لغو11")


def send_welcome_credentials(user, password):
    """SMS a newly created account its username + password (no link: the
    operator rejects bodies with links). Returns True when sent."""
    from .models import NotificationLog
    from .portal import _post_sms
    phone = (user.phone or '').strip()
    if not phone:
        return False
    ok = False
    try:
        ok, value = _post_sms(phone, _WELCOME_TEXT.format(username=user.username, password=password))
        if not ok:
            log.warning('welcome SMS to %s failed (Value=%s)', user.username, value)
    except Exception:
        log.exception('welcome SMS to %s crashed', user.username)
    # The password itself is never stored in the log.
    NotificationLog.objects.create(user=user, kind='welcome', key='', sent=bool(ok))
    return ok


def notify_manual_update(car):
    """SMS every opted-in active user who can open ``car``. At most one per
    user per car per 24h, so a pipeline re-run cannot spam."""
    from .access import user_can_open_car
    from .models import NotificationLog, PortalUser
    since = timezone.now() - timedelta(hours=24)
    users = (PortalUser.objects
             .filter(car_accesses__car_id=car.id, active=True, locked=False,
                     company__active=True, notify_manual_update=True)
             .exclude(phone='').select_related('company').distinct())
    sent = 0
    for u in users:
        try:
            if not user_can_open_car(u, car):
                continue
            key = f'car:{car.id}'
            if NotificationLog.objects.filter(user=u, kind='manual_update', key=key,
                                              created_at__gte=since).exists():
                continue
            name = (car.car_name or '').strip()[:80]
            if _send(u, 'manual_update', key, _MANUAL_TEXT.format(car=name)):
                sent += 1
        except Exception:
            log.exception('manual-update notify for %s failed', u.username)
    return sent


def _h(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def check_login_device(user, request, response, keep_token_id=None):
    """Recognise the browser via the rotating ``kg_dev`` cookie.

    Every login swaps the device ID for a fresh one and retires the old one
    (like refresh-token rotation). Outcomes:
      * current ID      -> same device chain; rotate silently.
      * retired ID      -> the cookie was copied: SMS the owner and sign out
                           every other session of the account.
      * unknown/missing -> new device: SMS (except the account's very first).
    Security SMS go out whenever a phone is on file; the new-device one also
    honours the ``notify_new_device`` preference."""
    from .models import KnownDevice, RetiredDevice
    try:
        old = (request.COOKIES.get(DEVICE_COOKIE) or '').strip() if request else ''
        ua = (request.META.get('HTTP_USER_AGENT', '') if request else '')[:300]
        new = secrets.token_hex(16)
        has_phone = bool((user.phone or '').strip())
        dev = KnownDevice.objects.filter(user=user, device_hash=_h(old)).first() if old else None
        if dev is not None:
            RetiredDevice.objects.create(user=user, device_hash=dev.device_hash)
            dev.device_hash, dev.user_agent = _h(new), ua
            dev.save(update_fields=['device_hash', 'user_agent', 'last_seen'])
        else:
            cloned = bool(old) and RetiredDevice.objects.filter(
                user=user, device_hash=_h(old)).exists()
            had_any = KnownDevice.objects.filter(user=user).exists()
            KnownDevice.objects.create(user=user, device_hash=_h(new), user_agent=ua)
            from .portal import _tehran_str
            if cloned:
                tokens = user.tokens.all()
                if keep_token_id is not None:
                    tokens = tokens.exclude(pk=keep_token_id)
                tokens.delete()
                log.warning('device-ID reuse for %s: other sessions revoked', user.username)
                if has_phone:
                    _send(user, 'device_clone', _h(old)[:16],
                          _CLONE_TEXT.format(user=user.username, when=_tehran_str()))
            elif had_any and user.notify_new_device and has_phone:
                _send(user, 'new_device', _h(new)[:16],
                      _DEVICE_TEXT.format(user=user.username, when=_tehran_str()))
        raw = new
        response.set_cookie(DEVICE_COOKIE, raw, max_age=2 * 365 * 86400,
                            httponly=True, secure=True, samesite='Lax', path='/')
    except Exception:
        log.exception('device check for %s failed', user.username)
    return response
