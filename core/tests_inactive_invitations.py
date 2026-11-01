"""Inactive-recipient guards use fictional accounts and no real mail transport."""
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext as _

from care.models import Child
from core.forms import InvitationForm
from core.models import AuditEvent, Invitation, Membership, Organization, User
from core.services import issue_and_deliver_invitation
from core.testing import practice_form_data


INACTIVE_MESSAGE = 'This email belongs to an inactive account. Contact the platform manager before inviting it.'


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class InactiveRecipientInvitationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user('inactive-invite-owner', 'inactive-owner@example.test')
        cls.inactive = User.objects.create_user('inactive-invite-recipient', 'inactive-recipient@example.test', is_active=False)
        cls.active = User.objects.create_user('active-invite-recipient', 'active-recipient@example.test')
        cls.organization = Organization.objects.create(name='Fictional inactive-recipient practice')
        Membership.objects.create(user=cls.owner, organization=cls.organization, role='owner')
        cls.child = Child.objects.create(organization=cls.organization, responsible=cls.owner,
            code='Fictional inactive-recipient dossier', age_years=5)

    def setUp(self):
        self.client.force_login(self.owner)

    def issue(self, kind, email, replacing=None):
        return issue_and_deliver_invitation(self.owner, self.organization,
            self.child if kind == 'family' else None, email, kind=kind, replacing=replacing)

    def prior(self, kind, email):
        invitation, _token = Invitation.issue(self.organization,
            self.child if kind == 'family' else None, email, self.owner, kind=kind)
        return invitation

    def test_form_rejects_inactive_case_insensitively_and_preserves_active_or_unknown(self):
        form = InvitationForm({'email': self.inactive.email.upper()})
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['email'], [_(INACTIVE_MESSAGE)])
        for email in [self.active.email.upper(), 'unknown-recipient@example.test']:
            with self.subTest(email=email):
                self.assertTrue(InvitationForm({'email': email}).is_valid())
        self.inactive.refresh_from_db()
        self.assertFalse(self.inactive.is_active)

    def test_service_rejects_new_inactive_recipient_without_token_audit_or_send(self):
        for kind in ['family', 'clinician']:
            with self.subTest(kind=kind), patch('django.core.mail.send_mail') as send:
                with self.assertRaisesMessage(ValidationError, _(INACTIVE_MESSAGE)):
                    self.issue(kind, self.inactive.email.upper())
                send.assert_not_called()
        self.assertFalse(Invitation.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action__startswith='invitation.').exists())
        self.inactive.refresh_from_db()
        self.assertFalse(self.inactive.is_active)

    def test_service_rejects_inactive_resend_without_revoking_or_changing_old_record(self):
        for kind in ['family', 'clinician']:
            with self.subTest(kind=kind):
                old = self.prior(kind, self.inactive.email)
                before = Invitation.objects.values().get(pk=old.pk)
                count = Invitation.objects.count()
                with patch('django.core.mail.send_mail') as send:
                    with self.assertRaisesMessage(ValidationError, _(INACTIVE_MESSAGE)):
                        self.issue(kind, old.email, replacing=old)
                    send.assert_not_called()
                self.assertEqual(Invitation.objects.values().get(pk=old.pk), before)
                self.assertEqual(Invitation.objects.count(), count)
        self.assertFalse(AuditEvent.objects.filter(action__startswith='invitation.').exists())

    def test_service_rechecks_account_deactivated_after_form_validation(self):
        for kind in ['family', 'clinician']:
            with self.subTest(kind=kind):
                User.objects.filter(pk=self.active.pk).update(is_active=True)
                form = InvitationForm({'email': self.active.email})
                self.assertTrue(form.is_valid())
                User.objects.filter(pk=self.active.pk).update(is_active=False)
                with patch('django.core.mail.send_mail') as send:
                    with self.assertRaisesMessage(ValidationError, _(INACTIVE_MESSAGE)):
                        self.issue(kind, form.cleaned_data['email'])
                    send.assert_not_called()
        self.assertFalse(Invitation.objects.exists())

    def test_active_and_unknown_recipients_can_create_and_replace_both_invitation_kinds(self):
        for kind in ['family', 'clinician']:
            for email in [self.active.email.upper(), 'unknown-recipient@example.test']:
                with self.subTest(kind=kind, email=email), patch('django.core.mail.send_mail', return_value=1) as send:
                    invitation = self.issue(kind, email)
                    self.assertEqual(invitation.delivery, 'sent')
                    self.assertEqual(invitation.email, email.lower())
                    replacement = self.issue(kind, invitation.email, replacing=invitation)
                    invitation.refresh_from_db()
                    self.assertTrue(invitation.revoked)
                    self.assertEqual(replacement.delivery, 'sent')
                    self.assertNotEqual(replacement.token_hash, invitation.token_hash)
                    self.assertEqual(send.call_count, 2)
        self.active.refresh_from_db()
        self.assertTrue(self.active.is_active)

    def test_initial_forms_display_error_in_three_languages_for_both_roles(self):
        for language in ['fr', 'en', 'ar']:
            with translation.override(language):
                for kind in ['family', 'clinician']:
                    with self.subTest(language=language, kind=kind), patch('django.core.mail.send_mail') as send:
                        path = reverse('child_detail', args=[self.child.pk]) if kind == 'family' else reverse('members')
                        data = {'email': self.inactive.email.upper()}
                        if kind == 'clinician':
                            data = practice_form_data(self.client, path, data)
                        response = self.client.post(path, data)
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.context['form'].errors['email'], [_(INACTIVE_MESSAGE)])
                        self.assertContains(response, _(INACTIVE_MESSAGE))
                        send.assert_not_called()
        self.assertFalse(Invitation.objects.exists())

    def test_resend_views_keep_both_old_links_and_show_the_service_error(self):
        for kind in ['family', 'clinician']:
            with self.subTest(kind=kind):
                old = self.prior(kind, self.inactive.email)
                before = Invitation.objects.values().get(pk=old.pk)
                with patch('django.core.mail.send_mail') as send:
                    response = self.client.post(reverse('resend_invitation', args=[old.pk]), follow=True)
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, _(INACTIVE_MESSAGE))
                    send.assert_not_called()
                self.assertEqual(Invitation.objects.values().get(pk=old.pk), before)
        self.assertEqual(Invitation.objects.count(), 2)
        self.assertFalse(AuditEvent.objects.filter(action__startswith='invitation.').exists())
