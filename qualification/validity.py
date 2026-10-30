"""Structured validity declarations; contract text is retained, never interpreted."""
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

VALIDITY_CHOICES = [('unknown', _('Validity to document')), ('limited', _('Limited period')), ('unlimited', _('Unlimited period'))]


def validate_validity(validity, start, end):
    if validity == 'limited' and not end:
        raise ValidationError(_('A limited permission requires an expiry date.'))
    if validity != 'limited' and end:
        raise ValidationError(_('Only a limited permission may have an expiry date.'))
    if start and end and end < start:
        raise ValidationError(_('The expiry date cannot precede the validity start date.'))


def currently_valid(validity, start, end, revoked=False):
    today = timezone.localdate()
    return bool(not revoked and validity in ['limited', 'unlimited']
        and (not start or today >= start)
        and (validity == 'unlimited' or (end and today <= end)))
