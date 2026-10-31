"""Real access workflows through the HTTP backend; all transport and data are fictional."""
from contextlib import contextmanager
import secrets
from datetime import datetime, timedelta
import hashlib
import json
import re
from unittest.mock import patch
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from care.models import Child, FamilyLink
from .models import AuditEvent, Entitlement, Invitation, Membership, Organization, User
from .testing import practice_form_data
from .services import issue_and_deliver_invitation


RESEND_TEST_API_KEY = "re_" + secrets.token_urlsafe(32)

@override_settings(DEMO_MODE=True, MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    EMAIL_BACKEND='core.email_backends.ResendEmailBackend', RESEND_ENABLED=True,
    RESEND_API_KEY=RESEND_TEST_API_KEY,
    EMAIL_HTTP_CONNECT_TIMEOUT=5, EMAIL_HTTP_READ_TIMEOUT=10,
    DEFAULT_FROM_EMAIL='access@fictional-mail.tld', PUBLIC_ORIGIN='https://app.fictional-mail.tld')
class HttpEmailWorkflowTests(TestCase):
    marker = 'PRIVATE_PROVIDER_WORKFLOW_MARKER'
    faults = ['forbidden', 'rate_limited', 'timeout', 'malformed', 'missing_id', 'empty_id', 'redirect']

    def setUp(self):
        self.owner = User.objects.create_user(username='http-mail-owner', email='http-mail-owner@example.test', password=secrets.token_urlsafe(24))
        self.pro = User.objects.create_user(username='http-mail-pro', email='http-mail-pro@example.test', password=secrets.token_urlsafe(24))
        self.other = User.objects.create_user(username='http-mail-other', email='http-mail-other@example.test', password=secrets.token_urlsafe(24))
        self.organization = Organization.objects.create(name='Fictional HTTP mail cabinet')
        self.foreign_organization = Organization.objects.create(name='Other fictional HTTP cabinet')
        Membership.objects.create(user=self.owner, organization=self.organization, role='owner')
        Membership.objects.create(user=self.pro, organization=self.organization, role='clinician')
        Membership.objects.create(user=self.other, organization=self.foreign_organization, role='owner')
        Entitlement.objects.create(organization=self.organization, expires_at=timezone.now()+timedelta(days=10), practitioner_quota=10)
        Entitlement.objects.create(organization=self.foreign_organization, expires_at=timezone.now()+timedelta(days=10), practitioner_quota=10)
        self.child = Child.objects.create(organization=self.organization, responsible=self.pro, code='HTTP email child · fictif', age_years=5)
        self.foreign_child = Child.objects.create(organization=self.foreign_organization, responsible=self.other, code='Other HTTP child · fictif', age_years=5)
        self.recipient = User.objects.create_user(username='http-mail-family', email='http-mail-family@example.test', password=secrets.token_urlsafe(24))

    def payload(self, connection):
        self.assertTrue(connection.request.called, 'The actual backend must reach its mocked HTTP transport')
        call = connection.request.call_args
        self.assertEqual(call.args[:2], ('POST', '/emails'))
        return json.loads(call.kwargs['body'].decode('utf-8'))

    def link(self, connection):
        links = re.findall(r'https?://[^\s<>]+', self.payload(connection)['text'])
        self.assertEqual(len(links), 1)
        return links[0]

    @contextmanager
    def provider(self, fault=None):
        # Patch only the network boundary. Django views, services and email backend run unchanged.
        with patch('core.email_backends.http.client.HTTPSConnection') as transport:
            connection = transport.return_value
            response = connection.getresponse.return_value
            response.status = {'forbidden':403, 'rate_limited':429, 'redirect':302}.get(fault, 202)
            response.read.return_value = b'{"id":"email_fixture_workflow_123"}'
            def sensitive():
                payload = self.payload(connection)
                return self.marker + ' ' + settings.RESEND_API_KEY + ' ' + payload['to'][0] + ' ' + payload['text']
            if fault == 'timeout':
                def timeout():
                    raise TimeoutError(sensitive())
                connection.getresponse.side_effect = timeout
            elif fault == 'malformed':
                response.read.side_effect = lambda *_args: sensitive().encode('utf-8')
            elif fault == 'missing_id':
                response.read.side_effect = lambda *_args: json.dumps({'message':sensitive()}).encode('utf-8')
            elif fault == 'empty_id':
                response.read.return_value = b'{"id":""}'
            yield transport, connection

    def issue_family(self, email=None):
        self.client.force_login(self.pro)
        return self.client.post(reverse('child_detail', args=[self.child.pk]), {'email':email or self.recipient.email})

    def assert_private_failure_logs(self, lines, connection=None, email=''):
        text = '\n'.join(lines)
        for marker in [self.marker, settings.RESEND_API_KEY, email]:
            if marker:
                self.assertNotIn(marker, text)
        if connection is not None and connection.request.called:
            self.assertNotIn(self.payload(connection)['text'], text)
            self.assertNotIn(self.link(connection), text)

    def test_family_invitation_accepts_provider_then_link_once_in_each_ui_language(self):
        for language in ['fr', 'en', 'ar']:
            with self.subTest(language=language), translation.override(language):
                recipient = User.objects.create_user(username='http-family-'+language, email='http-family-'+language+'@example.test')
                with self.provider() as (transport, connection):
                    response = self.issue_family(recipient.email)
                    self.assertEqual(response.status_code, 302)
                    self.assertEqual(transport.call_count, 1)
                    url = self.link(connection)
                    payload = self.payload(connection)
                    self.assertEqual(payload['to'], [recipient.email])
                    self.assertEqual(payload['subject'], _('Your Nehedrou invitation'))
                    self.assertNotIn(self.child.code, payload['text'])
                invitation = Invitation.objects.get(email=recipient.email)
                self.assertEqual(invitation.delivery, 'sent')
                self.assertTrue(AuditEvent.objects.filter(action='invitation.delivery_sent', object_id=str(invitation.pk)).exists())
                self.assertEqual(urlsplit(url).netloc, 'app.fictional-mail.tld')
                self.assertTrue(urlsplit(url).path.startswith('/'+language+'/invite/'))
                token = urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1]
                self.assertEqual(invitation.token_hash, hashlib.sha256(token.encode()).hexdigest())
                recipient_client = Client()
                recipient_client.force_login(recipient)
                self.assertEqual(recipient_client.get(urlsplit(url).path).status_code, 200)
                self.assertEqual(recipient_client.post(urlsplit(url).path).status_code, 302)
                self.assertEqual(recipient_client.get(urlsplit(url).path).status_code, 410)
                self.assertEqual(recipient_client.post(urlsplit(url).path).status_code, 410)
                self.assertEqual(FamilyLink.objects.filter(child=self.child, user=recipient, active=True).count(), 1)
                invitation.refresh_from_db()
                self.assertIsNotNone(invitation.used_at)

    def test_clinician_invitation_uses_owner_workflow_and_link_once_in_each_language(self):
        for language in ['fr', 'en', 'ar']:
            with self.subTest(language=language), translation.override(language):
                recipient = User.objects.create_user(username='http-clinician-'+language, email='http-clinician-'+language+'@example.test')
                self.client.force_login(self.owner)
                with self.provider() as (_transport, connection):
                    response = self.client.post(reverse('members'), practice_form_data(self.client, reverse('members'), {'email':recipient.email}))
                    self.assertEqual(response.status_code, 302)
                    path = urlsplit(self.link(connection)).path
                invitation = Invitation.objects.get(email=recipient.email)
                self.assertEqual((invitation.kind, invitation.delivery), ('clinician', 'sent'))
                self.assertTrue(path.startswith('/'+language+'/invite/'))
                receiver = Client()
                receiver.force_login(recipient)
                self.assertEqual(receiver.post(path).status_code, 302)
                self.assertEqual(receiver.post(path).status_code, 410)
                self.assertEqual(Membership.objects.get(user=recipient, organization=self.organization).role, 'clinician')

    def test_provider_refusal_timeout_and_malformed_acceptance_mark_invitations_failed(self):
        for index, fault in enumerate(self.faults):
            email = 'http-failed-'+str(index)+'@example.test'
            with self.subTest(fault=fault), self.provider(fault) as (transport, connection):
                response = self.issue_family(email)
                self.assertEqual(response.status_code, 302)
                invitation = Invitation.objects.get(email=email)
                self.assertEqual(invitation.delivery, 'failed')
                self.assertTrue(AuditEvent.objects.filter(action='invitation.delivery_failed', object_id=str(invitation.pk)).exists())
                self.assertFalse(AuditEvent.objects.filter(action='invitation.delivery_sent', object_id=str(invitation.pk)).exists())
                self.assertEqual(transport.call_count, 1)
                self.assertEqual(connection.request.call_count, 1)  # No redirect or hidden retry.
                shown = self.client.get(response.url)
                self.assertContains(shown, _('Invitation saved, but email delivery failed. Retry from pending invitations.'))
                self.assertNotContains(shown, self.marker)
                self.assertNotContains(shown, self.link(connection))

    def test_successful_http_retry_revokes_the_failed_link_before_replacing_it(self):
        with self.provider('rate_limited') as (_transport, connection):
            self.issue_family()
            old_path = urlsplit(self.link(connection)).path
        old = Invitation.objects.get(email=self.recipient.email)
        with self.provider() as (_transport, connection):
            self.assertEqual(self.client.post(reverse('resend_invitation', args=[old.pk])).status_code, 302)
            new_path = urlsplit(self.link(connection)).path
        old.refresh_from_db()
        self.assertTrue(old.revoked)
        current = Invitation.objects.exclude(pk=old.pk).get(email=self.recipient.email)
        self.assertEqual(current.delivery, 'sent')
        self.assertNotEqual(old.token_hash, current.token_hash)
        receiver = Client()
        receiver.force_login(self.recipient)
        self.assertEqual(receiver.get(old_path).status_code, 410)
        self.assertEqual(receiver.post(new_path).status_code, 302)
        self.assertEqual(receiver.post(new_path).status_code, 410)

    def test_forwarded_link_does_not_authorize_a_different_account_or_consume_it(self):
        with self.provider() as (_transport, connection):
            self.issue_family()
            path = urlsplit(self.link(connection)).path
        invitation = Invitation.objects.get(email=self.recipient.email)
        wrong = Client()
        wrong.force_login(self.other)
        self.assertEqual(wrong.post(path).status_code, 200)
        invitation.refresh_from_db()
        self.assertIsNone(invitation.used_at)
        self.assertFalse(FamilyLink.objects.filter(child=self.child).exists())
        wrong.force_login(self.recipient)
        self.assertEqual(wrong.post(path).status_code, 302)
        self.assertTrue(FamilyLink.objects.filter(child=self.child, user=self.recipient).exists())

    def test_foreign_cabinet_cannot_issue_resend_or_revoke_and_never_calls_provider(self):
        with self.provider() as (_transport, connection):
            self.issue_family()
        invitation = Invitation.objects.get(email=self.recipient.email)
        self.client.force_login(self.other)
        with self.provider() as (transport, _connection):
            self.assertEqual(self.client.post(reverse('child_detail', args=[self.child.pk]), {'email':'foreign-attempt@example.test'}).status_code, 404)
            self.assertEqual(self.client.post(reverse('resend_invitation', args=[invitation.pk])).status_code, 404)
            self.assertEqual(self.client.post(reverse('revoke_invite', args=[invitation.pk])).status_code, 404)
            with self.assertRaises(ValidationError):
                issue_and_deliver_invitation(self.other, self.organization, self.child, 'forbidden@example.test')
            with self.assertRaises(ValidationError):
                issue_and_deliver_invitation(self.pro, self.foreign_organization, self.foreign_child, 'forbidden@example.test', kind='clinician')
            transport.assert_not_called()
        self.assertEqual(Invitation.objects.count(), 1)
        invitation.refresh_from_db()
        self.assertFalse(invitation.revoked)

    def test_revoked_or_expired_delivered_invitations_do_not_create_family_access(self):
        for state in ['revoked', 'expired']:
            email = 'http-expiry-'+state+'@example.test'
            recipient = User.objects.create_user(username='http-expiry-'+state, email=email)
            with self.subTest(state=state), self.provider() as (_transport, connection):
                self.issue_family(email)
                path = urlsplit(self.link(connection)).path
            invitation = Invitation.objects.get(email=email)
            if state == 'revoked':
                self.assertEqual(self.client.post(reverse('revoke_invite', args=[invitation.pk])).status_code, 302)
            else:
                invitation.expires_at = timezone.now()-timedelta(seconds=1)
                invitation.save()
            receiver = Client()
            receiver.force_login(recipient)
            self.assertEqual(receiver.get(path).status_code, 410)
            self.assertEqual(receiver.post(path).status_code, 410)
            self.assertFalse(FamilyLink.objects.filter(child=self.child, user=recipient).exists())

    def test_password_reset_http_email_contains_a_once_only_valid_link_in_each_language(self):
        for language in ['fr', 'en', 'ar']:
            with self.subTest(language=language), translation.override(language):
                user = User.objects.create_user(username='http-reset-'+language, email='http-reset-'+language+'@example.test', password=secrets.token_urlsafe(24))
                requester = Client()
                with self.provider() as (transport, connection):
                    response = requester.post(reverse('password_reset'), {'email':user.email})
                    self.assertEqual(response.status_code, 302)
                    self.assertEqual(response.url, reverse('password_reset_done'))
                    self.assertEqual(transport.call_count, 1)
                    delivered = urlsplit(self.link(connection))
                    canonical = urlsplit(settings.PUBLIC_ORIGIN)
                    self.assertEqual((delivered.scheme, delivered.netloc), (canonical.scheme, canonical.netloc))
                    path = delivered.path
                    self.assertEqual(self.payload(connection)['to'], [user.email])
                self.assertTrue(path.startswith('/'+language+'/reset/'))
                receiver = Client()
                start = receiver.get(path)
                self.assertEqual(start.status_code, 302)
                self.assertIn('/set-password/', start.url)
                form = receiver.get(start.url)
                self.assertTrue(form.context['validlink'])
                new_password = secrets.token_urlsafe(24)
                self.assertEqual(receiver.post(start.url, {'new_password1':new_password, 'new_password2':new_password}).status_code, 302)
                user.refresh_from_db()
                self.assertTrue(user.check_password(new_password))
                reused = Client().get(path)
                self.assertEqual(reused.status_code, 200)
                self.assertFalse(reused.context['validlink'])

    @override_settings(ALLOWED_HOSTS=['testserver', 'allowed-alias.fictional-mail.tld'])
    def test_reset_uses_canonical_origin_for_an_allowed_alternate_host_and_unknown_stays_neutral(self):
        # This Host is allowed deliberately: outbound access links must still use PUBLIC_ORIGIN.
        alternate = 'allowed-alias.fictional-mail.tld'
        with self.subTest(account='known'), self.provider() as (transport, connection):
            response = Client().post(reverse('password_reset'), {'email':self.recipient.email}, HTTP_HOST=alternate)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse('password_reset_done'))
            self.assertEqual(transport.call_count, 1)
            delivered = urlsplit(self.link(connection))
            canonical = urlsplit(settings.PUBLIC_ORIGIN)
            self.assertEqual((delivered.scheme, delivered.netloc), (canonical.scheme, canonical.netloc))
            self.assertNotEqual(delivered.netloc, alternate)
        with self.subTest(account='unknown'), self.provider() as (transport, _connection):
            email = 'http-reset-alternate-unknown@example.test'
            response = Client().post(reverse('password_reset'), {'email':email}, HTTP_HOST=alternate)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse('password_reset_done'))
            transport.assert_not_called()
            self.assertNotContains(Client().get(response.url, HTTP_HOST=alternate), email)

    def test_reset_unknown_inactive_and_unusable_accounts_are_neutral_without_http_calls(self):
        inactive = User.objects.create_user(username='http-reset-inactive', email='http-reset-inactive@example.test', is_active=False, password=secrets.token_urlsafe(24))
        unusable = User.objects.create_user(username='http-reset-unusable', email='http-reset-unusable@example.test')
        self.assertFalse(unusable.has_usable_password())
        for language in ['fr', 'en', 'ar']:
            with translation.override(language):
                for email in ['http-reset-unknown@example.test', inactive.email, unusable.email]:
                    with self.subTest(language=language, email=email), self.provider() as (transport, _connection):
                        response = Client().post(reverse('password_reset'), {'email':email})
                        self.assertEqual(response.status_code, 302)
                        self.assertEqual(response.url, reverse('password_reset_done'))
                        transport.assert_not_called()
                        self.assertNotContains(Client().get(response.url), email)

    def test_reset_provider_failures_stay_neutral_and_logs_exclude_credentials_recipient_and_link(self):
        for index, fault in enumerate(self.faults):
            user = User.objects.create_user(username='http-reset-error-'+str(index), email='http-reset-error-'+str(index)+'@example.test', password=secrets.token_urlsafe(24))
            with self.subTest(fault=fault), self.provider(fault) as (_transport, connection):
                with self.assertLogs('django.contrib.auth', level='ERROR') as logged:
                    response = Client().post(reverse('password_reset'), {'email':user.email})
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.url, reverse('password_reset_done'))
                self.assert_private_failure_logs(logged.output, connection, user.email)
                self.assertNotContains(Client().get(response.url), user.email)

    def test_password_reset_expiry_still_blocks_the_delivered_http_link(self):
        requester = Client()
        with self.provider() as (_transport, connection):
            requester.post(reverse('password_reset'), {'email':self.recipient.email})
            path = urlsplit(self.link(connection)).path
        with override_settings(PASSWORD_RESET_TIMEOUT=1), patch('django.contrib.auth.tokens.default_token_generator._now', return_value=datetime.now()+timedelta(minutes=5)):
            response = Client().get(path)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['validlink'])

    @override_settings(EMAIL_BACKEND='core.email_backends.DisabledEmailBackend')
    def test_disabled_backend_saves_failed_invitation_without_transport_or_sensitive_log(self):
        with self.provider() as (transport, _connection), self.assertNoLogs('django', level='ERROR'):
            response = self.issue_family()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Invitation.objects.get(email=self.recipient.email).delivery, 'failed')
        transport.assert_not_called()
        self.assertNotContains(self.client.get(response.url), settings.RESEND_API_KEY)

    @override_settings(EMAIL_BACKEND='core.email_backends.DisabledEmailBackend')
    def test_disabled_backend_keeps_reset_neutral_with_only_generic_error_logging(self):
        with self.provider() as (transport, _connection), self.assertLogs('django.contrib.auth', level='ERROR') as logged:
            response = Client().post(reverse('password_reset'), {'email':self.recipient.email})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('password_reset_done'))
        transport.assert_not_called()
        self.assert_private_failure_logs(logged.output, email=self.recipient.email)
        self.assertNotIn('A password reset was requested for your Nehedrou account.', '\n'.join(logged.output))
