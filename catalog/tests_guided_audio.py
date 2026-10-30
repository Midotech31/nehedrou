"""Fictional word-specific audio collection; no microphone or native voice is used."""
from concurrent.futures import ThreadPoolExecutor
import copy
from datetime import date
import io
from queue import Queue
import time
from unittest import skipUnless
from unittest.mock import patch
import uuid
import wave

from django.conf import settings
from django.core import signing
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connection, connections, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from catalog.guided_audio import ASSOCIATION_SALT, CONTEXT_MAX_AGE
from catalog.models import Activity, EditorialGrant, MediaAsset, Review, Variety
from core.models import AuditEvent, User
from qualification.models import AvailabilityDecision


SETTINGS = dict(DEMO_MODE=True, MFA_REQUIRED=False, PUBLIC_ORIGIN='https://canonical.operator.tld',
    ALLOWED_HOSTS=['testserver','allowed-alias.operator.tld'],
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={'default':{'BACKEND':'django.core.files.storage.InMemoryStorage'},
        'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}})


def recording(*, silent=False, quiet=False):
    output = io.BytesIO()
    with wave.open(output, 'wb') as stream:
        stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(8000)
        frame = (0 if silent else 10 if quiet else 5000).to_bytes(2,'little',signed=True)
        stream.writeframes(frame*800)
    return output.getvalue()


class GuidedAudioFixture:
    def setUp(self):
        super().setUp()
        self.variety = Variety.objects.create(code='ar-dz-pilot', language='ar', label='Fictional Darja')
        self.other_variety = Variety.objects.create(code='ar-msa-pilot', language='ar', label='Fictional MSA')
        self.actor = User.objects.create_user(username='guided-editor', email='guided-editor@example.test')
        self.other = User.objects.create_user(username='guided-other', email='guided-other@example.test')
        EditorialGrant.objects.create(user=self.actor,variety=self.variety,edit=True)
        EditorialGrant.objects.create(user=self.other,variety=self.other_variety,edit=True)
        self.activity = Activity.objects.create(variety=self.variety,series=uuid.uuid4(),kind='vocabulary',
            title='Fictional collection draft',contrast='Fictional household prompts',word_a='دار',word_b='باب',
            transcription_a='/daːr/',transcription_b='/baːb/',instructions={'fr':'Fictif'},is_demo=False,
            item_metadata={'a':{'meaning':'maison (proposition de travail)','meaning_language':'fr'},
                'b':{'meaning':'porte (proposition de travail)','meaning_language':'fr'}})
        self.client.force_login(self.actor)

    def capture(self, side='a', client=None):
        client = client or self.client
        response = client.get('/en/editorial/upload/', {'draft':self.activity.pk,'audio_side':side})
        self.assertEqual(response.status_code,200)
        return response.context['guided']['capture_token'], response

    def upload(self, *, side='a', token=None, client=None, data=None, audio=None):
        client = client or self.client
        token = token or self.capture(side,client)[0]
        payload = {'draft':str(self.activity.pk),'audio_side':side,'guided_context':token,
            'kind':'audio','audio_variety':str(self.variety.pk),'audio_text':getattr(self.activity,'word_'+side),
            'audio_source':'human','rights':'Fictional recording; permissions pending',
            'rights_status':'unknown','file':SimpleUploadedFile('software-fixture.wav',audio or recording())}
        payload.update(data or {})
        return client.post('/en/editorial/upload/',payload,HTTP_HOST='allowed-alias.operator.tld')

    def associate(self, saved, *, client=None, side='a', activity=None, payload=None):
        values = {'association_token':saved.context['association_token'],'asset_id':str(saved.context['asset'].pk)}
        values.update(payload or {})
        return (client or self.client).post(reverse('editorial_audio_associate',args=[(activity or self.activity).pk,side]),values)

    def old_take(self):
        return MediaAsset.objects.create(kind='audio',uploaded_by=self.actor,
            file=SimpleUploadedFile('older-software-fixture.wav',recording()),rights='Fictional old take pending',
            provenance={'audio':{'text':self.activity.word_a,'variety':self.variety.code,'source':'human'}})


@override_settings(**SETTINGS)
class GuidedAudioCollectionTests(GuidedAudioFixture, TestCase):
    def test_context_get_is_read_only_prefills_actual_word_variety_and_no_voice_source(self):
        before = (Activity.objects.count(),MediaAsset.objects.count(),AuditEvent.objects.count())
        token,page = self.capture()
        form = page.context['form']
        self.assertEqual(form.initial['audio_text'],self.activity.word_a)
        self.assertEqual(str(form.initial['audio_variety']),str(self.variety.pk))
        self.assertEqual(form.initial['kind'],'audio')
        self.assertFalse(form.initial.get('audio_source'))
        self.assertContains(page,'lang="ar-DZ" dir="rtl"')
        self.assertContains(page,'lang="fr" dir="ltr">maison')
        self.assertContains(page,'lang="und-fonipa" dir="ltr"')
        self.assertContains(page,'name="guided_context"')
        self.assertNotContains(page,'autoplay')
        self.assertEqual(page['Cache-Control'],'private, no-store')
        self.assertEqual(before,(Activity.objects.count(),MediaAsset.objects.count(),AuditEvent.objects.count()))
        signed = signing.loads(token,salt='catalog.guided-audio.capture.v1')
        self.assertEqual(signed['fingerprint'],self.activity.fingerprint())
        for code in ('fr','en','ar'):
            response=self.client.get('/'+code+'/editorial/'+str(self.activity.pk)+'/edit/')
            self.assertContains(response,'audio_side=a')
            self.assertContains(response,'audio_side=b')

    def test_upload_and_get_saved_media_never_attach_then_explicit_post_changes_only_one_slot(self):
        old = self.old_take()
        self.activity.audio_a=settings.PUBLIC_ORIGIN+'/fr/media/'+str(old.pk)+'/'
        self.activity.media_manifest={'retained':'software fixture only'}
        self.activity.save()
        before=Activity.objects.values().get(pk=self.activity.pk)
        saved=self.upload()
        self.assertEqual(saved.status_code,200)
        asset=saved.context['asset']
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.audio_a,before['audio_a'])
        self.assertTrue(asset.intact)
        self.assertFalse(asset.documented)
        self.assertIn('https://canonical.operator.tld/',saved.context['media_reference'])
        self.assertNotContains(saved,'allowed-alias.operator.tld')
        self.assertContains(saved,'class="content-fingerprint"')
        self.assertLess(saved.content.index(b'data-audio-player'),saved.content.index(b'name="association_token"'))
        response=self.associate(saved)
        self.assertEqual(response.status_code,302)
        after=Activity.objects.values().get(pk=self.activity.pk)
        changed={key for key in before if before[key]!=after[key]}
        self.assertEqual(changed,{'audio_a'})
        self.assertEqual(after['audio_a'],saved.context['media_reference'])
        self.assertEqual(after['state'],'draft')
        self.assertEqual(after['media_manifest'],before['media_manifest'])
        self.assertTrue(MediaAsset.objects.get(pk=old.pk).intact)
        self.assertEqual(MediaAsset.objects.count(),2)
        self.assertFalse(Review.objects.exists())
        self.assertFalse(AvailabilityDecision.objects.exists())
        self.assertEqual(AuditEvent.objects.filter(action='catalog.audio_associated',object_id=str(self.activity.pk)).count(),1)

    def test_each_side_is_independent_and_stale_second_post_cannot_overwrite(self):
        saved=self.upload(side='b')
        self.assertEqual(self.associate(saved,side='b').status_code,302)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.audio_a,'')
        self.assertEqual(self.activity.audio_b,saved.context['media_reference'])
        self.assertEqual(self.associate(saved,side='b').status_code,409)
        self.assertEqual(MediaAsset.objects.count(),1)

    def test_guided_upload_rejects_different_word_variety_unknown_source_and_silence(self):
        for data,audio,field in [({'audio_text':'different'},None,'audio_text'),
                ({'audio_variety':str(self.other_variety.pk)},None,'audio_variety'),
                ({'audio_source':''},None,'audio_source'),({'audio_source':'unspecified'},None,'audio_source'),
                ({},recording(silent=True),'file')]:
            with self.subTest(field=field,data=data):
                response=self.upload(data=data,audio=audio)
                self.assertEqual(response.status_code,200)
                self.assertIn(field,response.context['form'].errors)
                self.assertEqual(MediaAsset.objects.count(),0)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.audio_a,'')

    def test_unknown_rights_and_very_quiet_signal_remain_unapproved_draft_material(self):
        saved=self.upload(audio=recording(quiet=True))
        self.assertEqual(saved.status_code,200)
        self.assertContains(saved,'very quiet')
        self.assertEqual(self.associate(saved).status_code,302)
        asset=saved.context['asset']
        self.assertFalse(asset.documented)
        self.assertEqual(asset.rights_status,'unknown')
        self.assertEqual(asset.rights_validity,'unknown')
        self.activity.refresh_from_db()
        self.assertFalse(self.activity.usable)
        self.assertFalse(self.activity.has_current_reviews())

    def test_context_tampering_cross_actor_other_target_side_and_asset_are_rejected(self):
        saved=self.upload()
        token=saved.context['association_token']
        self.assertEqual(self.associate(saved,payload={'association_token':token+'bad'}).status_code,400)
        self.assertEqual(self.associate(saved,side='b').status_code,400)
        self.assertEqual(self.associate(saved,payload={'asset_id':str(uuid.uuid4())}).status_code,400)
        another=Activity.objects.create(variety=self.variety,series=uuid.uuid4(),kind='vocabulary',
            title='Other draft',contrast='x',word_a='دار',word_b='باب',instructions={'fr':'Fictif'},is_demo=False)
        self.assertEqual(self.associate(saved,activity=another).status_code,400)
        EditorialGrant.objects.create(user=self.other,variety=self.variety,edit=True)
        other_client=Client();other_client.force_login(self.other)
        self.assertEqual(self.associate(saved,client=other_client).status_code,403)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.audio_a,'')
        self.assertTrue(saved.context['asset'].intact)

    def test_owned_signed_envelope_still_cannot_attach_another_uploaders_media(self):
        saved=self.upload()
        foreign=MediaAsset.objects.create(kind='audio',uploaded_by=self.other,
            file=SimpleUploadedFile('foreign-fixture.wav',recording()),rights='Private fictional media',
            provenance={'audio':{'text':self.activity.word_a,'variety':self.variety.code,'source':'human'}})
        token=signing.dumps({'schema':1,'capture':saved.context['guided']['capture_token'],'asset':str(foreign.pk)},salt=ASSOCIATION_SALT)
        response=self.associate(saved,payload={'association_token':token,'asset_id':str(foreign.pk)})
        self.assertEqual(response.status_code,404)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.audio_a,'')

    def test_get_csrf_and_permissions_cannot_bypass_explicit_post(self):
        saved=self.upload()
        url=reverse('editorial_audio_associate',args=[self.activity.pk,'a'])
        self.assertEqual(self.client.get(url).status_code,405)
        strict=Client(enforce_csrf_checks=True);strict.force_login(self.actor)
        self.assertEqual(self.associate(saved,client=strict).status_code,403)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get('/en/editorial/upload/',{'draft':self.activity.pk,'audio_side':'a'}).status_code,404)
        self.client.force_login(self.actor)
        EditorialGrant.objects.filter(user=self.actor,variety=self.variety).update(edit=False)
        self.assertEqual(self.associate(saved).status_code,403)
        self.assertTrue(saved.context['asset'].intact)

    def test_modified_draft_retains_new_take_and_existing_audio_and_returns_recovery_links(self):
        old=self.old_take()
        self.activity.audio_a=settings.PUBLIC_ORIGIN+'/fr/media/'+str(old.pk)+'/'
        self.activity.save()
        saved=self.upload()
        self.activity.title='Another editor saved this title';self.activity.save()
        response=self.associate(saved)
        self.assertEqual(response.status_code,409)
        self.assertContains(response,'Your recording is saved',status_code=409)
        self.assertContains(response,reverse('editorial_edit',args=[self.activity.pk]),status_code=409)
        self.assertContains(response,reverse('editorial_media',args=[saved.context['asset'].pk]),status_code=409)
        self.activity.refresh_from_db()
        self.assertIn(str(old.pk),self.activity.audio_a)
        self.assertTrue(saved.context['asset'].intact)
        self.assertEqual(MediaAsset.objects.count(),2)

    def test_capture_snapshot_survives_draft_change_before_upload_without_silent_rebinding(self):
        token,_page=self.capture()
        self.activity.word_a='كلمة أخرى';self.activity.save()
        saved=self.upload(token=token,data={'audio_text':'دار'})
        self.assertEqual(saved.status_code,200)
        self.assertEqual(saved.context['guided']['word'],'دار')
        self.assertEqual(saved.context['asset'].provenance['audio']['text'],'دار')
        self.assertEqual(self.associate(saved).status_code,409)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.audio_a,'')
        self.assertTrue(saved.context['asset'].intact)

    def test_expired_capture_and_association_keep_the_saved_file(self):
        token,_page=self.capture()
        with patch('django.core.signing.time.time',return_value=time.time()+CONTEXT_MAX_AGE+5):
            saved=self.upload(token=token)
        self.assertEqual(saved.status_code,200)
        self.assertFalse(saved.context['can_associate'])
        self.assertTrue(saved.context['asset'].intact)
        fresh=self.upload()
        with patch('django.core.signing.time.time',return_value=time.time()+CONTEXT_MAX_AGE+5):
            response=self.associate(fresh)
        self.assertEqual(response.status_code,410)
        self.assertContains(response,'Your recording is saved',status_code=410)
        self.assertTrue(fresh.context['asset'].intact)
        self.activity.refresh_from_db();self.assertEqual(self.activity.audio_a,'')

    def test_deleted_or_submitted_source_never_links_but_new_take_stays_owned(self):
        for removed in (False,True):
            with self.subTest(removed=removed):
                if removed:
                    self.activity.state='draft';self.activity.save()
                saved=self.upload()
                if removed:
                    self.activity.delete()
                    # Model.delete clears its in-memory PK; retain route identity.
                    self.activity.pk=saved.context['guided']['activity_id']
                else:
                    self.activity.state='review';self.activity.save()
                response=self.associate(saved)
                self.assertEqual(response.status_code,409)
                self.assertTrue(saved.context['asset'].intact)

    def test_revoked_corrupt_or_relabelled_audio_is_rechecked_before_association(self):
        for fault in ('revoked','bytes','profile'):
            with self.subTest(fault=fault):
                saved=self.upload()
                asset=saved.context['asset']
                if fault=='revoked':
                    asset.revoked=True;asset.revocation_reason='Fictional test withdrawal';asset.save()
                elif fault=='bytes':
                    with asset.file.open('wb') as output:output.write(b'Changed fixture bytes')
                else:
                    asset.provenance['audio']['text']='another word';asset.save()
                self.assertIn(self.associate(saved).status_code,(400,409))
                self.activity.refresh_from_db();self.assertEqual(self.activity.audio_a,'')
                self.assertTrue(MediaAsset.objects.filter(pk=asset.pk).exists())

    def test_collector_can_attach_own_take_without_exposing_other_unshared_uploads(self):
        EditorialGrant.objects.create(user=self.other,variety=self.variety,edit=True)
        collector=Client();collector.force_login(self.other)
        saved=self.upload(client=collector)
        asset=saved.context['asset']
        before=self.client.get(reverse('editorial_edit',args=[self.activity.pk]))
        self.assertNotIn(asset.pk,list(before.context['form'].fields['choose_audio_a'].queryset.values_list('pk',flat=True)))
        self.assertEqual(self.associate(saved,client=collector).status_code,302)
        after=self.client.get(reverse('editorial_edit',args=[self.activity.pk]))
        self.assertIn(asset.pk,list(after.context['form'].fields['choose_audio_a'].queryset.values_list('pk',flat=True)))

    def test_upload_outage_keeps_source_context_and_does_not_record_success(self):
        with patch('catalog.media_authoring.MediaAuthoringForm.save',side_effect=OSError('Private storage fault marker')):
            response=self.upload()
        self.assertContains(response,'Media storage is temporarily unavailable')
        self.assertNotContains(response,'Private storage fault marker')
        self.assertIn('guided',response.context)
        self.assertFalse(MediaAsset.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action='catalog.media_uploaded').exists())


@skipUnless(connection.vendor=='postgresql','Requires PostgreSQL row locks for simultaneous audio decisions')
@override_settings(**SETTINGS)
class GuidedAudioConcurrencyTests(GuidedAudioFixture, TransactionTestCase):
    def test_two_collections_for_the_same_slot_have_one_winner_without_losing_files(self):
        first,second=self.upload(),self.upload()
        clients=[]
        for _ in range(2):
            client=Client();client.force_login(self.actor);clients.append(client)
        from threading import Barrier
        barrier=Barrier(2)
        url=reverse('editorial_audio_associate',args=[self.activity.pk,'a'])
        def worker(client,saved):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return client.post(url,{'association_token':saved.context['association_token'],
                    'asset_id':str(saved.context['asset'].pk)}).status_code
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(worker,client,saved) for client,saved in zip(clients,(first,second))]
            results=sorted(future.result(timeout=20) for future in futures)
        self.assertEqual(results,[302,409])
        self.assertEqual(MediaAsset.objects.count(),2)
        self.assertEqual(AuditEvent.objects.filter(action='catalog.audio_associated').count(),1)
        self.activity.refresh_from_db()
        self.assertTrue(any(str(saved.context['asset'].pk) in self.activity.audio_a for saved in (first,second)))
        self.assertTrue(all(asset.intact for asset in MediaAsset.objects.all()))

    def test_association_waits_for_media_revocation_and_reads_committed_revoked_state(self):
        from threading import Event
        saved=self.upload();asset_id=saved.context['asset'].pk
        locked,release=Event(),Event()
        pids=Queue()
        client=Client();client.force_login(self.actor)
        url=reverse('editorial_audio_associate',args=[self.activity.pk,'a'])
        def revoke():
            close_old_connections()
            try:
                with transaction.atomic():
                    asset=MediaAsset.objects.select_for_update().get(pk=asset_id)
                    asset.revoked=True;asset.revocation_reason='Fictional concurrent withdrawal';asset.save()
                    locked.set()
                    if not release.wait(10):raise AssertionError('Test media lock was not released')
            finally:
                connections.close_all()
        def attach():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()');pids.put(cursor.fetchone()[0])
                return client.post(url,{'association_token':saved.context['association_token'],'asset_id':str(asset_id)}).status_code
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            revocation=pool.submit(revoke)
            self.assertTrue(locked.wait(5))
            attachment=pool.submit(attach);pid=pids.get(timeout=5)
            try:
                deadline=time.monotonic()+5
                blocked=False
                while time.monotonic()<deadline:
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s',[pid])
                        row=cursor.fetchone()
                    if row and row[0]=='Lock':blocked=True;break
                    time.sleep(.02)
                self.assertTrue(blocked,'Association must wait for the media row, not read pre-revocation metadata')
            finally:
                release.set()
            revocation.result(timeout=15)
            self.assertEqual(attachment.result(timeout=15),409)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.audio_a,'')
        self.assertTrue(MediaAsset.objects.get(pk=asset_id).revoked)
