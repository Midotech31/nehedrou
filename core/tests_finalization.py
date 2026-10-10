"""Regression tests for independently reproduced audit findings."""
import io
from pathlib import Path
from datetime import timedelta
from PIL import Image
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone, translation
from care.models import Child, FamilyLink, Program, PracticeSession, ProgramFeedback, Observation
from catalog.models import MediaAsset
from catalog.forms import MediaForm
from catalog.media_validation import validate_media
from . import tests as original_tests
from .testing import pcm_fixture
from .services import publish_feedback, record_practice, resolve_privacy
from .practice_runs import start_run, stop_run, task_ticket
from .models import Membership, PrivacyRequest, AuditEvent

@override_settings(DEMO_MODE=True, MFA_REQUIRED=False)
class FinalizationTests(TestCase):
    setUpTestData = classmethod(original_tests.WorkflowTests.setUpTestData.__func__)
    payload = original_tests.WorkflowTests.payload
    ticket = original_tests.WorkflowTests.ticket
    def setUp(self):
        translation.activate('fr')
        self.client.force_login(self.pro)
    def report(self, **changes):
        return record_practice(self.family, self.item, self.payload(**changes), self.ticket())
    def test_authenticated_forms_preserve_same_origin_for_csrf(self):
        from django.test import Client
        client=Client(enforce_csrf_checks=True);client.force_login(self.pro)
        url=reverse('family_feedback_create',args=[self.program.pk])
        response=client.get(url)
        self.assertEqual(response.headers['Referrer-Policy'],'same-origin')
        self.assertIn('no-store',response.headers['Cache-Control'])
        token=client.cookies['csrftoken'].value
        self.assertEqual(client.post(url,{'text':'Fictional CSRF check','csrfmiddlewaretoken':token},HTTP_ORIGIN='http://testserver').status_code,302)
        self.assertEqual(client.post(url,{'text':'Invalid origin','csrfmiddlewaretoken':token},HTTP_ORIGIN='null').status_code,403)
        self.assertEqual(client.post(url,{'text':'Outside origin','csrfmiddlewaretoken':token},HTTP_ORIGIN='https://outside.example').status_code,403)
        self.assertEqual(ProgramFeedback.objects.count(),1)

    def test_feedback_is_explicitly_shared_private_observation_is_not(self):
        report=self.report()
        Observation.objects.create(program=self.program, author=self.pro, text='Private-only-marker')
        url=reverse('family_feedback_create',args=[self.program.pk])+'?report='+str(report.pk)
        self.assertEqual(self.client.post(url,{'text':'Shared-guidance-marker'}).status_code,302)
        shared=ProgramFeedback.objects.get()
        self.assertEqual(shared.source_report_id, report.pk)
        self.assertTrue(AuditEvent.objects.filter(action='family_feedback.published',object_id=str(shared.pk)).exists())
        self.client.force_login(self.family)
        for name,pk in [('program_detail',self.program.pk),('report_detail',report.pk),('dashboard',None)]:
            response=self.client.get(reverse(name,args=[pk] if pk else []))
            self.assertContains(response,'Shared-guidance-marker')
            self.assertNotContains(response,'Private-only-marker')
        data=self.client.get(reverse('export_child',args=[self.child.pk])).json()['programs'][0]
        self.assertNotIn('professional_observations',data)
        self.assertEqual(data['family_feedback'][0]['source_report_id'],str(report.pk))
    def test_feedback_refuses_family_other_clinician_revoked_member_and_archive(self):
        url=reverse('family_feedback_create',args=[self.program.pk])
        for user in [self.family,self.other]:
            self.client.force_login(user)
            self.assertEqual(self.client.post(url,{'text':'Unauthorized'}).status_code,404)
            with self.assertRaises(ValidationError): publish_feedback(user,self.program,'Unauthorized')
        Membership.objects.filter(user=self.pro,organization=self.org).update(active=False)
        with self.assertRaises(ValidationError): publish_feedback(self.pro,self.program,'Revoked')
        Membership.objects.filter(user=self.pro,organization=self.org).update(active=True)
        Child.objects.filter(pk=self.child.pk).update(active=False)
        with self.assertRaises(ValidationError): publish_feedback(self.pro,self.program,'Archived')
        self.assertFalse(ProgramFeedback.objects.exists())
    def test_feedback_source_cannot_be_cross_program_and_published_text_is_immutable(self):
        report=self.report()
        another=Program.objects.create(child=self.child,organization=self.org,variety=self.program.variety,title='Other',created_by=self.pro,guidance='Fictional',schedule='Fictional')
        with self.assertRaises(ValidationError): publish_feedback(self.pro,another,'Wrong source',report)
        feedback=publish_feedback(self.pro,self.program,'Original',report)
        feedback.text='Changed'
        with self.assertRaises(ValidationError): feedback.save()
        feedback.refresh_from_db();self.assertEqual(feedback.text,'Original')
    def test_complete_history_filters_stable_pagination_and_language_routes(self):
        for index in range(65): self.report(completion='stopped' if index%2 else 'completed',answer='' if index%2 else 'a',comment=f'Historical {index}')
        shared_time=timezone.now()-timedelta(days=7)
        PracticeSession.objects.filter(item=self.item).update(created_at=shared_time)
        url=reverse('program_history',args=[self.program.pk])
        identifiers=[]
        for page in range(1,5):
            response=self.client.get(url,{'page':page})
            self.assertEqual(response.status_code,200)
            identifiers += [r.pk for r in response.context['page']]
            self.assertEqual(response.context['page'].paginator.count,65)
        self.assertEqual(len(set(identifiers)),65)
        self.assertEqual(identifiers,list(PracticeSession.objects.filter(item=self.item).order_by('-created_at','-pk').values_list('pk',flat=True)))
        response=self.client.get(url,{'status':'stopped','start':shared_time.date(),'end':shared_time.date()})
        self.assertEqual(response.context['page'].paginator.count,32)
        invalid=self.client.get(url,{'start':'2026-10-10','end':'2026-10-01'})
        self.assertTrue(invalid.context['form'].errors);self.assertEqual(invalid.context['page'].paginator.count,0)
        for lang in ['fr','en','ar']:
            with translation.override(lang):
                self.assertEqual(self.client.get(reverse('program_history',args=[self.program.pk])).status_code,200)
    def test_history_and_shared_guidance_revocation(self):
        report=self.report();publish_feedback(self.pro,self.program,'Shared',report)
        self.client.force_login(self.family)
        FamilyLink.objects.filter(user=self.family,child=self.child).update(active=False)
        for name,pk in [('program_history',self.program.pk),('report_detail',report.pk),('family_feedback_create',self.program.pk)]:
            self.assertEqual(self.client.get(reverse(name,args=[pk])).status_code,404)
    def test_export_queries_do_not_grow_with_number_of_runs_and_links_resolve(self):
        for _ in range(12):
            run=start_run(self.family,self.program);task=run.tasks.select_related('item','run').get()
            record_practice(self.family,task.item,self.payload(),task_ticket(task))
        url=reverse('export_child',args=[self.child.pk])
        with CaptureQueriesContext(connection) as first: self.client.get(url)
        for _ in range(12):
            run=start_run(self.family,self.program);stop_run(self.family,run)
        with CaptureQueriesContext(connection) as second: response=self.client.get(url)
        self.assertEqual(len(first),len(second))
        data=response.json();self.assertEqual(data['schema_version'],2)
        program=data['programs'][0];reports={s['id']:s for item in program['items'] for s in item['sessions']}
        tasks={t['id']:t for run in program['practice_runs'] for t in run['tasks']}
        for report in reports.values():
            if report['run_task_id']: self.assertEqual(tasks[report['run_task_id']]['report_id'],report['id'])
        for task in tasks.values():
            if task['report_id']: self.assertEqual(reports[task['report_id']]['run_task_id'],task['id'])
        # Family cannot receive another caregiver's private run references.
        pro_run=start_run(self.pro,self.program);task=pro_run.tasks.select_related('item','run').get()
        pro_report=record_practice(self.pro,task.item,self.payload(),task_ticket(task))
        self.client.force_login(self.family)
        family_data=self.client.get(url).json()['programs'][0]
        self.assertNotIn(str(pro_run.pk),[r['id'] for r in family_data['practice_runs']])
        family_reports={s['id']:s for item in family_data['items'] for s in item['sessions']}
        self.assertIsNone(family_reports[str(pro_report.pk)]['run_task_id'])
    def test_erasure_includes_shared_feedback_and_retention_anchor(self):
        report=self.report();feedback=publish_feedback(self.pro,self.program,'Shared',report)
        from .complete_views import retention_anchor
        self.assertGreaterEqual(retention_anchor(self.child),feedback.created_at)
        self.org.retention_days=0;self.org.save()
        request=PrivacyRequest.objects.create(organization=self.org,child=self.child,requester=self.family,kind='erasure')
        resolve_privacy(self.pro,request.pk,dict(decision='erase',confirmation=self.child.code,reason='Fictional erasure'))
        self.assertFalse(ProgramFeedback.objects.filter(pk=feedback.pk).exists())
    def test_new_screens_render_in_all_languages_without_private_data(self):
        report=self.report()
        for lang in ['fr','en','ar']:
            with translation.override(lang):
                for name,pk in [('family_feedback_create',self.program.pk),('report_detail',report.pk),('program_history',self.program.pk)]:
                    response=self.client.get(reverse(name,args=[pk]));self.assertEqual(response.status_code,200)
                    self.assertContains(response,'dir="rtl"' if lang=='ar' else f'lang="{lang}"')

@override_settings(DEMO_MODE=True, MFA_REQUIRED=False)
@override_settings(STORAGES={'default':{'BACKEND':'django.core.files.storage.InMemoryStorage'}})
class MediaValidationTests(TestCase):
    setUpTestData = classmethod(original_tests.WorkflowTests.setUpTestData.__func__)
    def form(self,name,data,kind):
        return MediaForm(data={'kind':kind,'rights':'Fictional owned fixture'},files={'file':SimpleUploadedFile(name,data)})
    def image(self,format='PNG',size=(8,8)):
        buffer=io.BytesIO();Image.new('RGB',size,'teal').save(buffer,format=format);return buffer.getvalue()
    def test_header_only_and_truncated_media_are_rejected(self):
        for name,data,kind in [('header.png',b'\x89PNG\r\n\x1a\n','image'),('header.wav',b'RIFF0000WAVE','audio'),('header.mp3',b'ID3','audio'),('truncated.wav',pcm_fixture()[:-20],'audio'),('truncated.jpg',self.image('JPEG')[:100],'image')]:
            with self.subTest(name=name): self.assertFalse(self.form(name,data,kind).is_valid())
    def test_valid_media_metadata_and_pointer_are_preserved(self):
        for name,data,kind,format in [('valid.png',self.image(),'image','PNG'),('valid.jpg',self.image('JPEG'),'image','JPEG'),('valid.wav',pcm_fixture(),'audio','WAV')]:
            file=SimpleUploadedFile(name,data);meta=validate_media(file,kind)
            self.assertEqual(meta['format'],format);self.assertEqual(meta['bytes'],len(data));self.assertEqual(file.tell(),0)
            self.assertTrue(self.form(name,data,kind).is_valid())
    def test_kind_extension_and_dimensions_must_match(self):
        self.assertFalse(self.form('wrong.png',self.image(),'audio').is_valid())
        self.assertFalse(self.form('wrong.jpg',self.image(),'image').is_valid())
        self.assertFalse(self.form('wide.png',self.image(size=(6001,1)),'image').is_valid())
    def test_uploaded_assets_are_immutable_and_old_unverified_media_unavailable(self):
        with override_settings(MEDIA_ROOT=str(Path.cwd()/'work/test-media')):
            asset=MediaAsset.objects.create(file=ContentFile(pcm_fixture(),name='valid.wav'),kind='audio',rights='Fictional',uploaded_by=self.pro)
            self.assertEqual(asset.technical_metadata['format'],'WAV')
            asset.file=ContentFile(pcm_fixture(),name='replacement.wav')
            with self.assertRaises(ValidationError): asset.save()
            asset.refresh_from_db()
            original_name=asset.file.name;original_metadata=dict(asset.technical_metadata)
            asset.file=ContentFile(b'RIFF0000WAVE',name=original_name)
            with self.assertRaises(ValidationError): asset.save()
            asset.refresh_from_db()
            self.assertEqual(asset.file.name,original_name);self.assertEqual(asset.technical_metadata,original_metadata)
            self.assertEqual(asset.file.read(),pcm_fixture());asset.file.close()
            from django.conf import settings
            self.item.activity.audio_a=settings.PUBLIC_ORIGIN+'/fr/media/'+str(asset.pk)+'/'
            self.assertTrue(self.item.activity.audio_available(self.item.activity.audio_a))
            MediaAsset.objects.filter(pk=asset.pk).update(technical_metadata={})
            self.assertFalse(self.item.activity.audio_available(self.item.activity.audio_a))
