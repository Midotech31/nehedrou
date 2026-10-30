"""Opt-in HTTPS transport for access emails; no provider setup or network on import."""
import http.client
import json
import math
import re
import ssl
from email import policy
from email.headerregistry import Address
from email.parser import HeaderParser
from itertools import chain
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.message import EmailMessage
from django.core.validators import validate_email
from django.utils.encoding import punycode
from django.utils.functional import Promise


RESEND_HOST = 'api.resend.com'
RESEND_PORT = 443
RESEND_PATH = '/emails'
MAX_RESPONSE_BYTES = 64 * 1024
MAX_REQUEST_BYTES = 1024 * 1024
MAX_API_KEY_LENGTH = 512
MAX_RECIPIENTS = 50
_PROVIDER_ID = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
_EMPTY = object()


class EmailTransportError(OSError):
    """Safe failure shared with invitation handling; never include provider data."""
    def __init__(self):
        super().__init__('Transactional email is unavailable.')


def _has_controls(value):
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def _text(value):
    if not isinstance(value, (str, Promise)):
        raise ValueError
    return str(value)


def _mailbox(value):
    """Parse exactly one complete mailbox without groups or header injection."""
    value = _text(value)
    if not value.strip() or _has_controls(value):
        raise ValueError
    header = HeaderParser(policy=policy.default).parsestr('To: ' + value + '\n')['To']
    if header is None or header.defects or len(header.addresses) != 1:
        raise ValueError
    if any(group.display_name is not None for group in header.groups):
        raise ValueError
    address = header.addresses[0]
    if not address.username or not address.domain:
        raise ValueError
    domain = punycode(address.domain).lower()
    normalized = Address(display_name=address.display_name or '', username=address.username, domain=domain)
    validate_email(normalized.addr_spec)
    if _has_controls(normalized.addr_spec) or _has_controls(normalized.display_name):
        raise ValueError
    return normalized


def _reserved_domain(domain):
    domain = domain.lower().rstrip('.')
    reserved = ('localhost', 'example.com', 'example.net', 'example.org')
    return any(domain == item or domain.endswith('.' + item) for item in reserved) or domain.endswith(('.example', '.test', '.invalid', '.localhost'))


def _valid_key(value):
    return isinstance(value, str) and 1 <= len(value) <= MAX_API_KEY_LENGTH and all(33 <= ord(char) <= 126 for char in value)


def _valid_timeout(value, maximum):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and 1 <= value <= maximum and math.isfinite(value)


def resend_configuration_checks():
    """Local booleans only; credentials/domain ownership and delivery are unverified."""
    sender = None
    try:
        sender = _mailbox(getattr(settings, 'DEFAULT_FROM_EMAIL', ''))
    except (ValidationError, ValueError, TypeError, IndexError):
        pass
    return {
        'enabled': getattr(settings, 'RESEND_ENABLED', False) is True,
        'api_key_present': _valid_key(getattr(settings, 'RESEND_API_KEY', '')),
        'sender_address': sender is not None,
        'sender_not_reserved': sender is not None and not _reserved_domain(sender.domain),
        'connect_timeout_bounded': _valid_timeout(getattr(settings, 'EMAIL_HTTP_CONNECT_TIMEOUT', 5), 15),
        'read_timeout_bounded': _valid_timeout(getattr(settings, 'EMAIL_HTTP_READ_TIMEOUT', 10), 30),
    }


def _first(messages):
    iterator = iter(messages or ())
    return next(iterator, _EMPTY), iterator


class DisabledEmailBackend(BaseEmailBackend):
    """Fail closed without printing tokens, bodies or recipients to server logs."""
    def send_messages(self, email_messages):
        try:
            first, _iterator = _first(email_messages)
            if first is _EMPTY:
                return 0
        except Exception:
            if self.fail_silently:
                return 0
            raise EmailTransportError() from None
        if self.fail_silently:
            return 0
        raise EmailTransportError() from None


class ResendEmailBackend(BaseEmailBackend):
    """One fixed-host HTTPS request per supported message; count accepted messages."""
    def send_messages(self, email_messages):
        sent = 0
        try:
            first, iterator = _first(email_messages)
            if first is _EMPTY:
                return 0
            if not all(resend_configuration_checks().values()):
                raise EmailTransportError()
            sender = _mailbox(settings.DEFAULT_FROM_EMAIL)
            api_key = settings.RESEND_API_KEY
            connect_timeout = float(getattr(settings, 'EMAIL_HTTP_CONNECT_TIMEOUT', 5))
            read_timeout = float(getattr(settings, 'EMAIL_HTTP_READ_TIMEOUT', 10))
            for message in chain((first,), iterator):
                try:
                    payload = self._payload(message, sender)
                    self._post(payload, api_key, connect_timeout, read_timeout)
                    sent += 1
                except Exception:
                    if not self.fail_silently:
                        raise EmailTransportError() from None
        except Exception:
            if not self.fail_silently:
                raise EmailTransportError() from None
        return sent

    @staticmethod
    def _payload(message, sender):
        if not isinstance(message, EmailMessage):
            raise ValueError
        # The current access messages need none of these features. Never drop them.
        if any(getattr(message, name, None) for name in ('cc', 'bcc', 'reply_to', 'attachments', 'extra_headers')):
            raise ValueError
        if getattr(message, 'mixed_subtype', 'mixed') != 'mixed' or getattr(message, 'alternative_subtype', 'alternative') != 'alternative':
            raise ValueError
        encoding = getattr(message, 'encoding', None)
        if encoding is not None and (not isinstance(encoding, str) or encoding.lower().replace('-', '') != 'utf8'):
            raise ValueError
        author = _mailbox(message.from_email)
        if author.addr_spec.casefold() != sender.addr_spec.casefold():
            raise ValueError
        recipients = message.to
        if not isinstance(recipients, (list, tuple)) or not 1 <= len(recipients) <= MAX_RECIPIENTS:
            raise ValueError
        addresses = [str(_mailbox(value)) for value in recipients]
        subject, body = _text(message.subject), _text(message.body)
        if _has_controls(subject):
            raise ValueError
        payload = {'from': str(sender), 'to': addresses, 'subject': subject}
        subtype = message.content_subtype
        alternatives = getattr(message, 'alternatives', [])
        if not isinstance(alternatives, (list, tuple)) or len(alternatives) > 1:
            raise ValueError
        if subtype == 'plain':
            payload['text'] = body
            if alternatives:
                content, mimetype = alternatives[0]
                if mimetype != 'text/html':
                    raise ValueError
                payload['html'] = _text(content)
        elif subtype == 'html' and not alternatives:
            payload['html'] = body
        else:
            raise ValueError
        encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
        if len(encoded) > MAX_REQUEST_BYTES:
            raise ValueError
        return encoded

    @staticmethod
    def _post(payload, api_key, connect_timeout, read_timeout):
        connection = response = None
        try:
            context = ssl.create_default_context()
            connection = http.client.HTTPSConnection(RESEND_HOST, RESEND_PORT, timeout=connect_timeout, context=context)
            connection.set_debuglevel(0)
            connection.connect()
            if connection.sock is None:
                raise EmailTransportError()
            connection.sock.settimeout(read_timeout)
            connection.request('POST', RESEND_PATH, body=payload, headers={
                'Authorization': 'Bearer ' + api_key,
                'Content-Type': 'application/json; charset=utf-8',
                'Accept': 'application/json',
                'Idempotency-Key': str(uuid4()),
            })
            response = connection.getresponse()
            if not 200 <= response.status < 300:
                raise EmailTransportError()
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE_BYTES:
                raise EmailTransportError()
            result = json.loads(raw.decode('utf-8'))
            identifier = result.get('id') if isinstance(result, dict) else None
            if not isinstance(identifier, str) or not _PROVIDER_ID.fullmatch(identifier):
                raise EmailTransportError()
        except Exception:
            raise EmailTransportError() from None
        finally:
            # A cleanup failure does not undo provider acceptance or reveal its body.
            for resource in (response, connection):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception:
                        pass
