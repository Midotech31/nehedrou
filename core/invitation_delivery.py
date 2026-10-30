"""Sender-facing invitation guidance from local configuration only.

No transport is constructed, no message is sent, and no credentials or arbitrary
backend identifiers are returned. This helper does not change invitation history,
tokens, creation or revocation. Views must re-evaluate it before a resend.
"""
from django.conf import settings
from django.utils.translation import gettext_lazy as _


DISABLED = 'core.email_backends.DisabledEmailBackend'
CONSOLE = 'django.core.mail.backends.console.EmailBackend'
SUPPORTED = ('core.email_backends.ResendEmailBackend',
             'django.core.mail.backends.smtp.EmailBackend')


def invitation_delivery_status():
    """Describe the supported local configuration; never establish delivery.

    SMTP uses the project's supported deployment profile (authenticated encrypted
    transport), not a claim that every other SMTP relay is technically impossible.
    Unknown backends, including locmem test backends, keep their existing behavior.
    """
    selected = settings.EMAIL_BACKEND
    if selected == DISABLED:
        state = 'unavailable'
    elif selected == CONSOLE:
        state = 'local_console' if settings.DEBUG and not getattr(settings, 'IS_RENDER', False) else 'unavailable'
    elif selected in SUPPORTED:
        from .ops_readiness import email_configuration
        try:
            configured = email_configuration()['configured']
        except (AttributeError, TypeError, ValueError, OverflowError):
            # Malformed supported settings cannot satisfy the local profile.
            configured = False
        state = 'configuration_present' if configured else 'unavailable'
    else:
        state = 'unverified_backend'

    known_unavailable = state == 'unavailable'
    if known_unavailable:
        notice = _('Email delivery is not configured for this service. You can record an invitation; recording it does not confirm an email was sent. Ask the service operator to configure delivery.')
    elif state == 'local_console':
        notice = _('Local development only: invitation messages are written to the console. No recipient delivery is provided by this transport.')
    elif state == 'configuration_present':
        notice = _('Email transport settings are present. This check does not verify sending or receipt.')
    else:
        notice = _('This email transport has not been checked here. An invitation status does not confirm receipt.')

    return {
        'state': state,
        'known_unavailable': known_unavailable,
        'can_retry': not known_unavailable,
        'submit_label': _('Record invitation') if state in ('unavailable', 'local_console') else _('Send invitation'),
        'notice': notice,
        'failure_message': (
            _('Invitation recorded, but email delivery is unavailable in this configuration. Ask the service operator to configure delivery before retrying.')
            if known_unavailable else
            _('Invitation saved, but email delivery failed. Retry from pending invitations.')
        ),
        'retry_blocked_message': _('Email delivery is unavailable in this configuration. The existing invitation has been kept. Ask the service operator to configure delivery before retrying.'),
        'network_attempted': False,
        'delivery_verified': False,
    }
