"""Bind organization-implicit mutations to the form that the user actually opened."""
from django.core import signing
from django.utils.translation import gettext_lazy as _

FIELD = 'practice_scope'
SALT = 'core.practice-form-scope.v1'
MAX_AGE = 8 * 60 * 60
ERROR = _('This form no longer matches the selected practice. Reopen it in the intended practice before saving.')


def practice_form_scope(request, organization, operation):
    """Return the original token and whether this request still matches its scope.

    A signature is not authorization: views must still check current roles and
    services must still enforce their permissions, quotas and object invariants.
    Never replace a rejected POST token with one for the newly selected practice.
    """
    expected = {'version': 1, 'actor': str(request.user.pk),
                'organization': str(organization.pk) if organization else None,
                'operation': operation}
    if request.method != 'POST':
        return signing.dumps(expected, salt=SALT), True
    token = request.POST.get(FIELD, '')
    if not organization or not isinstance(token, str) or not token or len(token) > 4096:
        return token, False
    try:
        payload = signing.loads(token, salt=SALT, max_age=MAX_AGE)
    except (signing.BadSignature, ValueError, TypeError):
        return token, False
    return token, payload == expected
