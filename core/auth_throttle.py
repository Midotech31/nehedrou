"""Operation-specific database quotas with concurrent admission reservations.

Counts include in-flight attempts. Proven authentication successes refund only their
own reservations; they never clear another request's failures. Successful account
creation stays charged to bound resource creation, without a failure cooldown.
Password reset email requests count even when their neutral response is a redirect.
"""
from datetime import timedelta
from ipaddress import ip_address, ip_network
from math import ceil

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.utils.translation import gettext as _

from .models import RateWindow

WINDOW_SECONDS = 15 * 60
# Pair, identifier, origin. Origin budgets are deliberately generous for shared NAT.
LIMITS = {
    'login': (10, 30, 120),
    'signup': (5, 10, 100),
    'invite': (10, 30, 120),
    'password_reset': (3, 5, 100),
    'password_reset_confirm': (5, 10, 100),
    'mfa_setup': (5, 10, 120),
    'mfa_verify': (5, 10, 120),
    'mfa_recovery': (5, 10, 120),
}


def client_origin(request):
    """Trust XFF only behind configured proxies, walking from the immediate peer.

    Malformed configuration or headers fail closed to REMOTE_ADDR. The ingress
    must append/replace XFF and reject direct access before being allowlisted.
    """
    peer = request.META.get('REMOTE_ADDR', '')
    try:
        address = ip_address(peer)
    except ValueError:
        return 'unknown-peer'
    configured = getattr(settings, 'AUTH_TRUSTED_PROXY_CIDRS', [])
    if isinstance(configured, str):
        configured = [entry.strip() for entry in configured.split(',') if entry.strip()]
    try:
        networks = [ip_network(entry, strict=False) for entry in configured]
    except (ValueError, TypeError):
        return str(address)
    trusted = lambda item: any(item.version == network.version and item in network for network in networks)
    if not trusted(address):
        return str(address)
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if not forwarded or len(forwarded) > 2048:
        return str(address)
    parts = forwarded.split(',')
    if len(parts) > 20:
        return str(address)
    try:
        chain = [ip_address(part.strip()) for part in parts]
    except ValueError:
        return str(address)
    for hop in reversed(chain):
        address = hop
        if not trusted(hop):
            break
    return str(address)


def attempt_identity(request, operation):
    if operation.startswith('mfa_'):
        return 'user:' + str(request.user.pk) if request.user.is_authenticated else 'anonymous'
    if operation == 'invite':
        return request.resolver_match.kwargs.get('token', '')[:256]
    if operation == 'password_reset_confirm':
        return request.resolver_match.kwargs.get('uidb64', '')[:256]
    field = 'email' if operation in ('password_reset', 'signup') else 'username'
    return request.POST.get(field, '').strip().casefold()[:254] or 'missing-identifier'


def bucket_specs(operation, identifier, origin):
    values = [('pair', identifier + '\0' + origin), ('identifier', identifier), ('origin', origin)]
    specs = [(salted_hmac('nehedrou.auth.' + operation + '.' + scope, value, algorithm='sha256').hexdigest(), limit, scope)
             for (scope, value), limit in zip(values, LIMITS[operation])]
    # Consistent scope order avoids deadlocks. Check the origin first so an
    # exhausted spraying client cannot create unbounded new identifier rows.
    return sorted(specs, key=lambda spec: {'origin':0, 'identifier':1, 'pair':2}[spec[2]])


def limited_response(retry_after):
    response = HttpResponse(_('Too many attempts. Try again later.'), status=429)
    response['Retry-After'] = str(max(1, ceil(retry_after)))
    response['Cache-Control'] = 'private, no-store'
    return response


def reserve_attempt(request):
    match = getattr(request, 'resolver_match', None)
    operation = match.url_name if match else None
    if request.method != 'POST' or operation not in LIMITS:
        return None
    specs = bucket_specs(operation, attempt_identity(request, operation), client_origin(request))
    now = timezone.now()
    retry_after = 0
    with transaction.atomic():
        windows = []
        for key, limit, scope in specs:
            window, _created = RateWindow.objects.get_or_create(key=key)
            window = RateWindow.objects.select_for_update().get(pk=window.pk)
            if window.created_at <= now - timedelta(seconds=WINDOW_SECONDS):
                window.count = 0
                window.created_at = now
                window.blocked_until = None
                window.save(update_fields=['count', 'created_at', 'blocked_until'])
            if window.count >= limit:
                retry_after = max(retry_after, (window.created_at + timedelta(seconds=WINDOW_SECONDS) - now).total_seconds())
            if window.blocked_until and window.blocked_until > now:
                retry_after = max(retry_after, (window.blocked_until - now).total_seconds())
            if retry_after:
                return max(1, ceil(retry_after))
            windows.append((window, scope))
        for window, _scope in windows:
            window.count += 1
            window.save(update_fields=['count'])
        request._auth_attempt = (operation, [(window.pk, window.created_at, scope) for window, scope in windows])
    return None


def authentication_succeeded(request):
    """Call only after the credential/token has actually been verified."""
    request._auth_succeeded = True


def finish_attempt(request, response):
    reservation = getattr(request, '_auth_attempt', None)
    if not reservation:
        return
    del request._auth_attempt
    operation, windows = reservation
    successful = getattr(request, '_auth_succeeded', False)
    if operation in ('login', 'signup', 'invite'):
        successful = response.status_code == 302 and request.user.is_authenticated
    if operation == 'password_reset_confirm':
        successful = response.status_code == 302 and response.headers.get('Location', '').endswith('/reset/done/')
    now = timezone.now()
    with transaction.atomic():
        for pk, started, scope in windows:
            window = RateWindow.objects.select_for_update().filter(pk=pk, created_at=started).first()
            if not window:
                continue  # An older request cannot modify a newer window.
            if successful:
                if operation == 'signup':
                    continue  # Successful account creation still consumes resources.
                window.count = max(0, window.count - 1)
                window.save(update_fields=['count'])
            elif scope == 'pair' and window.count >= 3:
                delay = min(300, 2 ** min(window.count - 2, 9))
                until = now + timedelta(seconds=delay)
                window.blocked_until = max(window.blocked_until or until, until)
                window.save(update_fields=['blocked_until'])
