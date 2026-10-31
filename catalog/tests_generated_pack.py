"""Synthetic source fixtures verify the import workflow, never image recognition."""
import copy
import hashlib
import io
import json
import shutil
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from django.conf import settings
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from catalog import generated_pack
from catalog.generated_pack import install_pack, PACK_ID
from catalog.models import Activity, Variety, MediaAsset, EditorialGrant, Review, GeneratedReviewPackImport
from catalog.media_validation import validate_media
from catalog.templatetags.editorial import editorial_image_srcset
from core.models import User
from qualification.models import EvidenceDocument, AvailabilityDecision


@override_settings(DEMO_MODE=False, MFA_REQUIRED=False, PUBLIC_ORIGIN='https://demo.example',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class GeneratedReviewPackTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name); self.source_dir = self.base / 'sources'; self.source_dir.mkdir()
        self.pack_dir = self.base / 'pack'; self.pack_dir.mkdir()
        self.storage = override_settings(MEDIA_ROOT=self.base / 'private', STORAGES={
            'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
            'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
        self.storage.enable(); self.addCleanup(self.storage.disable)
        original_path = generated_pack.MANIFEST_PATH
        self.manifest = json.loads(original_path.read_text(encoding='utf8'))
        # Portable tests use explicit synthetic PNGs, not the agent's E: art folder.
        for index, concept in enumerate(self.manifest['concepts']):
            stream = io.BytesIO(); Image.new('RGB', (1254, 1254), (30 + index * 20, 100, 150)).save(stream, 'PNG')
            blob = stream.getvalue(); (self.source_dir / concept['source']['file']).write_bytes(blob)
            concept['source'].update(bytes=len(blob), sha256=hashlib.sha256(blob).hexdigest())
            for record in concept['display_variants'].values():
                shutil.copyfile(original_path.parent / record['file'], self.pack_dir / record['file'])
        self.path = self.pack_dir / 'manifest.json'; self.write_manifest()
        self.manifest_patch = patch('catalog.generated_pack.MANIFEST_PATH', self.path)
        self.manifest_patch.start(); self.addCleanup(self.manifest_patch.stop)
        self.actor = User.objects.create_user(username='image-editor', email='image-editor@example.test')
        self.viewer = User.objects.create_user(username='image-reviewer', email='image-reviewer@example.test')
        self.outsider = User.objects.create_user(username='image-outsider', email='image-outsider@example.test')
        self.variety = Variety.objects.create(code='fr-fr-pilot', language='fr', label='Fictional French scope')
        EditorialGrant.objects.create(user=self.actor, variety=self.variety, edit=True, clinical_review=True)
        EditorialGrant.objects.create(user=self.viewer, variety=self.variety, linguistic_review=True)
        other_variety = Variety.objects.create(code='other-image-scope', language='en', label='Other image scope')
        EditorialGrant.objects.create(user=self.outsider, variety=other_variety, edit=True)
        rows = json.loads((Path(settings.BASE_DIR) / 'docs/catalog-candidates.json').read_text(encoding='utf8'))
        series = {row['source_series'] for row in self.manifest['pairs']}
        self.sources = []
        for row in rows:
            if row['series'] in series:
                values = dict(row); values.pop('variety_code')
                self.sources.append(Activity.objects.create(variety=self.variety, **values))

    def write_manifest(self):
        self.path.write_text(json.dumps(self.manifest, ensure_ascii=False), encoding='utf8')

    def test_default_command_is_read_only_dry_run_and_requires_existing_actor_scope(self):
        unused = self.source_dir / 'unused-seventh.png'; unused.write_bytes(b'Untouched unrelated image')
        stream = io.StringIO()
        call_command('install_generated_review_pack', actor=self.actor.username, source_dir=str(self.source_dir), stdout=stream)
        report = json.loads(stream.getvalue())
        self.assertEqual(report['status'], 'dry_run'); self.assertEqual(report['files_verified'], 18)
        self.assertEqual(Activity.objects.count(), 3); self.assertEqual(MediaAsset.objects.count(), 0)
        self.assertFalse(GeneratedReviewPackImport.objects.exists())
        self.assertEqual(unused.read_bytes(), b'Untouched unrelated image')
        with self.assertRaises(PermissionDenied):
            install_pack(self.outsider, self.source_dir, apply=True)
        with self.assertRaises(CommandError):
            call_command('install_generated_review_pack', actor='missing-account', source_dir=str(self.source_dir))
        self.assertFalse(MediaAsset.objects.exists())
        self.actor.is_active = False; self.actor.save()
        with self.assertRaises(PermissionDenied):
            install_pack(self.actor, self.source_dir, apply=True)

    def test_apply_creates_unknown_rights_sources_variants_and_three_new_drafts_idempotently(self):
        first = self.sources[0]; first.state = 'review'
        first.rights = 'Original vector illustrations under MIT; legacy source statement.'
        first.save()
        Review.objects.create(activity=first, reviewer=self.actor, kind='clinical', approved=False, note='Pending competent review')
        fingerprints = {row.pk: Activity.objects.get(pk=row.pk).fingerprint() for row in self.sources}
        original_rights = dict(Activity.objects.filter(pk__in=[row.pk for row in self.sources]).values_list('pk', 'rights'))
        result = install_pack(self.actor, self.source_dir, apply=True)
        self.assertEqual(result['status'], 'imported_pending_review')
        self.assertEqual(MediaAsset.objects.count(), 18); self.assertEqual(Activity.objects.count(), 6)
        self.assertEqual(Review.objects.count(), 1); self.assertEqual(EvidenceDocument.objects.count(), 0)
        self.assertEqual(AvailabilityDecision.objects.count(), 0)
        for source in self.sources:
            source.refresh_from_db(); self.assertEqual(source.fingerprint(), fingerprints[source.pk])
            self.assertEqual(source.rights, original_rights[source.pk])
        for asset in MediaAsset.objects.all():
            self.assertTrue(asset.intact); self.assertFalse(asset.documented)
            self.assertEqual(asset.rights_status, 'unknown'); self.assertEqual(asset.rights_validity, 'unknown')
            self.assertIsNone(asset.rights_evidence_id)
            self.assertEqual(asset.provenance['reviews']['clinical'], 'pending')
        drafts = Activity.objects.filter(pk__in=result['record']['activity_ids'])
        for draft in drafts:
            self.assertFalse(draft.is_demo); self.assertEqual(draft.state, 'draft'); self.assertFalse(draft.usable)
            self.assertEqual(draft.media_manifest, {}); self.assertFalse(draft.reviews.exists())
            self.assertNotIn('mit', draft.rights.lower()); self.assertNotIn('vector', draft.rights.lower())
            self.assertIn('pending review', draft.rights); self.assertIn('No image licence', draft.rights)
            self.assertEqual(draft.item_metadata['a']['familiarity']['status'], 'pending')
            self.assertNotIn('evidence', draft.item_metadata['a']['familiarity'])
            self.assertTrue(draft.image_a.startswith('editorial/asset-'))
            self.assertTrue(draft.image_available(draft.image_a))
            draft.state = 'published'
            with self.assertRaises(ValidationError): draft.save()
        self.assertEqual(install_pack(self.actor, self.source_dir, apply=True)['status'], 'already_imported')
        self.assertEqual(Activity.objects.count(), 6); self.assertEqual(MediaAsset.objects.count(), 18)
        receipt = GeneratedReviewPackImport.objects.get(pack_id=PACK_ID)
        receipt.record = {}
        with self.assertRaises(ValidationError): receipt.save()

    def test_webp_variants_have_manifest_dimensions_weights_and_whole_frame_derivation(self):
        for concept in self.manifest['concepts']:
            for size, record in concept['display_variants'].items():
                data = (self.pack_dir / record['file']).read_bytes()
                from django.core.files.base import ContentFile
                metadata = validate_media(ContentFile(data, name=record['file']), 'image')
                self.assertEqual(metadata['format'], 'WEBP')
                self.assertEqual((metadata['width'], metadata['height']), (int(size), int(size)))
                self.assertEqual(metadata['sha256'], record['sha256'])
                self.assertLess(len(data), 60_000)
                self.assertIn('no crop', record['derivation'])
        self.assertEqual(sum(record['bytes'] for concept in self.manifest['concepts'] for record in concept['display_variants'].values()), 202100)

    def test_sources_and_small_variants_are_protected_for_same_variety_reviewers(self):
        result = install_pack(self.actor, self.source_dir, apply=True)
        media = result['record']['media']['bread-v1']
        for role, expected in [(self.actor, 200), (self.viewer, 200), (self.outsider, 404)]:
            self.client.force_login(role)
            for variant in ['source', '512', '256']:
                response = self.client.get(reverse('editorial_media', args=[media[variant]['id']]))
                self.assertEqual(response.status_code, expected)
                if expected == 200:
                    self.assertEqual(response.headers['Content-Type'], 'image/png' if variant == 'source' else 'image/webp')
                    self.assertIn('no-store', response.headers['Cache-Control'])
        self.client.logout()
        self.assertEqual(self.client.get(reverse('editorial_media', args=[media['512']['id']])).status_code, 302)
        srcset = editorial_image_srcset('editorial/asset-' + media['512']['id'])
        self.assertIn('/media/' + media['256']['id'] + '/ 256w', srcset)
        self.assertIn('/media/' + media['512']['id'] + '/ 512w', srcset)

    def test_source_or_manifest_change_cannot_silently_reimport_or_replace_files(self):
        result = install_pack(self.actor, self.source_dir, apply=True)
        source = self.source_dir / self.manifest['concepts'][0]['source']['file']
        original = source.read_bytes(); source.write_bytes(b'Changed PNG')
        with self.assertRaises(ValidationError): install_pack(self.actor, self.source_dir, apply=True)
        source.write_bytes(original)
        asset = MediaAsset.objects.get(pk=result['record']['media']['bread-v1']['512']['id'])
        with asset.file.storage.open(asset.file.name, 'wb') as stream: stream.write(b'Out-of-band change')
        with self.assertRaises(ValidationError): install_pack(self.actor, self.source_dir, apply=True)
        self.assertEqual(Activity.objects.count(), 6)

    def test_failure_rolls_back_drafts_and_removes_only_new_private_files(self):
        with patch('catalog.generated_pack.clone_version', side_effect=ValidationError('Fictional rollback')):
            with self.assertRaises(ValidationError): install_pack(self.actor, self.source_dir, apply=True)
        self.assertEqual(Activity.objects.count(), 3); self.assertEqual(MediaAsset.objects.count(), 0)
        self.assertFalse(GeneratedReviewPackImport.objects.exists())
        self.assertFalse(any(path.is_file() for path in (self.base / 'private').rglob('*')))
        self.assertEqual(len(list(self.source_dir.glob('*.png'))), 6)

    def test_complex_onset_and_reserve_boundary_remain_explicit(self):
        result = install_pack(self.actor, self.source_dir, apply=True)
        complex_draft = Activity.objects.get(pk=next(row['id'] for row in result['record']['activities'] if row['words'] == ['poire', 'boire']))
        simple_draft = Activity.objects.get(pk=next(row['id'] for row in result['record']['activities'] if row['words'] == ['pain', 'bain']))
        complex_scope = complex_draft.item_metadata['a']['review_pack']['proposed_target_scope']
        self.assertEqual(complex_scope['context'], 'complex_onset_pw_bw')
        self.assertNotEqual(complex_scope, simple_draft.item_metadata['a']['review_pack']['proposed_target_scope'])
        held_out = self.manifest['reservation_boundary']['held_out_words_not_generated_or_family_assigned']
        words = [concept['word'] for concept in self.manifest['concepts']]
        self.assertFalse(set(words) & set(held_out))
        for cid in ['bath-v1', 'sphere-v1', 'drinking-v1']:
            self.assertTrue(next(concept for concept in self.manifest['concepts'] if concept['id'] == cid)['qa']['review_flags'])

    def test_claimed_approval_or_wrong_source_series_is_rejected_before_any_write(self):
        self.manifest['concepts'][0]['reviews']['clinical'] = 'approved'; self.write_manifest()
        with self.assertRaises(ValidationError): install_pack(self.actor, self.source_dir, apply=True)
        self.assertFalse(MediaAsset.objects.exists())
        self.manifest['concepts'][0]['reviews']['clinical'] = 'pending'
        self.manifest['pairs'][0]['source_series'] = str(uuid.uuid4()); self.write_manifest()
        with self.assertRaises(ValidationError): install_pack(self.actor, self.source_dir, apply=True)
        self.assertFalse(MediaAsset.objects.exists())


    def test_real_editorial_template_renders_protected_srcsets_and_legacy_has_no_extra_lookup(self):
        result = install_pack(self.actor, self.source_dir, apply=True)
        media = result['record']['media']['bread-v1']
        activity = next(row for row in result['record']['activities'] if row['words'] == ['pain', 'bain'])
        self.client.force_login(self.actor)
        response = self.client.get(reverse('editorial_detail', args=[activity['id']]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'srcset="/fr/media/' + media['256']['id'] + '/ 256w, /fr/media/' + media['512']['id'] + '/ 512w"')
        self.assertContains(response, 'sizes="(max-width: 700px) 130px, 160px"')
        with self.assertNumQueries(0):
            self.assertEqual(editorial_image_srcset('editorial/bread.svg'), '')
            self.assertEqual(editorial_image_srcset('editorial/asset-' + str(uuid.uuid4())), '')
        # The actual ordinary-source editorial page keeps its historical src URL.
        source_response = self.client.get(reverse('editorial_detail', args=[self.sources[0].pk]))
        self.assertEqual(source_response.status_code, 200)
        self.assertContains(source_response, 'srcset=""')


class GeneratedReviewPackBundleTests(SimpleTestCase):
    def test_versioned_full_sources_and_webp_derivatives_match_the_manifest(self):
        pack_dir = Path(settings.BASE_DIR) / 'content' / 'review_packs' / PACK_ID
        manifest, _, payloads = generated_pack.load_pack(pack_dir / 'sources')
        self.assertEqual(len(payloads), 18)
        self.assertFalse(manifest['clinical_approval'])
        self.assertFalse(manifest['linguistic_approval'])
        self.assertFalse(manifest['familiarity_trial_performed'])
        self.assertEqual(manifest['rights_status'], 'unknown')
        for concept in manifest['concepts']:
            source = pack_dir / 'sources' / concept['source']['file']
            self.assertEqual(source.stat().st_size, concept['source']['bytes'])
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), concept['source']['sha256'])
