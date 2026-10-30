"""Conservative Arabic reserves and exposure history, scoped to one variety.

These fixtures are unapproved simulations. Matching omitted vowel marks does
not establish that different Arabic lexemes or clinical productions are equal.
"""
import copy
import uuid
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from care.models import Program, ProgramItem, PracticeSession
from catalog.models import Activity, Variety
from followup.models import ClinicalGoal, ProbeExposure
from followup.tests import install_fixture, item as probe_item, HASHERS
from followup.validation import word_key, reserve_word_key
from followup.services import (create_definition, create_goal, start_administration, record_exposure,
                               professional_report, reserved_words_for)
from core.forms import ProgramForm
from core.reserves import activity_is_reserved
from core.services import create_program, record_practice


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False, PASSWORD_HASHERS=HASHERS)
class ArabicReserveTests(TestCase):
    def setUp(self):
        install_fixture(self)
        self.msa = Variety.objects.create(code='ar-msa-pilot', language='ar', label='Synthetic standard Arabic')
        self.darja = Variety.objects.create(code='ar-dz-pilot', language='ar', label='Synthetic local Darja')
        self.child.varieties.add(self.msa, self.darja)
        self.program = Program.objects.create(organization=self.organization, child=self.child, variety=self.msa,
                                             created_by=self.pro, title='Synthetic MSA programme')
        self.activities = [self.activity(self.msa, word) for word in ['بَاب', 'بـاب']]
        self.items = [ProgramItem.objects.create(program=self.program, activity=a, position=i)
                      for i, a in enumerate(self.activities, 1)]

    def activity(self, variety, word):
        return Activity.objects.create(
            variety=variety, series=uuid.uuid4(), title='Synthetic ' + variety.code + ' ' + word,
            contrast='Unapproved illustrative words', kind='vocabulary', word_a=word, word_b='نار',
            image_a='editorial/house.svg', image_b='editorial/fire.svg',
            instructions={language: 'Synthetic fictional instruction' for language in ['fr', 'en', 'ar']},
            rights='Synthetic demo of original local illustrations', population='Fictional profiles only',
            is_demo=True, state='published')

    def reserve(self):
        return ClinicalGoal.objects.create(
            organization=self.organization, child=self.child, author=self.pro, variety=self.msa,
            target_phoneme='b', target_position='initial', target_scope={'position': 'initial', 'context': 'isolated_word'}, rationale='Synthetic reserve test',
            expected_realization='/b/', functional_goal='Synthetic observation', reserved_words=['باب'])

    def ticket(self, item):
        return {'user': self.family.pk, 'item': str(item.pk), 'key': str(uuid.uuid4()), 'target': 'a'}

    def payload(self):
        return {'answer': 'a', 'completion': 'completed', 'parent_report': 'easy', 'comment': ''}

    def program_data(self, activity):
        return {'title': 'Synthetic assignment', 'variety': activity.variety,
                'activities': [activity], 'guidance': '', 'schedule': ''}

    def prepare_observation(self):
        row = probe_item(0, reserved=True)
        row.update(word='باب', ipa='/b/')
        probe = create_definition(self.pro, {
            'variety': self.msa, 'title': 'Synthetic MSA observation',
            'protocol': 'Synthetic unapproved protocol', 'task': 'picture_naming',
            'target_phoneme': 'b', 'target_position': 'initial', 'target_scope': {'position': 'initial', 'context': 'isolated_word'}, 'items': [row], 'is_demo': True})
        goal = create_goal(self.pro, self.child, {
            'variety': self.msa, 'target_phoneme': 'b', 'target_position': 'initial', 'target_scope': {'position': 'initial', 'context': 'isolated_word'},
            'rationale': 'Synthetic observation', 'expected_realization': '/b/',
            'functional_goal': 'Synthetic follow-up', 'probe_definition': probe})
        admin = start_administration(self.pro, goal, probe,
            {'attempt_rule': 'First predetermined fictional attempt', 'task': 'naming'},
            {row['id']: {'familiar': False, 'note': 'Synthetic familiarity only'}})
        return probe, goal, admin

    def test_vowels_and_tatweel_cannot_bypass_family_catalog_assignment_or_submission(self):
        goal = self.reserve()
        self.assertNotEqual(word_key('بَاب'), word_key('باب'))
        self.assertNotEqual(word_key('بـاب'), word_key('باب'))
        before_reserve = copy.deepcopy(goal.reserved_words)
        self.client.force_login(self.family)
        library = self.client.get(reverse('library'), {'content_language': 'ar', 'variety': self.msa.code})
        shown = set(library.context['page'].paginator.object_list.values_list('pk', flat=True))
        for item in self.items:
            self.assertTrue(activity_is_reserved(self.child, item.activity))
            self.assertNotIn(item.activity_id, shown)
            self.assertEqual(self.client.get(reverse('activity_detail', args=[item.activity_id])).status_code, 404)
            self.assertEqual(self.client.get(reverse('practice', args=[item.pk])).status_code, 410)
            self.assertFalse(ProgramForm(child=self.child).fields['activities'].queryset.filter(pk=item.activity_id).exists())
            with self.assertRaises(ValidationError):
                create_program(self.pro, self.child, self.program_data(item.activity))
            with self.assertRaises(ValidationError):
                record_practice(self.family, item, self.payload(), self.ticket(item))
        self.assertEqual(PracticeSession.objects.count(), 0)
        self.assertEqual(ProbeExposure.objects.count(), 0)
        goal.refresh_from_db()
        self.assertEqual(goal.reserved_words, before_reserve)
        self.assertEqual(reserved_words_for(self.child, self.msa), {'باب'})
        # No Arabic-specific comparison is applied to the French variety.
        self.assertNotEqual(reserve_word_key('بَاب', self.variety), reserve_word_key('باب', self.variety))

    def test_msa_reservation_never_blocks_a_separate_darja_programme_or_rewrites_exposure(self):
        self.reserve()
        activity = self.activity(self.darja, 'بَاب')
        self.assertFalse(activity_is_reserved(self.child, activity))
        assigned = create_program(self.pro, self.child, self.program_data(activity))
        item = assigned.items.get()
        self.client.force_login(self.family)
        library = self.client.get(reverse('library'), {'content_language': 'ar', 'variety': self.darja.code})
        self.assertIn(activity.pk, library.context['page'].paginator.object_list.values_list('pk', flat=True))
        report = record_practice(self.family, item, self.payload(), self.ticket(item))
        self.assertTrue(report.correct)
        exposure = ProbeExposure.objects.get(source_session=report, word='بَاب')
        self.assertEqual(exposure.variety_id, self.darja.pk)
        self.assertEqual(exposure.normalized_word, word_key('بَاب'))
        self.assertNotEqual(exposure.normalized_word, word_key('باب'))

    def test_previous_declared_vocalized_training_is_seen_without_rewriting_event_or_snapshot(self):
        event = record_exposure(self.pro, self.child, self.msa, 'بَاب', 'trained', 'Synthetic earlier declaration')
        before = (event.word, event.normalized_word, event.occurred_at)
        _, _, admin = self.prepare_observation()
        self.assertEqual(admin.snapshot['items'][0]['exposure_at_start'], 'trained')
        self.assertEqual(admin.snapshot['items'][0]['word'], 'باب')
        event.refresh_from_db()
        self.assertEqual((event.word, event.normalized_word, event.occurred_at), before)

    def test_pre_hook_practice_history_with_marks_is_seen_as_previous_training(self):
        session = record_practice(self.family, self.items[1], self.payload(), self.ticket(self.items[1]))
        before = (session.payload_digest, session.answer, session.correct)
        # Simulate a preserved session predating the append-only exposure hook.
        ProbeExposure.objects.filter(source_session=session).delete()
        _, _, admin = self.prepare_observation()
        self.assertEqual(admin.snapshot['items'][0]['exposure_at_start'], 'trained')
        session.refresh_from_db()
        self.assertEqual((session.payload_digest, session.answer, session.correct), before)

    def test_later_marked_training_is_reported_only_in_the_same_variety_and_never_rewrites_snapshot(self):
        _, _, admin = self.prepare_observation()
        original_snapshot = copy.deepcopy(admin.snapshot)
        self.assertEqual(original_snapshot['items'][0]['exposure_at_start'], 'uncertain')
        record_exposure(self.pro, self.child, self.darja, 'بَاب', 'trained', 'Synthetic different-variety declaration')
        self.assertEqual(professional_report(self.pro, admin)['contamination'], [])
        first = record_exposure(self.pro, self.child, self.msa, 'بَاب', 'trained', 'Synthetic later vocalized declaration')
        second = record_exposure(self.pro, self.child, self.msa, 'بـاب', 'trained', 'Synthetic later tatweel declaration')
        report = professional_report(self.pro, admin)
        self.assertEqual(len(report['contamination']), 1)
        self.assertEqual(report['contamination'][0]['item_key'], 'fixture-0')
        self.assertEqual(report['contamination'][0]['at'], first.occurred_at.isoformat())
        self.assertEqual(report['contamination'][0]['original_exposure'], 'uncertain')
        self.assertEqual(report['snapshot'], original_snapshot)
        admin.refresh_from_db()
        self.assertEqual(admin.snapshot, original_snapshot)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.normalized_word, word_key('بَاب'))
        self.assertEqual(second.normalized_word, word_key('بـاب'))
