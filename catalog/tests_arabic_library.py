"""Arabic catalogue import safety and real library discovery regressions.

All records are fictional test data; structure checks do not approve language,
clinical efficacy, recording rights or suitability for real children.
"""
import copy
import io
import json
import uuid
from importlib import import_module
from types import SimpleNamespace
from collections import Counter
from html import unescape
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from django.conf import settings
from django.db import connection
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation
from catalog.content_catalog import current_catalog
from catalog.models import Activity, EditorialGrant, Review, Variety
from catalog.search import search_key
from core import tests as workflow_tests
from core.models import User
from qualification.models import ReviewerCompetence


def document():
    return json.loads((Path(settings.BASE_DIR) / 'docs/arabic-library-v1.json').read_text(encoding='utf-8'))


def seed(*, demos=False):
    call_command('seed_arabic_library', demo_copies=demos, stdout=io.StringIO())


def source_ids(rows):
    return [uuid.UUID(row['series']) for row in rows]


def demo_id(row):
    return uuid.uuid5(uuid.NAMESPACE_URL, 'demo:' + row['series'])


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False)
class ArabicLoaderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        workflow_tests.WorkflowTests.setUpTestData.__func__(cls)
        cls.document = document()
        cls.rows = cls.document['activities']

    def setUp(self):
        translation.activate('en')

    def draft_values(self, row, variety, **changes):
        values = dict(row)
        values.pop('variety_code')
        values.update(variety=variety, **changes)
        return values

    def test_default_import_has_bounded_unapproved_contents_and_no_new_permissions(self):
        users = list(User.objects.values_list('pk', 'password'))
        grants = list(EditorialGrant.objects.values_list('pk', 'user_id', 'variety_id', 'edit', 'clinical_review', 'linguistic_review', 'publish'))
        seed()
        drafts = Activity.objects.filter(series__in=source_ids(self.rows))
        self.assertEqual(drafts.count(), 106)
        self.assertEqual(Counter(drafts.values_list('variety__code', flat=True)),
                         {'ar-msa-pilot': 42, 'ar-dz-pilot': 64})
        self.assertEqual(set(drafts.values_list('state', 'is_demo')), {('draft', False)})
        self.assertEqual(Activity.objects.filter(series__in=[demo_id(row) for row in self.rows]).count(), 0)
        self.assertEqual(Review.objects.count(), 0)
        self.assertEqual(ReviewerCompetence.objects.count(), 0)
        self.assertEqual(list(User.objects.values_list('pk', 'password')), users)
        self.assertEqual(list(EditorialGrant.objects.values_list('pk', 'user_id', 'variety_id', 'edit', 'clinical_review', 'linguistic_review', 'publish')), grants)
        for row in self.rows:
            item = drafts.get(series=row['series'], version=row['version'])
            self.assertFalse(item.usable)
            self.assertFalse(item.has_current_reviews())
            self.assertEqual((item.word_a, item.word_b), (row['word_a'], row['word_b']))
            self.assertEqual(set(item.practice_guide), {'fr', 'en', 'ar'})
            self.assertFalse(item.audio_a)
            self.assertFalse(item.audio_b)
            self.assertTrue(item.image_available(item.image_a))
            self.assertTrue(item.image_available(item.image_b))

    def test_seed_is_idempotent_without_overwriting_editorial_work_reviews_or_withdrawal(self):
        legacy = self.item.activity
        before_legacy = (legacy.fingerprint(), legacy.title, legacy.state)
        seed(demos=True)
        row = next(row for row in self.rows if row['variety_code'] == 'ar-dz-pilot')
        draft = Activity.objects.get(series=row['series'], version=row['version'])
        draft.title = 'Fictional editorial work that must survive'
        draft.state = 'review'
        draft.save()
        review = Review.objects.create(activity=draft, reviewer=User.objects.get(username='editorial'),
                                       kind='clinical', approved=False, note='Fictional unapproved review')
        withdrawn = Activity.objects.get(series=demo_id(row), version=row['version'])
        withdrawn.state = 'withdrawn'
        withdrawn.save()
        before = {str(a.pk): (a.fingerprint(), a.state, a.title) for a in Activity.objects.all()}
        before_review = (review.pk, review.content_digest, review.created_at, review.note)
        seed(demos=True)
        self.assertEqual({str(a.pk): (a.fingerprint(), a.state, a.title) for a in Activity.objects.all()}, before)
        review.refresh_from_db()
        self.assertEqual((review.pk, review.content_digest, review.created_at, review.note), before_review)
        self.assertEqual(Review.objects.count(), 1)
        self.assertFalse(review.approved)
        legacy.refresh_from_db()
        self.assertEqual((legacy.fingerprint(), legacy.title, legacy.state), before_legacy)
        self.assertEqual(Activity.objects.filter(series__in=source_ids(self.rows)).count(), 106)
        self.assertEqual(Activity.objects.filter(series__in=[demo_id(row) for row in self.rows]).count(), 106)
        self.assertFalse(current_catalog(Activity.objects.filter(state='published')).filter(pk=legacy.pk).exists())
        self.assertTrue(Activity.objects.filter(pk=legacy.pk).exists())

    def test_collision_in_reserved_draft_series_aborts_all_imported_rows(self):
        row = next(row for row in self.rows if row['kind'] != 'phonological_contrast')
        wrong_variety = Variety.objects.get(code='fr-fr-pilot')
        conflicting = Activity.objects.create(**self.draft_values(row, wrong_variety))
        before = set(Activity.objects.values_list('pk', flat=True))
        with self.assertRaises(CommandError):
            seed(demos=True)
        self.assertEqual(set(Activity.objects.values_list('pk', flat=True)), before)
        conflicting.refresh_from_db()
        self.assertEqual(conflicting.variety_id, wrong_variety.pk)
        self.assertFalse(Variety.objects.filter(code='ar-msa-pilot').exists())

    def test_collision_in_reserved_demo_series_rolls_back_earlier_imported_rows(self):
        row = next(row for row in self.rows if row['variety_code'] == 'ar-dz-pilot')
        variety = Variety.objects.get(code='ar-dz-pilot')
        conflicting = Activity.objects.create(**self.draft_values(row, variety, series=demo_id(row)))
        before = set(Activity.objects.values_list('pk', flat=True))
        with self.assertRaises(CommandError):
            seed(demos=True)
        self.assertEqual(set(Activity.objects.values_list('pk', flat=True)), before)
        conflicting.refresh_from_db()
        self.assertFalse(conflicting.is_demo)
        self.assertEqual(conflicting.state, 'draft')

    def test_non_arabic_reserved_variety_is_not_repurposed(self):
        existing = Variety.objects.create(code='ar-msa-pilot', language='en',
                                           label='Fictional existing collision', scope='Preserve this declaration')
        before = Activity.objects.count()
        with self.assertRaises(CommandError):
            seed()
        self.assertEqual(Activity.objects.count(), before)
        existing.refresh_from_db()
        self.assertEqual((existing.language, existing.label, existing.scope),
                         ('en', 'Fictional existing collision', 'Preserve this declaration'))

    def test_real_mode_rejects_demo_flag_but_can_import_blocked_design_drafts(self):
        before = Activity.objects.count()
        with override_settings(DEMO_MODE=False):
            with self.assertRaises(CommandError):
                seed(demos=True)
            self.assertEqual(Activity.objects.count(), before)
            seed()
            drafts = Activity.objects.filter(series__in=source_ids(self.rows))
            self.assertEqual(drafts.count(), 106)
            self.assertEqual(set(drafts.values_list('state', 'is_demo')), {('draft', False)})
            self.assertTrue(all(not draft.usable for draft in drafts))
            self.client.force_login(self.pro)
            library = self.client.get(reverse('library'), {'content_language': 'ar'})
            self.assertEqual(library.status_code, 200)
            self.assertEqual(library.context['result_count'], 0)

    def test_invalid_late_seed_flags_or_claimed_audio_roll_back_the_entire_document(self):
        before = set(Activity.objects.values_list('pk', flat=True))
        for changed in [{'state': 'published'}, {'is_demo': True}, {'audio_a': 'https://example.invalid/claimed.wav'}]:
            invalid = copy.deepcopy(self.document)
            invalid['activities'][-1].update(changed)
            with self.subTest(changed=changed), patch('catalog.management.commands.seed_arabic_library.json.loads', return_value=invalid):
                with self.assertRaises(CommandError):
                    seed(demos=True)
            self.assertEqual(set(Activity.objects.values_list('pk', flat=True)), before)
            self.assertFalse(Variety.objects.filter(code='ar-msa-pilot').exists())


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False)
class ArabicLibraryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        workflow_tests.WorkflowTests.setUpTestData.__func__(cls)
        cls.document = document()
        cls.rows = cls.document['activities']
        seed(demos=True)

    def setUp(self):
        translation.activate('en')
        self.client.force_login(self.pro)

    def page(self, **query):
        response = self.client.get(reverse('library'), query)
        self.assertEqual(response.status_code, 200)
        return response

    def test_spoken_varieties_are_separate_despite_the_same_arabic_interface_language(self):
        all_arabic = self.page(content_language='ar')
        self.assertEqual(all_arabic.context['result_count'], 74)
        collections = {row['code']: row['count'] for row in all_arabic.context['arabic_collections']}
        self.assertEqual(collections, {'ar-msa-pilot': 42, 'ar-dz-pilot': 32})
        for code, count in collections.items():
            response = self.page(content_language='ar', variety=code)
            self.assertEqual(response.context['result_count'], count)
            self.assertTrue(all(a.variety.code == code for a in response.context['page']))
            self.assertEqual(set(response.context['varieties'].values_list('language', flat=True)), {'ar'})
        mismatch = self.page(content_language='fr', variety='ar-msa-pilot')
        self.assertEqual(mismatch.context['result_count'], 0)

    def test_arabic_search_ignores_diacritics_tatweel_and_alef_forms_without_changing_content(self):
        row = next(row for row in self.rows if any(c in row['word_a'] for c in 'أإآٱا'))
        activity = Activity.objects.get(series=demo_id(row), version=row['version'])
        original = (activity.word_a, activity.word_b, activity.fingerprint())
        normalized = search_key(activity.word_a)
        noisy = 'َـ'.join(normalized)
        alternate_alef = normalized.translate(str.maketrans('ا', 'إ'))
        normal_page = self.page(content_language='ar', variety=row['variety_code'], q=normalized)
        self.assertGreater(normal_page.context['result_count'], 0)
        expected = set(normal_page.context['page'].paginator.object_list.values_list('pk', flat=True))
        self.assertIn(activity.pk, expected)
        for query in [noisy, alternate_alef]:
            response = self.page(content_language='ar', variety=row['variety_code'], q=query)
            actual = set(response.context['page'].paginator.object_list.values_list('pk', flat=True))
            self.assertEqual(actual, expected)
        activity.refresh_from_db()
        self.assertEqual((activity.word_a, activity.word_b, activity.fingerprint()), original)
        only_marks = self.page(content_language='ar', q='َـ')
        self.assertEqual(only_marks.context['result_count'], 0)

    def test_short_word_search_avoids_generic_guide_boilerplate_and_keeps_clinical_content(self):
        row = next(row for row in self.rows if row['variety_code'] == 'ar-msa-pilot' and row['word_a'] == 'قط')
        cat = Activity.objects.get(series=demo_id(row), version=row['version'])
        original = (cat.word_a, cat.word_b, cat.transcription_a, cat.transcription_b, cat.fingerprint())
        # Exercise the frozen pre-deployment backfill against an older polluted cache.
        Activity.objects.filter(pk=cat.pk).update(search_text='فقط')
        migration = import_module('catalog.migrations.0009_activity_classification')
        migration.index_existing(SimpleNamespace(get_model=lambda app, model: Activity),
                                 SimpleNamespace(connection=connection))
        response = self.page(content_language='ar', variety='ar-msa-pilot', q='قط')
        self.assertGreater(response.context['result_count'], 0)
        self.assertLess(response.context['result_count'], 10)
        self.assertIn(cat.pk, response.context['page'].paginator.object_list.values_list('pk', flat=True))
        cat.refresh_from_db()
        self.assertEqual((cat.word_a, cat.word_b, cat.transcription_a, cat.transcription_b, cat.fingerprint()), original)
        cat.save(update_fields=['search_text'])
        current = self.page(content_language='ar', variety='ar-msa-pilot', q='قط')
        self.assertEqual(current.context['result_count'], response.context['result_count'])
        self.assertEqual((cat.word_a, cat.word_b, cat.transcription_a, cat.transcription_b, cat.fingerprint()), original)

    def test_type_and_theme_filters_compose_with_each_spoken_variety(self):
        for code in ['ar-msa-pilot', 'ar-dz-pilot']:
            rows = [row for row in self.rows if row['variety_code'] == code]
            for (kind, theme), count in Counter((row['kind'], row['theme']) for row in rows).items():
                response = self.page(content_language='ar', variety=code, kind=kind, theme=theme)
                self.assertEqual(response.context['result_count'], count, (code, kind, theme))
                self.assertTrue(all(a.variety.code == code and a.kind == kind and a.theme == theme
                                    for a in response.context['page']))
        invalid = self.page(content_language='ar', kind='invented', theme='invented')
        self.assertEqual(invalid.context['selected_kind'], '')
        self.assertEqual(invalid.context['selected_theme'], '')
        self.assertEqual(invalid.context['result_count'], 74)

    def test_pagination_covers_every_current_arabic_demo_once_and_preserves_filters(self):
        first = self.page(content_language='ar', variety='ar-msa-pilot')
        self.assertEqual(first.context['page'].paginator.count, 42)
        seen = []
        for number in range(1, first.context['page'].paginator.num_pages + 1):
            response = self.page(content_language='ar', variety='ar-msa-pilot', page=number)
            self.assertLessEqual(len(response.context['page']), 12)
            seen.extend(a.pk for a in response.context['page'])
        expected = {demo_id(row) for row in self.rows if row['variety_code'] == 'ar-msa-pilot'}
        expected_pks = set(Activity.objects.filter(series__in=expected).values_list('pk', flat=True))
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(set(seen), expected_pks)
        import re
        links = re.findall(r'<a href="([^"]+)"', first.content.decode('utf-8'))
        pagination_links = [link for link in links if link.startswith('?page=')]
        self.assertTrue(pagination_links)
        for link in pagination_links:
            query = parse_qs(urlsplit(unescape(link)).query)
            self.assertEqual(query.get('content_language'), ['ar'])
            self.assertEqual(query.get('variety'), ['ar-msa-pilot'])

    def test_real_mode_never_shows_or_opens_unapproved_demonstration_copies(self):
        example = Activity.objects.get(series=demo_id(self.rows[0]), version=self.rows[0]['version'])
        with override_settings(DEMO_MODE=False):
            response = self.page(content_language='ar')
            self.assertEqual(response.context['result_count'], 0)
            self.assertEqual(self.client.get(reverse('activity_detail', args=[example.pk])).status_code, 404)
        self.assertEqual(Review.objects.count(), 0)
        self.assertEqual(ReviewerCompetence.objects.count(), 0)

    def test_ten_msa_phonological_proposals_are_structurally_single_segment_contrasts_only(self):
        phonological = [row for row in self.rows if row['kind'] == 'phonological_contrast']
        self.assertEqual(len(phonological), 10)
        self.assertTrue(all(row['variety_code'] == 'ar-msa-pilot' for row in phonological))
        for row in phonological:
            first = row['item_metadata']['a']
            second = row['item_metadata']['b']
            self.assertEqual(len(first['segments']), len(second['segments']))
            differences = [i for i, pair in enumerate(zip(first['segments'], second['segments'])) if pair[0] != pair[1]]
            self.assertEqual(len(differences), 1)
            for entry in [first, second]:
                self.assertIn(differences[0], [occurrence['index'] for occurrence in entry['target_occurrences']])
            self.assertEqual(row['response_mode'], 'matching')
            self.assertFalse(row['is_demo'])
            self.assertEqual(row['state'], 'draft')
        self.assertEqual(Review.objects.count(), 0)
