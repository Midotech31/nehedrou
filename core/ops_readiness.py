"""Private operator checks: no messages, credentials, patient content or network by default."""
import os
import re
import time
from urllib.parse import urlsplit
from email.utils import getaddresses
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import connection, DatabaseError, transaction
from core.storage_health import STORAGE_ERRORS

MAX_PROBE_BYTES = 1024 * 1024


def sender_checks():
    checks = {'sender_address': False, 'sender_not_reserved': False}
    value = settings.DEFAULT_FROM_EMAIL
    try:
        if not isinstance(value, str) or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValidationError('invalid sender')
        addresses = getaddresses([value])
        if len(addresses) != 1:
            raise ValidationError('invalid sender')
        sender = addresses[0][1]
        validate_email(sender)
    except (ValidationError, ValueError):
        return checks
    checks['sender_address'] = True
    domain = sender.rsplit('@', 1)[-1].lower()
    reserved = ('localhost', 'example.com', 'example.net', 'example.org')
    checks['sender_not_reserved'] = not (any(domain == item or domain.endswith('.' + item) for item in reserved) or
        domain.endswith(('.example', '.test', '.invalid', '.localhost')))
    return checks


def smtp_configuration():
    # Historical v1 section retained, including its explicit backend-selection test.
    checks = {
        'smtp_backend': settings.EMAIL_BACKEND == 'django.core.mail.backends.smtp.EmailBackend',
        'host_present': bool(settings.EMAIL_HOST.strip()),
        'port_valid': isinstance(settings.EMAIL_PORT, int) and 1 <= settings.EMAIL_PORT <= 65535,
        'one_transport_security_mode': bool(settings.EMAIL_USE_TLS) != bool(getattr(settings, 'EMAIL_USE_SSL', False)),
        'bounded_timeout': isinstance(getattr(settings, 'EMAIL_TIMEOUT', None), (int, float)) and 0 < settings.EMAIL_TIMEOUT <= 60,
        'credentials_present': bool(settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD),
        **sender_checks(),
    }
    return {'configured': all(checks.values()), 'checks': checks, 'network_attempted': False,
        'delivery_verified': False, 'missing': [name for name, ok in checks.items() if not ok],
        'scope': 'Configuration only. TLS/authentication, DNS sender policy, actual delivery and recovery/invitation receipt require an authorized live acceptance test.'}


def email_configuration(*, smtp=None):
    """Describe the selected supported transport without constructing it or sending mail."""
    selected = settings.EMAIL_BACKEND
    if selected == 'django.core.mail.backends.smtp.EmailBackend':
        legacy = smtp if smtp is not None else smtp_configuration()
        backend, transport, checks = 'smtp', 'smtp', dict(legacy['checks'])
    elif selected == 'core.email_backends.ResendEmailBackend':
        from core.email_backends import resend_configuration_checks
        declared = resend_configuration_checks()
        checks = {'resend_backend': True,
            **{('https_email_enabled' if key == 'enabled' else key): value for key, value in declared.items()}}
        backend, transport = 'resend', 'https'
    else:
        # Never echo an arbitrary backend setting into reports or the UI.
        backend = {'django.core.mail.backends.console.EmailBackend':'console',
            'core.email_backends.DisabledEmailBackend':'disabled'}.get(selected, 'unsupported')
        transport, checks = 'none', {'delivery_backend_selected': False}
    return {'backend': backend, 'transport': transport, 'configured': all(checks.values()),
        'checks': checks, 'network_attempted': False, 'delivery_verified': False,
        'missing': [name for name, ok in checks.items() if not ok],
        'scope': 'Selected transport configuration only. No network, domain verification, API authentication, message submission or recipient delivery has been tested.'}


def database_probe():
    started = time.perf_counter()
    try:
        # SET LOCAL is transaction-scoped: no timeout leaks to later clinical queries.
        with transaction.atomic(), connection.cursor() as cursor:
            previous_timeout = None
            if connection.vendor == 'postgresql':
                cursor.execute('SHOW statement_timeout')
                previous_timeout = cursor.fetchone()[0]
                cursor.execute("SET LOCAL statement_timeout = '2000ms'")
            cursor.execute('SELECT 1')
            valid = cursor.fetchone()[0] == 1
            if previous_timeout is not None:
                # Also restore a caller's setting when running inside a larger transaction.
                # A query error exits atomic and restores the setting through rollback.
                cursor.execute("SELECT set_config('statement_timeout', %s, true)", [previous_timeout])
    except DatabaseError:
        valid = False
    return {'requested': True, 'ok': valid, 'elapsed_ms': round((time.perf_counter() - started) * 1000, 3),
            'operation': 'SELECT 1', 'engine': connection.vendor,
            'statement_timeout_ms': 2000 if connection.vendor == 'postgresql' else None,
            'timeout_scope': 'PostgreSQL server statement timeout only; elapsed time includes connection and transport. Not an end-to-end network deadline.'}


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
    email = email_configuration(smtp=smtp)
    return {'schema': 'nehedrou-operations-readiness-v1', 'execution': execution_context(), 'configuration': configuration,
        'smtp': smtp, 'email': email, 'configuration_ready': all(configuration.values()) and email['configured'],
        'database': database_probe() if probe_database else {'requested': False},
        'storage': storage_probe(storage_object) if storage_object else {'requested': False},
        'scope': 'Technical preparation only. Configuration and timing samples do not establish clinical release, durable operation, an S3 latency benchmark, or verified email delivery.',
        'operator_acceptance_required': ['trusted_proxy_chain', 'private_storage_access_and_restart', 'offhost_backup_destination_and_schedule',
            'key_custody_and_retention', 'recent_restore_and_dossier_access', 'alert_recipients_and_escalation', 'live_email_delivery', 'validated_recovery_objectives']}


def execution_context():
    """Describe this process, without pretending a workstation is the deployed service."""
    candidate = os.getenv('RENDER_GIT_COMMIT', '') if settings.IS_RENDER else ''
    commit = candidate.lower() if re.fullmatch(r'[a-fA-F0-9]{40}', candidate) else None
    return {
        'observed_at': timezone.now().isoformat(),
        'process': 'render' if settings.IS_RENDER else 'operator_or_local_process',
        'build_commit': commit,
        'demonstration_mode': settings.DEMO_MODE,
        'privileged_mfa_required': settings.MFA_REQUIRED,
        'scope': 'Values come from this running Django process. Configuration does not prove delivery, retention, restoration or clinical qualification.',
    }
