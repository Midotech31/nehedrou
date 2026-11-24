"""Selected review exports use unapproved fictional drafts, never real approvals."""
import csv
import hashlib
import io
import json
import uuid
import zipfile

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.translation import override

from catalog.models import Activity, EditorialGrant, Review, Variety
from core.models import AuditEvent, User
from qualification.models import AvailabilityDecision


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False, PUBLIC_ORIGIN='https://demo.example',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
              'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class SelectedReviewBatchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.editor = User.objects.create_user('batch-editor', 'batch-editor@example.test')
        cls.outsider = User.objects.create_user('batch-outsider', 'batch-outsider@example.test')
        cls.variety = Variety.objects.create(code='batch-fr', language='fr', label='Fictional batch French')
        cls.other_variety = Variety.objects.create(code='batch-ar', language='ar', label='Fictional batch Arabic')
        cls.foreign_variety = Variety.objects.create(code='batch-en', language='en', label='Inaccessible fictional variety')
        for variety in [cls.variety, cls.other_variety]:
            EditorialGrant.objects.create(user=cls.editor, variety=variety, edit=True)
        cls.rows = [cls.make_activity('Fictional batch draft %02d' % index) for index in range(17)]
        cls.other = cls.make_activity('Fictional other allowed variety', variety=cls.other_variety)
        cls.foreign = cls.make_activity('Fictional inaccessible draft', variety=cls.foreign_variety)
        cls.demo = cls.make_activity('Fictional demonstration draft', is_demo=True)
        cls.audio_referenced = cls.make_activity('Fictional referenced unqualified audio',
            audio_a='https://demo.example/fr/media/' + str(uuid.uuid4()) + '/',
            audio_b='https://demo.example/fr/media/' + str(uuid.uuid4()) + '/')

    @classmethod
    def make_activity(cls, title, **extra):
        values = dict(variety=cls.variety, series=uuid.uuid4(), title=title,
            word_a='pa', word_b='ba', contrast='p/b', is_demo=False,
            population='Fictional software regression only', rights='No real approval or permission',
            instructions={'fr': 'Fictif', 'en': 'Fictional', 'ar': 'مثال وهمي'})
        values.update(extra)
        return Activity.objects.create(**values)

    def setUp(self):
        self.client.force_login(self.editor)
        self.path = reverse('editorial_review_pack')

    @staticmethod
    def item(activity, *, state=None, digest=None):
        return '%s:%s:%s' % (activity.pk, state or activity.state, digest or activity.fingerprint())

    def selected(self, items, **filters):
        # A list generates repeated selection_item query parameters, as the form does.
        return self.client.get(self.path, {'export': 'selected', 'selection_item': items, **filters})

    def assert_selected_zip(self, response, activities):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/zip')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        expected = {str(activity.pk) for activity in activities}
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertIsNone(archive.testzip())
            raw = archive.read('activities.json')
            manifest = json.loads(raw)
            self.assertIs(manifest['selection']['batch'], True)
            self.assertEqual({row['id'] for row in manifest['activities']}, expected)
            self.assertEqual(len(manifest['activities']), len(expected))
            self.assertEqual(archive.read('activities.sha256').decode(), hashlib.sha256(raw).hexdigest())
            dossiers = json.loads(archive.read('evidence_dossiers.json'))
            self.assertEqual({row['activity_id'] for row in dossiers['activities']}, expected)
            for name in ['review.csv', 'evidence_tasks.csv', 'media_requirements.csv', 'recording_prompts.csv']:
                records = list(csv.DictReader(io.StringIO(archive.read(name).decode('utf-8-sig'))))
                self.assertTrue(records, name)
                self.assertEqual({row['activity_id'] for row in records}, expected, name)
            # All fixtures intentionally remain drafts with no inferred clinical decision.
            self.assertTrue(all(row['state'] == Activity.objects.get(pk=row['id']).state
                                for row in manifest['activities']))
        return manifest

    def test_success_contains_only_chosen_versions_in_all_outputs_without_writes(self):
        chosen = [self.rows[1], self.other]
        before = list(Activity.objects.order_by('pk').values())
        counts = (Review.objects.count(), AvailabilityDecision.objects.count(), AuditEvent.objects.count())
        manifest = self.assert_selected_zip(self.selected([self.item(row) for row in chosen]), chosen)
        self.assertEqual({row['content_sha256'] for row in manifest['activities']},
                         {row.fingerprint() for row in chosen})
        self.assertEqual(list(Activity.objects.order_by('pk').values()), before)
        self.assertEqual((Review.objects.count(), AvailabilityDecision.objects.count(), AuditEvent.objects.count()), counts)

    def test_quality_form_ships_current_filters_and_exact_versions_in_each_language(self):
        row = self.rows[0]
        for language, label in [
            ('en', 'Download selected versions'),
            ('fr', 'Télécharger les versions sélectionnées'),
            ('ar', 'تنزيل الإصدارات المحدّدة'),
        ]:
            with self.subTest(language=language), override(language):
                response = self.client.get(reverse('editorial_quality'), {
                    'variety': self.variety.code, 'content': 'candidate', 'gap': 'audio',
                })
                self.assertContains(response, label)
                self.assertContains(response, f'action="{reverse("editorial_review_pack")}"')
                self.assertContains(response, f'name="selection_item" value="{self.item(row)}"')
                self.assertContains(response, 'name="content" value="candidate"')
                self.assertContains(response, 'name="gap" value="audio"')
                self.assertNotContains(response, self.item(self.other))

    def test_sixteen_items_are_accepted_and_seventeen_are_rejected(self):
        chosen = self.rows[:16]
        self.assert_selected_zip(self.selected([self.item(row) for row in chosen]), chosen)
        response = self.selected([self.item(row) for row in self.rows])
        self.assertEqual(response.status_code, 400)

    def test_empty_malformed_and_duplicate_selections_are_bad_requests(self):
        row = self.rows[0]
        valid = self.item(row)
        invalid = [
            [], [''], ['not-a-uuid:draft:' + 'a' * 64],
            [str(row.pk) + ':draft'], [str(row.pk) + '::' + row.fingerprint()],
            [self.item(row, state='unknown-state')], [str(row.pk) + ':draft:not-a-digest'],
            [self.item(row, digest='g' * 64)], [valid + ':extra'],
            [valid, valid], [valid, self.item(row, state='review')],
        ]
        for items in invalid:
            with self.subTest(items=items):
                self.assertEqual(self.selected(items).status_code, 400)
        self.assertEqual(self.client.get(self.path, {'export': 'selected'}).status_code, 400)

    def test_unknown_inaccessible_or_partly_inaccessible_selection_is_not_exported(self):
        valid = self.item(self.rows[0])
        unknown = '%s:draft:%s' % (uuid.uuid4(), 'a' * 64)
        for items in [[unknown], [self.item(self.foreign)], [valid, self.item(self.foreign)]]:
            with self.subTest(items=items):
                self.assertEqual(self.selected(items).status_code, 404)

    def test_current_variety_kind_content_state_and_gap_filters_are_enforced(self):
        row = self.rows[0]
        cases = [
            ([self.item(row)], {'variety': self.other_variety.code}),
            ([self.item(row)], {'kind': 'actions'}),
            ([self.item(row)], {'content': 'demo'}),
            ([self.item(row)], {'state': 'review'}),
            ([self.item(self.audio_referenced)], {'gap': 'audio'}),
        ]
        for items, filters in cases:
            with self.subTest(filters=filters):
                self.assertEqual(self.selected(items, **filters).status_code, 404)
        self.assert_selected_zip(self.selected([self.item(row)], variety=self.variety.code,
            kind='word_pair', content='candidate', state='draft', gap='audio'), [row])
        self.assert_selected_zip(self.selected([self.item(self.demo)], content='demo'), [self.demo])

    def test_historical_version_requires_history_scope_and_does_not_include_its_replacement(self):
        previous = self.rows[0]
        snapshot = self.item(previous)
        self.make_activity('Fictional newer draft', series=previous.series, version=previous.version + 1)
        self.assertEqual(self.selected([snapshot]).status_code, 404)
        self.assert_selected_zip(self.selected([snapshot], versions='all'), [previous])

    def test_changed_content_refuses_the_entire_batch_with_conflict(self):
        first, changed = self.rows[:2]
        selected = [self.item(first), self.item(changed)]
        changed.word_a = 'Changed fictional prompt'
        changed.save(update_fields=['word_a'])
        self.assertEqual(self.selected(selected).status_code, 409)

    def test_state_change_is_a_conflict_unless_a_filter_removes_the_version(self):
        row = self.rows[0]
        snapshot = self.item(row)
        digest = row.fingerprint()
        row.state = 'review'
        row.save(update_fields=['state'])
        self.assertEqual(row.fingerprint(), digest)  # State is deliberately outside the content fingerprint.
        self.assertEqual(self.selected([snapshot]).status_code, 409)
        self.assertEqual(self.selected([snapshot], state='draft').status_code, 404)

    def test_authentication_current_editorial_scope_and_get_only_are_required(self):
        items = [self.item(self.rows[0])]
        self.assertEqual(self.client.post(self.path, {'export': 'selected', 'selection_item': items}).status_code, 405)
        self.client.logout()
        self.assertEqual(self.selected(items).status_code, 302)
        self.client.force_login(self.outsider)
        self.assertEqual(self.selected(items).status_code, 404)
        self.client.force_login(self.editor)
        EditorialGrant.objects.filter(user=self.editor).delete()
        self.assertEqual(self.selected(items).status_code, 404)
