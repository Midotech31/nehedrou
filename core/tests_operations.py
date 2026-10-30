"""Operational safeguards with fictional configuration, no SMTP or cloud traffic."""
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
from cryptography.fernet import Fernet
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError
from django.test import SimpleTestCase, TestCase, override_settings
from core.ops_readiness import smtp_configuration, operations_report, storage_probe
from core.scheduled_backups import scheduled_backup
from scripts.probe_http import parse_sample, sample


SMTP = dict(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend', EMAIL_HOST='smtp.fixture.invalid',
            EMAIL_PORT=587, EMAIL_USE_TLS=True, EMAIL_USE_SSL=False, EMAIL_TIMEOUT=10,
            EMAIL_HOST_USER='fixture-only', EMAIL_HOST_PASSWORD='fixture-only', DEFAULT_FROM_EMAIL='Nehedrou <fixture@operator-domain.tld>')


class OperationsConfigurationTests(SimpleTestCase):
    @override_settings(**SMTP)
    def test_smtp_check_is_configuration_only_without_any_network_or_message(self):
        with patch('smtplib.SMTP') as smtp, patch('django.core.mail.send_mail') as send, patch('core.ops_readiness.database_probe') as db:
            report = operations_report()
        self.assertTrue(report['smtp']['configured'])
        self.assertFalse(report['smtp']['delivery_verified'])
        self.assertFalse(report['smtp']['network_attempted'])
        self.assertFalse(report['database']['requested'])
        smtp.assert_not_called()
        send.assert_not_called()
        db.assert_not_called()
        text = json.dumps(report)
        for value in ['smtp.fixture.invalid', 'fixture-only', 'operator-domain.tld']:
            self.assertNotIn(value, text)

    @override_settings(**SMTP)
    def test_console_placeholder_sender_and_conflicting_transport_never_pass(self):
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend'):
            self.assertFalse(smtp_configuration()['configured'])
        with override_settings(DEFAULT_FROM_EMAIL='access@nehdrou.example'):
            self.assertFalse(smtp_configuration()['configured'])
        with override_settings(EMAIL_USE_SSL=True):
            self.assertFalse(smtp_configuration()['configured'])
        with override_settings(EMAIL_TIMEOUT=None):
            self.assertFalse(smtp_configuration()['configured'])

    @override_settings(**SMTP)
    def test_reserved_sender_subdomains_never_count_as_mail_configuration(self):
        for domain in ['example.com', 'outbound.example.com', 'deep.outbound.example.net', 'mail.example.org', 'mail.localhost', 'fictional.invalid']:
            with self.subTest(domain=domain), override_settings(DEFAULT_FROM_EMAIL='sender@' + domain), patch('smtplib.SMTP') as smtp:
                report = smtp_configuration()
            self.assertFalse(report['configured'])
            self.assertFalse(report['checks']['sender_not_reserved'])
            smtp.assert_not_called()

    def test_readiness_command_reports_missing_email_without_sending(self):
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend'), patch('smtplib.SMTP') as smtp:
            output = io.StringIO()
            call_command('check_operations', stdout=output)
            self.assertFalse(json.loads(output.getvalue())['smtp']['configured'])
            with self.assertRaises(CommandError):
                call_command('check_operations', strict=True, stdout=io.StringIO())
            smtp.assert_not_called()

    @override_settings(MEDIA_STORAGE_BACKEND='filesystem')
    def test_storage_probe_is_bounded_read_only_and_hides_key_and_exception(self):
        source = Mock()
        source.read.return_value = b'fictional private bytes'
        context = Mock()
        context.__enter__ = Mock(return_value=source)
        context.__exit__ = Mock(return_value=False)
        with patch('django.core.files.storage.default_storage.open', return_value=context) as opened:
            report = storage_probe('private-sentinel/fixture.bin')
        self.assertTrue(report['ok'])
        self.assertEqual(report['backend'], 'filesystem')
        opened.assert_called_once_with('private-sentinel/fixture.bin', 'rb')
        source.read.assert_called_once_with(1024 * 1024 + 1)
        self.assertNotIn('private-sentinel', json.dumps(report))
        with patch('django.core.files.storage.default_storage.open', side_effect=OSError('secret-backend-detail')):
            report = storage_probe('private-sentinel/fixture.bin')
        self.assertFalse(report['ok'])
        self.assertNotIn('secret-backend-detail', json.dumps(report))
        for invalid in ['../escape', '/absolute', 'C:/absolute', 'double//separator']:
            self.assertFalse(storage_probe(invalid)['ok'])

    def test_external_timing_parser_keeps_distinct_spans_without_claiming_cold_start(self):
        data = parse_sample('HTTP/2 200\r\nserver-timing: app;dur=12.1, db;dur=10.0\r\n\r\n\n200 0.01 0.03 0.06 0.16 0.2')
        self.assertEqual((data['dns_ms'], data['tcp_after_dns_ms'], data['tls_after_tcp_ms'], data['ttfb_ms'], data['total_ms']), (10, 20, 30, 160, 200))
        self.assertEqual(data['server_timing'], 'app;dur=12.1, db;dur=10.0')
        with patch('subprocess.run') as run:
            for url in ['http://public.example/healthz/', 'https://secret@public.example/healthz/', 'https://public.example/fr/children/uuid/', 'https://public.example/healthz/?token=secret']:
                with self.assertRaises(ValueError):
                    sample(url)
            run.assert_not_called()


    def test_postgres_sslmode_keeps_the_connection_timeout(self):
        env = {key: value for key, value in os.environ.items() if not key.startswith(('EMAIL_', 'POSTGRES_', 'DJANGO_', 'DEMO_', 'RENDER', 'MFA_', 'NEHEDROU_', 'AWS_'))}
        env.update(DJANGO_DEBUG='1', DEMO_MODE='1', POSTGRES_HOST='127.0.0.1', POSTGRES_PASSWORD='fictional-setting-only')
        code = "import json;from config import settings;print(json.dumps(settings.DATABASES['default']['OPTIONS']))"
        for mode in ['', 'require', 'verify-full']:
            with self.subTest(mode=mode):
                result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1], env={**env, 'POSTGRES_SSLMODE': mode}, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                options = json.loads(result.stdout)
                self.assertEqual(options['connect_timeout'], 5)
                self.assertEqual(options.get('sslmode', ''), mode)

    def test_settings_reject_dual_tls_and_unbounded_timeout_before_smtp_use(self):
        env = {key: value for key, value in os.environ.items() if not key.startswith(('EMAIL_', 'POSTGRES_', 'DJANGO_', 'DEMO_', 'RENDER', 'MFA_', 'NEHEDROU_', 'AWS_'))}
        env.update(DJANGO_DEBUG='1', DEMO_MODE='1', EMAIL_USE_TLS='0', EMAIL_USE_SSL='1', EMAIL_TIMEOUT='10')
        code = "from config import settings;print(settings.EMAIL_USE_SSL, settings.EMAIL_TIMEOUT)"
        for tls, timeout in [('1', '10'), ('0', '0'), ('0', '61')]:
            invalid = {**env, 'EMAIL_USE_TLS': tls, 'EMAIL_TIMEOUT': timeout}
            result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1], env=invalid, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
        valid = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertIn('True 10.0', valid.stdout)


class PrivateScheduledBackupTests(SimpleTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.quiet = self.root / 'private-quiesce'
        self.resume = self.root / 'private-resume'
        self.quiet.write_text('operator fixture only')
        self.resume.write_text('operator fixture only')
        self.environment = {
            'NEHEDROU_BACKUP_SCHEDULE_ENABLED': '1', 'NEHEDROU_BACKUP_OFFHOST_CONFIRMED': '1',
            'NEHEDROU_BACKUP_DESTINATION': str(self.root), 'NEHEDROU_BACKUP_KEY': Fernet.generate_key().decode(),
            'NEHEDROU_BACKUP_QUIESCE_HOOK': str(self.quiet), 'NEHEDROU_BACKUP_RESUME_HOOK': str(self.resume)}

    def test_job_stays_disabled_and_missing_offhost_attestation_cannot_run_hooks(self):
        with patch.dict(os.environ, {'NEHEDROU_BACKUP_SCHEDULE_ENABLED': '0'}), patch('core.scheduled_backups.run_hook') as hook:
            with self.assertRaises(CommandError):
                scheduled_backup()
            hook.assert_not_called()
        with patch.dict(os.environ, {**self.environment, 'NEHEDROU_BACKUP_OFFHOST_CONFIRMED': '0'}), patch('core.scheduled_backups.run_hook') as hook:
            with self.assertRaises(CommandError):
                scheduled_backup()
            hook.assert_not_called()

    def test_failure_always_resumes_writes_and_clears_own_lock_without_claiming_backup(self):
        with patch.dict(os.environ, self.environment), patch('core.scheduled_backups.run_hook') as hook, patch('core.scheduled_backups.create_backup', side_effect=CommandError('Fictional storage failure')):
            with self.assertRaises(CommandError):
                scheduled_backup()
        self.assertEqual([call.args[1] for call in hook.call_args_list], ['Quiesce', 'Resume'])
        self.assertFalse((self.root / '.nehedrou-backup.lock').exists())

    def test_success_authenticates_archive_before_reporting_and_concurrent_lock_blocks(self):
        with patch.dict(os.environ, self.environment), patch('core.scheduled_backups.run_hook') as hook, patch('core.scheduled_backups.create_backup', return_value={'encrypted': True}) as create, patch('core.scheduled_backups.inspect_backup', return_value=({'schema': 'nehedrou-encrypted-backup-v1'}, {})):
            report = scheduled_backup()
            self.assertTrue(report['authenticated_manifest_verified'])
            self.assertEqual([call.args[1] for call in hook.call_args_list], ['Quiesce', 'Resume'])
            destination = create.call_args.args[0]
            self.assertEqual(destination.parent, self.root.resolve())
            (self.root / '.nehedrou-backup.lock').write_text('Fictional other job')
            hook.reset_mock()
            with self.assertRaises(CommandError):
                scheduled_backup()
            hook.assert_not_called()


class HealthTimingTests(TestCase):
    def test_public_health_keeps_body_contract_and_safe_timing_header(self):
        response = self.client.get('/healthz/')
        self.assertEqual(response.json(), {'status': 'ok'})
        self.assertIn('app;dur=', response['Server-Timing'])
        self.assertIn('db;dur=', response['Server-Timing'])
        with patch('core.health.connection.cursor', side_effect=DatabaseError('private-connection-marker')):
            response = self.client.get('/healthz/')
        self.assertEqual(response.json(), {'status': 'unavailable'})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private-connection-marker', str(dict(response.headers)))
