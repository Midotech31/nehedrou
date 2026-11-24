"""Carry an authenticated recipient's exact invitation across a forced MFA challenge."""
import hashlib
import re
from urllib.parse import urlencode

from django.urls import Resolver404, resolve, reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from django.views.decorators.debug import sensitive_variables

from .models import Invitation


SESSION_KEY = 'mfa_practice_invitation'
PARAM = 'invitation'
TTL_SECONDS = 15 * 60


def _marker(entry):
    value = f'{entry["actor"]}:{entry["digest"]}:{entry["started_at"]}'
    return salted_hmac('core.practice-invitation-mfa.v1', value, algorithm='sha256').hexdigest()


@sensitive_variables('token', 'match')
def remember_invitation(request):
    if request.method != 'GET':
        return ''
    try:
        match = resolve(request.path_info, urlconf=getattr(request, 'urlconf', None))
    except Resolver404:
        return ''
    if match.view_name != 'invite':
        return ''
    token = match.kwargs['token']
    if len(token) > 256:
        return ''
    digest = hashlib.sha256(token.encode()).hexdigest()
    if not Invitation.objects.filter(token_hash=digest, email__iexact=request.user.email).exists():
        return ''
    entry = {'actor': str(request.user.pk), 'digest': digest, 'started_at': int(timezone.now().timestamp())}
    request.session[SESSION_KEY] = entry
    return _marker(entry)


def _matching_entry(request):
    markers = request.GET.getlist(PARAM)
    if len(markers) != 1 or not re.fullmatch(r'[0-9a-f]{64}', markers[0]):
        return None
    entry = request.session.get(SESSION_KEY)
    if entry is None:
        return None
    current = int(timezone.now().timestamp())
    if (not isinstance(entry, dict) or entry.get('actor') != str(request.user.pk)
            or not isinstance(entry.get('digest'), str) or not re.fullmatch(r'[0-9a-f]{64}', entry['digest'])
            or type(entry.get('started_at')) is not int or not 0 <= current - entry['started_at'] <= TTL_SECONDS):
        request.session.pop(SESSION_KEY, None)
        return None
    # One tab must not act on another invitation which replaced its continuation.
    return entry if constant_time_compare(markers[0], _marker(entry)) else None


def challenge_marker(request):
    return request.GET[PARAM] if _matching_entry(request) else ''


def invitation_digest(request):
    entry = _matching_entry(request)
    return entry['digest'] if entry else None


def challenge_url(route, marker=''):
    path = reverse(route)
    return f'{path}?{urlencode({PARAM: marker})}' if marker else path
