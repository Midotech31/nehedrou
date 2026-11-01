"""Deterministic stale-form interleavings using fictional reviewer declarations."""
from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.models import EditorialGrant, Variety
from core.models import AuditEvent, User
from .forms import CompetenceForm
from .models import ReviewerCompetence, ReviewerCompetenceDecision
from .services import has_competence, record_competence_decision, save_competence_declaration


@override_settings(DEMO_MODE=False, MFA_REQUIRED=False, LANGUAGE_CODE='en')
class CompetenceDecisionSnapshotTests(TestCase):
    def setUp(self):
        self.variety = Variety.objects.create(code='fr-race-fixture', language='fr', label='Fictional test variety')
        self.owner = User.objects.create_user(username='fictional-reviewer', email='reviewer@fictional.example')
        self.publisher = User.objects.create_user(username='fictional-verifier', email='verifier@fictional.example')
        EditorialGrant.objects.create(user=self.owner, variety=self.variety, clinical_review=True)
        EditorialGrant.objects.create(user=self.publisher, variety=self.variety, publish=True)
        self.declaration = ReviewerCompetence.objects.create(
            user=self.owner, variety=self.variety, discipline='clinical',
            professional_role='Fictional professional role', experience='Fictional experience for regression tests only')
        self.path = reverse('qualification:competence_verification', args=[self.declaration.pk])

    def decision(self, status='verified', expected_digest=None):
        return record_competence_decision(
            self.publisher, self.declaration.pk, status,
            'Fictional independent documentary check; not a real qualification.', date(2026, 1, 1),
            expected_digest=expected_digest or self.declaration.fingerprint())

    def payload(self, digest):
        return {'expected_digest': digest, 'status': 'verified', 'checked_on': '2026-01-01',
                'basis': 'Fictional independent documentary check; not a real qualification.'}

    def test_stale_snapshot_is_refused_without_a_decision_pointer_or_audit(self):
        previous = self.decision()
        old_digest = self.declaration.fingerprint()
        self.declaration = save_competence_declaration(self.owner, {
            'experience': 'Changed fictional experience after the verifier opened the form'}, self.declaration.pk)
        counts = (ReviewerCompetenceDecision.objects.count(), AuditEvent.objects.count())

        with self.assertRaisesMessage(ValidationError, 'This reviewer declaration changed.'):
            self.decision(expected_digest=old_digest)

        self.declaration.refresh_from_db()
        self.assertEqual(self.declaration.current_decision_id, previous.pk)
        self.assertEqual((ReviewerCompetenceDecision.objects.count(), AuditEvent.objects.count()), counts)
        self.assertFalse(has_competence(self.owner, self.variety, 'clinical'))

    def test_stale_get_cannot_approve_unseen_content_and_reload_can_record_a_legitimate_decision(self):
        self.client.force_login(self.publisher)
        opened = self.client.get(self.path)
        old_digest = opened.context['form']['expected_digest'].value()
        self.assertEqual(old_digest, self.declaration.fingerprint())
        self.declaration.experience = 'Changed fictional experience after the verifier read the declaration'
        self.declaration.save()
        counts = (ReviewerCompetenceDecision.objects.count(), AuditEvent.objects.count())

        stale = self.client.post(self.path, self.payload(old_digest))
        self.assertEqual(stale.status_code, 200)
        self.assertTrue(stale.context['reload_declaration'])
        self.assertEqual(stale.context['form']['expected_digest'].value(), old_digest)
        self.assertContains(stale, 'Reload current declaration')
        self.assertEqual((ReviewerCompetenceDecision.objects.count(), AuditEvent.objects.count()), counts)

        reloaded = self.client.get(self.path)
        current_digest = reloaded.context['form']['expected_digest'].value()
        self.assertEqual(current_digest, self.declaration.fingerprint())
        self.assertNotEqual(current_digest, old_digest)
        accepted = self.client.post(self.path, self.payload(current_digest))
        self.assertEqual(accepted.status_code, 302)
        self.declaration.refresh_from_db()
        self.assertEqual(self.declaration.current_decision.snapshot_digest, current_digest)
        self.assertEqual(ReviewerCompetenceDecision.objects.count(), counts[0] + 1)
        self.assertEqual(AuditEvent.objects.filter(action='qualification.competence_verified').count(), 1)
        self.assertTrue(has_competence(self.owner, self.variety, 'clinical'))

    def test_missing_snapshot_is_required_and_records_nothing(self):
        self.client.force_login(self.publisher)
        payload = self.payload(self.declaration.fingerprint())
        del payload['expected_digest']
        counts = (ReviewerCompetenceDecision.objects.count(), AuditEvent.objects.count())
        response = self.client.post(self.path, payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn('expected_digest', response.context['form'].errors)
        self.assertEqual((ReviewerCompetenceDecision.objects.count(), AuditEvent.objects.count()), counts)

    def test_stale_owner_form_preserves_a_later_rejection_and_ignores_non_declarative_fields(self):
        previous = self.decision()
        stale = ReviewerCompetence.objects.get(pk=self.declaration.pk)
        form = CompetenceForm({
            'variety': str(self.variety.pk), 'discipline': stale.discipline,
            'professional_role': stale.professional_role, 'experience': stale.experience,
            'credential_reference': '', 'evidence': '', 'active': 'on', 'acknowledge': 'on'}, instance=stale)
        self.assertTrue(form.is_valid(), form.errors)
        rejection = self.decision(status='rejected')
        self.assertEqual(stale.current_decision_id, previous.pk)

        saved = save_competence_declaration(self.owner, {
            **form.cleaned_data, 'current_decision': previous, 'user': self.publisher}, stale.pk)

        saved.refresh_from_db()
        self.assertEqual(saved.user_id, self.owner.pk)
        self.assertEqual(saved.current_decision_id, rejection.pk)
        self.assertEqual(saved.current_decision.status, 'rejected')
        self.assertEqual(ReviewerCompetenceDecision.objects.count(), 2)
        self.assertFalse(has_competence(self.owner, self.variety, 'clinical'))

    def test_declaration_service_requires_owner_and_current_variety_scope(self):
        with self.assertRaises(PermissionDenied):
            save_competence_declaration(self.publisher, {'experience': 'Fictional attempt'}, self.declaration.pk)
        EditorialGrant.objects.filter(user=self.owner).delete()
        counts = (ReviewerCompetenceDecision.objects.count(), AuditEvent.objects.count())
        with self.assertRaises(PermissionDenied):
            save_competence_declaration(self.owner, {'experience': 'Fictional attempt'}, self.declaration.pk)
        self.declaration.refresh_from_db()
        self.assertEqual(self.declaration.experience, 'Fictional experience for regression tests only')
        self.assertEqual((ReviewerCompetenceDecision.objects.count(), AuditEvent.objects.count()), counts)
