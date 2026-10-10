"""Content provenance, historical integrity and actual guide display regressions."""
import hashlib
import io
import json
import os
import uuid
from pathlib import Path
from unittest.mock import patch
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation
from catalog.content_catalog import current_catalog, public_example
from catalog.models import Activity, EditorialGrant, Review, Variety
from catalog.templatetags.content_guide import guide_language
from core.models import User
from care.models import Program, ProgramItem, PracticeSession
from core import tests as workflow_tests


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False)
class ContentQualificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with patch.dict(os.environ, {'DEMO_PASSWORD': 'Fictional-Content-Test-2026!'}):
            call_command('seed_demo', stdout=io.StringIO())
        call_command('seed_candidates', demo_copies=True, stdout=io.StringIO())
        cls.editor = User.objects.get(username='editorial')
        cls.candidate = Activity.objects.get(series=public_example('fr')['series'], version=2)

    def test_legacy_fingerprint_and_reviews_survive_empty_additive_fields(self):
        activity = self.candidate
        activity.practice_guide, activity.evidence_sources, activity.state = {}, [], 'review'
        activity.save()
        legacy = {field.attname: getattr(activity, field.attname) for field in activity._meta.concrete_fields
                  if field.name not in ['id', 'state', 'created_at', 'practice_guide', 'evidence_sources']}
        digest = hashlib.sha256(json.dumps(legacy, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(activity.fingerprint(), digest)
        for kind in ['clinical', 'linguistic']:
            Review.objects.create(activity=activity, reviewer=self.editor, kind=kind, approved=True, note='Fictional regression decision')
        self.assertTrue(activity.has_current_reviews())
        activity.practice_guide = public_example('fr')['practice_guide']
        activity.save()
        self.assertFalse(activity.has_current_reviews())
        self.assertEqual(activity.reviews.count(), 2)

    def test_seed_preserves_legacy_published_content_and_customized_new_draft(self):
        row = dict(public_example('fr'))
        row.pop('variety_code'); row.pop('series'); row.pop('version')
        row.update(variety=self.candidate.variety, series=uuid.uuid5(uuid.NAMESPACE_URL, 'demo:' + str(self.candidate.series)), version=1,
                   title='Historical unchanged title', is_demo=True, state='published', practice_guide={}, evidence_sources=[])
        historical = Activity.objects.create(**row)
        digest = historical.fingerprint()
        self.candidate.title = 'Editorial work must survive seeding'; self.candidate.save()
        call_command('seed_candidates', demo_copies=True, stdout=io.StringIO())
        historical.refresh_from_db(); self.candidate.refresh_from_db()
        self.assertEqual(historical.title, 'Historical unchanged title')
        self.assertEqual(historical.fingerprint(), digest)
        self.assertEqual(historical.state, 'published')
        self.assertEqual(self.candidate.title, 'Editorial work must survive seeding')
        self.assertEqual(Activity.objects.filter(is_demo=False).count(), 37)
        self.assertNotIn(historical.pk, current_catalog(Activity.objects.filter(is_demo=True, state='published')).values_list('pk', flat=True))
        self.assertTrue(Activity.objects.filter(pk=historical.pk).exists())

    def test_latest_published_version_is_selected_but_other_drafts_do_not_hide_it(self):
        series = uuid.uuid4()
        row = {field.name: getattr(self.candidate, field.name) for field in self.candidate._meta.concrete_fields
               if field.name not in ['id', 'created_at', 'series', 'version', 'state', 'is_demo']}
        first = Activity.objects.create(**row, series=series, version=1, state='published', is_demo=True)
        second = Activity.objects.create(**row, series=series, version=2, state='draft', is_demo=True)
        self.assertEqual(list(current_catalog(Activity.objects.filter(series=series, state='published'))), [first])
        second.state = 'published'; second.save()
        self.assertEqual(list(current_catalog(Activity.objects.filter(series=series, state='published'))), [second])
        self.assertTrue(Activity.objects.filter(pk=first.pk, state='published').exists())

    def test_active_corpus_is_bounded_and_arabic_attestation_is_not_approval(self):
        rows = json.loads((Path(settings.BASE_DIR) / 'docs/catalog-candidates.json').read_text(encoding='utf-8'))
        held = json.loads((Path(settings.BASE_DIR) / 'docs/catalog-exclusions-v2.json').read_text(encoding='utf-8'))
        self.assertEqual(len(rows), 37); self.assertEqual(len(held), 23)
        self.assertNotIn(('pot', 'peau'), [(row['word_a'], row['word_b']) for row in rows])
        arabic = [row for row in rows if row['variety_code'] == 'ar-dz-pilot']
        self.assertEqual([(row['word_a'], row['word_b']) for row in arabic], [('دار', 'نار')])
        self.assertFalse(arabic[0]['transcription_a']); self.assertFalse(arabic[0]['transcription_b'])
        self.assertIn('Dellys', arabic[0]['evidence_sources'][-1]['title'])
        for row in rows:
            self.assertEqual(row['state'], 'draft'); self.assertFalse(row['is_demo'])
            self.assertFalse(row['audio_a']); self.assertFalse(row['audio_b'])
            self.assertEqual(set(row['practice_guide']), {'fr', 'en', 'ar'})
        self.assertEqual(Review.objects.count(), 0)

    def test_unsafe_reference_and_unstructured_steps_cannot_be_saved(self):
        activity = self.candidate
        activity.evidence_sources = [{'title': 'Unsafe', 'url': 'javascript:alert(1)', 'scope': 'Invalid'}]
        with self.assertRaises(ValidationError): activity.save()
        activity.evidence_sources = []
        activity.practice_guide = {'fr': {'objective': 'Incomplete'}}
        with self.assertRaises(ValidationError): activity.save()
        self.assertEqual(guide_language({'fr': {'objective': 'French only'}}, 'ar'), {})

    def test_reviewer_only_sees_allowed_review_type_and_cannot_edit_or_upload(self):
        reviewer = User.objects.create_user(username='linguistic-only', email='linguistic@example.test')
        EditorialGrant.objects.create(user=reviewer, variety=self.candidate.variety, linguistic_review=True)
        self.candidate.state = 'review'; self.candidate.save()
        self.client.force_login(reviewer)
        response = self.client.get(reverse('editorial_detail', args=[self.candidate.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="linguistic"')
        self.assertNotContains(response, 'value="clinical"')
        index = self.client.get(reverse('editorial_index'))
        self.assertNotContains(index, reverse('editorial_create'))
        self.assertNotContains(index, reverse('editorial_upload'))
        response = self.client.post(reverse('editorial_detail', args=[self.candidate.pk]), {'kind': 'clinical', 'approved': True, 'note': 'Not permitted'})
        self.assertEqual(Review.objects.count(), 0)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get(reverse('editorial_upload')).status_code, 403)

    def test_plain_editor_does_not_get_review_submission(self):
        editor = User.objects.create_user(username='draft-only', email='draft@example.test')
        EditorialGrant.objects.create(user=editor, variety=self.candidate.variety, edit=True)
        self.candidate.state = 'review'; self.candidate.save()
        self.client.force_login(editor)
        response = self.client.get(reverse('editorial_detail', args=[self.candidate.pk]))
        self.assertNotContains(response, 'name="kind"')
        self.assertEqual(self.client.post(reverse('editorial_detail', args=[self.candidate.pk]), {'kind': 'clinical', 'approved': True, 'note': 'Not permitted'}).status_code, 403)
        self.assertEqual(Review.objects.count(), 0)


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False)
class AssignedGuideDisplayTests(TestCase):
    setUpTestData = classmethod(workflow_tests.WorkflowTests.setUpTestData.__func__)

    def test_guide_is_visible_in_actual_practice_program_catalogue_and_print(self):
        call_command('seed_candidates', demo_copies=True, stdout=io.StringIO())
        row = public_example('fr')
        demo = Activity.objects.get(series=uuid.uuid5(uuid.NAMESPACE_URL, 'demo:' + row['series']), version=2)
        self.program = Program.objects.create(organization=self.org, child=self.child, variety=demo.variety,
                                              created_by=self.pro, title='Fictional guide program',
                                              guidance='Individual fictional guidance', schedule='Chosen with clinician')
        self.item = ProgramItem.objects.create(program=self.program, activity=demo, position=1)
        self.client.force_login(self.family)
        for code in ['fr', 'en', 'ar']:
            self.family.instruction_language = code; self.family.save()
            with translation.override(code):
                for name, pk in [('practice', self.item.pk), ('program_detail', self.program.pk), ('print_program', self.program.pk), ('activity_detail', demo.pk)]:
                    response = self.client.get(reverse(name, args=[pk]))
                    self.assertEqual(response.status_code, 200, (code, name))
                    self.assertContains(response, row['practice_guide'][code]['objective'])
                practice = self.client.get(reverse('practice', args=[self.item.pk]))
                self.assertContains(practice, row['practice_guide'][code]['listen'][1])
                self.assertContains(practice, row['practice_guide'][code]['exchange'][0])
        self.assertEqual(PracticeSession.objects.count(), 0)
