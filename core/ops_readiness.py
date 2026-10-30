"""Private operator checks: no messages, credentials, patient content or network by default."""
import time
from urllib.parse import urlsplit
from email.utils import parseaddr
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import connection, DatabaseError
from core.storage_health import STORAGE_ERRORS

MAX_PROBE_BYTES = 1024 * 1024


def smtp_configuration():
    checks = {
        'smtp_backend': settings.EMAIL_BACKEND == 'django.core.mail.backends.smtp.EmailBackend',
        'host_present': bool(settings.EMAIL_HOST.strip()),
        'port_valid': isinstance(settings.EMAIL_PORT, int) and 1 <= settings.EMAIL_PORT <= 65535,
        'one_transport_security_mode': bool(settings.EMAIL_USE_TLS) != bool(getattr(settings, 'EMAIL_USE_SSL', False)),
        'bounded_timeout': isinstance(getattr(settings, 'EMAIL_TIMEOUT', None), (int, float)) and 0 < settings.EMAIL_TIMEOUT <= 60,
        'credentials_present': bool(settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD),
        'sender_address': False,
        'sender_not_reserved': False,
    }
    try:
        sender = parseaddr(settings.DEFAULT_FROM_EMAIL)[1]
        if '\n' in settings.DEFAULT_FROM_EMAIL or '\r' in settings.DEFAULT_FROM_EMAIL:
            raise ValidationError('invalid sender')
        validate_email(sender)
    except ValidationError:
        pass
    else:
        checks['sender_address'] = True
        domain = sender.rsplit('@', 1)[-1].lower()
        checks['sender_not_reserved'] = not (domain in ['localhost', 'example.com', 'example.net', 'example.org'] or
            domain.endswith(('.example', '.test', '.invalid', '.localhost')))
    return {'configured': all(checks.values()), 'checks': checks, 'network_attempted': False,
        'delivery_verified': False, 'missing': [name for name, ok in checks.items() if not ok],
        'scope': 'Configuration only. TLS/authentication, DNS sender policy, actual delivery and recovery/invitation receipt require an authorized live acceptance test.'}


def database_probe():
    started = time.perf_counter()
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            valid = cursor.fetchone()[0] == 1
    except DatabaseError:
        valid = False
    return {'requested': True, 'ok': valid, 'elapsed_ms': round((time.perf_counter() - started) * 1000, 3),
            'operation': 'SELECT 1', 'engine': connection.vendor}


def storage_probe(key):
    """Read one operator-selected existing object; never write a public or private object."""
    if not isinstance(key, str) or not key or len(key) > 300 or ':' in key or '\x00' in key or key.startswith(('/', '\\')) or '\\' in key or any(part in ['', '.', '..'] for part in key.split('/')):
        return {'requested': True, 'ok': False, 'reason': 'invalid_relative_storage_key'}
    from django.core.files.storage import default_storage
    started = time.perf_counter()
    try:
        with default_storage.open(key, 'rb') as source:
            data = source.read(MAX_PROBE_BYTES + 1)
        valid = len(data) <= MAX_PROBE_BYTES
        result = {'requested': True, 'ok': valid, 'bytes_read': min(len(data), MAX_PROBE_BYTES),
                  'reason': 'ok' if valid else 'sample_exceeds_1_mib'}
    except STORAGE_ERRORS:
        result = {'requested': True, 'ok': False, 'reason': 'storage_unavailable'}
    result.update(elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
                  backend=settings.MEDIA_STORAGE_BACKEND, operation='one bounded object read')
    # No object key, URL, bytes, account name or exception text appears in output.
    return result


def operations_report(*, probe_database=False, storage_object=None):
    origin = urlsplit(settings.PUBLIC_ORIGIN)
    configuration = {
        'debug_disabled': not settings.DEBUG,
        'postgresql_configured': settings.DATABASES['default']['ENGINE'].endswith('postgresql'),
        'ephemeral_database_disabled': not settings.DEMO_EPHEMERAL,
        'durability_declared': settings.MEDIA_STORAGE_DURABLE,
        'private_remote_media_configured': settings.MEDIA_STORAGE_BACKEND == 's3',
        'https_canonical_origin': origin.scheme == 'https' and bool(origin.hostname) and not origin.username and not origin.password and origin.path in ['', '/'] and not origin.query and not origin.fragment,
    }
    smtp = smtp_configuration()
    return {'schema': 'nehedrou-operations-readiness-v1', 'configuration': configuration,
        'smtp': smtp, 'configuration_ready': all(configuration.values()) and smtp['configured'],
        'database': database_probe() if probe_database else {'requested': False},
        'storage': storage_probe(storage_object) if storage_object else {'requested': False},
        'scope': 'Technical preparation only. Configuration and timing samples do not establish clinical release, durable operation, an S3 latency benchmark, or verified email delivery.',
        'operator_acceptance_required': ['trusted_proxy_chain', 'private_storage_access_and_restart', 'offhost_backup_destination_and_schedule',
            'key_custody_and_retention', 'recent_restore_and_dossier_access', 'alert_recipients_and_escalation', 'live_email_delivery', 'validated_recovery_objectives']}
