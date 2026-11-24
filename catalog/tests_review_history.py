"""Historical labels describe decisions; they never grant clinical approval."""
import copy
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from core.models import AuditEvent, User
from followup.models import ProbeDefinition, ProbeReview
from followup.services import transition_definition
from followup.tests import item
from qualification.models import LexicalPack, PackReview
from qualification.services import change_pack_state, pack_readiness_reasons
from .models import Activity, EditorialGrant, Review, Variety
from .review_history import decision_history
from .services import transition


class DecisionHistoryTests(SimpleTestCase):
    def decision(self, number, *, kind='clinical', digest='current', approved=False, seconds=0):
        # Inert historical values only: no persisted review or invented human.
        return SimpleNamespace(pk=uuid.UUID(int=number), kind=kind,
            content_digest=digest, approved=approved,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds))

    def test_newer_negative_decision_supersedes_an_older_positive_one_without_mutation(self):
        older = self.decision(1, approved=True)
        newer = self.decision(2, approved=False, seconds=1)
        before = copy.deepcopy([vars(older), vars(newer)])
        rows = decision_history([older, newer], 'current')
        self.assertEqual([(row['review'].pk.int, row['status']) for row in rows],
            [(2, 'latest_for_content'), (1, 'superseded')])
        self.assertFalse(rows[0]['review'].approved)
        self.assertTrue(rows[1]['review'].approved)
        self.assertEqual([vars(older), vars(newer)], before)

    def test_newer_other_content_does_not_supersede_the_current_fingerprint(self):
        current = self.decision(1)
        changed = self.decision(2, digest='another-content', approved=True, seconds=1)
        rows = decision_history([current, changed], 'current')
        self.assertEqual([row['status'] for row in rows],
            ['other_content', 'latest_for_content'])

    def test_each_discipline_has_its_own_latest_decision(self):
        rows = decision_history([self.decision(1), self.decision(2, kind='linguistic')], 'current')
        self.assertEqual([row['status'] for row in rows], ['latest_for_content'] * 2)

    def test_timestamp_then_primary_key_break_ties_like_the_publication_gates(self):
        rows = decision_history([self.decision(3), self.decision(1, seconds=1), self.decision(4)], 'current')
        self.assertEqual([row['review'].pk.int for row in rows], [1, 4, 3])
        self.assertEqual([row['status'] for row in rows],
            ['latest_for_content', 'superseded', 'superseded'])

    def test_legacy_empty_digest_is_other_content_and_empty_history_stays_empty(self):
        self.assertEqual(decision_history([], 'current'), [])
        self.assertEqual(decision_history([self.decision(1, digest='')], 'current')[0]['status'],
            'other_content')

    def test_status_labels_are_translated_without_an_approval_claim(self):
        expected = {
            'en': 'Latest decision for this content fingerprint',
            'fr': 'Dernière décision pour cette empreinte de contenu',
            'ar': 'آخر قرار لبصمة هذا المحتوى',
        }
        for language, label in expected.items():
            with self.subTest(language=language), translation.override(language):
                row = decision_history([self.decision(1)], 'current')[0]
                self.assertEqual(str(row['label']), label)


@override_settings(DEMO_MODE=False, MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DecisionHistoryPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.variety = Variety.objects.create(code='fr-history-fixture', language='fr',
            label='Synthetic editorial history only')
        cls.editor = User.objects.create_user('history-editor', 'editor@history.example.test')
        cls.clinical = User.objects.create_user('history-clinical', 'clinical@history.example.test')
        cls.linguistic = User.objects.create_user('history-linguistic', 'linguistic@history.example.test')
        EditorialGrant.objects.create(user=cls.editor, variety=cls.variety, edit=True, publish=True)
        EditorialGrant.objects.create(user=cls.clinical, variety=cls.variety, clinical_review=True)
        EditorialGrant.objects.create(user=cls.linguistic, variety=cls.variety, linguistic_review=True)
        cls.foreign = User.objects.create_user('history-foreign', 'foreign@history.example.test')
        foreign_variety = Variety.objects.create(code='fr-history-other', language='fr', label='Other fixture')
        EditorialGrant.objects.create(user=cls.foreign, variety=foreign_variety, edit=True)
        cls.activity = Activity.objects.create(variety=cls.variety, series=uuid.uuid4(),
            title='Unapproved history activity', contrast='p/b', word_a='pa', word_b='ba',
            instructions={'fr': 'Fictif', 'en': 'Fictional', 'ar': 'مثال وهمي'},
            is_demo=False, state='review')
        cls.pack = LexicalPack.objects.create(series=uuid.uuid4(), variety=cls.variety,
            created_by=cls.editor, title='Unapproved history pack', region='Fictional region',
            scope='Synthetic scope', population='Fictional population',
            indications='Synthetic design', limits='No clinical approval', state='review')
        cls.definition = ProbeDefinition.objects.create(variety=cls.variety, authored_by=cls.editor,
            title='Unapproved history protocol', protocol='Synthetic original protocol',
            task='picture_naming', target_phoneme='p', target_position='initial',
            target_scope={'position': 'initial', 'context': 'isolated_word'},
            items=[item(0)], is_demo=False, state='review')

    def contents(self):
        return [
            ('activity', self.activity, 'editorial_detail'),
            ('pack', self.pack, 'qualification:pack_detail'),
            ('protocol', self.definition, 'followup:definition_detail'),
        ]

    def record(self, name, obj, kind='clinical', note='Synthetic changes requested'):
        actor = self.clinical if kind == 'clinical' else self.linguistic
        # All persisted decisions request changes. The tests create no approval,
        # competence verification, evidence, publication or availability decision.
        values = {'kind': kind, 'approved': False, 'note': note}
        if name == 'activity':
            return Review.objects.create(activity=obj, reviewer=actor, **values)
        if name == 'pack':
            return PackReview.objects.create(pack=obj, reviewer=actor, **values)
        return ProbeReview.objects.create(definition=obj, author=actor,
            competence='Synthetic test declaration, not a verified qualification', **values)

    def snapshot(self):
        return (
            list(Activity.objects.order_by('pk').values()),
            list(LexicalPack.objects.order_by('pk').values()),
            list(ProbeDefinition.objects.order_by('pk').values()),
            list(Review.objects.order_by('pk').values()),
            list(PackReview.objects.order_by('pk').values()),
            list(ProbeReview.objects.order_by('pk').values()),
            AuditEvent.objects.count(),
        )

    def page(self, route, obj, language='en'):
        with translation.override(language):
            return self.client.get(reverse(route, args=[obj.pk]))

    def test_no_review_means_no_current_decision_or_write_for_any_content_type(self):
        self.client.force_login(self.editor)
        for name, obj, route in self.contents():
            with self.subTest(content=name):
                before = self.snapshot()
                response = self.page(route, obj)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['review_history'], [])
                self.assertNotContains(response, 'data-review-status=')
                self.assertEqual(self.snapshot(), before)

    def test_latest_and_superseded_decisions_render_for_each_discipline_in_all_languages(self):
        self.client.force_login(self.editor)
        for name, obj, route in self.contents():
            older = self.record(name, obj, note='Older synthetic clinical decision')
            latest = self.record(name, obj, note='Latest synthetic clinical decision')
            language_review = self.record(name, obj, kind='linguistic')
            for language in ('fr', 'en', 'ar'):
                with self.subTest(content=name, language=language):
                    before = self.snapshot()
                    response = self.page(route, obj, language)
                    self.assertEqual(response.status_code, 200)
                    states = {row['review'].pk: row['status'] for row in response.context['review_history']}
                    self.assertEqual(states, {older.pk: 'superseded', latest.pk: 'latest_for_content',
                        language_review.pk: 'latest_for_content'})
                    self.assertContains(response, 'data-review-status="superseded"', count=1)
                    self.assertContains(response, 'data-review-status="latest_for_content"', count=2)
                    self.assertEqual(self.snapshot(), before)
        self.assertFalse(Review.objects.filter(approved=True).exists())
        self.assertFalse(PackReview.objects.filter(approved=True).exists())
        self.assertFalse(ProbeReview.objects.filter(approved=True).exists())

    def test_return_to_draft_and_content_edit_marks_retained_decisions_as_other_content(self):
        self.client.force_login(self.editor)
        for name, obj, route in self.contents():
            with self.subTest(content=name):
                old_review = self.record(name, obj)
                if name == 'activity':
                    obj = transition(self.editor, obj.pk, 'draft')
                elif name == 'pack':
                    obj = change_pack_state(self.editor, obj.pk, 'draft')
                else:
                    obj = transition_definition(self.editor, obj, 'draft')
                obj.title += ' — revised editorial content'
                obj.save()
                before = self.snapshot()
                response = self.page(route, obj)
                self.assertEqual(response.status_code, 200)
                history = response.context['review_history']
                self.assertEqual([(row['review'].pk, row['status']) for row in history],
                    [(old_review.pk, 'other_content')])
                self.assertContains(response, 'Decision for different content')
                self.assertNotContains(response, 'data-review-status="latest_for_content"')
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(old_review.approved)

    def test_current_content_label_does_not_make_incomplete_real_content_ready(self):
        self.client.force_login(self.editor)
        for name, obj, route in self.contents():
            with self.subTest(content=name):
                self.record(name, obj)
                self.record(name, obj, kind='linguistic')
                response = self.page(route, obj)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'data-review-status="latest_for_content"', count=2)
                if name == 'activity':
                    self.assertFalse(obj.has_current_reviews())
                    self.assertFalse(response.context['readiness']['ready'])
                elif name == 'pack':
                    self.assertTrue(pack_readiness_reasons(obj))
                else:
                    self.assertTrue(response.context['readiness_reasons'])

    def test_history_does_not_expand_existing_access_scope(self):
        self.client.force_login(self.foreign)
        for name, obj, route in self.contents():
            with self.subTest(content=name):
                self.record(name, obj)
                before = self.snapshot()
                response = self.page(route, obj)
                self.assertEqual(response.status_code, 404)
                self.assertNotContains(response, 'Synthetic changes requested', status_code=404)
                self.assertEqual(self.snapshot(), before)
