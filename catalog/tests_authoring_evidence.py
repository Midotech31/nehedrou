"""Guided references use actual private fixture bytes; no human result is inferred."""
import tempfile
import json
from pathlib import Path
from datetime import timedelta
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation
from catalog.authoring import ActivityAuthoringForm
from catalog.models import Activity, EditorialGrant, Review, Variety
from core.models import User
from qualification.models import EvidenceDocument


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False)
class GuidedActivityEvidenceTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='nehedrou-guided-proof-')
        self.addCleanup(directory.cleanup)
        self.media = Path(directory.name)
        settings = override_settings(MEDIA_ROOT=self.media)
        settings.enable()
        self.addCleanup(settings.disable)
        self.author = User.objects.create_user(username='proof-author')
        self.variety = Variety.objects.create(code='ar-dz-pilot', language='ar', label='Darja')
        self.other = Variety.objects.create(code='fr-fr-pilot', language='fr', label='French')
        self.foreign = Variety.objects.create(code='en-us-pilot', language='en', label='English')
        EditorialGrant.objects.create(user=self.author, variety=self.variety, edit=True)
        EditorialGrant.objects.create(user=self.author, variety=self.other, linguistic_review=True)
        self.proof = self.document(self.variety)

    def document(self, variety, **extra):
        values = dict(variety=variety, title='Technical familiarity fixture', category='familiarity',
            file=ContentFile(b'Technical test bytes only. No familiarity study or clinical validation.', name='fixture.txt'),
            provenance='Local software fixture only, not a human result.', uploaded_by=self.author,
            validity='unlimited')
        values.update(extra)
        return EvidenceDocument.objects.create(**values)

    def data(self, **extra):
        values = dict(variety=str(self.variety.pk), title='Original fictional activity',
            kind='vocabulary', response_mode='matching', contrast='Home',
            word_a='دار', word_b='باب', meaning_a='Home', meaning_b='Door',
            segments_a='d a r', segments_b='b a b', is_demo='on')
        values.update(extra)
        return values

    def form(self, **extra):
        return ActivityAuthoringForm(self.data(**extra), actor=self.author)

    def existing(self, sha=None):
        form = self.form()
        self.assertTrue(form.is_valid(), form.errors)
        activity = form.save()
        activity.item_metadata['a'].update(
            familiarity={'evidence':str(self.proof.pk), 'sha256':sha or self.proof.sha256,
                         'note':'Recorded note', 'method':'Do not discard this authored field'},
            accepted_variants=[{'ipa':'daːr', 'reason':'Fictional variant awaiting review'}],
            local_review={'status':'pending'})
        activity.save()
        return activity

    def test_new_form_offers_only_existing_private_familiarity_documents(self):
        other = self.document(self.other)
        foreign = self.document(self.foreign)
        rights = self.document(self.variety, category='rights')
        revoked = self.document(self.variety, revoked=True, revocation_reason='Technical fixture withdrawn')
        form = ActivityAuthoringForm(actor=self.author)
        choices = form.fields['familiarity_evidence_a']
        self.assertEqual(set(choices.queryset.values_list('pk', flat=True)), {self.proof.pk, other.pk})
        self.assertNotIn(foreign.pk, choices.queryset.values_list('pk', flat=True))
        self.assertNotIn(rights.pk, choices.queryset.values_list('pk', flat=True))
        self.assertNotIn(revoked.pk, choices.queryset.values_list('pk', flat=True))
        self.assertIn(str(self.other.display_label), choices.label_from_instance(other))

    def test_selection_binds_exact_server_fingerprint_without_approving_content(self):
        form = self.form(familiarity_evidence_a=str(self.proof.pk), familiarity_a='Actual reference supplied for human review')
        self.assertTrue(form.is_valid(), form.errors)
        activity = form.save()
        self.assertEqual(activity.item_metadata['a']['familiarity'], {
            'evidence':str(self.proof.pk), 'sha256':self.proof.sha256,
            'note':'Actual reference supplied for human review'})
        self.assertEqual(activity.state, 'draft')
        self.assertFalse(activity.usable)
        self.assertFalse(activity.has_current_reviews())
        self.assertFalse(Review.objects.exists())
        self.assertEqual(EvidenceDocument.objects.count(), 1)

    def test_forged_other_variety_or_category_or_unshared_reference_is_rejected(self):
        documents = [self.document(self.other), self.document(self.foreign), self.document(self.variety, category='rights')]
        for document in documents:
            with self.subTest(document=document.pk):
                form = self.form(familiarity_evidence_a=str(document.pk))
                self.assertFalse(form.is_valid())
                self.assertIn('familiarity_evidence_a', form.errors)
        self.assertFalse(Activity.objects.exists())

    def test_revoked_reference_is_rejected(self):
        self.proof.revoked = True
        self.proof.revocation_reason = 'Technical fixture withdrawn'
        self.proof.save()
        form = self.form(familiarity_evidence_a=str(self.proof.pk))
        self.assertFalse(form.is_valid())
        self.assertIn('familiarity_evidence_a', form.errors)

    def test_expired_and_changed_or_missing_bytes_are_rejected(self):
        expired = self.document(self.variety, validity='limited',
            valid_until=timezone.localdate() - timedelta(days=1))
        changed = self.document(self.variety)
        missing = self.document(self.variety)
        changed_path = Path(changed.file.path)
        missing_path = Path(missing.file.path)
        self.assertTrue(changed_path.is_relative_to(self.media))
        self.assertTrue(missing_path.is_relative_to(self.media))
        changed_path.write_bytes(b'Altered technical fixture bytes')
        missing_path.unlink()
        for document in [expired, changed, missing]:
            with self.subTest(document=document.pk):
                form = self.form(familiarity_evidence_a=str(document.pk))
                self.assertFalse(form.is_valid())
                self.assertIn('familiarity_evidence_a', form.errors)
        self.assertFalse(Activity.objects.exists())

    def test_legacy_post_preserves_binding_variants_and_extra_metadata(self):
        activity = self.existing()
        before = activity.item_metadata['a'].copy()
        form = ActivityAuthoringForm(self.data(familiarity_a='Updated note'), actor=self.author, instance=activity)
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.item_metadata['a']['familiarity']['evidence'], before['familiarity']['evidence'])
        self.assertEqual(saved.item_metadata['a']['familiarity']['sha256'], before['familiarity']['sha256'])
        self.assertEqual(saved.item_metadata['a']['accepted_variants'], before['accepted_variants'])
        self.assertEqual(saved.item_metadata['a']['local_review'], {'status':'pending'})

    def test_same_selection_does_not_repair_a_stale_fingerprint(self):
        activity = self.existing(sha='0'*64)
        form = ActivityAuthoringForm(self.data(familiarity_evidence_a=str(self.proof.pk)), actor=self.author, instance=activity)
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.item_metadata['a']['familiarity']['sha256'], '0'*64)
        from catalog.readiness import activity_content_reasons
        self.assertTrue(any(saved.word_a in reason for reason in activity_content_reasons(saved)))

    def test_empty_selection_preserves_reference_and_only_explicit_removal_clears_it(self):
        activity = self.existing()
        form = ActivityAuthoringForm(self.data(familiarity_evidence_a='', familiarity_a='Updated'), actor=self.author, instance=activity)
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.item_metadata['a']['familiarity']['sha256'], self.proof.sha256)
        form = ActivityAuthoringForm(self.data(remove_familiarity_evidence_a='on', familiarity_a='Retain the note'), actor=self.author, instance=saved)
        self.assertTrue(form.is_valid(), form.errors)
        cleared = form.save().item_metadata['a']['familiarity']
        self.assertNotIn('evidence', cleared)
        self.assertNotIn('sha256', cleared)
        self.assertEqual(cleared['note'], 'Retain the note')
        self.assertEqual(cleared['method'], 'Do not discard this authored field')

    def test_changing_selected_document_binds_new_bytes_and_preserves_authored_metadata(self):
        activity = self.existing()
        replacement = self.document(self.variety)
        form = ActivityAuthoringForm(self.data(familiarity_evidence_a=str(replacement.pk)), actor=self.author, instance=activity)
        self.assertTrue(form.is_valid(), form.errors)
        proof = form.save().item_metadata['a']['familiarity']
        self.assertEqual(proof['evidence'], str(replacement.pk))
        self.assertEqual(proof['sha256'], replacement.sha256)
        self.assertEqual(proof['method'], 'Do not discard this authored field')

    def test_guided_variants_accept_ipa_and_explicit_reason_and_can_be_cleared(self):
        form = self.form(variants_a='daːr ; Fictional local variant awaiting review\ndɑr ; Another authored proposal')
        self.assertTrue(form.is_valid(), form.errors)
        activity = form.save()
        self.assertEqual(activity.item_metadata['a']['accepted_variants'], [
            {'ipa':'daːr','reason':'Fictional local variant awaiting review'},
            {'ipa':'dɑr','reason':'Another authored proposal'}])
        form = ActivityAuthoringForm(self.data(variants_a=''), actor=self.author, instance=activity)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().item_metadata['a']['accepted_variants'], [])

    def test_variant_rows_need_both_ipa_and_reason(self):
        for value in ['missing separator', ' ; No IPA', 'daːr ; ']:
            with self.subTest(value=value):
                form = self.form(variants_a=value)
                self.assertFalse(form.is_valid())
                self.assertIn('variants_a', form.errors)
        self.assertFalse(Activity.objects.exists())

    def test_all_ui_languages_expose_guided_fields_and_safe_upload_link(self):
        self.client.force_login(self.author)
        for language in ['fr', 'en', 'ar']:
            response = self.client.get(f'/{language}/editorial/new/')
            self.assertEqual(response.status_code, 200)
            for name in ['familiarity_evidence_a', 'familiarity_evidence_b', 'remove_familiarity_evidence_a', 'variants_a', 'variants_b']:
                self.assertContains(response, 'name="' + name + '"')
            self.assertContains(response, 'href="/' + language + '/qualification/evidence/new/" target="_blank" rel="noopener"')
            self.assertContains(response, 'dir="auto"')
            self.assertNotContains(response, 'Editorial static path')

    def test_reviewer_cannot_create_or_attach_a_reference_through_http(self):
        EditorialGrant.objects.filter(user=self.author, variety=self.variety).update(edit=False, clinical_review=True)
        self.client.force_login(self.author)
        response = self.client.post('/fr/editorial/new/', self.data(familiarity_evidence_a=str(self.proof.pk)))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Activity.objects.exists())

    def test_unchanged_variant_projection_preserves_extra_metadata_but_edit_drops_it(self):
        activity = self.existing()
        activity.item_metadata['a']['accepted_variants'][0].update(region='Fictional region', evidence='Historical reference')
        activity.save()
        form = ActivityAuthoringForm(self.data(variants_a='daːr ; Fictional variant awaiting review'), actor=self.author, instance=activity)
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.item_metadata['a']['accepted_variants'][0]['region'], 'Fictional region')
        self.assertEqual(saved.item_metadata['a']['accepted_variants'][0]['evidence'], 'Historical reference')
        form = ActivityAuthoringForm(self.data(variants_a='daːr ; Changed rationale awaiting review'), actor=self.author, instance=saved)
        self.assertTrue(form.is_valid(), form.errors)
        edited = form.save().item_metadata['a']['accepted_variants']
        self.assertEqual(edited, [{'ipa':'daːr', 'reason':'Changed rationale awaiting review'}])

    def test_autosaved_new_fields_resume_and_save_without_new_authority(self):
        self.client.force_login(self.author)
        page = self.client.get('/fr/editorial/new/')
        working_id = page.context['working_id']
        fields = self.data(familiarity_evidence_a=str(self.proof.pk), variants_a='daːr ; Fictional proposal')
        response = self.client.post(reverse('editorial_autosave', args=[working_id]),
            json.dumps({'fields':fields, 'revision':0, 'activity':'', 'base_digest':''}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        resumed = self.client.get(response.json()['resume_url'])
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(resumed.context['form']['familiarity_evidence_a'].value(), str(self.proof.pk))
        self.assertEqual(resumed.context['form']['variants_a'].value(), 'daːr ; Fictional proposal')
        saved_response = self.client.post('/fr/editorial/new/', {**fields, 'working_copy':str(working_id), 'content_baseline':''})
        self.assertEqual(saved_response.status_code, 302)
        activity = Activity.objects.get()
        self.assertEqual(activity.item_metadata['a']['familiarity']['sha256'], self.proof.sha256)
        self.assertEqual(activity.item_metadata['a']['accepted_variants'], [{'ipa':'daːr','reason':'Fictional proposal'}])
        self.assertEqual(activity.state, 'draft')
        self.assertFalse(Review.objects.exists())

    def test_empty_reference_label_describes_a_new_activity(self):
        form = ActivityAuthoringForm(actor=self.author)
        with translation.override('en'):
            self.assertEqual(str(form.fields['familiarity_evidence_a'].empty_label), 'No evidence has been supplied.')

    def test_normalizing_uuid_spelling_does_not_repair_the_recorded_hash(self):
        activity = self.existing(sha='0'*64)
        activity.item_metadata['a']['familiarity']['evidence'] = str(self.proof.pk).upper()
        activity.save()
        form = ActivityAuthoringForm(self.data(familiarity_evidence_a=str(self.proof.pk)), actor=self.author, instance=activity)
        self.assertTrue(form.is_valid(), form.errors)
        proof = form.save().item_metadata['a']['familiarity']
        self.assertEqual(proof['sha256'], '0'*64)
        self.assertEqual(proof['evidence'], str(self.proof.pk).upper())

    def test_editing_one_variant_and_reordering_preserve_only_exact_unchanged_content(self):
        activity = self.existing()
        activity.item_metadata['a']['accepted_variants'] = [
            {'ipa':'daːr', 'reason':'First authored proposal', 'region':'Region one', 'evidence':'First reference'},
            {'ipa':'dɑr', 'reason':'Second authored proposal', 'region':'Region two', 'evidence':'Second reference'}]
        activity.save()
        form = ActivityAuthoringForm(self.data(variants_a='daːr ; First authored proposal\ndɑr ; Changed second rationale\ndɛr ; New proposal'), actor=self.author, instance=activity)
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.item_metadata['a']['accepted_variants'], [
            {'ipa':'daːr', 'reason':'First authored proposal', 'region':'Region one', 'evidence':'First reference'},
            {'ipa':'dɑr', 'reason':'Changed second rationale'},
            {'ipa':'dɛr', 'reason':'New proposal'}])
        form = ActivityAuthoringForm(self.data(variants_a='dɑr ; Changed second rationale\ndaːr ; First authored proposal\ndɛr ; New proposal'), actor=self.author, instance=saved)
        self.assertTrue(form.is_valid(), form.errors)
        reordered = form.save().item_metadata['a']['accepted_variants']
        self.assertEqual(reordered, [
            {'ipa':'dɑr', 'reason':'Changed second rationale'},
            {'ipa':'daːr', 'reason':'First authored proposal', 'region':'Region one', 'evidence':'First reference'},
            {'ipa':'dɛr', 'reason':'New proposal'}])

    def test_identical_variants_consume_historical_metadata_once_in_original_order(self):
        activity = self.existing()
        activity.item_metadata['a']['accepted_variants'] = [
            {'ipa':'daːr', 'reason':'Same authored proposal', 'evidence':'First reference'},
            {'ipa':'daːr', 'reason':'Same authored proposal', 'evidence':'Second reference'}]
        activity.save()
        form = ActivityAuthoringForm(self.data(variants_a='daːr ; Same authored proposal\ndaːr ; Same authored proposal\ndaːr ; Same authored proposal'), actor=self.author, instance=activity)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().item_metadata['a']['accepted_variants'], [
            {'ipa':'daːr', 'reason':'Same authored proposal', 'evidence':'First reference'},
            {'ipa':'daːr', 'reason':'Same authored proposal', 'evidence':'Second reference'},
            {'ipa':'daːr', 'reason':'Same authored proposal'}])
