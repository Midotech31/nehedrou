"""Personal reviewer onboarding with synthetic local software fixtures only."""
import uuid
from datetime import date
from urllib.parse import urlencode

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation
from django.utils.html import escape

from core.models import AuditEvent, User
from qualification.models import ReviewerCompetence, ReviewerCompetenceDecision
from qualification.reviewer_guidance import reviewer_experience_guidance
from qualification.services import record_competence_decision, save_competence_declaration
from qualification.test_support import evidence_fixture, prepare_activity_fixture
from .models import Activity, EditorialGrant, Review, Variety


@override_settings(DEMO_MODE=False, MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
              'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class ReviewerExperienceGuidanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.variety = Variety.objects.create(code='fr-guidance-fixture', language='fr', label='Fictional guidance variety')
        cls.foreign_variety = Variety.objects.create(code='ar-other-guidance', language='ar', label='Other fictional scope')
        cls.reviewer = User.objects.create_user('guidance-reviewer', 'reviewer@guidance.example.test')
        cls.other = User.objects.create_user('guidance-other', 'other@guidance.example.test')
        cls.editor = User.objects.create_user('guidance-editor', 'editor@guidance.example.test')
        cls.foreign = User.objects.create_user('guidance-foreign', 'foreign@guidance.example.test')
        cls.ordinary = User.objects.create_user('guidance-ordinary', 'ordinary@guidance.example.test')
        EditorialGrant.objects.create(user=cls.reviewer, variety=cls.variety, clinical_review=True, linguistic_review=True)
        EditorialGrant.objects.create(user=cls.other, variety=cls.variety, linguistic_review=True)
        EditorialGrant.objects.create(user=cls.editor, variety=cls.variety, edit=True, publish=True)
        EditorialGrant.objects.create(user=cls.foreign, variety=cls.foreign_variety, clinical_review=True)
        cls.activity = Activity.objects.create(variety=cls.variety, series=uuid.uuid4(), state='review',
            title='Fictional onboarding activity', word_a='pa', word_b='ba', contrast='p/b',
            instructions={'fr':'Fictif', 'en':'Fictional', 'ar':'مثال وهمي'},
            rights='Fictional regression rights only', population='Synthetic software fixtures only',
            limitations='No clinical qualification', is_demo=False)
        cls.other_document = evidence_fixture(cls.variety, cls.other, 'clinical_content')
        cls.other_declaration = ReviewerCompetence.objects.create(user=cls.other, variety=cls.variety,
            discipline='linguistic', professional_role='OTHER-PRIVATE-ROLE', experience='OTHER-PRIVATE-EXPERIENCE',
            credential_reference='OTHER-PRIVATE-CREDENTIAL', evidence=cls.other_document)

    def setUp(self):
        translation.activate('en')
        self.client.force_login(self.reviewer)

    def page(self):
        return self.client.get(reverse('editorial_detail', args=[self.activity.pk]))

    def rows(self, response):
        return {row['kind']: row for row in response.context['reviewer_experience']}

    def declare(self, discipline='clinical', **extra):
        return save_competence_declaration(self.reviewer, {
            'variety':self.variety, 'discipline':discipline,
            'professional_role':'Fictional reviewer', 'experience':'Fictional local software-test experience',
            'credential_reference':'', 'evidence':None, 'active':True, **extra})

    def verify(self, declaration, status='verified'):
        return record_competence_decision(self.editor, declaration.pk, status,
            'Fictional independent software-test verification only.', date(2026, 1, 1),
            expected_digest=declaration.fingerprint())

    def submit(self, approved=False, kind='clinical'):
        return self.client.post(reverse('editorial_detail', args=[self.activity.pk]),
            {'expected_digest':self.activity.fingerprint(), 'kind':kind, 'approved':approved,
             'note':'Fictional software review, no real clinical approval'})

    def test_new_reviewer_get_has_own_scoped_links_and_creates_no_records(self):
        counts = [model.objects.count() for model in [Review, ReviewerCompetence, ReviewerCompetenceDecision, AuditEvent]]
        response = self.page()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(self.rows(response)), {'clinical','linguistic'})
        for kind, row in self.rows(response).items():
            self.assertEqual(row['state'], 'missing')
            expected = reverse('qualification:competence')+'?'+urlencode({'variety':self.variety.code,'discipline':kind})
            self.assertEqual(row['url'], expected)
            self.assertContains(response, escape(expected))
        self.assertEqual(counts, [model.objects.count() for model in [Review, ReviewerCompetence, ReviewerCompetenceDecision, AuditEvent]])

    def test_declaration_link_prefills_only_permitted_variety_and_valid_discipline(self):
        row = self.rows(self.page())['clinical']
        response = self.client.get(row['url'])
        self.assertEqual(str(response.context['form']['variety'].value()), str(self.variety.pk))
        self.assertEqual(response.context['form']['discipline'].value(), 'clinical')
        invalid = self.client.get(reverse('qualification:competence'), {'variety':self.foreign_variety.code,'discipline':'invented'})
        self.assertFalse(invalid.context['form']['variety'].value())
        self.assertFalse(invalid.context['form']['discipline'].value())
        self.assertEqual(ReviewerCompetence.objects.filter(user=self.reviewer).count(), 0)

    def test_real_declaration_form_creates_pending_experience_without_verification(self):
        response = self.client.post(reverse('qualification:competence'), {
            'variety':self.variety.pk,'discipline':'clinical','professional_role':'Fictional role',
            'experience':'Fictional test experience only','credential_reference':'','active':'on','acknowledge':'on'})
        self.assertEqual(response.status_code, 302)
        declaration = ReviewerCompetence.objects.get(user=self.reviewer, discipline='clinical')
        row = self.rows(self.page())['clinical']
        self.assertEqual(row['state'], 'check_required')
        self.assertEqual(row['url'], reverse('qualification:competence_edit', args=[declaration.pk]))
        self.assertFalse(ReviewerCompetenceDecision.objects.filter(competence=declaration).exists())
        self.assertFalse(Review.objects.exists())

    def test_current_independent_check_does_not_approve_incomplete_content(self):
        declaration = self.declare(); self.verify(declaration)
        self.assertEqual(self.rows(self.page())['clinical']['state'], 'current')
        response = self.submit(approved=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertFalse(Review.objects.exists())
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.state, 'review')

    def test_modified_then_rejected_declaration_requires_a_new_independent_check(self):
        declaration = self.declare(); self.verify(declaration)
        declaration.refresh_from_db(); declaration.experience += ' changed'; declaration.save()
        self.assertEqual(self.rows(self.page())['clinical']['state'], 'check_required')
        self.verify(declaration, status='rejected')
        self.assertEqual(self.rows(self.page())['clinical']['state'], 'check_required')

    def test_revoked_supporting_evidence_is_rechecked_on_the_next_get(self):
        proof = evidence_fixture(self.variety,self.reviewer,'clinical_content')
        declaration = self.declare(evidence=proof); self.verify(declaration)
        self.assertEqual(self.rows(self.page())['clinical']['state'], 'current')
        proof.revoked=True; proof.revocation_reason='Fictional withdrawal'; proof.save()
        self.assertEqual(self.rows(self.page())['clinical']['state'], 'check_required')
        self.assertFalse(Review.objects.exists())

    def test_inactive_declaration_is_not_presented_as_current(self):
        declaration = self.declare(); self.verify(declaration)
        declaration.refresh_from_db(); declaration.active=False; declaration.save()
        self.assertEqual(self.rows(self.page())['clinical']['state'], 'inactive')

    def test_permission_withdrawal_removes_only_that_discipline_and_post_stays_forbidden(self):
        self.declare()
        grant = EditorialGrant.objects.get(user=self.reviewer,variety=self.variety)
        grant.clinical_review=False; grant.save()
        self.assertEqual(set(self.rows(self.page())), {'linguistic'})
        self.assertEqual(self.submit(kind='clinical').status_code, 403)
        grant.delete()
        self.assertEqual(self.page().status_code, 404)

    def test_status_and_links_expose_no_other_persons_declaration_or_documents(self):
        response = self.page()
        for private in ['OTHER-PRIVATE-ROLE','OTHER-PRIVATE-EXPERIENCE','OTHER-PRIVATE-CREDENTIAL',
            str(self.other_declaration.pk), str(self.other_document.pk)]:
            self.assertNotContains(response, private)
        own = self.declare()
        response = self.client.get(reverse('qualification:competence_edit', args=[own.pk]),
            {'variety':self.foreign_variety.code,'discipline':'linguistic'})
        self.assertEqual(str(response.context['form']['variety'].value()),str(self.variety.pk))
        self.assertEqual(response.context['form']['discipline'].value(),'clinical')
        self.assertEqual(self.client.get(reverse('qualification:competence_edit',args=[self.other_declaration.pk])).status_code,404)

    def test_editor_only_foreign_and_ordinary_read_boundaries_are_preserved(self):
        self.client.force_login(self.editor)
        response = self.page()
        self.assertEqual(response.context['reviewer_experience'], [])
        self.assertNotContains(response, 'reviewer-experience-title')
        self.assertEqual(reviewer_experience_guidance(self.editor,self.variety,['clinical']), [])
        for user in [self.foreign,self.ordinary]:
            self.client.force_login(user)
            self.assertEqual(self.page().status_code,404)
        self.client.logout()
        self.assertEqual(self.page().status_code,302)

    def test_draft_guidance_is_visible_but_review_submission_remains_unavailable(self):
        self.activity.state='draft'; self.activity.save()
        response = self.page()
        self.assertContains(response,'reviewer-experience-title')
        self.assertTrue(response.context['review_waiting_for_submission'])
        self.assertFalse(response.context['can_review'])
        self.assertEqual(self.submit().status_code,403)

    def test_request_changes_still_works_without_an_experience_check(self):
        response = self.submit()
        self.assertEqual(response.status_code,302)
        review = Review.objects.get(activity=self.activity,reviewer=self.reviewer)
        self.assertFalse(review.approved)
        self.assertFalse(ReviewerCompetence.objects.filter(user=self.reviewer).exists())

    def test_existing_complete_version_can_receive_a_real_service_checked_test_review(self):
        prepare_activity_fixture(self.activity,self.reviewer,self.other)
        Review.objects.filter(activity=self.activity,reviewer=self.reviewer).delete()
        self.assertEqual(self.rows(self.page())['clinical']['state'],'current')
        self.assertEqual(self.submit(approved=True).status_code,302)
        review = Review.objects.get(activity=self.activity,reviewer=self.reviewer)
        self.assertTrue(review.approved)
        self.assertEqual(review.content_digest,self.activity.fingerprint())

    def test_personal_guidance_is_localized_in_three_interfaces(self):
        expected={'en':'Your reviewer experience','fr':'Votre expérience de relecture','ar':'خبرتك في المراجعة'}
        for language,title in expected.items():
            with self.subTest(language=language),translation.override(language):
                response=self.page()
                self.assertContains(response,title)
                self.assertContains(response,'data-experience-state="missing"',count=2)
