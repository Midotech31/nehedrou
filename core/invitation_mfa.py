"""Carry an authenticated recipient's exact invitation across a forced MFA challenge."""
import hashlib
import re
from urllib.parse import urlencode

from django.urls import Resolver404, resolve, reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from django.views.decorators.debug import sensitive_variables

from catalog.models import EditorialAccessInvitation
from .models import Invitation


SESSION_KEY = 'mfa_practice_invitation'
PARAM = 'invitation'
TTL_SECONDS = 15 * 60
KINDS_BY_INVITATION_ROUTE = {'invite': 'practice', 'accept_editorial_invite': 'editorial'}
MODELS_BY_KIND = {'practice': Invitation, 'editorial': EditorialAccessInvitation}
RESUME_BY_KIND = {'practice': 'resume_practice_invitation', 'editorial': 'resume_editorial_invitation'}


def _marker(entry):
    value = f'{entry["actor"]}:{entry["digest"]}:{entry["started_at"]}'
    if 'kind' in entry:
        value += ':' + entry['kind']
    # Existing practice-only challenges can finish through the practice route.
    return salted_hmac('core.practice-invitation-mfa.v1', value, algorithm='sha256').hexdigest()


@sensitive_variables('token', 'match')
def remember_invitation(request):
    if request.method != 'GET':
        return ''
    try:
        match = resolve(request.path_info, urlconf=getattr(request, 'urlconf', None))
    except Resolver404:
        return ''
    kind = KINDS_BY_INVITATION_ROUTE.get(match.view_name)
    if not kind:
        return ''
    token = match.kwargs['token']
    if len(token) > 256:
        return ''
    digest = hashlib.sha256(token.encode()).hexdigest()
    address = MODELS_BY_KIND[kind].objects.filter(token_hash=digest).values_list('email', flat=True).first()
    if not address or address.strip().lower() != request.user.email.strip().lower():
        return ''
    entry = {'actor': str(request.user.pk), 'digest': digest, 'kind': kind,
             'started_at': int(timezone.now().timestamp())}
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
            or entry.get('kind', 'practice') not in ('practice', 'editorial')
            or not isinstance(entry.get('digest'), str) or not re.fullmatch(r'[0-9a-f]{64}', entry['digest'])
            or type(entry.get('started_at')) is not int or not 0 <= current - entry['started_at'] <= TTL_SECONDS):
        request.session.pop(SESSION_KEY, None)
        return None
    # One tab must not act on another invitation which replaced its continuation.
    return entry if constant_time_compare(markers[0], _marker(entry)) else None


def challenge_context(request):
    entry = _matching_entry(request)
    if not entry:
        return '', ''
    marker = request.GET[PARAM]
    return marker, challenge_url(RESUME_BY_KIND[entry.get('kind', 'practice')], marker)


def invitation_digest(request, *, kind):
    entry = _matching_entry(request)
    return entry['digest'] if entry and entry.get('kind', 'practice') == kind else None


def challenge_url(route, marker=''):
    path = reverse(route)
    return f'{path}?{urlencode({PARAM: marker})}' if marker else path
