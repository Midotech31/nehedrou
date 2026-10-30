"""Regression checks at the boundary of family practice and private probes."""
import uuid
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation
from care.models import PracticeSession
from followup.models import ClinicalGoal, ProbeExposure
from . import tests as original_tests
from .forms import PracticeForm, ProgramForm
from .services import record_practice, create_program
from .complete_views import retention_anchor


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False)
class FollowupIntegrationTests(TestCase):
    setUpTestData = classmethod(original_tests.WorkflowTests.setUpTestData.__func__)
    ticket = original_tests.WorkflowTests.ticket
    payload = original_tests.WorkflowTests.payload

    def setUp(self):
        translation.activate('fr')

    def reserve(self):
        return ClinicalGoal.objects.create(
            organization=self.org, child=self.child, author=self.pro,
            variety=self.program.variety, target_phoneme='/p/', target_position='initial', target_scope={'position': 'initial', 'context': 'isolated_word'},
            rationale='Fictional regression fixture', expected_realization='Fictional target',
            functional_goal='Fictional objective', reserved_words=[self.item.activity.word_a.casefold()])

    def test_reserved_word_is_never_shown_by_family_structured_routes(self):
        self.reserve()
        self.client.force_login(self.family)
        self.assertEqual(self.client.get(reverse('practice', args=[self.item.pk])).status_code, 410)
        self.assertEqual(self.client.get(reverse('activity_detail', args=[self.item.activity_id])).status_code, 404)
        for route, args in [('library', []), ('program_detail', [self.program.pk]), ('print_program', [self.program.pk])]:
            response = self.client.get(reverse(route, args=args))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, self.item.activity.title)
        exported = self.client.get(reverse('export_child', args=[self.child.pk])).json()
        self.assertEqual(exported['programs'][0]['items'], [])
        self.client.force_login(self.pro)
        self.assertContains(self.client.get(reverse('program_detail', args=[self.program.pk])), self.item.activity.title)

    def test_reserve_rejects_assignment_practice_and_new_run(self):
        from .practice_runs import start_run
        self.reserve()
        data = dict(title='Fictional', variety=self.program.variety, activities=[self.item.activity], goal='', guidance='', schedule='')
        with self.assertRaises(ValidationError):
            create_program(self.pro, self.child, data)
        with self.assertRaises(ValidationError):
            record_practice(self.family, self.item, self.payload(), self.ticket())
        with self.assertRaises(ValidationError):
            start_run(self.family, self.program)
        self.assertFalse(ProgramForm(child=self.child).fields['activities'].queryset.filter(pk=self.item.activity_id).exists())
        self.assertEqual(PracticeSession.objects.count(), 0)

    def test_professional_role_on_another_child_does_not_bypass_family_reserve(self):
        from care.models import Child
        from .models import Membership
        self.reserve()
        Membership.objects.create(user=self.family, organization=self.org, role='clinician')
        own_child = Child.objects.create(organization=self.org, responsible=self.family, code='Other fictional child', age_years=5)
        own_child.varieties.add(self.program.variety)
        self.client.force_login(self.family)
        self.assertEqual(self.client.get(reverse('activity_detail', args=[self.item.activity_id])).status_code, 404)
        self.assertNotContains(self.client.get(reverse('library')), self.item.activity.title)

    def test_exposure_is_an_idempotent_declaration_not_a_correct_production(self):
        ticket = self.ticket()
        payload = self.payload(answer='b', support_used='model')
        report = record_practice(self.family, self.item, payload, ticket)
        self.assertFalse(report.correct)
        self.assertEqual(report.support_used, 'model')
        self.assertEqual(set(ProbeExposure.objects.values_list('status', flat=True)), {'trained'})
        self.assertEqual(ProbeExposure.objects.count(), 2)
        self.assertEqual(record_practice(self.family, self.item, payload, ticket).pk, report.pk)
        self.assertEqual(ProbeExposure.objects.count(), 2)

    def test_stopped_exposure_and_explicit_reason_do_not_create_an_answer(self):
        report = record_practice(self.family, self.item, self.payload(completion='stopped', answer='', stop_reason='fatigue'), self.ticket())
        self.assertIsNone(report.correct)
        self.assertEqual(report.stop_reason, 'fatigue')
        self.assertEqual(set(ProbeExposure.objects.values_list('status', flat=True)), {'uncertain'})

    def test_old_ticket_payload_remains_idempotent_after_new_optional_fields(self):
        ticket = self.ticket()
        old = self.payload()
        report = record_practice(self.family, self.item, old, ticket)
        new = dict(old, support_used='', stop_reason='')
        self.assertEqual(record_practice(self.family, self.item, new, ticket).pk, report.pk)
        with self.assertRaises(ValidationError):
            record_practice(self.family, self.item, dict(new, support_used='gesture'), ticket)

    def test_optional_stopping_reason_is_valid_only_for_stopped_practice(self):
        data = dict(self.payload(), ticket='fixture', stop_reason='fatigue')
        form = PracticeForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn('stop_reason', form.errors)
        form = PracticeForm(dict(data, completion='stopped'))
        self.assertTrue(form.is_valid(), form.errors)

    def test_reserving_words_preserves_existing_report_and_professional_access(self):
        report = record_practice(self.family, self.item, self.payload(), self.ticket())
        self.reserve()
        self.client.force_login(self.family)
        self.assertEqual(self.client.get(reverse('report_detail', args=[report.pk])).status_code, 403)
        self.client.force_login(self.pro)
        self.assertEqual(self.client.get(reverse('report_detail', args=[report.pk])).status_code, 200)
        self.assertTrue(PracticeSession.objects.filter(pk=report.pk).exists())

    def test_followup_event_extends_the_practice_retention_anchor(self):
        when = timezone.now()
        ProbeExposure.objects.create(child=self.child, variety=self.program.variety, word='fixture', normalized_word='fixture', status='uncertain', author=self.pro, note='Fictional', occurred_at=when)
        self.assertGreaterEqual(retention_anchor(self.child), when)
