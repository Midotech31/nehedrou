"""CMS guide language visibility on fictional drafts; no content translation or approval."""
import copy
import io
import uuid
import wave
from html.parser import HTMLParser

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from catalog.models import Activity, EditorialGrant, MediaAsset, Review, Variety
from catalog.services import clone_version, transition
from core.models import AuditEvent, User
from qualification.models import AvailabilityDecision


class GuideDOM(HTMLParser):
    void = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}

    def __init__(self, html):
        super().__init__()
        self.stack, self.nodes, self.texts = [], [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        parent = self.stack[-1] if self.stack else {}
        node = {'tag':tag, 'attrs':attrs, 'lang':attrs.get('lang', parent.get('lang', '')),
                'dir':attrs.get('dir', parent.get('dir', '')), 'text':''}
        self.nodes.append(node)
        if tag not in self.void:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack)-1, -1, -1):
            if self.stack[index]['tag'] == tag:
                del self.stack[index:]
                break

    def handle_data(self, text):
        for node in self.stack:
            node['text'] += text
        if text.strip() and self.stack:
            node = self.stack[-1]
            self.texts.append((text.strip(), node['lang'], node['dir']))

    def by_class(self, name):
        return [node for node in self.nodes if name in node['attrs'].get('class', '').split()]


def fictional_wav():
    output = io.BytesIO()
    with wave.open(output, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes((5000).to_bytes(2, 'little', signed=True) * 800)
    return output.getvalue()


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False, PUBLIC_ORIGIN='https://cms-fixture.operator.tld',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={'default':{'BACKEND':'django.core.files.storage.InMemoryStorage'},
              'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class CMSGuideLanguageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.editor = User.objects.create_user(username='cms-guide-editor', email='cms-guide-editor@example.test', instruction_language='fr')
        cls.reviewer = User.objects.create_user(username='cms-guide-reader', email='cms-guide-reader@example.test', instruction_language='ar')
        cls.outsider = User.objects.create_user(username='cms-guide-outsider', email='cms-guide-outsider@example.test')
        cls.english = Variety.objects.create(code='en-us-general-pilot', language='en', label='Fictional English')
        cls.darja = Variety.objects.create(code='ar-dz-pilot', language='ar', label='Fictional Darja')
        for variety in (cls.english, cls.darja):
            EditorialGrant.objects.create(user=cls.editor, variety=variety, edit=True)
            EditorialGrant.objects.create(user=cls.reviewer, variety=variety, clinical_review=True)
        cls.guides = {
            language:{'objective':objective, 'audience':audience, 'review_notes':review,
                **{key:[step] for key in ['discover','listen','exchange','support','limits']}}
            for language,objective,audience,review,step in [
                ('fr','Objectif français du guide sélectionné','Public français du guide','Relecture française en attente','Étape française du guide'),
                ('ar','هدف عربي للدليل المختار','جمهور الدليل العربي','المراجعة العربية معلقة','خطوة عربية للدليل')]
        }
        cls.asset = MediaAsset.objects.create(kind='audio', uploaded_by=cls.editor,
            file=SimpleUploadedFile('fictional-cms-signal.wav', fictional_wav()),
            rights='Fictional signal only; no approved voice or permission evidence',
            provenance={'audio':{'text':'coat','variety':cls.english.code,'source':'human'}})
        cls.source = Activity.objects.create(variety=cls.english, series=uuid.uuid4(), kind='vocabulary',
            title='Fictional CMS historical version', contrast='Fictional household words', word_a='coat', word_b='goat',
            transcription_a='/koʊt/', transcription_b='/goʊt/', image_a='editorial/hat.svg', image_b='editorial/boat.svg',
            audio_a=settings.PUBLIC_ORIGIN + '/fr/media/' + str(cls.asset.pk) + '/',
            instructions={'fr':'Consigne française conservée','en':'Preserved English prompt','ar':'تعليمة عربية محفوظة'},
            practice_guide=copy.deepcopy(cls.guides), population='Population source conservée',
            limitations='Limites source conservées', rights='Droits source conservés', is_demo=False)
        cls.source = transition(cls.editor, cls.source.pk, 'review')
        cls.review = Review.objects.create(activity=cls.source, reviewer=cls.reviewer,
            kind='clinical', approved=False, note='Fictional historical changes requested')
        cls.draft = clone_version(cls.editor, cls.source)
        cls.darja_draft = Activity.objects.create(variety=cls.darja, series=uuid.uuid4(), kind='vocabulary',
            title='Fictional CMS Darja draft', contrast='Fictional home words', word_a='دار', word_b='باب',
            transcription_a='/daːr/', transcription_b='/baːb/', image_a='editorial/hat.svg', image_b='editorial/boat.svg',
            instructions={'fr':'Consigne source française','en':'Source English prompt','ar':'تعليمة دارجة محفوظة'},
            practice_guide=copy.deepcopy(cls.guides), population='Population source darja conservée',
            limitations='Limites source darja conservées', rights='Droits source darja conservés', is_demo=False)

    def setUp(self):
        # LocaleMiddleware changes the active language; restore it after every test.
        self.enterContext(translation.override(settings.LANGUAGE_CODE))
        self.client.force_login(self.editor)

    def page(self, activity=None, language='fr'):
        return self.client.get('/' + language + '/editorial/' + str((activity or self.draft).pk) + '/')

    def assert_text_language(self, dom, text, language, direction):
        self.assertIn((text, language, direction), dom.texts)

    def assert_source_texts(self, response, activity):
        dom = GuideDOM(response.content.decode())
        self.assertEqual(len(dom.by_class('editorial-source-texts')), 1)
        for text in (activity.population, activity.limitations, activity.rights):
            self.assert_text_language(dom, text, 'und', 'auto')
        return dom

    def test_ar_interface_keeps_french_guide_preference_and_english_word_language(self):
        with translation.override('ar'):
            response = self.page(language='ar')
            self.assertEqual(response.status_code, 200)
            dom = self.assert_source_texts(response, self.draft)
            banner = dom.by_class('instruction-language')
            self.assertEqual(len(banner), 1)
            self.assertIn(str(self.editor.get_instruction_language_display()), banner[0]['text'])
            self.assertContains(response, reverse('preferences'))
            self.assertLess(response.content.index(b'class="instruction-language"'), response.content.index(self.guides['fr']['objective'].encode()))
            self.assert_text_language(dom, self.guides['fr']['objective'], 'fr', 'ltr')
            self.assert_text_language(dom, self.guides['fr']['discover'][0], 'fr', 'ltr')
            self.assert_text_language(dom, 'coat', 'en-US', 'ltr')
            self.assert_text_language(dom, '/koʊt/', 'und-fonipa', 'ltr')
            self.assertNotContains(response, self.guides['ar']['objective'])
            self.assertFalse(dom.by_class('editorial-guide-missing'))
        self.editor.refresh_from_db()
        self.assertEqual(self.editor.instruction_language, 'fr')

    def test_fr_interface_keeps_arabic_guide_preference_and_darja_words(self):
        self.editor.instruction_language = 'ar'
        self.editor.save(update_fields=['instruction_language'])
        with translation.override('fr'):
            response = self.page(self.darja_draft)
            self.assertEqual(response.status_code, 200)
            dom = self.assert_source_texts(response, self.darja_draft)
            self.assertIn(str(self.editor.get_instruction_language_display()), dom.by_class('instruction-language')[0]['text'])
            self.assert_text_language(dom, self.guides['ar']['objective'], 'ar', 'rtl')
            self.assert_text_language(dom, self.guides['ar']['support'][0], 'ar', 'rtl')
            self.assert_text_language(dom, 'دار', 'ar-DZ', 'rtl')
            self.assertNotContains(response, self.guides['fr']['objective'])
        self.editor.refresh_from_db()
        self.assertEqual(self.editor.instruction_language, 'ar')

    def missing_ar(self):
        self.darja_draft.practice_guide = {'fr':copy.deepcopy(self.guides['fr'])}
        self.darja_draft.evidence_sources = [{'title':'Preserved source title', 'title_language':'en',
            'url':'https://source.example.test/framework', 'scope':'Portée documentaire conservée', 'scope_language':'fr'}]
        self.darja_draft.save()
        self.editor.instruction_language = 'ar'
        self.editor.save(update_fields=['instruction_language'])

    def test_missing_selected_guide_is_explicit_without_fallback_and_editor_can_open_draft(self):
        self.missing_ar()
        with translation.override('fr'):
            response = self.page(self.darja_draft)
            self.assertEqual(response.status_code, 200)
            dom = GuideDOM(response.content.decode())
            missing = dom.by_class('editorial-guide-missing')
            self.assertEqual(len(missing), 1)
            self.assertIn(translation.gettext('Guide unavailable in the selected instruction language'), missing[0]['text'])
            self.assertNotContains(response, self.guides['fr']['objective'])
            self.assertNotContains(response, self.guides['fr']['discover'][0])
            self.assertNotContains(response, self.guides['ar']['objective'])
            edit_url = reverse('editorial_edit', args=[self.darja_draft.pk])
            self.assertContains(response, edit_url)
            self.assertEqual(self.client.get(edit_url).status_code, 200)
            self.assert_text_language(dom, 'Preserved source title', 'en', 'ltr')
            self.assert_text_language(dom, 'Portée documentaire conservée', 'fr', 'ltr')
            self.assertContains(response, 'https://source.example.test/framework')

    def test_reader_sees_missing_guide_without_edit_permission_or_link(self):
        self.missing_ar()
        self.client.force_login(self.reviewer)
        with translation.override('ar'):
            response = self.page(self.darja_draft, language='ar')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(GuideDOM(response.content.decode()).by_class('editorial-guide-missing')), 1)
            edit_url = reverse('editorial_edit', args=[self.darja_draft.pk])
            self.assertNotContains(response, edit_url)
            self.assertEqual(self.client.get(edit_url).status_code, 403)
            self.assertNotContains(response, self.guides['fr']['objective'])

    def test_non_draft_guide_gap_keeps_reviews_actions_and_warnings_without_edit_link(self):
        self.source.practice_guide = {'fr':copy.deepcopy(self.guides['fr'])}
        self.source.save()
        self.editor.instruction_language = 'ar'
        self.editor.save(update_fields=['instruction_language'])
        with translation.override('fr'):
            response = self.page(self.source)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, reverse('editorial_edit', args=[self.source.pk]))
            self.assertContains(response, reverse('editorial_clone', args=[self.source.pk]))
            self.assertContains(response, reverse('editorial_transition', args=[self.source.pk]))
            self.assertContains(response, self.review.note)
            self.assertContains(response, translation.gettext('Changes requested'))
            self.assertContains(response, translation.gettext('Real use requires exact media, documented rights, word definitions, two competent reviewers and an availability decision.'))
            self.assertEqual(len(GuideDOM(response.content.decode()).by_class('editorial-guide-missing')), 1)

    def test_scope_and_authentication_still_prevent_content_disclosure(self):
        self.client.force_login(self.outsider)
        response = self.page(self.darja_draft, language='ar')
        self.assertEqual(response.status_code, 404)
        for text in (self.darja_draft.title, self.guides['ar']['objective'], self.darja_draft.population):
            self.assertNotContains(response, text, status_code=404)
        self.client.logout()
        response = self.page(self.draft, language='ar')
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(self.draft.word_a.encode(), response.content)

    def snapshot(self):
        return copy.deepcopy({
            'activities':list(Activity.objects.order_by('pk').values()),
            'reviews':list(Review.objects.order_by('pk').values()),
            'media':list(MediaAsset.objects.order_by('pk').values()),
            'audits':list(AuditEvent.objects.order_by('pk').values()),
            'availability':list(AvailabilityDecision.objects.order_by('pk').values()),
            'preferences':list(User.objects.order_by('pk').values_list('pk','instruction_language')),
        })

    def test_http_reads_preserve_fingerprints_history_preferences_and_protected_audio(self):
        before = self.snapshot()
        fingerprints = {a.pk:a.fingerprint() for a in Activity.objects.all()}
        with self.asset.file.open('rb') as stream:
            original_bytes = stream.read()
        for language in ('ar','fr','en'):
            for activity in (self.source,self.draft,self.darja_draft):
                response = self.page(activity, language)
                self.assertEqual(response.status_code, 200)
                if activity.pk in (self.source.pk,self.draft.pk):
                    self.assertContains(response, 'data-audio-player')
                    self.assertContains(response, '/' + language + '/media/' + str(self.asset.pk) + '/')
        audio = self.client.get('/fr/media/' + str(self.asset.pk) + '/')
        self.assertEqual(audio.status_code, 200)
        self.assertEqual(audio.content, original_bytes)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual({a.pk:a.fingerprint() for a in Activity.objects.all()}, fingerprints)
        self.assertFalse(Review.objects.filter(approved=True).exists())
        self.assertFalse(AvailabilityDecision.objects.exists())
