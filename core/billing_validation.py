"""Billing format checks; a three-letter code is not an ISO currency approval."""
import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


def validate_billing_currency(value):
    if not isinstance(value, str) or re.fullmatch(r'[A-Z]{3}', value) is None:
        raise ValidationError(
            _('Use exactly three uppercase Latin letters for the currency (for example, DZD).'),
            code='invalid_currency_format',
        )
