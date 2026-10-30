"""Fictional dossiers cannot be orphaned by transfer to a disabled account."""
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from care.models import Child
from .forms import ReassignForm
from .models import AuditEvent, ChildResponsibilityTransfer, Membership, Organization, User
from .services import revoke_membership, transfer_child


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False,
                   PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DisabledRecipientTransferTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='disabled-owner', email='disabled-owner@example.test')
        self.source = User.objects.create_user(username='disabled-source', email='disabled-source@example.test')
        self.recipient = User.objects.create_user(username='disabled-recipient', email='disabled-recipient@example.test')
        self.organization = Organization.objects.create(name='Fictional disabled recipient practice')
        Membership.objects.create(user=self.owner, organization=self.organization, role='owner')
        self.source_membership = Membership.objects.create(user=self.source, organization=self.organization, role='clinician')
        Membership.objects.create(user=self.recipient, organization=self.organization, role='clinician')
        self.children = [Child.objects.create(organization=self.organization, responsible=self.source,
            code='Fictional disabled recipient ' + str(active), age_years=5, active=active)
            for active in (True, False)]

    def assert_unchanged(self):
        for child in self.children:
            child.refresh_from_db()
            self.assertEqual(child.responsible_id, self.source.pk)
        self.assertFalse(ChildResponsibilityTransfer.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action='child.reassigned').exists())
        self.source_membership.refresh_from_db()
        self.assertTrue(self.source_membership.active)

    def test_disabled_account_is_not_a_form_choice_or_valid_post(self):
        User.objects.filter(pk=self.recipient.pk).update(is_active=False)
        form = ReassignForm(organization=self.organization)
        self.assertFalse(form.fields['responsible'].queryset.filter(pk=self.recipient.pk).exists())
        self.client.force_login(self.source)
        for child in self.children:
            with self.subTest(active=child.active):
                response = self.client.post(reverse('child_reassign', args=[child.pk]), {'responsible': self.recipient.pk})
                self.assertEqual(response.status_code, 200)
                self.assertIn('responsible', response.context['form'].errors)
        self.assert_unchanged()

    def test_stale_active_choice_is_rechecked_and_revocation_stays_blocked(self):
        form = ReassignForm({'responsible': self.recipient.pk}, organization=self.organization)
        self.assertTrue(form.is_valid(), form.errors)
        selected = form.cleaned_data['responsible']
        User.objects.filter(pk=selected.pk).update(is_active=False)
        self.assertTrue(selected.is_active)  # The submitted instance is intentionally stale.
        for child in self.children:
            with self.subTest(active=child.active), self.assertRaises(ValidationError):
                transfer_child(self.source, child, selected)
        with self.assertRaises(ValidationError):
            revoke_membership(self.owner, self.organization, self.source_membership.pk)
        self.assert_unchanged()

    def test_current_active_database_account_can_receive_despite_stale_instance(self):
        self.recipient.is_active = False  # Only the caller's old instance is disabled.
        for child in self.children:
            transfer_child(self.source, child, self.recipient)
            child.refresh_from_db()
            self.assertEqual(child.responsible_id, self.recipient.pk)
        revoke_membership(self.owner, self.organization, self.source_membership.pk)
        self.assertEqual(ChildResponsibilityTransfer.objects.count(), 2)
        self.client.force_login(User.objects.get(pk=self.recipient.pk))
        for child in self.children:
            self.assertEqual(self.client.get(reverse('child_detail', args=[child.pk])).status_code, 200)
