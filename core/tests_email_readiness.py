"""Selected email transport diagnostics; fictional credentials and zero external traffic."""
import io
import json
import os
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from catalog.models import Variety
from core.models import User
from core.ops_readiness import email_configuration, operations_report, smtp_configuration
from core.management.commands.check_readiness import DEFAULT_OFFERED_CONTENT_VARIETIES


HTTP = dict(EMAIL_BACKEND='core.email_backends.ResendEmailBackend', RESEND_ENABLED=True,
    RESEND_API_KEY='fixture-api-credential-only', EMAIL_HTTP_CONNECT_TIMEOUT=5,
    EMAIL_HTTP_READ_TIMEOUT=10, DEFAULT_FROM_EMAIL='Fixture <sender@operator-domain.tld>')
SMTP = dict(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
    EMAIL_HOST='private-smtp-host.invalid', EMAIL_PORT=587, EMAIL_USE_TLS=True,
    EMAIL_USE_SSL=False, EMAIL_TIMEOUT=10, EMAIL_HOST_USER='private-smtp-user',
    EMAIL_HOST_PASSWORD='private-smtp-password', DEFAULT_FROM_EMAIL='Fixture <sender@operator-domain.tld>')


@override_settings(**HTTP)
class SelectedEmailConfigurationTests(SimpleTestCase):
    def test_https_is_selected_without_smtp_and_never_opens_a_network_connection(self):
        with patch('http.client.HTTPSConnection') as https, patch('smtplib.SMTP') as smtp, patch('socket.create_connection') as socket, patch('django.core.mail.send_mail') as send:
            report = operations_report()
        self.assertEqual(report['schema'], 'nehedrou-operations-readiness-v1')
        self.assertEqual(report['email']['backend'], 'resend')
        self.assertEqual(report['email']['transport'], 'https')
        self.assertTrue(report['email']['configured'])
        self.assertFalse(report['smtp']['configured'])
        self.assertFalse(report['email']['network_attempted'])
        self.assertFalse(report['email']['delivery_verified'])
        self.assertTrue(all(type(value) is bool for value in report['email']['checks'].values()))
        https.assert_not_called(); smtp.assert_not_called(); socket.assert_not_called(); send.assert_not_called()

    def test_selected_transport_controls_configuration_ready_not_legacy_smtp(self):
        with override_settings(DEBUG=False, DEMO_EPHEMERAL=False, MEDIA_STORAGE_DURABLE=True,
                MEDIA_STORAGE_BACKEND='s3', PUBLIC_ORIGIN='https://public.fixture.invalid'), patch.dict(settings.DATABASES['default'], {'ENGINE':'django.db.backends.postgresql'}):
            self.assertTrue(operations_report()['configuration_ready'])
            with override_settings(RESEND_ENABLED=False):
                self.assertFalse(operations_report()['configuration_ready'])

    def test_disabled_or_missing_key_blocks_without_any_traffic(self):
        for overrides, missing in [({'RESEND_ENABLED':False}, 'https_email_enabled'),
                ({'RESEND_API_KEY':''}, 'api_key_present'),
                ({'RESEND_API_KEY':'contains whitespace'}, 'api_key_present'),
                ({'RESEND_API_KEY':'fixture\nheader'}, 'api_key_present'),
                ({'RESEND_API_KEY':'x'*513}, 'api_key_present')]:
            with self.subTest(overrides=tuple(overrides)), override_settings(**overrides), patch('http.client.HTTPSConnection') as https, patch('smtplib.SMTP') as smtp:
                report = email_configuration()
            self.assertFalse(report['configured'])
            self.assertIn(missing, report['missing'])
            https.assert_not_called(); smtp.assert_not_called()

    def test_reserved_invalid_and_multiple_senders_never_qualify(self):
        for sender in ('sender@example.com', 'sender@mail.example.com', 'sender@private.test',
                'sender@nehdrou.example', 'not-an-address', 'sender@real-domain.tld\nBcc: other@real-domain.tld',
                'sender@real-domain.tld, other@real-domain.tld', 'Group: sender@real-domain.tld;'):
            with self.subTest(sender=sender), override_settings(DEFAULT_FROM_EMAIL=sender):
                self.assertFalse(email_configuration()['configured'])

    def test_timeout_bounds_are_local_gates(self):
        for name, values in [('EMAIL_HTTP_CONNECT_TIMEOUT', (0,16,True,None)),
                ('EMAIL_HTTP_READ_TIMEOUT', (0,31,True,float('nan')))]:
            for value in values:
                with self.subTest(name=name,value=value), override_settings(**{name:value}):
                    self.assertFalse(email_configuration()['configured'])
        with override_settings(EMAIL_HTTP_CONNECT_TIMEOUT=15, EMAIL_HTTP_READ_TIMEOUT=30):
            self.assertTrue(email_configuration()['configured'])

    def test_smtp_selection_remains_supported_and_does_not_fall_back_to_https(self):
        with override_settings(**SMTP), patch('http.client.HTTPSConnection') as https, patch('smtplib.SMTP') as smtp:
            legacy = smtp_configuration()
            report = email_configuration(smtp=legacy)
        self.assertTrue(legacy['configured'])
        self.assertTrue(report['configured'])
        self.assertEqual(report['backend'], 'smtp')
        self.assertEqual(report['transport'], 'smtp')
        self.assertEqual(report['checks'], legacy['checks'])
        self.assertFalse(report['delivery_verified'])
        https.assert_not_called(); smtp.assert_not_called()

    def test_console_or_unknown_backend_does_not_enable_delivery_or_echo_setting(self):
        for backend, label in [('django.core.mail.backends.console.EmailBackend','console'),
                ('core.email_backends.DisabledEmailBackend','disabled'),
                ('private-backend-credential-marker','unsupported')]:
            with override_settings(EMAIL_BACKEND=backend):
                report = email_configuration()
            self.assertFalse(report['configured'])
            self.assertEqual(report['backend'], label)
            self.assertEqual(report['transport'], 'none')
            self.assertNotIn('private-backend-credential-marker', json.dumps(report))

    def test_report_retains_runtime_provenance_without_secret_or_address_values(self):
        private = 'PRIVATE-EMAIL-SECRET-MARKER'
        with override_settings(IS_RENDER=False, RESEND_API_KEY=private, EMAIL_HOST=private,
                EMAIL_HOST_USER=private, EMAIL_HOST_PASSWORD=private,
                DEFAULT_FROM_EMAIL='PRIVATE-SENDER@operator-private-domain.tld'), patch.dict(os.environ, {'RENDER_GIT_COMMIT':'a'*40}):
            report = operations_report()
        self.assertEqual(report['execution']['process'], 'operator_or_local_process')
        self.assertIsNone(report['execution']['build_commit'])
        self.assertIn('observed_at', report['execution'])
        for value in (private,'PRIVATE-SENDER','operator-private-domain.tld','api.resend.com'):
            self.assertNotIn(value, json.dumps(report))


@override_settings(**HTTP, MFA_REQUIRED=False, DEMO_MODE=True,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class EmailDiagnosticsHttpTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.operator = User.objects.create_user(username='email-ops-fixture', email='email-ops@example.test')
        cls.operator.user_permissions.add(Permission.objects.get(codename='manage_entitlements'))
        cls.ordinary = User.objects.create_user(username='email-family-fixture', email='email-family@example.test')

    def test_private_get_and_head_are_selected_transport_read_only_diagnostics(self):
        self.client.force_login(self.operator)
        with patch('http.client.HTTPSConnection') as https, patch('smtplib.SMTP') as smtp, patch('core.ops_readiness.database_probe') as db, patch('core.ops_readiness.storage_probe') as storage:
            response = self.client.get('/en/operations/?format=json')
            head = self.client.head('/en/operations/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(head.status_code, 200)
        report = response.json()
        self.assertEqual(report['execution']['delivery'], 'authenticated_private_web_view')
        self.assertEqual(report['email']['backend'], 'resend')
        self.assertTrue(report['email']['configured'])
        self.assertFalse(report['email']['network_attempted'])
        self.assertFalse(report['email']['delivery_verified'])
        self.assertIn('private', response['Cache-Control'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        https.assert_not_called(); smtp.assert_not_called(); db.assert_not_called(); storage.assert_not_called()

    def test_roles_remain_restricted_and_email_post_cannot_send(self):
        self.client.force_login(self.ordinary)
        with patch('core.operations_views.operations_report') as report:
            self.assertEqual(self.client.get('/en/operations/').status_code, 403)
            report.assert_not_called()
        self.client.force_login(self.operator)
        with patch('http.client.HTTPSConnection') as https, patch('smtplib.SMTP') as smtp:
            response = self.client.post('/en/operations/', {'action':'email','recipient':'external@fixture.invalid'})
        self.assertEqual(response.status_code, 400)
        https.assert_not_called(); smtp.assert_not_called()

    def test_all_languages_render_selected_checks_without_raw_credentials(self):
        self.client.force_login(self.operator)
        for code in ('fr','en','ar'):
            response = self.client.get('/'+code+'/operations/')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.context['email_rows']), 7)
            for value in ('fixture-api-credential-only','operator-domain.tld','sender@','api.resend.com'):
                self.assertNotIn(value, response.content.decode())

    def test_readiness_command_uses_selected_email_gate_and_retains_smtp_section(self):
        for code in DEFAULT_OFFERED_CONTENT_VARIETIES:
            Variety.objects.create(code=code,language=code[:2],label='Fictional '+code)
        output = io.StringIO()
        with patch('http.client.HTTPSConnection') as https, patch('smtplib.SMTP') as smtp:
            call_command('check_readiness', json=True, stdout=output)
        report = json.loads(output.getvalue())
        self.assertTrue(report['checks']['email_configured'])
        self.assertFalse(report['smtp']['configured'])
        self.assertTrue(report['email']['configured'])
        self.assertFalse(report['email']['delivery_verified'])
        self.assertFalse(report['technical_gates_passed'])  # No real content is created.
        https.assert_not_called(); smtp.assert_not_called()

    def test_diagnostic_uses_the_backend_pure_local_checks(self):
        from core.email_backends import resend_configuration_checks
        expected = {('https_email_enabled' if key == 'enabled' else key):value
            for key,value in resend_configuration_checks().items()}
        observed = email_configuration()['checks']
        self.assertEqual({key:value for key,value in observed.items() if key != 'resend_backend'}, expected)
