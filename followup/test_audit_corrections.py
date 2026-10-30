"""October audit regressions with synthetic data and no clinical approvals."""
import copy
import uuid

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from care.models import FamilyLink
from core.models import Membership
from .models import ClinicalGoal, ProbeAdministration
from .services import (create_goal, start_administration, save_rating, finalize_administration, professional_report,
                       record_exposure, create_coaching, record_home_practice, share_summary)
from .tests import install_fixture, definition, goal, start, rating, HASHERS


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False, PASSWORD_HASHERS=HASHERS)
class TargetContextRegressionTests(TestCase):
    def setUp(self):
        install_fixture(self)
        self.probe = definition(self)

    def independent_goal(self, position='initial', context='isolated_word'):
        return create_goal(self.pro, self.child, {'variety': self.variety, 'target_phoneme': '/p/',
            'target_position': position, 'target_scope': {'position': position, 'context': context},
            'rationale': 'Synthetic audit case', 'expected_realization': '/p/', 'functional_goal': 'Synthetic observation'})

    def test_final_goal_rejects_initial_probe_in_service_model_and_link(self):
        objective = self.independent_goal('final')
        with self.assertRaises(ValidationError):
            start(self, self.probe, objective)
        with self.assertRaises(ValidationError):
            ProbeAdministration.objects.create(organization=self.organization, child=self.child, goal=objective,
                definition=self.probe, professional=self.pro, payload_digest='a' * 64,
                conditions={'attempt_rule': 'first'}, familiarity={}, snapshot={})
        objective.probe_definition = self.probe
        with self.assertRaises(ValidationError):
            objective.save()
        self.assertEqual(ProbeAdministration.objects.count(), 0)

    def test_same_position_different_structured_context_is_rejected(self):
        objective = self.independent_goal(context='carrier_phrase')
        with self.assertRaises(ValidationError):
            start(self, self.probe, objective)
        objective.target_scope = {'position': 'initial', 'context': 'isolated_word'}
        objective.save()
        self.assertEqual(start(self, self.probe, objective).snapshot['target_scope'], objective.target_scope)

    def test_alternate_context_requires_name_reason_and_never_becomes_comparable(self):
        objective = self.independent_goal('final')
        data = {'conditions': {'attempt_rule': 'first'}, 'familiarity': {i['id']: {'familiar': False} for i in self.probe.items},
                'observation_scope': 'alternate_context'}
        with self.assertRaises(ValidationError):
            start_administration(self.pro, objective, self.probe, **data)
        with self.assertRaises(ValidationError):
            start_administration(self.pro, objective, self.probe, alternate_context_label='Initial context', **data)
        data.update(alternate_context_label='Initial /p/ separate observation',
            alternate_context_reason='Describe an explicitly different initial position; no final-position equivalence claimed.')
        first = start_administration(self.pro, objective, self.probe, **data)
        snapshot = copy.deepcopy(first.snapshot)
        for item in self.probe.items:
            save_rating(self.pro, first, item['id'], rating())
        finalize_administration(self.pro, first)
        second = start_administration(self.pro, objective, self.probe, **data)
        self.assertFalse(professional_report(self.pro, second)['comparable'])
        self.assertEqual(second.snapshot['alternate_context_label'], data['alternate_context_label'])
        first.refresh_from_db()
        self.assertEqual(first.snapshot, snapshot)
        first.alternate_context_reason = 'Rewritten later'
        with self.assertRaises(ValidationError):
            first.save()
        other = definition(self)
        other.target_phoneme = 'b'
        other.save()
        with self.assertRaises(ValidationError):
            start_administration(self.pro, objective, other, **data)

    def test_legacy_context_is_not_inferred_or_compared_and_old_snapshot_is_preserved(self):
        objective = goal(self, self.probe)
        original = start(self, self.probe, objective)
        snapshot = copy.deepcopy(original.snapshot)
        snapshot.pop('target_scope')
        snapshot['goal'].pop('target_scope')
        snapshot['schema_version'] = 1
        ProbeAdministration.objects.filter(pk=original.pk).update(snapshot=snapshot)
        ClinicalGoal.objects.filter(pk=objective.pk).update(target_scope={})
        objective.refresh_from_db()
        with self.assertRaises(ValidationError):
            start(self, self.probe, objective)
        original.refresh_from_db()
        self.assertEqual(professional_report(self.pro, original)['snapshot'], snapshot)
        self.assertFalse(professional_report(self.pro, original)['comparable'])
        objective.active = False
        objective.save(update_fields=['active'])
        self.assertEqual(ClinicalGoal.objects.get(pk=objective.pk).target_scope, {})

    def test_start_choices_filter_context_and_untrusted_post_cannot_bypass_it(self):
        objective = self.independent_goal('final')
        self.client.force_login(self.pro)
        url = reverse('followup:administration_start', args=[objective.pk])
        response = self.client.get(url)
        self.assertNotContains(response, self.probe.title)
        self.assertEqual(self.client.get(url, {'definition': self.probe.pk}).status_code, 404)
        alternate = self.client.get(url, {'definition': self.probe.pk, 'scope': 'alternate_context'})
        self.assertContains(alternate, self.probe.title)
        response = self.client.post(url, {'definition': str(self.probe.pk), 'observation_scope': 'goal',
            'key': str(uuid.uuid4()), 'task': 'naming', 'instructions': 'Synthetic', 'attempt_rule': 'first'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ProbeAdministration.objects.count(), 0)


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False, PASSWORD_HASHERS=HASHERS)
class DossierExportRegressionTests(TestCase):
    def setUp(self):
        install_fixture(self)
        self.probe = definition(self)
        self.goal = goal(self, self.probe)
        self.admin = start(self, self.probe, self.goal)
        for row in self.probe.items:
            save_rating(self.pro, self.admin, row['id'], rating())
        finalize_administration(self.pro, self.admin)
        save_rating(self.pro, self.admin, 'fixture-0', rating('TARGET_INCORRECT'), reason='Synthetic correction retained')
        record_exposure(self.pro, self.child, self.variety, 'mot-1', 'trained', 'Private exposure source')
        self.coaching = create_coaching(self.pro, self.child, {'variety': self.variety, 'instruction_language': 'fr',
            'instructions': 'Shared instruction', 'example': 'A shared example', 'clinician_note': 'Private coaching note'})
        record_home_practice(self.family, self.coaching, {'participation': 'completed', 'difficulty': 'easy', 'comment': 'Family return'})
        share_summary(self.pro, self.admin, 'An expressly shared summary')
        self.url = reverse('export_child', args=[self.child.pk])

    def test_professional_export_is_complete_without_any_family_program(self):
        self.client.force_login(self.pro)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual((body['schema_version'], body['export_scope'], body['programs']), (3, 'professional', []))
        data = body['followup']
        self.assertEqual(data['goals'][0]['id'], str(self.goal.pk))
        self.assertEqual(data['protocols'][0]['version'], self.probe.version)
        admin = data['observations'][0]
        self.assertEqual(admin['snapshot'], self.admin.snapshot)
        self.assertEqual(admin['conditions'], self.admin.conditions)
        self.assertEqual(admin['familiarity'], self.admin.familiarity)
        rated = next(row for row in admin['ratings'] if row['item_key'] == 'fixture-0')
        self.assertEqual(rated['code'], 'TARGET_ACCEPTABLE')
        self.assertEqual(rated['current_data']['code'], 'TARGET_INCORRECT')
        self.assertEqual(rated['revisions'][0]['reason'], 'Synthetic correction retained')
        self.assertEqual(data['exposures'][0]['note'], 'Private exposure source')
        self.assertEqual(data['coaching'][0]['clinician_note'], 'Private coaching note')
        self.assertEqual(data['home_practice_feedback'][0]['comment'], 'Family return')
        self.assertNotIn('idempotency_key', admin)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertTrue(body['exclusions'])

    def test_family_export_has_only_shared_followup_and_redacts_reserved_text(self):
        share_summary(self.pro, self.admin, 'A shared summary accidentally includes mot-1.')
        self.client.force_login(self.family)
        response = self.client.get(self.url)
        data = response.json()
        self.assertEqual(data['export_scope'], 'family')
        text = response.content.decode()
        for secret in ['Private coaching note', 'Private exposure source', 'Synthetic correction retained', 'mot-1']:
            self.assertNotIn(secret, text)
        for private_section in ['goals', 'protocols', 'observations', 'exposures']:
            self.assertNotIn(private_section, data['followup'])
        self.assertEqual(data['followup']['coaching'][0]['instructions'], 'Shared instruction')
        self.assertEqual(data['followup']['shared_observations'][0]['shared_text'], '[withheld: reserved content]')
        self.assertGreater(data['exclusions'][-1]['text_fields'], 0)
        share_summary(self.pro, self.admin, '')
        self.assertEqual(self.client.get(self.url).json()['followup']['shared_observations'], [])

    def test_revocation_and_foreign_accounts_block_export(self):
        self.client.force_login(self.foreign)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.client.force_login(self.family)
        FamilyLink.objects.filter(child=self.child, user=self.family).update(active=False)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.client.force_login(self.pro)
        Membership.objects.filter(user=self.pro, organization=self.organization).update(active=False)
        self.assertEqual(self.client.get(self.url).status_code, 404)


    def test_handover_exports_full_history_to_new_responsible_professional(self):
        from core.models import User
        from core.services import transfer_child
        successor = User.objects.create_user(username='dossier-successor', email='dossier-successor@example.test')
        Membership.objects.create(user=successor, organization=self.organization, role='clinician')
        transfer_child(self.pro, self.child, successor)
        self.client.force_login(self.pro)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.client.force_login(successor)
        exported = self.client.get(self.url).json()['followup']
        self.assertEqual(exported['goals'][0]['author_id'], self.pro.pk)
        self.assertEqual(exported['observations'][0]['professional_id'], self.pro.pk)
        self.assertEqual(exported['responsibility_transfers'][0]['previous_clinician_id'], self.pro.pk)
        self.assertEqual(exported['responsibility_transfers'][0]['new_clinician_id'], successor.pk)
