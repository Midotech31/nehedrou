import csv
import io
import json
import uuid
import zipfile
from django.test import TestCase, override_settings
from catalog.models import Activity, EditorialGrant, DraftWorkingCopy, Variety
from core.models import User
from catalog.quality import completeness


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False)
class WorkingCopyAndQualityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='working-author', email='working@example.test')
        cls.other = User.objects.create_user(username='working-other', email='other-working@example.test')
        cls.reader = User.objects.create_user(username='working-reader', email='reader-working@example.test')
        cls.variety = Variety.objects.create(code='ar-dz-pilot', language='ar', label='Darja')
        cls.foreign = Variety.objects.create(code='fr-fr-pilot', language='fr', label='French')
        EditorialGrant.objects.create(user=cls.author, variety=cls.variety, edit=True)
        EditorialGrant.objects.create(user=cls.other, variety=cls.foreign, edit=True)
        EditorialGrant.objects.create(user=cls.reader, variety=cls.variety, clinical_review=True)

    def setUp(self):
        self.client.force_login(self.author)

    def save_copy(self, identifier=None, revision=0, fields=None, **extra):
        identifier = identifier or uuid.uuid4()
        response = self.client.post(f'/fr/editorial/work/{identifier}/', json.dumps(dict(fields=fields or {'title':'Draft still missing words'}, revision=revision, **extra)), content_type='application/json')
        return identifier, response

    def activity(self, variety=None, **extra):
        data = dict(variety=variety or self.variety, series=uuid.uuid4(), title='Fictional words', word_a='دار', word_b='باب', contrast='Home', instructions={'fr':'Fictional test instructions'})
        data.update(extra)
        return Activity.objects.create(**data)

    def test_incomplete_input_survives_reload_without_creating_an_activity(self):
        identifier, response = self.save_copy(fields={'title':'Incomplete original', 'guide_ar_objective':'هدف غير مكتمل'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Activity.objects.exists())
        restored = self.client.get(response.json()['resume_url'])
        self.assertContains(restored, 'Incomplete original')
        self.assertContains(restored, 'هدف غير مكتمل')
        self.assertEqual(DraftWorkingCopy.objects.get(pk=identifier).revision, 1)

    def test_working_copies_and_scoped_content_are_private(self):
        identifier, response = self.save_copy()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(response.json()['resume_url']).status_code, 404)
        self.assertEqual(self.save_copy(identifier, revision=1)[1].status_code, 404)
        foreign = self.activity(self.foreign, title='FOREIGN CONTENT SECRET')
        self.client.force_login(self.author)
        self.assertNotContains(self.client.get('/fr/editorial/quality/'), foreign.title)
        exported = self.client.get('/fr/editorial/quality/export/')
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            self.assertNotIn(foreign.title, archive.read('activities.json').decode())

    def test_lost_update_is_rejected(self):
        identifier, response = self.save_copy()
        self.assertEqual(self.save_copy(identifier, revision=1, fields={'title':'Second change'})[1].status_code, 200)
        stale = self.save_copy(identifier, revision=1, fields={'title':'Stale overwrite'})[1]
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(DraftWorkingCopy.objects.get(pk=identifier).data['title'], 'Second change')

    def test_revoked_permissions_block_autosave_and_recovery(self):
        identifier, response = self.save_copy(fields={'variety':str(self.variety.pk), 'title':'Owned'})
        EditorialGrant.objects.filter(user=self.author).update(edit=False)
        self.assertEqual(self.save_copy(identifier, revision=1)[1].status_code, 403)
        self.assertEqual(self.client.get(response.json()['resume_url']).status_code, 403)

    def test_foreign_variety_and_activity_cannot_be_written(self):
        self.assertEqual(self.save_copy(fields={'variety':str(self.foreign.pk)})[1].status_code, 403)
        foreign = self.activity(self.foreign)
        self.assertEqual(self.save_copy(activity=str(foreign.pk), base_digest=foreign.fingerprint())[1].status_code, 403)
        self.assertFalse(DraftWorkingCopy.objects.exists())

    def test_review_only_user_cannot_autosave(self):
        self.client.force_login(self.reader)
        self.assertEqual(self.save_copy()[1].status_code, 403)
        self.assertEqual(self.client.get('/fr/editorial/quality/').status_code, 200)

    def test_csrf_and_post_only(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.author)
        url = f'/fr/editorial/work/{uuid.uuid4()}/'
        self.assertEqual(client.post(url, '{}', content_type='application/json').status_code, 403)
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_working_copy_does_not_accept_publication_or_permission_fields(self):
        for fields in [{'state':'published'}, {'owner':str(self.other.pk)}, {'is_demo':False}, {'title':['not text']}, {'variety':'invalid'}, {'title':'x'*16001}]:
            self.assertEqual(self.save_copy(fields=fields)[1].status_code, 400)
        self.assertFalse(DraftWorkingCopy.objects.exists())

    def test_payload_size_is_bounded(self):
        response = self.client.post(f'/fr/editorial/work/{uuid.uuid4()}/', 'x'*180001, content_type='application/json')
        self.assertEqual(response.status_code, 413)

    def test_source_change_and_transition_block_working_copy(self):
        activity = self.activity()
        identifier, response = self.save_copy(activity=str(activity.pk), base_digest=activity.fingerprint())
        self.assertEqual(response.status_code, 200)
        activity.title = 'Edited by another author'; activity.save()
        response = self.save_copy(identifier, revision=1, activity=str(activity.pk), base_digest=activity.fingerprint())[1]
        self.assertEqual(response.status_code, 409)
        activity.state = 'review'; activity.save()
        self.assertEqual(self.save_copy(identifier, revision=1, activity=str(activity.pk))[1].status_code, 403)

    def test_final_save_commits_working_copy_without_publication(self):
        identifier, response = self.save_copy(fields={'title':'Started original'})
        data = {'working_copy':str(identifier), 'title':'Saved original', 'variety':str(self.variety.pk), 'kind':'vocabulary',
                'contrast':'Home', 'word_a':'دار', 'word_b':'باب', 'response_mode':'matching', 'is_demo':'on'}
        response = self.client.post('/fr/editorial/new/', data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Activity.objects.get().state, 'draft')
        self.assertTrue(DraftWorkingCopy.objects.get().committed)
        self.assertNotContains(self.client.get('/fr/editorial/'), '?resume='+str(identifier))
        self.assertEqual(self.save_copy(identifier, revision=1)[1].status_code, 404)

    def test_manual_stale_edit_cannot_overwrite_content(self):
        activity = self.activity()
        baseline = activity.fingerprint()
        activity.title = 'Another author saved'; activity.save()
        response = self.client.post(f'/fr/editorial/{activity.pk}/edit/', {'content_baseline':baseline, 'title':'Stale title', 'kind':'word_pair', 'response_mode':'matching', 'contrast':'Home', 'word_a':'دار', 'word_b':'باب', 'is_demo':'on'})
        self.assertEqual(response.status_code, 200)
        activity.refresh_from_db()
        self.assertEqual(activity.title, 'Another author saved')

    def test_progress_does_not_infer_clinical_validation(self):
        activity = self.activity(population='Fictional', limitations='To review', rights='Fictional rights')
        report = completeness(activity)
        self.assertLess(report['completed'], report['total'])
        self.assertTrue(any(check['key'] == 'audio' and not check['complete'] for check in report['checks']))
        self.assertFalse(activity.has_current_reviews())
        self.assertFalse(activity.usable)
        response = self.client.get('/fr/editorial/quality/export/')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            payload = json.loads(archive.read('activities.json'))
            self.assertEqual(payload['activities'][0]['clinical_validation'], 'not_inferred_from_completeness')
            self.assertEqual(archive.testzip(), None)

    def test_export_neutralizes_spreadsheet_formulas(self):
        activity = self.activity(word_a='=1+1')
        with zipfile.ZipFile(io.BytesIO(self.client.get('/fr/editorial/quality/export/').content)) as archive:
            self.assertIn("'=1+1", archive.read('review.csv').decode('utf-8-sig'))

    def test_restore_escapes_untrusted_author_text(self):
        identifier, response = self.save_copy(fields={'title':'</script><script>alert(1)</script>'})
        page = self.client.get(response.json()['resume_url'])
        self.assertNotContains(page, '<script>alert(1)</script>')
        self.assertContains(page, '&lt;/script&gt;')

    def test_full_scope_and_filters_work_in_each_interface_language(self):
        activity = self.activity()
        for code in ['fr','en','ar']:
            page = self.client.get(f'/{code}/editorial/quality/?variety=ar-dz-pilot&gap=audio')
            self.assertContains(page, activity.title)
            self.assertContains(page, 'Designed by Benabdeloued Mohamed Alias Pitou')
            page = self.client.get(f'/{code}/editorial/quality/?kind=storytelling')
            self.assertNotContains(page, activity.title)

    def test_documented_familiarity_is_preserved_when_editing_a_note(self):
        from catalog.authoring import ActivityAuthoringForm
        proof = {'evidence':str(uuid.uuid4()),'sha256':'a'*64,'note':'Known locally'}
        activity = self.activity(item_metadata={'a':{'meaning':'house','segments':[],'target_occurrences':[],'accepted_variants':[],'familiarity':proof},'b':{'meaning':'door','segments':[],'target_occurrences':[],'accepted_variants':[],'familiarity':'Family word'}})
        form = ActivityAuthoringForm({'title':activity.title,'variety':str(self.variety.pk),'kind':'vocabulary','contrast':'Home','response_mode':'matching','word_a':'دار','word_b':'باب','meaning_a':'house','meaning_b':'door','familiarity_a':'Updated note','familiarity_b':'Family word'},instance=activity,actor=self.author)
        self.assertTrue(form.is_valid(),form.errors)
        saved = form.save()
        self.assertEqual(saved.item_metadata['a']['familiarity']['evidence'], proof['evidence'])
        self.assertEqual(saved.item_metadata['a']['familiarity']['sha256'], proof['sha256'])
        self.assertEqual(saved.item_metadata['a']['familiarity']['note'], 'Updated note')

    def test_plain_media_rights_fields_bind_audio_without_approving_it(self):
        import wave
        import tempfile
        from django.core.files.uploadedfile import SimpleUploadedFile
        from catalog.models import MediaAsset
        audio=io.BytesIO()
        with wave.open(audio,'wb') as recording:
            recording.setnchannels(1);recording.setsampwidth(2);recording.setframerate(16000);recording.writeframes(b'\0\0'*1600)
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            response=self.client.post('/fr/editorial/upload/',{'file':SimpleUploadedFile('fixture.wav',audio.getvalue(),content_type='audio/wav'),
                'kind':'audio','rights':'Fictional recording for a software test','rights_status':'unknown','rights_holder':'Fictional adult',
                'rights_licence':'Unreviewed permission','rights_adult_speaker_permission':'Pending actual consent','audio_variety':str(self.variety.pk),'audio_text':'دار','audio_source':'human'})
            self.assertEqual(response.status_code,200)
            asset=MediaAsset.objects.get()
            self.assertEqual(asset.provenance['holder'],'Fictional adult')
            self.assertEqual(asset.provenance['adult_speaker_permission'],'Pending actual consent')
            self.assertFalse(asset.documented)
            self.assertContains(response,'<audio controls')

    def test_set_aside_is_reversible_and_does_not_delete_author_input(self):
        identifier,response=self.save_copy(fields={'title':'Retained private work'})
        url=f'/fr/editorial/work/{identifier}/set-aside/'
        self.assertEqual(self.client.post(url,{'action':'dismiss'}).status_code,302)
        self.assertEqual(DraftWorkingCopy.objects.get(pk=identifier).data['title'],'Retained private work')
        self.assertEqual(self.client.get(response.json()['resume_url']).status_code,404)
        self.assertEqual(self.client.post(url,{'action':'restore'}).status_code,302)
        self.assertContains(self.client.get(response.json()['resume_url']),'Retained private work')
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url,{'action':'dismiss'}).status_code,404)
        self.assertFalse(DraftWorkingCopy.objects.get(pk=identifier).dismissed)

    def test_capacity_can_be_recovered_by_setting_a_copy_aside(self):
        copies=[DraftWorkingCopy.objects.create(owner=self.author,data={'title':'Fictional working copy'}) for _ in range(30)]
        self.assertEqual(self.save_copy()[1].status_code,409)
        self.assertEqual(self.client.post(f'/fr/editorial/work/{copies[0].pk}/set-aside/',{'action':'dismiss'}).status_code,302)
        self.assertEqual(self.save_copy()[1].status_code,200)
        self.assertEqual(DraftWorkingCopy.objects.filter(owner=self.author,committed=False,dismissed=False).count(),30)

    def test_recording_kit_uses_exact_versions_and_keeps_human_decisions_blank(self):
        activity=self.activity()
        response=self.client.get('/fr/editorial/quality/export/')
        self.assertEqual(response.status_code,200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            reader=csv.DictReader(io.StringIO(archive.read('recording_prompts.csv').decode('utf-8-sig')))
            rows=[row for row in reader if row['activity_id']==str(activity.pk)]
        self.assertEqual(len(rows),2)
        self.assertEqual({row['side'] for row in rows},{'a','b'})
        self.assertTrue(all(row['content_sha256']==activity.fingerprint() and row['spoken_variety']==self.variety.code for row in rows))
        self.assertTrue(all(not row['clinical_decision'] and not row['linguistic_decision'] and not row['adult_speaker_reference'] for row in rows))
