"""Speech integration fixtures test software, never native/clinical validity."""
import io
import math
import struct
import uuid
import wave
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from catalog.models import Activity, EditorialGrant, MediaAsset, Variety
from catalog.media_authoring import MediaAuthoringForm
from catalog.authoring import ActivityAuthoringForm
from core.models import User


def fixture(silent=False):
    out = io.BytesIO()
    with wave.open(out, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
        audio.writeframes(b''.join(struct.pack('<h', 0 if silent else int(8000 * math.sin(2 * math.pi * 220 * i / 16000))) for i in range(8000)))
    return out.getvalue()

@override_settings(DEMO_MODE=True, MFA_REQUIRED=False, PUBLIC_ORIGIN='https://demo.example', PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AudioIntegrationTests(TestCase):
    def setUp(self):
        self.directory=TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.settings_override=override_settings(MEDIA_ROOT=self.directory.name)
        self.settings_override.enable(); self.addCleanup(self.settings_override.disable)
        self.editor=User.objects.create_user(username='audio-author',email='audio-author@example.test')
        self.foreign=User.objects.create_user(username='other-audio-author',email='other-audio-author@example.test')
        self.variety=Variety.objects.create(code='ar-dz-pilot',language='ar',label='Darja')
        self.other=Variety.objects.create(code='ar-msa-pilot',language='ar',label='MSA')
        EditorialGrant.objects.create(user=self.editor,variety=self.variety,edit=True)
        self.data=fixture()
        self.asset=MediaAsset.objects.create(kind='audio',file=ContentFile(self.data,name='technical-tone.wav'),uploaded_by=self.editor,
                   rights='Software fixture only; not a speech model',provenance={'audio':{'text':'دار','variety':self.variety.code,'source':'synthetic'}})
        self.client.force_login(self.editor)
        self.url=f'/fr/media/{self.asset.pk}/'

    def upload_data(self, **extra):
        return {'kind':'audio','rights_status':'unknown','rights':'Fictional adult rights pending','audio_variety':str(self.variety.pk),'audio_text':'دار','audio_source':'human',**extra}

    def test_all_locales_have_recorder_and_no_automatic_microphone_access(self):
        for language in ['fr','en','ar']:
            page=self.client.get(f'/{language}/editorial/upload/')
            self.assertContains(page,'data-record-consent');self.assertContains(page,'audio-recorder.js')
            self.assertContains(page,'name="audio_text"');self.assertNotContains(page,'autoplay')
            self.assertIn('blob:',page.headers['Content-Security-Policy'])
            self.assertEqual(page.headers['Permissions-Policy'], 'microphone=(self), camera=(), geolocation=()')
        page=self.client.get('/fr/')
        self.assertEqual(page.headers['Permissions-Policy'],'microphone=(), camera=(), geolocation=()')

    def test_guided_upload_requires_exact_text_variety_and_source(self):
        for field in ['audio_variety','audio_text','audio_source']:
            data=self.upload_data();data.pop(field)
            form=MediaAuthoringForm(data, {'file':SimpleUploadedFile('test.wav',self.data)},actor=self.editor,instance=MediaAsset(uploaded_by=self.editor))
            self.assertFalse(form.is_valid());self.assertIn(field,form.errors)

    def test_scope_does_not_offer_msa_to_darja_only_editor(self):
        form=MediaAuthoringForm(self.upload_data(audio_variety=str(self.other.pk)), {'file':SimpleUploadedFile('test.wav',self.data)},actor=self.editor,instance=MediaAsset(uploaded_by=self.editor))
        self.assertFalse(form.is_valid());self.assertIn('audio_variety',form.errors)

    def test_saved_provenance_and_signal_do_not_grant_approval(self):
        response=self.client.post('/fr/editorial/upload/',self.upload_data(file=SimpleUploadedFile('test.wav',self.data),rights_adult_speaker_permission='Fictional consent pending'))
        self.assertContains(response,'data-audio-player')
        asset=MediaAsset.objects.exclude(pk=self.asset.pk).get()
        self.assertEqual(asset.provenance['audio']['source'],'human')
        self.assertEqual(asset.provenance['audio']['text'],'دار')
        self.assertFalse(asset.technical_metadata['signal']['silent']);self.assertFalse(asset.documented)

    def test_upload_outage_keeps_friendly_form_and_no_audit_success(self):
        with patch('catalog.media_authoring.MediaAuthoringForm.save',side_effect=OSError('private provider failure')):
            response=self.client.post('/en/editorial/upload/',self.upload_data(file=SimpleUploadedFile('test.wav',self.data)))
        self.assertContains(response,'Media storage is temporarily unavailable')
        self.assertNotContains(response,'private provider failure')
        self.assertEqual(MediaAsset.objects.count(),1)

    def test_full_get_and_head_share_exact_private_headers(self):
        get=self.client.get(self.url);head=self.client.head(self.url,HTTP_RANGE='bytes=0-5')
        self.assertEqual(get.content,self.data);self.assertEqual(head.content,b'')
        for response in [get,head]:
            self.assertEqual(response.status_code,200);self.assertEqual(response.headers['Content-Length'],str(len(self.data)))
            self.assertEqual(response.headers['Content-Type'],'audio/wav');self.assertEqual(response.headers['Accept-Ranges'],'bytes')
            self.assertIn('no-store',response.headers['Cache-Control'])

    def test_single_bounded_ranges_match_original_bytes(self):
        for value,first,last in [('bytes=0-43',0,43),('bytes=50-',50,len(self.data)-1),('bytes=-100',len(self.data)-100,len(self.data)-1),('bytes=10-99999999',10,len(self.data)-1)]:
            with self.subTest(value=value):
                response=self.client.get(self.url,HTTP_RANGE=value)
                self.assertEqual(response.status_code,206);self.assertEqual(response.content,self.data[first:last+1])
                self.assertEqual(response.headers['Content-Range'],f'bytes {first}-{last}/{len(self.data)}')
                self.assertEqual(response.headers['Content-Length'],str(last-first+1))

    def test_unsatisfiable_ranges_empty_416(self):
        for value in ['bytes=99999999-','bytes=50-49','bytes=-0','bytes='+'9'*100+'-']:
            response=self.client.get(self.url,HTTP_RANGE=value)
            self.assertEqual(response.status_code,416);self.assertEqual(response.content,b'')
            self.assertEqual(response.headers['Content-Range'],f'bytes */{len(self.data)}')

    def test_invalid_or_multiple_ranges_and_if_range_return_full_get(self):
        for kwargs in [{'HTTP_RANGE':'bytes=x-y'},{'HTTP_RANGE':'bytes=0-2,6-8'},{'HTTP_RANGE':'items=0-2'},{'HTTP_RANGE':'bytes=0-2','HTTP_IF_RANGE':'unknown'}]:
            response=self.client.get(self.url,**kwargs)
            self.assertEqual(response.status_code,200);self.assertEqual(response.content,self.data)

    def test_range_and_head_never_bypass_authorization(self):
        self.client.force_login(self.foreign)
        for method in [self.client.get,self.client.head]:
            self.assertEqual(method(self.url,HTTP_RANGE='bytes=0-43').status_code,404)
        self.client.logout()
        self.assertEqual(self.client.get(self.url,HTTP_RANGE='bytes=0-43').status_code,302)

    def test_changed_and_missing_private_bytes_return_404(self):
        with self.asset.file.open('wb') as output:output.write(b'changed')
        self.assertEqual(self.client.get(self.url).status_code,404)
        self.asset.file.delete(save=False)
        self.assertEqual(self.client.head(self.url).status_code,404)

    def test_silence_is_flagged_not_claimed_a_voice(self):
        from catalog.media_validation import validate_media
        metadata=validate_media(SimpleUploadedFile('silent.wav',fixture(True)),'audio')
        self.assertTrue(metadata['signal']['silent'])
        self.assertEqual(metadata['signal']['quiet_percent'],100)

    def test_player_detects_word_and_variety_mismatch(self):
        from catalog.audio_presentation import audio_context
        context=audio_context(self.asset,'باب','ar-msa-pilot')
        self.assertEqual(len(context['audio_warnings']),2)

    def test_library_detail_actually_renders_protected_recording(self):
        from django.core.management import call_command
        import os
        with patch.dict(os.environ,{'DEMO_PASSWORD':'Software-fixture-only-password'}):call_command('seed_demo',stdout=io.StringIO())
        source=Activity.objects.filter(variety__code='fr-fr-pilot',state='published').first()
        values={field.attname:getattr(source,field.attname) for field in Activity._meta.concrete_fields if field.name not in ['id','series','created_at','state']}
        values.update(series=uuid.uuid4(),audio_a='https://demo.example'+self.url)
        activity=Activity.objects.create(**values);activity.state='published';activity.save()
        self.client.force_login(User.objects.get(username='praticien'))
        page=self.client.get(__import__('django.urls',fromlist=['reverse']).reverse('activity_detail',args=[activity.pk]))
        self.assertContains(page,'data-audio-player');self.assertContains(page,f'/fr/media/{self.asset.pk}/')

    def test_device_synthesis_never_uses_darja_or_phonological_examples(self):
        for code in ['fr-fr-pilot','en-us-general-pilot','ar-msa-pilot','ar-dz-pilot']:
            activity=Activity(is_demo=True,kind='vocabulary',variety=Variety(code=code))
            self.assertEqual(activity.device_voice_allowed,code!='ar-dz-pilot')
            if code!='ar-dz-pilot':self.assertTrue(activity.device_voice_language)
            activity.kind='phonological_contrast';self.assertFalse(activity.device_voice_allowed)
            activity.kind='word_pair';self.assertFalse(activity.device_voice_allowed)
            activity.kind='vocabulary';activity.is_demo=False;self.assertFalse(activity.device_voice_allowed)

    def test_binding_rejects_silence_and_mismatched_variety_or_text(self):
        from catalog.audio_checks import audio_binding_errors
        self.assertEqual(audio_binding_errors(self.asset,'دار',self.variety),[])
        self.assertTrue(audio_binding_errors(self.asset,'باب',self.variety))
        self.assertTrue(audio_binding_errors(self.asset,'دار',self.other))
        self.asset.technical_metadata['signal']['silent']=True
        self.assertTrue(audio_binding_errors(self.asset,'دار',self.variety))


    def test_documented_rights_do_not_qualify_silent_or_undocumented_source(self):
        from qualification.test_support import media_fixture
        asset=media_fixture(self.variety,self.editor,'audio')
        self.assertTrue(asset.documented)
        asset.technical_metadata['signal']['silent']=True
        self.assertFalse(asset.documented)
        asset.technical_metadata['signal']['silent']=False
        asset.provenance['audio']={'source':'unspecified','text':'دار','variety':self.variety.code}
        self.assertFalse(asset.documented)


    def test_cms_preview_audio_map_is_scoped_and_protected(self):
        foreign=MediaAsset.objects.create(kind='audio',file=ContentFile(self.data,name='other-tone.wav'),uploaded_by=self.foreign,rights='Unshared software fixture')
        page=self.client.get('/fr/editorial/new/')
        mapping=page.context['author_config']['audios']
        self.assertEqual(mapping[str(self.asset.pk)],self.url)
        self.assertNotIn(str(foreign.pk),mapping)
        self.assertContains(page,'id="preview-audio-a"')


    def test_advanced_audio_provenance_cannot_break_selectors(self):
        from django.core.exceptions import ValidationError
        for profile in ['bad',[],{'source':'human','text':[], 'variety':self.variety.code},{'source':'other','text':'word','variety':self.variety.code}]:
            self.asset.provenance={'audio':profile}
            with self.assertRaises(ValidationError):self.asset.full_clean()
