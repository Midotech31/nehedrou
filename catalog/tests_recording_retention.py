"""Synthetic WAV uploads only; no microphone, real voice or clinical approval."""
import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event
from unittest import skipUnless
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, OperationalError, close_old_connections, connection, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from core.models import AuditEvent
from qualification.models import AvailabilityDecision
from .models import EditorialGrant, MediaAsset, MediaUploadReceipt, Review
from .tests_guided_audio import GuidedAudioFixture, SETTINGS, recording


@override_settings(**SETTINGS)
class RecordingRetentionTests(GuidedAudioFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.key = uuid.uuid4()
        self.token = self.capture()[0]

    def retained(self, *, key=None, client=None, data=None, audio=None):
        payload = {'upload_attempt':str(key or self.key), 'draft':str(self.activity.pk),
            'audio_side':'a','guided_context':self.token,'kind':'audio',
            'audio_variety':str(self.variety.pk),'audio_text':self.activity.word_a,
            'audio_source':'human','rights':'Fictional recording; permissions pending',
            'rights_status':'unknown',
            'file':SimpleUploadedFile('software-fixture.wav',audio or recording())}
        payload.update(data or {})
        return (client or self.client).post('/en/editorial/upload/',payload,
            HTTP_X_NEHEDROU_RECORDING_RETENTION='1',HTTP_ACCEPT='application/json')

    def test_validation_error_then_corrected_explicit_save_creates_only_one_media(self):
        invalid=self.retained(data={'audio_text':'different word'})
        self.assertEqual(invalid.status_code,422)
        self.assertEqual(invalid.json()['status'],'invalid')
        self.assertIn('audio_text',[row['field'] for row in invalid.json()['errors']])
        self.assertFalse(MediaAsset.objects.exists());self.assertFalse(MediaUploadReceipt.objects.exists())
        success=self.retained()
        self.assertEqual(success.status_code,200)
        self.assertEqual(success.json()['status'],'saved')
        self.assertEqual(MediaAsset.objects.count(),1)
        receipt=MediaUploadReceipt.objects.get()
        self.assertEqual(receipt.asset.technical_metadata['sha256'],hashlib.sha256(recording()).hexdigest())
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.audio_a,'')
        self.assertFalse(Review.objects.exists());self.assertFalse(AvailabilityDecision.objects.exists())

    def test_storage_failure_can_retry_same_attempt_without_receipt_or_success_audit(self):
        with patch('catalog.media_authoring.MediaAuthoringForm.save',side_effect=OSError('private provider detail')):
            failed=self.retained()
        self.assertEqual(failed.status_code,503)
        self.assertEqual(failed.json()['status'],'retry')
        self.assertNotIn('private provider detail',failed.content.decode())
        self.assertFalse(MediaAsset.objects.exists());self.assertFalse(MediaUploadReceipt.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action='catalog.media_uploaded').exists())
        self.assertEqual(self.retained().json()['status'],'saved')
        self.assertEqual(MediaUploadReceipt.objects.count(),1)

    def test_lost_success_response_replay_reuses_exact_receipt_and_media(self):
        first=self.retained()
        second=self.retained()
        self.assertEqual(second.status_code,200)
        self.assertTrue(second.json()['replayed'])
        self.assertEqual(first.json()['result_url'],second.json()['result_url'])
        self.assertEqual(MediaAsset.objects.count(),1);self.assertEqual(MediaUploadReceipt.objects.count(),1)
        self.assertEqual(AuditEvent.objects.filter(action='catalog.media_uploaded').count(),1)

    def test_same_key_changed_fields_or_bytes_never_creates_a_second_media(self):
        first=self.retained()
        for changed in [{'data':{'rights':'changed attempted rights'}},{'audio':recording(quiet=True)}]:
            with self.subTest(changed=list(changed)):
                conflict=self.retained(**changed)
                self.assertEqual(conflict.status_code,409)
                self.assertEqual(conflict.json()['status'],'conflict')
                self.assertEqual(conflict.json()['result_url'],first.json()['result_url'])
        self.assertEqual(MediaAsset.objects.count(),1)

    def test_foreign_receipt_collision_reveals_no_saved_result_or_file(self):
        first=self.retained()
        foreign=Client();foreign.force_login(self.other)
        payload={'guided_context':'','draft':'','audio_side':'',
                 'audio_variety':str(self.other_variety.pk),'audio_text':'different'}
        collision=self.retained(client=foreign,data=payload)
        self.assertEqual(collision.status_code,409)
        self.assertNotIn('result_url',collision.json())
        self.assertEqual(foreign.get(first.json()['result_url']).status_code,404)
        self.assertEqual(MediaAsset.objects.count(),1)

    def test_result_is_private_get_only_and_does_not_associate_or_create_records(self):
        success=self.retained();url=success.json()['result_url']
        counts=(MediaAsset.objects.count(),MediaUploadReceipt.objects.count(),AuditEvent.objects.count())
        result=self.client.get(url)
        self.assertEqual(result.status_code,200)
        self.assertContains(result,'Link this recording to this draft word')
        self.assertIn('no-store',result['Cache-Control'])
        self.assertEqual(self.client.post(url).status_code,405)
        self.assertEqual(counts,(MediaAsset.objects.count(),MediaUploadReceipt.objects.count(),AuditEvent.objects.count()))
        self.activity.refresh_from_db();self.assertEqual(self.activity.audio_a,'')
        self.assertEqual(self.associate(result).status_code,302)

    def test_current_permission_withdrawal_blocks_retry_and_result_without_new_write(self):
        success=self.retained()
        EditorialGrant.objects.filter(user=self.actor,variety=self.variety).update(edit=False)
        self.assertEqual(self.retained().status_code,403)
        self.assertEqual(self.client.get(success.json()['result_url']).status_code,403)
        self.assertEqual(MediaAsset.objects.count(),1)

    def test_result_never_enables_association_of_revoked_media(self):
        success=self.retained()
        asset=MediaAsset.objects.get();asset.revoked=True;asset.revocation_reason='Fictional withdrawal';asset.save()
        result=self.client.get(success.json()['result_url'])
        self.assertEqual(result.status_code,200)
        self.assertFalse(result.context['can_associate'])
        self.assertNotContains(result,'name="association_token"')

    def test_missing_or_revoked_saved_file_is_never_confirmed_or_replaced_by_replay(self):
        success=self.retained();asset=MediaAsset.objects.get()
        asset.file.storage.delete(asset.file.name)
        response=self.retained()
        self.assertEqual(response.status_code,409)
        self.assertEqual(response.json()['status'],'unavailable')
        self.assertEqual(response.json()['result_url'],success.json()['result_url'])
        self.assertFalse(asset.file.storage.exists(asset.file.name))
        self.assertEqual(MediaAsset.objects.count(),1);self.assertEqual(MediaUploadReceipt.objects.count(),1)
        asset.revoked=True;asset.revocation_reason='Fictional missing-file withdrawal';asset.save()
        self.assertEqual(self.retained().json()['status'],'unavailable')

    def test_unguided_saved_result_also_displays_the_unavailable_file_message(self):
        response=self.retained(data={'guided_context':'','draft':'','audio_side':''})
        asset=MediaAsset.objects.get();asset.file.storage.delete(asset.file.name)
        retry=self.retained(data={'guided_context':'','draft':'','audio_side':''})
        self.assertEqual(retry.json()['status'],'unavailable')
        result=self.client.get(response.json()['result_url'])
        self.assertContains(result,'This recording is revoked, missing or changed.')

    def test_original_capture_fingerprint_survives_the_saved_result_route(self):
        success=self.retained()
        self.activity.title+=' changed';self.activity.save()
        result=self.client.get(success.json()['result_url'])
        self.assertEqual(self.associate(result).status_code,409)
        self.activity.refresh_from_db();self.assertEqual(self.activity.audio_a,'')

    def test_expired_original_capture_cannot_be_refreshed_by_the_result_route(self):
        success=self.retained()
        with patch('catalog.guided_audio.CONTEXT_MAX_AGE',-1):
            result=self.client.get(success.json()['result_url'])
        self.assertFalse(result.context['can_associate'])
        self.assertNotContains(result,'name="association_token"')

    def test_receipts_are_immutable_and_cannot_reference_another_uploaders_asset(self):
        self.retained();receipt=MediaUploadReceipt.objects.get()
        receipt.payload_digest='a'*64
        with self.assertRaises(ValidationError):receipt.save()
        foreign=self.old_take();foreign.uploaded_by=self.other;foreign.save()
        with self.assertRaises(ValidationError):
            MediaUploadReceipt.objects.create(actor=self.actor,asset=foreign,payload_digest='a'*64)

    def test_receipt_failure_rolls_back_media_audit_and_only_its_new_storage_file(self):
        old=self.old_take();old_bytes=old.file.read();old.file.close()
        names=[]
        original=MediaAsset.save
        def observed(asset,*args,**kwargs):
            value=original(asset,*args,**kwargs)
            names.append((asset.file.storage,asset.file.name))
            return value
        with patch.object(MediaAsset,'save',observed),patch('catalog.recording_retention.MediaUploadReceipt.objects.create',side_effect=IntegrityError('synthetic receipt failure')):
            response=self.retained()
        self.assertEqual(response.status_code,503)
        self.assertEqual(MediaAsset.objects.count(),1)
        self.assertFalse(MediaUploadReceipt.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action='catalog.media_uploaded').exists())
        self.assertTrue(names);self.assertTrue(all(not storage.exists(name) for storage,name in names))
        old.file.open('rb');self.assertEqual(old.file.read(),old_bytes)

    def test_normal_file_import_keeps_html_path_and_no_receipt(self):
        response=self.upload(token=self.token)
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Editorial media saved')
        self.assertFalse(MediaUploadReceipt.objects.exists())

    def test_csrf_still_required_for_enhanced_upload(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.actor)
        self.assertEqual(self.retained(client=client).status_code,403)
        self.assertFalse(MediaAsset.objects.exists());self.assertFalse(MediaUploadReceipt.objects.exists())

    def test_invalid_attempt_key_and_non_audio_are_rejected_without_writes(self):
        self.assertEqual(self.retained(key='invalid').status_code,400)
        self.assertEqual(self.retained(data={'kind':'image'}).status_code,422)
        self.assertFalse(MediaAsset.objects.exists());self.assertFalse(MediaUploadReceipt.objects.exists())

    def test_upload_page_localizes_retention_and_preserves_ordinary_multipart_form(self):
        labels={'fr':'Ouvrir le média sauvegardé','en':'Open saved media','ar':'فتح الوسائط المحفوظة'}
        for language,label in labels.items():
            with self.subTest(language=language):
                response=self.client.get(f'/{language}/editorial/upload/',{'draft':self.activity.pk,'audio_side':'a'})
                self.assertContains(response,'recording-retention.js')
                self.assertContains(response,label)
                self.assertContains(response,'enctype="multipart/form-data"')

    def test_csrf_field_rotation_does_not_duplicate_a_completed_attempt(self):
        first=self.retained(data={'csrfmiddlewaretoken':'fictional-first-token'})
        second=self.retained(data={'csrfmiddlewaretoken':'fictional-second-token'})
        self.assertEqual(second.json()['result_url'],first.json()['result_url'])
        self.assertTrue(second.json()['replayed'])
        self.assertEqual(MediaAsset.objects.count(),1)

    def test_authorised_asset_deletion_cascades_its_technical_receipt(self):
        self.retained();MediaAsset.objects.get().delete()
        self.assertFalse(MediaUploadReceipt.objects.exists())


@override_settings(**SETTINGS)
class RecordingRetentionCommitAckTests(GuidedAudioFixture, TransactionTestCase):
    def test_lost_commit_ack_keeps_the_committed_wav_and_exact_retry_reuses_it(self):
        token=self.capture()[0];key=uuid.uuid4()
        def upload():
            return self.client.post('/en/editorial/upload/',{
                'upload_attempt':str(key),'draft':str(self.activity.pk),
                'audio_side':'a','guided_context':token,'kind':'audio',
                'audio_variety':str(self.variety.pk),'audio_text':self.activity.word_a,
                'audio_source':'human','rights':'Fictional test only','rights_status':'unknown',
                'file':SimpleUploadedFile('synthetic.wav',recording())},
                HTTP_X_NEHEDROU_RECORDING_RETENTION='1')
        real_commit=connection.commit;lost=False
        def committed_but_lost():
            nonlocal lost
            real_commit()
            if not lost:
                lost=True
                raise OperationalError('synthetic lost commit reply')
        with patch.object(connection,'commit',committed_but_lost):
            response=upload()
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.json()['status'],'uncertain')
        self.assertEqual(MediaAsset.objects.count(),1);self.assertEqual(MediaUploadReceipt.objects.count(),1)
        self.assertEqual(AuditEvent.objects.filter(action='catalog.media_uploaded').count(),1)
        asset=MediaAsset.objects.get();self.assertTrue(asset.intact)
        retry=upload()
        self.assertEqual(retry.status_code,200);self.assertTrue(retry.json()['replayed'])
        self.assertTrue(MediaAsset.objects.get().intact)
        self.assertEqual(MediaAsset.objects.count(),1)


@skipUnless(connection.vendor=='postgresql','Requires PostgreSQL row locks for upload/grant ordering')
@override_settings(**SETTINGS)
class RecordingRetentionConcurrencyTests(GuidedAudioFixture, TransactionTestCase):
    def test_upload_waiting_for_revoked_edit_grant_rechecks_and_writes_nothing(self):
        from . import recording_retention
        token=self.capture()[0]
        entered=Event()
        original=recording_retention._require_editor
        def observed(*args,**kwargs):
            if kwargs.get('lock'):entered.set()
            return original(*args,**kwargs)
        def upload():
            close_old_connections()
            try:
                return self.client.post('/en/editorial/upload/',{
                    'upload_attempt':str(uuid.uuid4()),'draft':str(self.activity.pk),
                    'audio_side':'a','guided_context':token,'kind':'audio',
                    'audio_variety':str(self.variety.pk),'audio_text':self.activity.word_a,
                    'audio_source':'human','rights':'Fictional test only','rights_status':'unknown',
                    'file':SimpleUploadedFile('synthetic.wav',recording())},
                    HTTP_X_NEHEDROU_RECORDING_RETENTION='1').status_code
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool,patch.object(recording_retention,'_require_editor',observed):
            with transaction.atomic():
                grant=EditorialGrant.objects.select_for_update().get(user=self.actor,variety=self.variety)
                grant.edit=False;grant.save()
                future=pool.submit(upload)
                self.assertTrue(entered.wait(5),'Upload reached the fresh locked permission check')
                with self.assertRaises(TimeoutError):future.result(timeout=.15)
            self.assertEqual(future.result(timeout=5),403)
        self.assertFalse(MediaAsset.objects.exists());self.assertFalse(MediaUploadReceipt.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action='catalog.media_uploaded').exists())
