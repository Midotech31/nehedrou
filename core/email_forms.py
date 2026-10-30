"""Access emails always link to the operator-controlled canonical origin."""
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.forms import PasswordResetForm


class CanonicalPasswordResetForm(PasswordResetForm):
    def save(self, domain_override=None, **kwargs):
        # Settings validate this origin at startup. Request Host and proxy headers
        # must never determine the destination of an outbound recovery link.
        origin = urlsplit(settings.PUBLIC_ORIGIN)
        kwargs['use_https'] = origin.scheme == 'https'
        context = dict(kwargs.get('extra_email_context') or {})
        context.update(domain=origin.netloc, site_name=settings.PRODUCT_NAME,
                       protocol='https' if kwargs['use_https'] else 'http')
        kwargs['extra_email_context'] = context
        return super().save(domain_override=origin.netloc, **kwargs)
