"""Fictional checks for the contact explicitly shared on a practice's data notice."""
from datetime import timedelta
import uuid

from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from care.models import Child, FamilyLink
from core.access import CURRENT_NOTICE_VERSION
from core.models import Entitlement, Membership, NoticeAcknowledgement, Organization, ProcessingActivity, User
from core.services import issue_manual_practice_invitation
from core.testing import practice_form_data


@override_settings(DEMO_MODE=False, MFA_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class PracticeNoticeContactTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alpha = Organization.objects.create(
            name='Fictional Alpha', data_notice_contact_email='privacy@alpha.example.test')
        cls.beta = Organization.objects.create(
            name='Fictional Beta', data_notice_contact_email='privacy@beta.example.test')
        cls.owner = User.objects.create_user('notice-owner', 'owner-login@example.test')
        cls.clinician = User.objects.create_user('notice-clinician', 'clinician-login@example.test')
        cls.family = User.objects.create_user('notice-family', 'family-login@example.test')
        cls.operator = User.objects.create_user('notice-operator', 'operator-login@example.test')
        cls.operator.user_permissions.add(Permission.objects.get(codename='manage_processing_register'))
        for organization in (cls.alpha, cls.beta):
            Membership.objects.create(user=cls.owner, organization=organization, role='owner')
            Membership.objects.create(user=cls.clinician, organization=organization, role='clinician')
        cls.first_child = Child.objects.create(
            organization=cls.alpha, code='Fictional one', age_years=5, responsible=cls.clinician)
        cls.sibling = Child.objects.create(
            organization=cls.alpha, code='Fictional two', age_years=6, responsible=cls.clinician)
        cls.other_child = Child.objects.create(
            organization=cls.beta, code='Fictional three', age_years=7, responsible=cls.clinician)
        FamilyLink.objects.create(child=cls.first_child, user=cls.family)
        ProcessingActivity.objects.create(
            organization=cls.alpha, name='Fictional private register entry',
            controller_name='Fictional operator', controller_contact='internal-register@example.test',
            data_protection_contact='internal-adviser@example.test', purposes='Fictional purposes',
            legal_basis='Fictional basis', data_subject_categories='Fictional users',
            personal_data_categories='Fictional data', recipient_categories='Fictional recipients',
            international_transfers='No fictional transfers', retention_periods='Fictional period',
            security_measures='Fictional safeguards', operations='Fictional operations')

    def select(self, organization, workspace='professional'):
        session = self.client.session
        session['organization'] = str(organization)
        session['workspace'] = workspace
        session.save()

    def assert_fallback(self, response):
        self.assertContains(response, 'ask your practice for its contact details')
        self.assertNotContains(response, self.alpha.data_notice_contact_email)
        self.assertNotContains(response, self.beta.data_notice_contact_email)

    def test_owner_can_save_validate_preserve_and_clear_only_selected_practice_contact(self):
        self.client.force_login(self.owner)
        self.select(self.alpha.pk)
        url = '/en/practice/settings/'
        data = practice_form_data(self.client, url, {
            'name': self.alpha.name, 'country': 'DZ', 'retention_days': 120, 'organization': str(self.beta.pk),
        })

        response = self.client.post(url, {**data, 'data_notice_contact_email': 'office@alpha.example.test'})
        self.assertEqual(response.status_code, 302)
        self.alpha.refresh_from_db()
        self.assertEqual(self.alpha.data_notice_contact_email, 'office@alpha.example.test')
        self.assertEqual(self.alpha.retention_days, 120)

        response = self.client.post(url, {**data, 'data_notice_contact_email': 'invalid address'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('data_notice_contact_email', response.context['form'].errors)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.alpha.refresh_from_db()
        self.assertEqual(self.alpha.data_notice_contact_email, 'office@alpha.example.test')

        self.assertEqual(self.client.post(url, {**data, 'data_notice_contact_email': ''}).status_code, 302)
        self.alpha.refresh_from_db()
        self.beta.refresh_from_db()
        self.assertEqual(self.alpha.data_notice_contact_email, '')
        self.assertEqual(self.beta.data_notice_contact_email, 'privacy@beta.example.test')
        self.assertContains(self.client.get('/en/information/'), 'ask your practice for its contact details')

    def test_other_roles_cannot_edit_the_contact(self):
        url = '/en/practice/settings/'
        for user in (self.clinician, self.family, self.operator):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.select(self.alpha.pk)
                self.assertEqual(self.client.get(url).status_code, 404)
                self.assertEqual(self.client.post(url, {
                    'data_notice_contact_email': 'wrong-role@example.test',
                }).status_code, 404)
        self.alpha.refresh_from_db()
        self.assertEqual(self.alpha.data_notice_contact_email, 'privacy@alpha.example.test')

    def test_owner_notice_and_settings_are_localized_and_contact_is_escaped(self):
        self.client.force_login(self.owner)
        self.select(self.alpha.pk)
        self.alpha.data_notice_contact_email = 'privacy&records@alpha.example.test'
        self.alpha.save(update_fields=['data_notice_contact_email'])
        for language, direction, settings_label, notice_label in (
            ('en', 'ltr', 'Email address shown on the data notice', 'Practice contact for data questions'),
            ('fr', 'ltr', 'Adresse e-mail affichée dans la notice sur les données',
             'Contact du cabinet pour les questions sur les données'),
            ('ar', 'rtl', 'عنوان البريد الإلكتروني المعروض في إشعار البيانات', 'عنوان العيادة لأسئلة البيانات'),
        ):
            with self.subTest(language=language):
                form = self.client.get(f'/{language}/practice/settings/')
                notice = self.client.get(f'/{language}/information/')
                self.assertContains(form, settings_label)
                self.assertEqual(form.context['form'].fields['data_notice_contact_email'].widget.attrs['dir'], 'ltr')
                self.assertContains(notice, notice_label)
                self.assertContains(notice, f'<html lang="{language}" dir="{direction}">')
                self.assertContains(notice, '<bdi dir="ltr">privacy&amp;records@alpha.example.test</bdi>')
                self.assertNotContains(notice, self.beta.data_notice_contact_email)
                self.assertNotContains(notice, self.owner.email)
                self.assertNotContains(notice, 'internal-register@example.test')
                self.assertNotContains(notice, 'internal-adviser@example.test')

    def test_family_contact_requires_only_one_distinct_active_linked_practice(self):
        self.client.force_login(self.family)
        FamilyLink.objects.create(child=self.sibling, user=self.family)
        unrelated = FamilyLink.objects.create(child=self.other_child, user=self.family)
        path = '/en/information/'
        self.assert_fallback(self.client.get(path))
        unrelated.active = False
        unrelated.save(update_fields=['active'])
        response = self.client.get(path)
        self.assertContains(response, self.alpha.data_notice_contact_email)
        self.assertNotContains(response, self.beta.data_notice_contact_email)
        self.assertNotContains(response, 'internal-register@example.test')
        self.assertNotContains(response, 'internal-adviser@example.test')

    def test_stale_practice_selection_does_not_display_a_fallback_practice_address(self):
        self.client.force_login(self.owner)
        self.select(uuid.uuid4())
        path = '/en/information/'
        self.assert_fallback(self.client.get(path))
        self.select(self.beta.pk)
        response = self.client.get(path)
        self.assertContains(response, self.beta.data_notice_contact_email)
        self.assertNotContains(response, self.alpha.data_notice_contact_email)

    def test_pending_invitation_has_precedence_and_existing_acceptance_still_grants_the_link(self):
        Entitlement.objects.create(organization=self.beta, expires_at=timezone.now() + timedelta(days=5),
                                   child_quota=10, practitioner_quota=10)
        NoticeAcknowledgement.objects.create(user=self.clinician, organization=self.beta,
                                             version=CURRENT_NOTICE_VERSION, language='en')
        invitation, token = issue_manual_practice_invitation(
            self.clinician, self.beta, self.other_child, self.family.email, 'family', uuid.uuid4())
        self.client.force_login(self.family)
        self.select(uuid.uuid4())
        with translation.override('en'):
            path = reverse('data_notice')
            self.assert_fallback(self.client.get(path))
            response = self.client.post(reverse('invite', args=[token]))
            self.assertRedirects(response, path, fetch_redirect_response=False)
            response = self.client.get(path)
            self.assertContains(response, self.beta.data_notice_contact_email)
            self.assertNotContains(response, self.alpha.data_notice_contact_email)
            self.assertNotContains(response, self.family.email)
            self.assertEqual(response.context['organization'], self.beta)
            self.assertEqual(self.client.post(path, practice_form_data(self.client, path)).status_code, 302)
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.used_at)
        self.assertTrue(NoticeAcknowledgement.objects.filter(
            user=self.family, organization=self.beta, version=CURRENT_NOTICE_VERSION).exists())
        linked_children = set(FamilyLink.objects.filter(user=self.family, active=True).values_list('child_id', flat=True))
        self.assertEqual(linked_children, {self.first_child.pk, self.other_child.pk})

    @override_settings(DEMO_MODE=True)
    def test_demo_notice_uses_the_fictional_use_copy(self):
        self.client.force_login(self.owner)
        self.select(self.alpha.pk)
        response = self.client.get('/en/information/')
        self.assertContains(response, 'This local version uses fictional profiles')
        self.assertNotContains(response, self.alpha.data_notice_contact_email)
