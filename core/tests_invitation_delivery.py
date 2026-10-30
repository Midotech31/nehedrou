"""Invitation preflight is local, secret-free and does not replace delivery."""
import json
from unittest.mock import patch

from django.core import mail
from django.core.mail import send_mail
from django.test import SimpleTestCase, override_settings
from django.utils import translation

from core.invitation_delivery import invitation_delivery_status


HTTP = dict(EMAIL_BACKEND='core.email_backends.ResendEmailBackend', RESEND_ENABLED=True,
    RESEND_API_KEY='re_fictional_invitation_config', EMAIL_HTTP_CONNECT_TIMEOUT=5,
    EMAIL_HTTP_READ_TIMEOUT=10, DEFAULT_FROM_EMAIL='Access <access@fictional-mail.tld>')
SMTP = dict(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
    EMAIL_HOST='smtp.fictional-mail.tld', EMAIL_PORT=587, EMAIL_USE_TLS=True,
    EMAIL_USE_SSL=False, EMAIL_TIMEOUT=10, EMAIL_HOST_USER='fictional-login',
    EMAIL_HOST_PASSWORD='fictional-password', DEFAULT_FROM_EMAIL='access@fictional-mail.tld')


class InvitationDeliveryStatusTests(SimpleTestCase):
    def setUp(self):
        self.enterContext(translation.override('en'))

    def assert_local_only(self, **overrides):
        # These guards also reject backend construction and DNS, not just send_mail.
        with override_settings(**overrides), \
                patch('django.core.mail.get_connection') as backend, \
                patch('django.core.mail.send_mail') as send, \
                patch('socket.getaddrinfo') as dns, \
                patch('socket.create_connection') as socket, \
                patch('http.client.HTTPSConnection') as https, \
                patch('smtplib.SMTP') as smtp, \
                patch('smtplib.SMTP_SSL') as smtp_ssl:
            report = invitation_delivery_status()
        for guarded in [backend, send, dns, socket, https, smtp, smtp_ssl]:
            guarded.assert_not_called()
        self.assertFalse(report['network_attempted'])
        self.assertFalse(report['delivery_verified'])
        return report

    def test_disabled_backend_prepares_recording_and_blocks_only_retry(self):
        report = self.assert_local_only(EMAIL_BACKEND='core.email_backends.DisabledEmailBackend')
        self.assertEqual(report['state'], 'unavailable')
        self.assertTrue(report['known_unavailable'])
        self.assertFalse(report['can_retry'])
        self.assertEqual(str(report['submit_label']), 'Record invitation')
        self.assertIn('record an invitation', str(report['notice']))
        self.assertIn('existing invitation has been kept', str(report['retry_blocked_message']))

    @override_settings(**HTTP)
    def test_incomplete_resend_is_known_unavailable_without_network(self):
        for values in ({'RESEND_ENABLED':False}, {'RESEND_API_KEY':''},
                {'RESEND_API_KEY':'contains whitespace'}, {'DEFAULT_FROM_EMAIL':'sender@example.test'},
                {'EMAIL_HTTP_CONNECT_TIMEOUT':0}, {'EMAIL_HTTP_READ_TIMEOUT':float('nan')}):
            with self.subTest(field=next(iter(values))):
                report = self.assert_local_only(**values)
                self.assertEqual(report['state'], 'unavailable')
                self.assertFalse(report['can_retry'])

    @override_settings(**HTTP)
    def test_present_resend_configuration_allows_attempt_without_claiming_receipt(self):
        report = self.assert_local_only()
        self.assertEqual(report['state'], 'configuration_present')
        self.assertFalse(report['known_unavailable'])
        self.assertTrue(report['can_retry'])
        self.assertEqual(str(report['submit_label']), 'Send invitation')
        self.assertIn('does not verify sending or receipt', str(report['notice']))

    @override_settings(**SMTP)
    def test_incomplete_supported_smtp_profile_is_known_unavailable(self):
        for values in ({'EMAIL_HOST':''}, {'EMAIL_HOST':None}, {'EMAIL_PORT':0},
                {'EMAIL_USE_SSL':True}, {'EMAIL_USE_TLS':False}, {'EMAIL_TIMEOUT':None},
                {'EMAIL_HOST_USER':''}, {'EMAIL_HOST_PASSWORD':''}, {'DEFAULT_FROM_EMAIL':'invalid'}):
            with self.subTest(field=next(iter(values))):
                report = self.assert_local_only(**values)
                self.assertTrue(report['known_unavailable'])
                self.assertFalse(report['can_retry'])

    @override_settings(**SMTP)
    def test_present_smtp_profile_stays_unverified(self):
        for tls, ssl in [(True, False), (False, True)]:
            with self.subTest(tls=tls), override_settings(EMAIL_USE_TLS=tls, EMAIL_USE_SSL=ssl):
                report = self.assert_local_only()
                self.assertEqual(report['state'], 'configuration_present')
                self.assertTrue(report['can_retry'])
                self.assertFalse(report['delivery_verified'])

    def test_console_is_distinct_only_in_local_debug(self):
        backend = 'django.core.mail.backends.console.EmailBackend'
        for debug, render, expected in [(True,False,'local_console'),
                (False,False,'unavailable'), (True,True,'unavailable'), (False,True,'unavailable')]:
            with self.subTest(debug=debug, render=render):
                report = self.assert_local_only(EMAIL_BACKEND=backend, DEBUG=debug, IS_RENDER=render)
                self.assertEqual(report['state'], expected)
                self.assertEqual(str(report['submit_label']), 'Record invitation')
                self.assertEqual(report['can_retry'], expected == 'local_console')

    def test_custom_backend_never_gets_arbitrary_identifier_exposed_or_is_blocked(self):
        private = 'private.backend.SECRET_CONFIGURATION_MARKER'
        report = self.assert_local_only(EMAIL_BACKEND=private)
        self.assertEqual(report['state'], 'unverified_backend')
        self.assertFalse(report['known_unavailable'])
        self.assertTrue(report['can_retry'])
        self.assertEqual(str(report['submit_label']), 'Send invitation')
        self.assertNotIn(private, json.dumps(report, default=str))

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_locmem_retains_actual_test_transport_behavior(self):
        report = self.assert_local_only()
        self.assertEqual(report['state'], 'unverified_backend')
        self.assertTrue(report['can_retry'])
        self.assertEqual(send_mail('Fictional invitation', 'Fictional message',
            'access@fictional-mail.tld', ['recipient@example.test']), 1)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(**HTTP)
    def test_configuration_is_rechecked_after_change_without_cache(self):
        self.assertTrue(invitation_delivery_status()['can_retry'])
        with override_settings(RESEND_ENABLED=False):
            self.assertFalse(invitation_delivery_status()['can_retry'])
        self.assertTrue(invitation_delivery_status()['can_retry'])

    @override_settings(**SMTP)
    def test_returned_content_never_exposes_private_configuration(self):
        private = 'PRIVATE_INVITATION_SECRET'
        with override_settings(EMAIL_HOST=private, EMAIL_HOST_USER=private,
                EMAIL_HOST_PASSWORD=private, RESEND_API_KEY=private,
                DEFAULT_FROM_EMAIL='PRIVATE-SENDER@private-operator.tld'):
            report = self.assert_local_only()
        rendered = json.dumps(report, default=str)
        for value in [private, 'PRIVATE-SENDER', 'private-operator.tld', 'smtp.fictional-mail.tld']:
            self.assertNotIn(value, rendered)

    def test_guidance_has_the_same_boolean_contract_in_each_ui_language(self):
        for language in ['fr','en','ar']:
            with self.subTest(language=language), translation.override(language):
                report = self.assert_local_only(EMAIL_BACKEND='core.email_backends.DisabledEmailBackend')
                self.assertTrue(report['known_unavailable'])
                self.assertFalse(report['can_retry'])
                self.assertTrue(str(report['notice']))
