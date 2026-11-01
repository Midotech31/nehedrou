"""Fictional media only: checks gates and I/O counts, never clinical/S3 latency."""
import copy
import uuid
from datetime import date
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.http import Http404
from django.test import TestCase, RequestFactory, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from catalog.models import Activity, MediaAsset, Variety
from catalog.audio_checks import audio_binding_errors
from catalog.audio_delivery import protected_media_response
from catalog.authoring import ActivityAuthoringForm
from catalog.forms import MediaForm
from catalog.integrity import integrity_scope, prepare_activities, IntegrityMiddleware
from catalog.readiness import referenced_asset, snapshot_media
from catalog.services import transition
from core.models import User
from qualification.models import EvidenceDocument, _digest_file
from qualification.test_support import (media_fixture, evidence_fixture, competence_fixture,
    prepare_activity_fixture, availability_fixture)


@override_settings(DEMO_MODE=False, MFA_REQUIRED=False,
    PUBLIC_ORIGIN='https://demo.example',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
              'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class MediaQualificationRegressionTests(TestCase):
    def setUp(self):
        self.variety = Variety.objects.create(code='test-fr-exact', language='fr', label='Fictional French')
        self.actor = User.objects.create_user(username='media-review', email='media-review@example.test')
        self.other = User.objects.create_user(username='media-linguist', email='media-linguist@example.test')
        competence_fixture(self.actor, self.variety, 'clinical')
        competence_fixture(self.other, self.variety, 'linguistic')

    def activity(self, publish=False):
        activity = Activity.objects.create(variety=self.variety, series=uuid.uuid4(),
            title='Fictional page activity', contrast='p/b', word_a='pa', word_b='ba',
            instructions={'fr': 'Fictif', 'en': 'Fictional', 'ar': 'مثال'},
            population='Fictional software fixture', rights='Fictional rights only', is_demo=False)
        prepare_activity_fixture(activity, self.actor, self.other)
        if publish:
            activity = transition(self.actor, activity.pk, 'approved')
            activity = transition(self.actor, activity.pk, 'published')
            availability_fixture('practice', self.variety, activity.fingerprint(), self.actor)
        return activity

    def test_absent_empty_and_unknown_voice_profiles_are_never_documented_or_bound(self):
        asset = media_fixture(self.variety, self.actor, 'audio', word='pa')
        for profile in [None, {}, {'text': ' ', 'variety': self.variety.code, 'source': 'human'},
                        {'text': 'pa', 'variety': ' ', 'source': 'human'},
                        {'text': 'pa', 'variety': self.variety.code, 'source': 'unspecified'}]:
            with self.subTest(profile=profile):
                if profile is None:
                    asset.provenance.pop('audio', None)
                else:
                    asset.provenance['audio'] = profile
                self.assertFalse(asset.documented)
                self.assertTrue(audio_binding_errors(asset, 'pa', self.variety))
        # Archive storage retains the actual original unknown metadata.
        for profile in [None, {}]:
            asset.provenance.pop('audio', None)
            if profile is not None:
                asset.provenance['audio'] = profile
            asset.save()
            self.assertFalse(MediaAsset.objects.get(pk=asset.pk).documented)

    def test_imported_missing_audio_profile_cannot_review_approve_or_publish(self):
        activity = self.activity()
        asset = referenced_asset(activity.audio_a, 'audio')
        asset.provenance.pop('audio')
        asset.save()
        # An importer can retain an incomplete legacy object; it cannot qualify it.
        self.assertFalse(activity.has_current_reviews())
        with self.assertRaises(ValidationError):
            transition(self.actor, activity.pk, 'approved')
        activity.state = 'published'
        with self.assertRaises(ValidationError):
            activity.save()
        from catalog.models import Review
        with self.assertRaises(ValidationError):
            Review.objects.create(activity=activity, reviewer=self.actor, kind='clinical', approved=True, note='Cannot invent profile')

    def test_advanced_upload_stays_archive_until_exact_profile_and_dates_are_declared(self):
        source = media_fixture(self.variety, self.actor, 'audio', word='pa')
        with source.file.open('rb') as stream:
            data = stream.read()
        provenance = copy.deepcopy(source.provenance)
        provenance.pop('audio')
        form = MediaForm({'kind': 'audio', 'rights': 'Fictional rights',
            'rights_status': 'original_documented', 'rights_validity': 'unlimited',
            'rights_evidence': source.rights_evidence_id, 'provenance': provenance},
            {'file': SimpleUploadedFile('archive.wav', data)}, instance=MediaAsset(uploaded_by=self.actor))
        self.assertTrue(form.is_valid(), form.errors)
        archive = form.save()
        self.assertFalse(archive.documented)
        values = {'variety': self.variety.pk, 'title': 'Fixture', 'kind': 'word_pair',
            'response_mode': 'matching', 'contrast': 'p/b', 'word_a': 'pa', 'word_b': 'ba',
            'choose_audio_a': archive.pk}
        author = ActivityAuthoringForm(values, actor=self.actor)
        self.assertFalse(author.is_valid())
        self.assertIn('choose_audio_a', author.errors)
        demonstration = ActivityAuthoringForm({**values, 'is_demo': 'on'}, actor=self.actor)
        self.assertTrue(demonstration.is_valid(), demonstration.errors)
        self.assertTrue(demonstration.save().is_demo)
        self.assertFalse(archive.documented)

    def test_catalog_import_only_retains_unqualified_drafts(self):
        import io
        import json
        import tempfile
        from pathlib import Path
        from django.core.management import call_command
        from django.core.management.base import CommandError
        source = self.activity()
        audio = referenced_asset(source.audio_a, 'audio')
        audio.provenance.pop('audio'); audio.save()
        row = {'variety_code': self.variety.code, 'series': str(uuid.uuid4()),
            'title': 'Imported incomplete legacy', 'contrast': 'p/b', 'word_a': 'pa',
            'word_b': 'ba', 'audio_a': source.audio_a, 'audio_b': source.audio_b,
            'instructions': {'fr': 'Fictional import'}, 'is_demo': False, 'state': 'draft'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'import.json'
            path.write_text(json.dumps([row]), encoding='utf-8')
            call_command('import_catalog', str(path), apply=True, stdout=io.StringIO())
            imported = Activity.objects.get(title=row['title'])
            self.assertEqual(imported.state, 'draft')
            self.assertFalse(imported.usable)
            imported.state = 'published'
            with self.assertRaises(ValidationError):
                imported.save()
            path.write_text(json.dumps([{**row, 'series': str(uuid.uuid4()), 'state': 'published'}]), encoding='utf-8')
            with self.assertRaises(CommandError):
                call_command('import_catalog', str(path), apply=True, stdout=io.StringIO())

    def test_exact_word_and_variety_mismatch_remain_blocked(self):
        asset = media_fixture(self.variety, self.actor, 'audio', word='pa')
        other = Variety.objects.create(code='other-test', language='en', label='Other')
        self.assertEqual(audio_binding_errors(asset, 'pa', self.variety), [])
        self.assertTrue(audio_binding_errors(asset, 'ba', self.variety))
        self.assertTrue(audio_binding_errors(asset, 'pa', other))

    def test_unknown_legacy_validity_never_infers_dates_from_contract_text(self):
        asset = media_fixture(self.variety, self.actor, 'image')
        asset.rights_validity = 'unknown'
        asset.provenance['duration'] = 'Unlimited permission in free text is not a structured decision'
        asset.save()
        self.assertTrue(asset.intact)
        self.assertFalse(asset.documented)
        evidence = EvidenceDocument.objects.create(variety=self.variety, uploaded_by=self.actor,
            title='Legacy contract', category='rights', provenance='Expired in 2001; retained contract',
            file=SimpleUploadedFile('legacy.txt', b'Original contract retained'))
        self.assertEqual(evidence.validity, 'unknown')
        self.assertIsNone(evidence.valid_until)
        self.assertTrue(evidence.intact)
        self.assertFalse(evidence.usable)

    def test_structured_start_expiry_inclusive_and_unlimited_with_controlled_clock(self):
        asset = media_fixture(self.variety, self.actor, 'audio', word='pa')
        asset.rights_validity = 'limited'
        asset.rights_valid_from = date(2026, 10, 1)
        asset.rights_valid_until = date(2026, 10, 30)
        asset.save()
        for today, expected in [(date(2026, 9, 30), False), (date(2026, 10, 1), True),
                                (date(2026, 10, 30), True), (date(2026, 10, 31), False)]:
            with self.subTest(today=today), patch('qualification.validity.timezone.localdate', return_value=today):
                self.assertEqual(asset.documented, expected)
        asset.rights_validity = 'unlimited'; asset.rights_valid_until = None
        with patch('qualification.validity.timezone.localdate', return_value=date(2099, 1, 1)):
            self.assertTrue(asset.documented)
        for values in [('limited', None, None), ('unlimited', None, date(2026, 10, 1)),
                       ('limited', date(2026, 10, 30), date(2026, 10, 1))]:
            asset.rights_validity, asset.rights_valid_from, asset.rights_valid_until = values
            with self.assertRaises(ValidationError):
                asset.full_clean()

    def test_expired_rights_evidence_blocks_content_preserving_exact_contract(self):
        evidence = EvidenceDocument.objects.create(variety=self.variety, uploaded_by=self.actor,
            title='Limited fictional contract', category='rights', provenance='Original contract text',
            validity='limited', valid_from=date(2026, 10, 1), valid_until=date(2026, 10, 30),
            file=SimpleUploadedFile('limited.txt', b'Fictional unmodified limited contract'))
        asset = media_fixture(self.variety, self.actor, 'image', rights=evidence)
        digest = evidence.sha256
        with patch('qualification.validity.timezone.localdate', return_value=date(2026, 10, 30)):
            self.assertTrue(asset.documented)
        with patch('qualification.validity.timezone.localdate', return_value=date(2026, 10, 31)):
            self.assertTrue(evidence.intact)
            self.assertFalse(asset.documented)
        self.assertEqual(EvidenceDocument.objects.get(pk=evidence.pk).sha256, digest)
        evidence.valid_until = date(2027, 1, 1)
        with self.assertRaises(ValidationError):
            evidence.save()

    def test_expiry_blocks_new_publication_and_assignment_without_changing_history(self):
        from core.services import create_program
        from core.models import Organization, Membership, Entitlement
        from care.models import Child
        from django.utils import timezone
        from datetime import timedelta
        activity = self.activity()
        for field in ['image_a', 'image_b', 'audio_a', 'audio_b']:
            asset = referenced_asset(getattr(activity, field), 'audio' if field.startswith('audio') else 'image')
            asset.rights_validity = 'limited'; asset.rights_valid_until = date(2026, 10, 30); asset.save()
        activity.media_manifest = snapshot_media(activity); activity.save()
        from catalog.models import Review
        with patch('qualification.validity.timezone.localdate', return_value=date(2026, 10, 30)):
            for user, kind in [(self.actor, 'clinical'), (self.other, 'linguistic')]:
                Review.objects.create(activity=activity, reviewer=user, kind=kind, approved=True, note='Fictional date regression')
            activity = transition(self.actor, activity.pk, 'approved')
            original_manifest = copy.deepcopy(activity.media_manifest)
        with patch('qualification.validity.timezone.localdate', return_value=date(2026, 10, 31)):
            with self.assertRaises(ValidationError):
                transition(self.actor, activity.pk, 'published')
        with patch('qualification.validity.timezone.localdate', return_value=date(2026, 10, 30)):
            activity = transition(self.actor, activity.pk, 'published')
            availability_fixture('practice', self.variety, activity.fingerprint(), self.actor)
        org = Organization.objects.create(name='Fictional expiry practice')
        Membership.objects.create(organization=org, user=self.actor, role='owner')
        Entitlement.objects.create(organization=org, status='active', expires_at=timezone.now() + timedelta(days=10))
        child = Child.objects.create(organization=org, responsible=self.actor, code='FICTIONAL-EXPIRY', age_years=5)
        child.varieties.add(self.variety)
        data = {'title': 'Fictional new assignment', 'goal': '', 'guidance': '', 'schedule': '', 'variety': self.variety, 'activities': [activity]}
        from care.models import ProgramItem
        with patch('qualification.validity.timezone.localdate', return_value=date(2026, 10, 30)):
            historical = create_program(self.actor, child, data)
        with patch('qualification.validity.timezone.localdate', return_value=date(2026, 10, 31)):
            with self.assertRaises(ValidationError):
                create_program(self.actor, child, data)
            with self.assertRaises(ValidationError):
                ProgramItem.objects.create(program=historical, activity=activity, position=2)
            # Retained history can still be saved without a new assignment.
            historical.items.get().save()
        self.assertEqual(historical.items.count(), 1)
        activity.refresh_from_db()
        self.assertEqual(activity.state, 'published')
        self.assertEqual(activity.media_manifest, original_manifest)
        self.assertEqual(activity.reviews.count(), 4)

    def test_media_revocation_requires_reason_scope_and_cannot_silently_reinstate(self):
        asset = media_fixture(self.variety, self.actor, 'image')
        self.client.force_login(self.other)
        url = reverse('editorial_media_revoke', args=[asset.pk])
        # The other fixture reviewer has an explicit publisher grant for this variety.
        from catalog.models import EditorialGrant
        EditorialGrant.objects.filter(user=self.other).update(publish=False)
        self.assertEqual(self.client.post(url, {'reason': 'No authority'}).status_code, 403)
        self.client.force_login(self.actor)
        self.client.post(url, {'reason': ''})
        asset.refresh_from_db(); self.assertFalse(asset.revoked)
        self.client.post(url, {'reason': 'Fictional withdrawal of permission'})
        asset.refresh_from_db(); self.assertTrue(asset.revoked); self.assertFalse(asset.documented)
        asset.revoked = False
        with self.assertRaises(ValidationError):
            asset.save()

    def test_page_batches_sql_and_hashes_each_unique_private_file_once_per_request(self):
        activities = [self.activity(publish=True) for _ in range(4)]
        # Each activity owns four files, one rights/familiarity document and five
        # availability documents: 44 unique private files for this complete page.
        with integrity_scope(), CaptureQueriesContext(connection) as queries, patch('qualification.models._digest_file', wraps=_digest_file) as reads:
            rows = prepare_activities(Activity.objects.filter(pk__in=[row.pk for row in activities]).select_related('variety'))
            for _ in range(3):
                self.assertTrue(all(row.usable for row in rows))
            self.assertEqual(reads.call_count, 44)
            self.assertLessEqual(len(queries), 7)
        self.assertIsNone(__import__('catalog.integrity', fromlist=['_state'])._state.get())

    def test_next_request_rereads_bytes_and_rights_even_with_same_activity_instance(self):
        activity = self.activity(publish=True)
        for _ in range(2):
            with integrity_scope():
                prepare_activities([activity]); self.assertTrue(activity.usable)
        asset = referenced_asset(activity.audio_a, 'audio')
        with asset.file.storage.open(asset.file.name, 'rb') as stream:
            original = stream.read()
        with asset.file.storage.open(asset.file.name, 'wb') as stream:
            stream.write(b'Modified after the previous request')
        with integrity_scope():
            prepare_activities([activity]); self.assertFalse(activity.usable)
        with asset.file.storage.open(asset.file.name, 'wb') as stream:
            stream.write(original)
        proof = asset.rights_evidence
        proof.revoked = True; proof.revocation_reason = 'Fictional withdrawal'; proof.save()
        with integrity_scope():
            prepare_activities([activity]); self.assertFalse(activity.usable)

    def test_delivery_always_hashes_actual_bytes_even_when_request_digest_is_memoized(self):
        asset = media_fixture(self.variety, self.actor, 'audio', word='pa')
        with integrity_scope():
            self.assertTrue(asset.intact)
            with asset.file.storage.open(asset.file.name, 'wb') as stream:
                stream.write(b'Changed during this request')
            for method in ['get', 'head']:
                request = getattr(RequestFactory(), method)('/', HTTP_RANGE='bytes=0-10')
                with self.assertRaises(Http404):
                    protected_media_response(request, asset)

    def test_request_middleware_cleans_scope_when_view_raises(self):
        def failing(request):
            raise RuntimeError('Fictional failure')
        with self.assertRaises(RuntimeError):
            IntegrityMiddleware(failing)(RequestFactory().get('/'))
        self.assertIsNone(__import__('catalog.integrity', fromlist=['_state'])._state.get())



    @override_settings(DEMO_MODE=True)
    def test_noneditor_archive_playback_requires_explicit_demo_and_never_revoked_media(self):
        activity = self.activity(publish=True)
        asset = referenced_asset(activity.audio_a, 'audio')
        asset.provenance.pop('audio'); asset.save()
        outsider = User.objects.create_user(username='archive-viewer', email='archive-viewer@example.test')
        self.client.force_login(outsider)
        url = reverse('editorial_media', args=[asset.pk])
        # Incomplete clinical audio cannot be delivered through a real activity.
        self.assertEqual(self.client.get(url).status_code, 404)
        values = {field.attname: getattr(activity, field.attname) for field in Activity._meta.concrete_fields
                  if field.name not in ['id', 'created_at', 'series', 'state', 'is_demo']}
        demonstration = Activity.objects.create(**values, series=uuid.uuid4(), state='published', is_demo=True)
        self.assertTrue(demonstration.usable)
        self.assertEqual(self.client.get(url).status_code, 200)
        asset.revoked = True; asset.revocation_reason = 'Fictional media withdrawal'; asset.save()
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_actual_http_program_page_bounds_sql_and_private_reads(self):
        from core.models import Organization, Membership, Entitlement
        from core.services import create_program
        from care.models import Child
        from django.utils import timezone
        from datetime import timedelta
        activities = [self.activity(publish=True) for _ in range(4)]
        org = Organization.objects.create(name='Fictional page practice')
        Membership.objects.create(organization=org, user=self.actor, role='owner')
        Entitlement.objects.create(organization=org, status='active', expires_at=timezone.now() + timedelta(days=10))
        child = Child.objects.create(organization=org, responsible=self.actor, code='FICTIONAL-PAGE', age_years=5)
        child.varieties.add(self.variety)
        program = create_program(self.actor, child, {'title': 'Fictional multi-activity page',
            'variety': self.variety, 'activities': activities, 'guidance': '', 'schedule': ''})
        self.client.force_login(self.actor)
        with CaptureQueriesContext(connection) as queries, patch('qualification.models._digest_file', wraps=_digest_file) as reads:
            response = self.client.get(reverse('program_detail', args=[program.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(item.usable for item in response.context['items']))
        self.assertEqual(reads.call_count, 44)
        self.assertLessEqual(len(queries), 40)

    def test_inventory_distinguishes_series_versions_and_actual_availability_without_patient_reads(self):
        import io
        import json
        from django.core.management import call_command
        from catalog.services import clone_version
        from core.models import Organization, Membership
        from care.models import Child
        source = self.activity(publish=True)
        clone_version(self.actor, source)
        org = Organization.objects.create(name='PRIVATE-ORG-SENTINEL')
        Membership.objects.create(organization=org, user=self.actor, role='owner')
        Child.objects.create(organization=org, responsible=self.actor, code='PRIVATE-CHILD-SENTINEL', age_years=5)
        stream = io.StringIO()
        with CaptureQueriesContext(connection) as queries:
            call_command('content_inventory', json=True, stdout=stream)
        output = stream.getvalue()
        self.assertNotIn('PRIVATE-ORG-SENTINEL', output)
        self.assertNotIn('PRIVATE-CHILD-SENTINEL', output)
        for query in queries:
            sql = query['sql'].lower()
            self.assertTrue(sql.lstrip().startswith('select'), sql)
            for forbidden in ['care_child', 'care_program', 'followup_clinicalgoal', 'followup_probeadministration']:
                self.assertNotIn(forbidden, sql)
        report = json.loads(output)
        alignment = report['review_pack_alignment']
        self.assertEqual(alignment['status'], 'review_preparation_only_not_approved')
        self.assertEqual(alignment['candidate_rows'], 74)
        self.assertIn('ar-dz-pilot', alignment['by_variety'])
        self.assertIn('version_mismatch', alignment['by_variety']['ar-dz-pilot'])
        self.assertIn('Does not compare content fingerprints', alignment['scope'])
        self.assertNotIn('PRIVATE-CHILD-SENTINEL', json.dumps(alignment))
        from types import SimpleNamespace
        from uuid import UUID
        from catalog.management.commands.content_inventory import _review_pack_alignment
        drift = _review_pack_alignment([SimpleNamespace(variety=SimpleNamespace(code='ar-dz-pilot'),
            series=UUID('01bfe5ec-57f0-5d3c-a7fb-0a8abbdd3d9a'), version=1)])
        self.assertEqual(drift['by_variety']['ar-dz-pilot']['version_mismatch'], 1)
        row = next(row for row in report['varieties'] if row['variety'] == self.variety.code)
        self.assertEqual(row['database']['candidate_series'], 1)
        self.assertEqual(row['database']['candidate_versions'], 2)
        self.assertEqual(row['database']['latest_candidate_states'], {'draft': 1})
        self.assertEqual(row['current_real_availability']['practice'], 1)
        self.assertEqual(row['referenced_uploaded_media_all_versions']['unique'], 4)
        asset = referenced_asset(source.audio_a, 'audio')
        proof = asset.rights_evidence
        proof.revoked = True; proof.revocation_reason = 'Fictional withdrawal'; proof.save()
        stream = io.StringIO(); call_command('content_inventory', stdout=stream)
        row = next(row for row in json.loads(stream.getvalue())['varieties'] if row['variety'] == self.variety.code)
        self.assertEqual(row['current_real_availability']['practice'], 0)
        self.assertEqual(row['database']['candidate_versions'], 2)
        stream = io.StringIO(); call_command('content_inventory', metadata_only=True, stdout=stream)
        row = next(row for row in json.loads(stream.getvalue())['varieties'] if row['variety'] == self.variety.code)
        self.assertIsNone(row['current_real_availability']['practice'])

    def test_pack_and_probe_media_rights_evidence_must_cover_the_same_variety(self):
        from django.utils.translation import gettext as _
        from qualification.models import LexicalPack, LexicalCandidate
        from qualification.services import pack_content_reasons
        from followup.models import ProbeDefinition
        from followup.services import content_reasons
        image = media_fixture(self.variety, self.actor, 'image')
        audio = media_fixture(self.variety, self.actor, 'audio', word='pa')
        other = Variety.objects.create(code='proof-other', language='en', label='Other variety')
        wrong = evidence_fixture(other, self.actor, 'rights')
        pack = LexicalPack.objects.create(variety=self.variety, series=uuid.uuid4(), title='Fictional rights pack',
            region='Fictional region', scope='Fictional variety', population='Fictional', indications='Fictional',
            limits='Fictional only', created_by=self.actor)
        LexicalCandidate.objects.create(pack=pack, word='pa', meaning='Fictional meaning', ipa='/pa/',
            segments=['p', 'a'], occurrences=[{'index': 0, 'phoneme': 'p', 'position': 'initial'}],
            role='training', provenance='Fictional lexical source', image=image, audio=audio)
        probe = ProbeDefinition(variety=self.variety, is_demo=False, rights='Fictional rights', rights_status='original_documented',
            target_phoneme='p', target_position='initial', target_scope={'position': 'initial', 'context': 'isolated_word'},
            items=[{'id': 'fictional-proof', 'word': 'pa', 'meaning': 'Fictional meaning', 'segments': ['p', 'a'],
                'target_occurrence_index': 0, 'target_occurrences': [{'index': 0, 'phoneme': 'p', 'position': 'initial'}],
                'image_asset': str(image.pk), 'audio_asset': str(audio.pk)}])
        general = _('Exact reviewed image/audio files with rights are missing or changed.')
        self.assertNotIn(general, content_reasons(probe))
        for asset in [image, audio]:
            original = asset.rights_evidence
            asset.rights_evidence = wrong; asset.save()
            self.assertTrue(asset.documented)  # The file has valid rights for another variety.
            reason = _('Missing intact media and documented rights: %(word)s / %(kind)s.') % {'word': 'pa', 'kind': asset.kind}
            self.assertIn(reason, pack_content_reasons(pack))
            self.assertIn(general, content_reasons(probe))
            asset.rights_evidence = original; asset.save()


    def test_probe_image_delivery_rehashes_bytes_despite_warmed_request_integrity_cache(self):
        from followup.views import item_media_response
        asset = media_fixture(self.variety, self.actor, 'image')
        item = {'id': 'warmed-image', 'image_asset': str(asset.pk)}
        frozen = {'warmed-image:image_asset': {'reference': str(asset.pk), 'sha256': asset.technical_metadata['sha256']}}
        with integrity_scope():
            self.assertTrue(asset.intact)
            original = item_media_response(item, 'image', frozen, request=RequestFactory().get('/'))
            self.assertEqual(original.status_code, 200)
            self.assertEqual(item_media_response(item, 'image', frozen).content, original.content)
            with asset.file.storage.open(asset.file.name, 'wb') as stream:
                stream.write(b'Changed image bytes after the cached verification')
            self.assertTrue(asset.intact)  # Confirm this request still holds the old digest.
            with self.assertRaises(Http404):
                item_media_response(item, 'image', frozen)
            for method in ['get', 'head']:
                request = getattr(RequestFactory(), method)('/', HTTP_RANGE='bytes=0-10')
                with self.assertRaises(Http404):
                    item_media_response(item, 'image', frozen, request=request)
