"""Browser-form contract using fictional local evidence, not clinical approval."""
import hashlib
import uuid
from html.parser import HTMLParser

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from catalog.authoring import ActivityAuthoringForm
from catalog.models import Activity, EditorialGrant, Review, Variety
from core.models import AuditEvent, User
from .models import AvailabilityDecision, EvidenceDocument, ReviewerCompetence, ReviewerCompetenceDecision


class RenderedForms(HTMLParser):
    def __init__(self, content):
        super().__init__();self.forms=[];self.current=None;self.feed(content)
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='form':
            self.current={'attrs':attrs,'inputs':{}};self.forms.append(self.current)
        elif tag=='input' and self.current is not None:
            self.current['inputs'][attrs.get('name','')]=attrs
    def handle_endtag(self,tag):
        if tag=='form':self.current=None
    def with_input(self,name):
        return next(form for form in self.forms if name in form['inputs'])


@override_settings(DEMO_MODE=False,MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={'default':{'BACKEND':'django.core.files.storage.InMemoryStorage'},
              'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class EvidenceMultipartTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.variety=Variety.objects.create(code='ar-evidence-fixture',language='ar',label='Fictional evidence scope')
        cls.foreign_variety=Variety.objects.create(code='fr-evidence-other',language='fr',label='Other fictional scope')
        cls.editor=User.objects.create_user('multipart-editor','editor@multipart.example.test')
        cls.foreign=User.objects.create_user('multipart-foreign','foreign@multipart.example.test')
        cls.reviewer=User.objects.create_user('multipart-reviewer','reviewer@multipart.example.test')
        cls.ordinary=User.objects.create_user('multipart-ordinary','ordinary@multipart.example.test')
        EditorialGrant.objects.create(user=cls.editor,variety=cls.variety,edit=True)
        EditorialGrant.objects.create(user=cls.foreign,variety=cls.foreign_variety,edit=True)
        EditorialGrant.objects.create(user=cls.reviewer,variety=cls.variety,clinical_review=True)

    def setUp(self):
        translation.activate('en');self.client.force_login(self.editor)

    def payload(self, **extra):
        return {'variety':str(self.variety.pk),'title':'Fictional document, no clinical authorisation',
                'category':'familiarity','provenance':'Fictional software evidence only; no observation or approval.',
                'validity':'unknown', **extra}

    def file(self, name='fictional.txt'):
        return SimpleUploadedFile(name,b'Fictional test document only. No clinical evidence or rights approval.')

    def assert_no_qualification(self):
        self.assertFalse(Review.objects.exists())
        self.assertFalse(ReviewerCompetenceDecision.objects.exists())
        self.assertFalse(AvailabilityDecision.objects.exists())

    def test_rendered_file_form_is_multipart_in_three_interfaces_without_writes(self):
        for language in ['fr','en','ar']:
            with self.subTest(language=language):
                page=self.client.get(f'/{language}/qualification/evidence/new/')
                self.assertEqual(page.status_code,200)
                self.assertTrue(page.context['form'].is_multipart())
                form=RenderedForms(page.content.decode()).with_input('file')
                self.assertEqual(form['attrs']['method'],'post')
                self.assertEqual(form['attrs'].get('enctype'),'multipart/form-data')
                self.assertEqual(form['inputs']['file']['type'],'file')
                self.assertTrue(form['inputs']['csrfmiddlewaretoken']['value'])
        self.assertFalse(EvidenceDocument.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action='qualification.evidence_uploaded').exists())

    def test_valid_document_uses_rendered_csrf_form_and_keeps_exact_private_bytes(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.editor)
        page=client.get(reverse('qualification:evidence_upload'))
        form=RenderedForms(page.content.decode()).with_input('file')
        upload=self.file();expected=upload.read();upload.seek(0)
        response=client.post(reverse('qualification:evidence_upload'),self.payload(
            csrfmiddlewaretoken=form['inputs']['csrfmiddlewaretoken']['value'],file=upload))
        self.assertEqual(response.status_code,302)
        document=EvidenceDocument.objects.get()
        self.assertEqual(document.variety,self.variety)
        self.assertEqual(document.uploaded_by,self.editor)
        self.assertEqual(document.sha256,hashlib.sha256(expected).hexdigest())
        self.assertTrue(document.intact);self.assertFalse(document.usable)
        download=client.get(reverse('qualification:evidence_file',args=[document.pk]))
        self.assertEqual(b''.join(download.streaming_content),expected)
        self.assertIn('no-store',download['Cache-Control'])
        activity=Activity.objects.create(variety=self.variety,series=uuid.uuid4(),title='Fictional draft',
            contrast='Fictional scope',word_a='pa',word_b='ba',instructions={'en':'Fictional','fr':'Fictif','ar':'مثال وهمي'})
        author=ActivityAuthoringForm(actor=self.editor,instance=activity)
        self.assertIn(document.pk,author.fields['familiarity_evidence_a'].queryset.values_list('pk',flat=True))
        self.assertFalse(author['familiarity_evidence_a'].value())
        self.assertEqual(AuditEvent.objects.filter(action='qualification.evidence_uploaded').count(),1)
        self.assert_no_qualification()

    def test_missing_or_disallowed_file_stays_invalid_without_document(self):
        for extra in [{},{'file':self.file('fictional.exe')}]:
            with self.subTest(has_file=bool(extra)):
                response=self.client.post(reverse('qualification:evidence_upload'),self.payload(**extra))
                self.assertEqual(response.status_code,200)
                self.assertIn('file',response.context['form'].errors)
                self.assertEqual(RenderedForms(response.content.decode()).with_input('file')['attrs']['enctype'],'multipart/form-data')
                self.assertFalse(EvidenceDocument.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action='qualification.evidence_uploaded').exists())

    def test_cross_variety_upload_and_foreign_download_remain_denied(self):
        response=self.client.post(reverse('qualification:evidence_upload'),self.payload(
            variety=str(self.foreign_variety.pk),file=self.file()))
        self.assertEqual(response.status_code,200)
        self.assertIn('variety',response.context['form'].errors)
        self.assertFalse(EvidenceDocument.objects.exists())
        self.client.post(reverse('qualification:evidence_upload'),self.payload(file=self.file()))
        document=EvidenceDocument.objects.get();self.client.force_login(self.foreign)
        self.assertEqual(self.client.get(reverse('qualification:evidence_file',args=[document.pk])).status_code,404)

    def test_non_editors_cannot_upload_and_csrf_is_still_required(self):
        for user in [self.reviewer,self.ordinary]:
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(self.client.get(reverse('qualification:evidence_upload')).status_code,403)
                self.assertEqual(self.client.post(reverse('qualification:evidence_upload'),self.payload(file=self.file())).status_code,403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('qualification:evidence_upload')).status_code,302)
        client=Client(enforce_csrf_checks=True);client.force_login(self.editor)
        self.assertEqual(client.post(reverse('qualification:evidence_upload'),self.payload(file=self.file())).status_code,403)
        self.assertFalse(EvidenceDocument.objects.exists())

    def test_ordinary_declaration_form_keeps_its_original_non_multipart_contract(self):
        page=self.client.get(reverse('qualification:competence'))
        self.assertFalse(page.context['form'].is_multipart())
        form=RenderedForms(page.content.decode()).with_input('professional_role')
        self.assertEqual(form['attrs']['method'],'post')
        self.assertNotIn('enctype',form['attrs'])
        response=self.client.post(reverse('qualification:competence'),{
            'variety':str(self.variety.pk),'discipline':'clinical','professional_role':'Fictional test role',
            'experience':'Fictional software declaration only','active':'on','acknowledge':'on'})
        self.assertEqual(response.status_code,302)
        self.assertFalse(ReviewerCompetence.objects.get(user=self.editor).independently_verified)
        self.assertFalse(EvidenceDocument.objects.exists());self.assert_no_qualification()
