from datetime import timedelta

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from care.models import Child, FamilyLink
from catalog.models import Variety
from followup.models import ClinicalGoal
from .access import CURRENT_NOTICE_VERSION
from .models import Entitlement, Invitation, Membership, NoticeAcknowledgement, Organization, User
from .testing import practice_form_data


@override_settings(DEMO_MODE=False, MFA_REQUIRED=False,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class NoticeGateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('notice-gate-owner', 'notice-gate@example.test')
        cls.organization = Organization.objects.create(name='Fictional practice')
        Membership.objects.create(user=cls.user, organization=cls.organization, role='owner')
        Entitlement.objects.create(organization=cls.organization, status='active',
            expires_at=timezone.now() + timedelta(days=2), child_quota=3)
        cls.variety = Variety.objects.create(code='notice-fr', language='fr', label='French')

    def setUp(self):
        self.client.force_login(self.user)

    def test_profile_creation_requires_acknowledging_current_notice_for_same_practice(self):
        path = reverse('child_create')
        form = practice_form_data(self.client, path, {
            'code': 'Fictional profile', 'age_years': 5,
            'varieties': [str(self.variety.pk)],
        })
        response = self.client.post(path, form)
        self.assertRedirects(response, reverse('data_notice'), fetch_redirect_response=False)
        self.assertFalse(self.organization.child_set.exists())

        notice_path = reverse('data_notice')
        acknowledgement = practice_form_data(self.client, notice_path)
        response = self.client.post(notice_path, acknowledgement)
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        self.assertTrue(NoticeAcknowledgement.objects.filter(
            user=self.user, organization=self.organization,
            version=CURRENT_NOTICE_VERSION).exists())

        response = self.client.post(path, form)
        child = self.organization.child_set.get()
        self.assertRedirects(response, reverse('child_detail', kwargs={'pk': child.pk}), fetch_redirect_response=False)
        self.assertEqual(self.organization.child_set.count(), 1)

    def test_old_notice_acknowledgement_does_not_unlock_real_data_creation(self):
        NoticeAcknowledgement.objects.create(user=self.user, organization=self.organization,
            version='older-notice', language='en')
        path = reverse('child_create')
        form = practice_form_data(self.client, path, {
            'code': 'Fictional profile', 'age_years': 5,
            'varieties': [str(self.variety.pk)],
        })
        response = self.client.post(path, form)
        self.assertRedirects(response, reverse('data_notice'), fetch_redirect_response=False)
        self.assertFalse(self.organization.child_set.exists())

    def test_clinical_followup_goal_cannot_be_written_before_notice_acknowledgement(self):
        child = Child.objects.create(code='Fictional follow-up profile', age_years=5,
            responsible=self.user, organization=self.organization)
        child.varieties.add(self.variety)
        path = reverse('followup:goal_create', kwargs={'child_id': child.pk})
        response = self.client.post(path, {
            'variety': str(self.variety.pk),
            'external_assessment_status': 'confirmed',
            'target_phoneme': 'p',
            'target_position': 'initial',
            'context_key': 'isolated_word',
            'rationale': 'Fictional test rationale',
            'expected_realization': '/p/',
            'functional_goal': 'Fictional test goal',
        })
        self.assertRedirects(response, reverse('data_notice'), fetch_redirect_response=False)
        self.assertFalse(ClinicalGoal.objects.filter(child=child).exists())
    def invite_child(self, email):
        child = Child.objects.create(code='Fictional invited profile', age_years=5,
            responsible=self.user, organization=self.organization)
        child.varieties.add(self.variety)
        invitation, token = Invitation.issue(self.organization, child, email, self.user, kind='family')
        return child, invitation, token

    def test_family_invitation_is_not_linked_until_current_notice_is_acknowledged(self):
        invited = User.objects.create_user('notice-family', 'notice-family@example.test')
        child, invitation, token = self.invite_child(invited.email)
        client = self.client_class()
        client.force_login(invited)
        path = reverse('invite', kwargs={'token': token})

        response = client.post(path, {})
        self.assertRedirects(response, reverse('data_notice'), fetch_redirect_response=False)
        self.assertFalse(FamilyLink.objects.filter(child=child, user=invited).exists())

        notice_path = reverse('data_notice')
        acknowledgement = practice_form_data(client, notice_path)
        response = client.post(notice_path, acknowledgement)
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        self.assertTrue(FamilyLink.objects.filter(child=child, user=invited, active=True).exists())
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.used_at)

    def test_new_family_account_is_created_but_not_linked_before_notice_acknowledgement(self):
        child, invitation, token = self.invite_child('new-notice-family@example.test')
        client = Client()
        path = reverse('invite', kwargs={'token': token})
        response = client.post(path, {
            'username': 'care-parent-98',
            'instruction_language': 'ar',
            'password1': 'BlueRiver!Orbit73*',
            'password2': 'BlueRiver!Orbit73*',
        })
        self.assertEqual(response.status_code, 302, str(response.context['form'].errors) if response.context and response.context.get('form') else '')
        self.assertRedirects(response, reverse('data_notice'), fetch_redirect_response=False)
        invited = User.objects.get(email='new-notice-family@example.test')
        self.assertFalse(FamilyLink.objects.filter(child=child, user=invited).exists())

        acknowledgement = practice_form_data(client, reverse('data_notice'))
        response = client.post(reverse('data_notice'), acknowledgement)
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        self.assertTrue(FamilyLink.objects.filter(child=child, user=invited, active=True).exists())
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.used_at)
    def test_professional_invitation_is_not_activated_until_notice_acknowledgement(self):
        invited = User.objects.create_user('notice-clinician', 'notice-clinician@example.test')
        invitation, token = Invitation.issue(self.organization, None, invited.email,
            self.user, kind='clinician')
        client = self.client_class()
        client.force_login(invited)
        response = client.post(reverse('invite', kwargs={'token': token}), {})
        self.assertRedirects(response, reverse('data_notice'), fetch_redirect_response=False)
        self.assertFalse(Membership.objects.filter(user=invited, organization=self.organization).exists())

        acknowledgement = practice_form_data(client, reverse('data_notice'))
        response = client.post(reverse('data_notice'), acknowledgement)
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        self.assertTrue(Membership.objects.filter(user=invited, organization=self.organization,
            active=True, role='clinician').exists())
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.used_at)
