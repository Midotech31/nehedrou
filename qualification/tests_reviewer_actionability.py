"""Current reviewer eligibility and immutable checks on private qualification pages."""
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from catalog.models import Activity, EditorialGrant, Variety
from catalog.services import review_version
from core.models import AuditEvent, User
from .models import ReviewerCompetence, ReviewerCompetenceDecision
from .services import record_competence_decision
from .test_support import evidence_fixture


@override_settings(DEMO_MODE=False, MFA_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class ReviewerActionabilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.variety = Variety.objects.create(code='ar-actionability-dz', language='ar', label='Fictional Darja scope')
        cls.other_variety = Variety.objects.create(code='ar-actionability-msa', language='ar', label='Fictional MSA scope')
        cls.reviewer = User.objects.create_user('fictional-reviewer-state', 'reviewer-state@example.test')
        cls.publisher = User.objects.create_user('fictional-publisher-state', 'publisher-state@example.test')
        cls.outside_publisher = User.objects.create_user('fictional-other-publisher', 'other-publisher@example.test')
        cls.grant = EditorialGrant.objects.create(user=cls.reviewer, variety=cls.variety, clinical_review=True)
        EditorialGrant.objects.create(user=cls.publisher, variety=cls.variety, publish=True)
        EditorialGrant.objects.create(user=cls.outside_publisher, variety=cls.other_variety, publish=True)
        cls.declaration = ReviewerCompetence.objects.create(
            user=cls.reviewer, variety=cls.variety, discipline='clinical',
            professional_role='Fictional professional role', experience='Fictional Darja experience',
        )
        cls.original_basis = 'Fictional independent identity and scope method for this regression.'
        cls.initial_decision = record_competence_decision(
            cls.publisher, cls.declaration.pk, 'verified', cls.original_basis, timezone.localdate(),
            expected_digest=cls.declaration.fingerprint(),
        )
        cls.example = Activity.objects.create(
            variety=cls.variety, series=uuid4(), title='Fictional editorial approval target', contrast='example',
            word_a='a', word_b='b', instructions={'fr': 'Exemple'}, state='review', is_demo=True,
        )

    def account(self, user):
        client = Client()
        client.force_login(user)
        return client

    def list_path(self, language='en'):
        return f'/{language}/qualification/competence-checks/'

    def detail_path(self, language='en'):
        return f'{self.list_path(language)}{self.declaration.pk}/'

    def assert_status(self, response, status, localized_text=None):
        self.assertContains(response, f'data-competence-status="{status}"')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertIn('private', response['Cache-Control'])
        if localized_text:
            self.assertContains(response, localized_text)

    def assert_history(self, response):
        self.assertContains(response, self.original_basis)
        self.assertContains(response, self.publisher.username)
        self.assertContains(response, self.initial_decision.checked_on.isoformat())

    def approve(self):
        return review_version(
            self.reviewer, self.example, 'clinical', True, 'Fictional ordinary approval',
            expected_digest=self.example.fingerprint(),
        )

    def test_inactive_account_shows_current_state_and_retains_previous_check_in_all_languages(self):
        User.objects.filter(pk=self.reviewer.pk).update(is_active=False)
        client = self.account(self.publisher)
        decisions_before = list(ReviewerCompetenceDecision.objects.values())
        audits_before = list(AuditEvent.objects.values())
        messages = {
            'fr': 'Compte de relecture inactif',
            'en': 'Reviewer account inactive',
            'ar': 'حساب المراجع غير نشط',
        }
        for language, message in messages.items():
            for url in (self.list_path(language), self.detail_path(language)):
                with self.subTest(url=url):
                    page = client.get(url)
                    self.assert_status(page, 'account_inactive', message)
                    self.assertNotContains(page, 'data-competence-status="eligible"')
                    self.assert_history(page)
        self.assertEqual(list(ReviewerCompetenceDecision.objects.values()), decisions_before)
        self.assertEqual(list(AuditEvent.objects.values()), audits_before)
        self.assertEqual(ReviewerCompetence.objects.get(pk=self.declaration.pk).current_decision_id,
                         self.initial_decision.pk)
        outsider = self.account(self.outside_publisher)
        self.assertNotContains(outsider.get(self.list_path()), self.original_basis)
        self.assertEqual(outsider.get(self.detail_path()).status_code, 404)

    def test_permission_loss_checks_exact_variety_and_discipline_on_both_workspaces(self):
        publisher = self.account(self.publisher)
        reviewer = self.account(self.reviewer)
        self.assert_status(publisher.get(self.detail_path()), 'eligible')
        self.assertTrue(self.approve().approved)
        self.grant.clinical_review = False
        self.grant.linguistic_review = True
        self.grant.save()
        EditorialGrant.objects.create(user=self.reviewer, variety=self.other_variety, clinical_review=True)
        page = publisher.get(self.detail_path())
        self.assert_status(page, 'permission_missing', 'Review permission missing for this discipline and variety')
        self.assert_history(page)
        own_page = reviewer.get('/en/qualification/')
        self.assert_status(own_page, 'permission_missing')
        self.assertNotContains(own_page, self.original_basis)
        with self.assertRaises(PermissionDenied):
            self.approve()

    def test_stale_fingerprint_requires_a_new_check_instead_of_rewriting_history(self):
        self.declaration.experience = 'Fictional replacement after the historical check.'
        self.declaration.save(update_fields=['experience'])
        page = self.account(self.publisher).get(self.detail_path())
        self.assert_status(page, 'check_required', 'Independent check required')
        self.assert_history(page)
        self.assertEqual(ReviewerCompetenceDecision.objects.count(), 1)
        with self.assertRaises(ValidationError):
            self.approve()

    def test_current_check_does_not_replace_nonempty_experience_or_usable_private_evidence(self):
        with self.settings(STORAGES={
            'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
            'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
        }):
            publisher = self.account(self.publisher)
            self.declaration.experience = ' '
            self.declaration.save(update_fields=['experience'])
            self.record_new_check()
            self.assert_status(publisher.get(self.detail_path()), 'check_required')
            self.declaration.experience = 'Fictional experience backed by a fictional document.'
            evidence = evidence_fixture(self.variety, self.publisher, 'clinical_content')
            self.declaration.evidence = evidence
            self.declaration.save(update_fields=['experience', 'evidence'])
            self.record_new_check()
            self.assert_status(publisher.get(self.detail_path()), 'eligible')
            evidence.revoked = True
            evidence.revocation_reason = 'Fictitious withdrawal of supporting document.'
            evidence.save()
            self.assert_status(publisher.get(self.detail_path()), 'check_required')
            with self.assertRaises(ValidationError):
                self.approve()

    def test_active_superuser_bypasses_only_the_exact_grant(self):
        self.grant.delete()
        self.reviewer.is_superuser = True
        self.reviewer.save(update_fields=['is_superuser'])
        publisher = self.account(self.publisher)
        self.assert_status(publisher.get(self.detail_path()), 'eligible')
        self.assertTrue(self.approve().approved)
        self.declaration.experience += ' Fictitious change after the old check.'
        self.declaration.save(update_fields=['experience'])
        self.assert_status(publisher.get(self.detail_path()), 'check_required')
        User.objects.filter(pk=self.reviewer.pk).update(is_active=False)
        self.assert_status(publisher.get(self.detail_path()), 'account_inactive')

    def record_new_check(self):
        return record_competence_decision(
            self.publisher, self.declaration.pk, 'verified', 'New fictional independent documentary check.',
            timezone.localdate(), expected_digest=self.declaration.fingerprint(),
        )
