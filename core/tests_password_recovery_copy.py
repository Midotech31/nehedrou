"""Transport-aware recovery copy; fictional users, no live email or reset grant."""
from unittest.mock import patch

from django.contrib.auth.views import PasswordResetDoneView, PasswordResetView
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import resolve, reverse
from django.utils import translation
from django.utils.translation import gettext as _

from core.email_backends import DisabledEmailBackend
from core.email_forms import CanonicalPasswordResetForm
from core.invitation_delivery import invitation_delivery_status
from core.models import AuditEvent, RecoveryCode, User


UNAVAILABLE_TITLE = 'Password recovery unavailable'
UNAVAILABLE_COPY = 'Email delivery is unavailable on this service. This page cannot send a password recovery email.'
ATTEMPT_COPY = 'If an eligible account matches this email address, we try to send a recovery link. Delivery is not confirmed.'
OLD_SUCCESS_COPY = 'If an account matches this email address, a recovery link has been sent.'


@override_settings(DEMO_MODE=False, DEBUG=False, MFA_REQUIRED=False,
    EMAIL_BACKEND='core.email_backends.DisabledEmailBackend',
    PUBLIC_ORIGIN='https://recovery.fictional-mail.tld',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class PasswordRecoveryCopyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('copy-reset-known', 'copy-reset-known@example.test',
                                          password='Fictional-Reset-Copy-Password-2026!')
        cls.inactive = User.objects.create_user('copy-reset-inactive', 'copy-reset-inactive@example.test',
                                              is_active=False, password='Fictional-Inactive-Password-2026!')
        cls.unusable = User.objects.create_user('copy-reset-unusable', 'copy-reset-unusable@example.test')

    def assert_unavailable(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['password_recovery_unavailable'])
        self.assertContains(response, _(UNAVAILABLE_TITLE))
        self.assertContains(response, _(UNAVAILABLE_COPY))
        self.assertNotContains(response, _(OLD_SUCCESS_COPY))
        self.assertNotContains(response, _(ATTEMPT_COPY))
        self.assertNotContains(response, 'name="email"')
        self.assertNotContains(response, 'core.email_backends')
        self.assertNotContains(response, self.user.email)
        self.assertNotContains(response, self.inactive.email)

    def test_disabled_get_and_direct_done_are_configuration_only_in_all_languages(self):
        with patch.object(CanonicalPasswordResetForm, 'get_users') as accounts, \
                patch('smtplib.SMTP') as smtp, patch('http.client.HTTPSConnection') as https:
            for language in ('fr', 'en', 'ar'):
                with self.subTest(language=language), translation.override(language):
                    page = Client().get(reverse('password_reset'))
                    self.assert_unavailable(page)
                    self.assertIsInstance(page.context['form'], CanonicalPasswordResetForm)
                    self.assert_unavailable(Client().get(reverse('password_reset_done')))
            accounts.assert_not_called()
            smtp.assert_not_called()
            https.assert_not_called()

    def test_real_disabled_post_is_neutral_for_known_unknown_inactive_and_unusable_accounts(self):
        before = list(User.objects.order_by('pk').values_list('pk', 'password', 'last_login', 'is_active'))
        original_send = DisabledEmailBackend.send_messages
        with patch.object(DisabledEmailBackend, 'send_messages', autospec=True, side_effect=original_send) as disabled, \
                patch('django.contrib.auth.forms.logger.error'), patch('smtplib.SMTP') as smtp, \
                patch('http.client.HTTPSConnection') as https:
            for language in ('fr', 'en', 'ar'):
                with translation.override(language):
                    for address in (self.user.email, 'copy-reset-unknown@example.test',
                                    self.inactive.email, self.unusable.email):
                        with self.subTest(language=language, address=address):
                            client = Client()
                            response = client.post(reverse('password_reset'), {'email': address})
                            self.assertEqual(response.status_code, 302)
                            self.assertEqual(response.url, reverse('password_reset_done'))
                            self.assert_unavailable(client.get(response.url))
            # Only the active usable account reaches Django's real disabled transport.
            self.assertEqual(disabled.call_count, 3)
            smtp.assert_not_called()
            https.assert_not_called()
        self.assertEqual(list(User.objects.order_by('pk').values_list('pk', 'password', 'last_login', 'is_active')), before)
        self.assertFalse(RecoveryCode.objects.exists())
        self.assertFalse(AuditEvent.objects.exists())

    def assert_supported_transport(self, backend, patch_target, **configuration):
        with override_settings(EMAIL_BACKEND=backend, **configuration):
            self.assertFalse(invitation_delivery_status()['known_unavailable'])
            with patch(patch_target, autospec=True, return_value=1) as send:
                for language in ('fr', 'en', 'ar'):
                    with self.subTest(language=language, backend=backend), translation.override(language):
                        page = self.client.get(reverse('password_reset'))
                        self.assertFalse(page.context['password_recovery_unavailable'])
                        self.assertContains(page, 'name="email"')
                        self.assertIsInstance(page.context['form'], CanonicalPasswordResetForm)
                        self.assertNotContains(page, _(UNAVAILABLE_COPY))
                        for address, expected in ((self.user.email, 1), ('copy-reset-unknown@example.test', 0)):
                            send.reset_mock()
                            response = self.client.post(reverse('password_reset'), {'email': address})
                            self.assertEqual(response.status_code, 302)
                            self.assertEqual(response.url, reverse('password_reset_done'))
                            done = self.client.get(response.url)
                            self.assertFalse(done.context['password_recovery_unavailable'])
                            self.assertContains(done, _(ATTEMPT_COPY))
                            self.assertNotContains(done, _(OLD_SUCCESS_COPY))
                            self.assertNotContains(done, address)
                            self.assertEqual(send.call_count, expected)
                            if expected:
                                messages = send.call_args.args[1]
                                self.assertEqual(len(messages), 1)
                                self.assertEqual(messages[0].to, [self.user.email])
                                self.assertIn('https://recovery.fictional-mail.tld/' + language + '/reset/', messages[0].body)

    def test_configured_smtp_preserves_the_existing_canonical_send_workflow(self):
        self.assert_supported_transport('django.core.mail.backends.smtp.EmailBackend',
            'django.core.mail.backends.smtp.EmailBackend.send_messages',
            EMAIL_HOST='smtp.fixture.invalid', EMAIL_PORT=587, EMAIL_USE_TLS=True, EMAIL_USE_SSL=False,
            EMAIL_TIMEOUT=10, EMAIL_HOST_USER='fictional-unused-user', EMAIL_HOST_PASSWORD='fictional-unused-password',
            DEFAULT_FROM_EMAIL='access@fictional-mail.tld')

    def test_configured_https_preserves_the_existing_canonical_send_workflow(self):
        self.assert_supported_transport('core.email_backends.ResendEmailBackend',
            'core.email_backends.ResendEmailBackend.send_messages', RESEND_ENABLED=True,
            RESEND_API_KEY='re_fictional_unused_key_for_copy_regression_only',
            EMAIL_HTTP_CONNECT_TIMEOUT=5, EMAIL_HTTP_READ_TIMEOUT=10,
            DEFAULT_FROM_EMAIL='access@fictional-mail.tld')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_unknown_local_test_transport_keeps_its_existing_behavior(self):
        page = self.client.get(reverse('password_reset'))
        self.assertFalse(page.context['password_recovery_unavailable'])
        self.assertContains(page, 'name="email"')
        response = self.client.post(reverse('password_reset'), {'email': self.user.email})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertContains(self.client.get(response.url), _(ATTEMPT_COPY))

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend', EMAIL_HOST='')
    def test_known_incomplete_supported_profile_uses_the_existing_configuration_helper(self):
        self.assertTrue(invitation_delivery_status()['known_unavailable'])
        self.assert_unavailable(self.client.get(reverse('password_reset')))

    def test_routes_keep_django_views_canonical_form_and_csrf_protection(self):
        request_view = resolve(reverse('password_reset')).func
        done_view = resolve(reverse('password_reset_done')).func
        self.assertTrue(issubclass(request_view.view_class, PasswordResetView))
        self.assertTrue(issubclass(done_view.view_class, PasswordResetDoneView))
        self.assertIs(request_view.view_initkwargs['form_class'], CanonicalPasswordResetForm)
        before = self.user.password
        response = Client(enforce_csrf_checks=True).post(reverse('password_reset'), {'email': self.user.email})
        self.assertEqual(response.status_code, 403)
        self.user.refresh_from_db()
        self.assertEqual(self.user.password, before)
