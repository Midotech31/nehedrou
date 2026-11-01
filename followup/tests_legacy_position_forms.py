"""Legacy positions require a conscious supported choice before draft authoring can save."""
from html.parser import HTMLParser

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from catalog.models import EditorialGrant
from core.models import AuditEvent
from .models import ProbeDefinition, ProbeReview
from .tests import install_fixture, item
from . import tests_views as view_tests


class NativePositionSelect(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.options = []
        self.required = False
        self.in_option = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag=='select':
            self.required = 'required' in attrs
        elif tag=='option':
            self.options.append({'value':attrs.get('value'),'selected':'selected' in attrs,'label':''})
            self.in_option = True

    def handle_endtag(self, tag):
        if tag=='option':
            self.in_option = False

    def handle_data(self, text):
        if self.in_option:
            self.options[-1]['label'] += text

    @property
    def native_value(self):
        return next((option['value'] for option in self.options if option['selected']),self.options[0]['value'])


@override_settings(DEMO_MODE=True,MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class LegacyPositionAuthoringTests(TestCase):
    placeholder = {'fr':'Choisir une position cible','en':'Choose a target position','ar':'اختاروا موضع الصوت المستهدف'}

    def setUp(self):
        install_fixture(self)
        grant = EditorialGrant.objects.get(user=self.editor,variety=self.variety)
        grant.publish = False
        grant.save()
        self.source = self.make_definition('first_consonant',{})
        self.probe = self.source
        self.client.force_login(self.editor)

    def make_definition(self, position, scope):
        return ProbeDefinition.objects.create(
            variety=self.variety,authored_by=self.editor,title='Fictional legacy authoring fixture',
            protocol='Software regression only',task='Fictional naming',target_phoneme='p',
            target_position=position,target_scope=scope,items=[item(0)],is_demo=True)

    def clone(self, source):
        response = self.client.post(reverse('followup:definition_clone',args=[source.pk]))
        self.assertEqual(response.status_code,302)
        return ProbeDefinition.objects.filter(series=source.series).order_by('-version').first()

    def payload(self, definition):
        return view_tests.FollowupViewTests.design_payload(self,definition)

    def test_legacy_edit_and_clone_native_defaults_cannot_change_position_in_any_language(self):
        source_digest = self.source.fingerprint()
        for language in ('fr','en','ar'):
            with self.subTest(language=language),translation.override(language):
                clone = self.clone(self.source)
                self.assertEqual((clone.target_position,clone.target_scope),('first_consonant',{}))
                for definition in (self.source,clone):
                    with self.subTest(version=definition.version):
                        path = reverse('followup:definition_edit',args=[definition.pk])
                        before = definition.fingerprint()
                        page = self.client.get(path)
                        self.assertEqual(page.status_code,200)
                        field = page.context['form']['target_position']
                        self.assertEqual(field.value(),'first_consonant')
                        native = NativePositionSelect(str(field))
                        self.assertTrue(native.required)
                        self.assertEqual(native.options[0]['label'],self.placeholder[language])
                        self.assertEqual(native.native_value,'')
                        counts = (ProbeDefinition.objects.count(),ProbeReview.objects.count(),AuditEvent.objects.count())
                        data = {**self.payload(definition),'title':'Attempted unconfirmed edit',
                                'target_position':native.native_value,'context_key':'fictitious_context'}
                        response = self.client.post(path,data)
                        self.assertEqual(response.status_code,200)
                        self.assertIn('target_position',response.context['form'].errors)
                        definition.refresh_from_db()
                        self.assertEqual((definition.target_position,definition.target_scope),('first_consonant',{}))
                        self.assertEqual(definition.fingerprint(),before)
                        self.assertEqual((ProbeDefinition.objects.count(),ProbeReview.objects.count(),AuditEvent.objects.count()),counts)
                self.source.refresh_from_db()
                self.assertEqual(self.source.fingerprint(),source_digest)

    def test_supported_positions_keep_their_preselection_and_context(self):
        for language in ('fr','en','ar'):
            with translation.override(language):
                for position in ('initial','medial','final'):
                    with self.subTest(language=language,position=position):
                        scope = {'position':position,'context':'fictitious_documented_context'}
                        definition = self.make_definition(position,scope)
                        path = reverse('followup:definition_edit',args=[definition.pk])
                        page = self.client.get(path)
                        self.assertEqual(page.status_code,200)
                        native = NativePositionSelect(str(page.context['form']['target_position']))
                        self.assertEqual([option['value'] for option in native.options if option['selected']],[position])
                        self.assertEqual(native.native_value,position)
                        response = self.client.post(path,{**self.payload(definition),'title':'Explicit draft wording change'})
                        self.assertEqual(response.status_code,302)
                        definition.refresh_from_db()
                        self.assertEqual((definition.target_position,definition.target_scope),(position,scope))

    def test_explicit_supported_choice_with_context_can_update_a_legacy_draft(self):
        source_digest = self.source.fingerprint()
        for language,position in [('fr','initial'),('en','medial'),('ar','final')]:
            with self.subTest(language=language,position=position),translation.override(language):
                clone = self.clone(self.source)
                data = {**self.payload(clone),'target_position':position,'context_key':'explicit_fictitious_context'}
                response = self.client.post(reverse('followup:definition_edit',args=[clone.pk]),data)
                self.assertEqual(response.status_code,302)
                clone.refresh_from_db()
                self.assertEqual(clone.target_position,position)
                self.assertEqual(clone.target_scope,{'position':position,'context':'explicit_fictitious_context'})
                self.assertEqual((clone.state,clone.reviews.count()),('draft',0))
        self.source.refresh_from_db()
        self.assertEqual(self.source.fingerprint(),source_digest)
