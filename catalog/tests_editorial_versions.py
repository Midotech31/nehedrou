"""Version navigation and exports use the same authorised editorial selection."""
import csv
import html
import io
import json
import re
import uuid
import zipfile
from urllib.parse import parse_qs, urlsplit

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from catalog.content_validation import STEP_FIELDS, TEXT_FIELDS
from catalog.models import Activity, EditorialGrant, Review, Variety
from core.models import User


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class EditorialVersionNavigationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = User.objects.create_user(username='fictional-version-editor', email='version-editor@example.test')
        cls.variety = Variety.objects.create(code='version-fr-test', language='fr', label='Fictional French')
        cls.foreign = Variety.objects.create(code='version-other-test', language='ar', label='Foreign scope')
        EditorialGrant.objects.create(user=cls.actor, variety=cls.variety, edit=True, clinical_review=True)

    def setUp(self):
        self.client.force_login(self.actor)

    def activity(self, **extra):
        values = dict(variety=self.variety, series=uuid.uuid4(), version=1,
            title='Fictional version', contrast='Fictional theme', kind='vocabulary',
            word_a='first', word_b='second', is_demo=False,
            instructions={'fr':'Exemple fictif', 'en':'Fictional example', 'ar':'مثال وهمي'})
        values.update(extra)
        return Activity.objects.create(**values)

    def exported(self, **params):
        response = self.client.get(reverse('editorial_review_pack'), params)
        self.assertEqual(response.status_code, 200)
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        self.addCleanup(archive.close)
        return json.loads(archive.read('activities.json')), archive

    def links(self, response):
        return [html.unescape(link) for link in re.findall(r'href="([^"]+)"', response.content.decode())]

    def test_latest_selection_does_not_resurface_old_state_or_kind(self):
        older = self.activity(state='review')
        current = self.activity(series=older.series, version=2, kind='requests')
        previous = self.activity()
        withdrawn = self.activity(series=previous.series, version=2, state='withdrawn')
        self.activity(variety=self.foreign)
        index = self.client.get(reverse('editorial_index'))
        self.assertEqual({row.pk for row in index.context['page']}, {current.pk, withdrawn.pk})
        quality = self.client.get(reverse('editorial_quality'))
        self.assertEqual({row['activity'].pk for row in quality.context['page']}, {current.pk})
        data, _archive = self.exported()
        self.assertEqual({row['id'] for row in data['activities']}, {str(current.pk)})
        self.assertEqual(data['selection']['versions'], 'latest')
        for filters in ({'state':'review'}, {'kind':'vocabulary'}):
            data, _archive = self.exported(**filters)
            self.assertEqual(data['activities'], [])
        data, _archive = self.exported(versions='all', state='review')
        self.assertEqual({row['id'] for row in data['activities']}, {str(older.pk)})

    def test_exact_history_stays_available_and_decisions_bind_only_that_version(self):
        older = self.activity(state='review', title='Fictional historical version')
        current = self.activity(series=older.series, version=2, title='Fictional current draft')
        detail = self.client.get(reverse('editorial_detail', args=[older.pk]))
        self.assertFalse(detail.context['is_latest_version'])
        self.assertContains(detail, reverse('editorial_detail', args=[current.pk]))
        self.assertTrue(detail.context['can_review'])
        response = self.client.post(reverse('editorial_detail', args=[older.pk]),
            {'expected_digest':older.fingerprint(), 'kind':'clinical', 'note':'Fictional review requests changes to this historical version.'})
        self.assertEqual(response.status_code, 302)
        decision = Review.objects.get()
        self.assertEqual(decision.activity_id, older.pk)
        self.assertEqual(decision.content_digest, older.fingerprint())
        self.assertFalse(current.reviews.exists())
        quality = self.client.get(reverse('editorial_quality'), {'activity':str(older.pk)})
        self.assertEqual([row['activity'].pk for row in quality.context['page']], [older.pk])
        data, archive = self.exported(activity=str(older.pk))
        self.assertEqual(data['selection']['versions'], 'exact')
        self.assertEqual(data['activities'][0]['series'], str(older.series))
        self.assertEqual(data['activities'][0]['evidence_dossier']['series'], str(older.series))
        rows = list(csv.DictReader(io.StringIO(archive.read('review.csv').decode('utf-8-sig'))))
        self.assertEqual(rows[0]['series_uuid'], str(older.series))
        foreign = self.activity(variety=self.foreign)
        for endpoint in ('editorial_quality', 'editorial_review_pack'):
            self.assertEqual(self.client.get(reverse(endpoint), {'activity':str(foreign.pk), 'versions':'all'}).status_code, 404)

    def test_content_purpose_filters_are_shared_by_lists_and_exports(self):
        candidate = self.activity()
        demo = self.activity(is_demo=True)
        for content, expected in (('candidate', candidate.pk), ('demo', demo.pk)):
            index = self.client.get(reverse('editorial_index'), {'content':content})
            quality = self.client.get(reverse('editorial_quality'), {'content':content})
            data, _archive = self.exported(content=content)
            self.assertEqual({row.pk for row in index.context['page']}, {expected})
            self.assertEqual({row['activity'].pk for row in quality.context['page']}, {expected})
            self.assertEqual({row['id'] for row in data['activities']}, {str(expected)})

    def test_pagination_and_download_keep_the_same_filters(self):
        selected = [self.activity(title=f'Fictional selected {index:02}') for index in range(17)]
        self.activity(is_demo=True)
        self.activity(variety=self.foreign)
        self.activity(audio_a='https://example.test/a.wav', audio_b='https://example.test/b.wav')
        params = {'variety':self.variety.code, 'versions':'all', 'content':'candidate',
            'gap':'audio', 'kind':'vocabulary', 'state':'draft'}
        response = self.client.get(reverse('editorial_quality'), params)
        links = self.links(response)
        next_page = next(link for link in links if link.startswith('?page=2'))
        parsed = parse_qs(urlsplit(next_page).query)
        for key, value in params.items():
            self.assertEqual(parsed[key], [value])
        page_two = self.client.get(reverse('editorial_quality') + next_page)
        self.assertEqual(page_two.context['page'].paginator.count, 17)
        self.assertEqual(len(page_two.context['page']), 1)
        download = next(link for link in links if link.startswith(reverse('editorial_review_pack')))
        self.assertNotIn('page', parse_qs(urlsplit(download).query))
        response = self.client.get(download)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            data = json.loads(archive.read('activities.json'))
        self.assertEqual({row['id'] for row in data['activities']}, {str(row.pk) for row in selected})
        self.assertEqual(data['selection'], {'versions':'all', 'content':'candidate', 'gap':'audio'})

    def test_guide_gap_is_applied_to_the_export_as_well_as_the_page(self):
        missing = self.activity()
        guide = {key:'Fictional review input' for key in TEXT_FIELDS}
        guide.update({key:['Fictional review input'] for key in STEP_FIELDS})
        self.activity(practice_guide={'fr':guide})
        response = self.client.get(reverse('editorial_quality'), {'gap':'guide'})
        data, _archive = self.exported(gap='guide')
        self.assertEqual({row['activity'].pk for row in response.context['page']}, {missing.pk})
        self.assertEqual({row['id'] for row in data['activities']}, {str(missing.pk)})

    def test_version_warning_and_filters_are_translated_in_each_interface(self):
        old = self.activity(state='review')
        self.activity(series=old.series, version=2)
        for code, warning in [('fr','Ancienne version'), ('en','Historical version'), ('ar','نسخة سابقة')]:
            with self.subTest(code=code), translation.override(code):
                detail = self.client.get(reverse('editorial_detail', args=[old.pk]))
                self.assertContains(detail, warning)
                index = self.client.get(reverse('editorial_index'))
                self.assertContains(index, 'name="versions"')
                self.assertContains(index, 'name="content"')
