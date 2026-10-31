from .testing import practice_form_data
"""Known unavailable transport must not invite futile token rotation."""
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext as _

from care.models import Child, FamilyLink
from core.models import Invitation, Membership, Organization, User


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    EMAIL_BACKEND='core.email_backends.DisabledEmailBackend')
class InvitationDeliveryViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user('delivery-owner', 'delivery-owner@example.test')
        cls.outsider = User.objects.create_user('delivery-outsider', 'delivery-outsider@example.test')
        cls.organization = Organization.objects.create(name='Fictional delivery practice')
        Membership.objects.create(user=cls.owner, organization=cls.organization, role='owner')
        cls.child = Child.objects.create(organization=cls.organization, responsible=cls.owner,
                                        code='Fictional delivery dossier', age_years=5)

    def setUp(self):
        self.client.force_login(self.owner)

    def failed_invitation(self, kind):
        invitation, _token = Invitation.issue(self.organization, self.child if kind == 'family' else None,
            'delivery-recipient@example.test', self.owner, kind=kind)
        invitation.delivery = 'failed'
        invitation.save(update_fields=['delivery'])
        return invitation

    @staticmethod
    def snapshot(invitation):
        return (invitation.token_hash, invitation.revoked, invitation.used_at,
                invitation.expires_at, invitation.delivery)

    def test_senders_see_recording_and_configuration_notice_in_each_language(self):
        for language in ('fr', 'en', 'ar'):
            with self.subTest(language=language), translation.override(language):
                for target in ('members', 'child_detail'):
                    path = reverse(target, args=[self.child.pk] if target == 'child_detail' else None)
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.context['invitation_delivery']['known_unavailable'])
                    self.assertContains(response, _('Record invitation'))
                    self.assertContains(response, response.context['invitation_delivery']['notice'])
                    self.assertNotContains(response, 'core.email_backends')
                    self.assertNotContains(response, 'api.resend.com')

    def test_initial_invitations_remain_recorded_failed_without_external_transport(self):
        for kind in ('family', 'clinician'):
            with self.subTest(kind=kind), patch('http.client.HTTPSConnection') as https, patch('smtplib.SMTP') as smtp:
                path = reverse('child_detail', args=[self.child.pk]) if kind == 'family' else reverse('members')
                data = {'email':'initial-'+kind+'@example.test'}
                if kind == 'clinician':
                    data = practice_form_data(self.client, path, data)
                response = self.client.post(path, data)
                self.assertEqual(response.status_code, 302)
                invitation = Invitation.objects.get(email='initial-'+kind+'@example.test')
                self.assertEqual(invitation.delivery, 'failed')
                shown = self.client.get(response.url)
                self.assertContains(shown, _('Invitation recorded, but email delivery is unavailable in this configuration. Ask the service operator to configure delivery before retrying.'))
                https.assert_not_called(); smtp.assert_not_called()

    def test_known_unavailable_retry_keeps_both_invitation_kinds_unchanged(self):
        for kind in ('family', 'clinician'):
            with self.subTest(kind=kind):
                invitation = self.failed_invitation(kind)
                expected = self.snapshot(invitation)
                count = Invitation.objects.count()
                with patch('core.views.issue_and_deliver_invitation') as send:
                    response = self.client.post(reverse('resend_invitation', args=[invitation.pk]))
                self.assertEqual(response.status_code, 302)
                send.assert_not_called()
                invitation.refresh_from_db()
                self.assertEqual(self.snapshot(invitation), expected)
                self.assertEqual(Invitation.objects.count(), count)
                shown = self.client.get(response.url)
                self.assertNotContains(shown, reverse('resend_invitation', args=[invitation.pk]))
                self.assertContains(shown, _('Email delivery is unavailable in this configuration. The existing invitation has been kept. Ask the service operator to configure delivery before retrying.'))
                revoke = 'revoke_invite' if kind == 'family' else 'revoke_member_invitation'
                self.assertContains(shown, reverse(revoke, args=[invitation.pk]))

    def test_authorisation_is_checked_before_the_unavailable_transport_guard(self):
        invitations = [self.failed_invitation(kind) for kind in ('family', 'clinician')]
        self.client.force_login(self.outsider)
        with patch('core.views.invitation_delivery_status') as status, patch('core.views.issue_and_deliver_invitation') as send:
            for invitation in invitations:
                response = self.client.post(reverse('resend_invitation', args=[invitation.pk]))
                self.assertEqual(response.status_code, 404)
            status.assert_not_called(); send.assert_not_called()
        self.assertEqual(Invitation.objects.filter(revoked=True).count(), 0)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_a_transport_change_allows_the_existing_retry_and_rotates_the_old_link(self):
        from django.core import mail
        invitation = self.failed_invitation('family')
        response = self.client.get(reverse('child_detail', args=[self.child.pk]))
        self.assertFalse(response.context['invitation_delivery']['known_unavailable'])
        self.assertContains(response, reverse('resend_invitation', args=[invitation.pk]))
        response = self.client.post(reverse('resend_invitation', args=[invitation.pk]))
        self.assertEqual(response.status_code, 302)
        invitation.refresh_from_db()
        self.assertTrue(invitation.revoked)
        replacement = Invitation.objects.exclude(pk=invitation.pk).get()
        self.assertEqual(replacement.delivery, 'sent')
        self.assertNotEqual(replacement.token_hash, invitation.token_hash)
        self.assertEqual(len(mail.outbox), 1)

    def test_family_view_does_not_expose_invitation_operator_guidance(self):
        FamilyLink.objects.create(child=self.child, user=self.outsider)
        self.client.force_login(self.outsider)
        response = self.client.get(reverse('child_detail', args=[self.child.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['professional'])
        self.assertIsNone(response.context['invitation_delivery'])
        self.assertNotContains(response, _('Record invitation'))
